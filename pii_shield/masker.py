# -*- coding: utf-8 -*-
"""Ядро: маскирование текста, проверка на утечку, обратная подстановка."""
from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from . import detectors as det
from . import names_ru as nru
from .tags import DEFAULT_STYLE, TAG_RE, tag_key
from .vault import Vault

#: Метки, маскируемые по умолчанию.
DEFAULT_LABELS = {
    "PERSON", "ORG", "EMAIL", "PHONE", "ADDRESS", "BIRTHDATE", "PASSPORT",
    "SNILS", "INN", "OGRN", "KPP", "BIK", "ACCOUNT", "CARD", "IBAN", "DOCDATE",
    "POLICY", "LICENSE", "PLATE", "IP", "HANDLE", "DOCNUM", "CUSTOM",
}
#: Метки, которые включаются флагами.
OPTIONAL_LABELS = {"DATE", "URL", "GEO"}


@dataclass
class MaskConfig:
    style: str = DEFAULT_STYLE
    labels: set[str] = field(default_factory=lambda: set(DEFAULT_LABELS))
    aggressive_names: bool = False
    custom_terms: list[str] = field(default_factory=list)
    allowlist: list[str] = field(default_factory=list)
    #: индекс латинских фамилий: слово -> ключ персоны (None = неоднозначно).
    latin_index: dict = field(default_factory=dict)
    #: общий для всех фрагментов индекс «основа слова -> ключ персоны».
    #: Позволяет склеить «Кузнецов» в одной ячейке с «Кузнецов И.П.» в другой.
    person_index: dict = field(default_factory=dict)

    def enable(self, *labels: str) -> "MaskConfig":
        self.labels |= {l.upper() for l in labels}
        return self

    def disable(self, *labels: str) -> "MaskConfig":
        self.labels -= {l.upper() for l in labels}
        return self


# --------------------------------------------------------------- поиск спанов


def _person_spans(text: str, cfg: MaskConfig) -> list[det.Span]:
    """Спаны ФИО: полные упоминания + одиночные словоформы известных людей."""
    mentions = nru.find_person_mentions(text, aggressive=cfg.aggressive_names)
    keys = _cluster_persons(mentions, cfg.person_index)
    spans: list[det.Span] = []
    covered: list[tuple[int, int]] = []
    for m in mentions:
        k = keys[id(m)]
        spans.append(det.Span(m.start, m.end, "PERSON", m.surface,
                              int(76 * m.confidence) + 10, note=repr(k),
                              hint=m.nominative))
        covered.append((m.start, m.end))

    # карта «основа слова -> ключ персоны» для второго прохода
    stem_map: dict[str, tuple[str, str, str]] = {}
    ambiguous: set[str] = set()
    for m in mentions:
        k = keys[id(m)]
        for word in (m.surname, m.first):
            if not word:
                continue
            st = nru.stem(word)
            if stem_map.get(st, k) != k:
                ambiguous.add(st)
            stem_map[st] = k
    # общий индекс документа (собран первым проходом по всем фрагментам)
    for st, k in cfg.person_index.items():
        if k is None:
            ambiguous.add(st)
            stem_map.setdefault(st, (st, "", ""))
        elif stem_map.get(st, k) != k:
            ambiguous.add(st)
        else:
            stem_map[st] = k
    # неоднозначную фамилию всё равно скрываем — просто под собственным тегом,
    # привязанным к основе слова, а не к конкретному человеку.
    for st in ambiguous:
        stem_map[st] = (st, "", "")

    covered.sort()
    for start_i, end_i, k in nru.find_repeat_mentions(text, stem_map, covered):
        spans.append(det.Span(start_i, end_i, "PERSON", text[start_i:end_i], 74,
                              note=repr(k), hint=nru.to_nominative(surname=text[start_i:end_i])))
    return spans


def _cluster_persons(mentions: list[nru.PersonMention],
                     shared: dict | None = None) -> dict[int, tuple[str, str, str]]:
    """Склеить неполные упоминания с полными (Кузнецов -> Кузнецов И.П.)."""
    detailed: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for k in (shared or {}).values():
        if k and k[0] and (k[1] or k[2]):
            detailed[k[0]].add(k)
    for m in mentions:
        k = m.key
        if k[0] and (k[1] or k[2]):
            detailed[k[0]].add(k)
    out: dict[int, tuple[str, str, str]] = {}
    for m in mentions:
        k = m.key
        if k[0]:
            cands = [c for c in detailed.get(k[0], ())
                     if (not k[1] or k[1] == c[1]) and (not k[2] or k[2] == c[2])]
            if len(cands) == 1:
                k = cands[0]
        out[id(m)] = k
    return out


_LATIN_WORD = re.compile(r"\b[A-Z][a-z]{2,20}\b")


def _latin_repeat_spans(text: str, base: list[det.Span], cfg: MaskConfig) -> list[det.Span]:
    """Одиночные латинские фамилии уже известных людей: «Ivanov reported…»."""
    if "PERSON" not in cfg.labels:
        return []
    index: dict[str, tuple] = {k: v for k, v in cfg.latin_index.items() if v is not None}
    for sp in base:
        if sp.label != "PERSON" or not sp.note or not sp.note.startswith("('latin'"):
            continue
        try:
            key = ast.literal_eval(sp.note)
        except (ValueError, SyntaxError):
            continue
        for w in re.findall(r"[A-Z][a-z]+", sp.value):
            if det._TAIL_RE.search(w):
                index.setdefault(w.lower(), key)
    if not index:
        return []
    covered = [(sp.start, sp.end) for sp in base]
    out: list[det.Span] = []
    for m in _LATIN_WORD.finditer(text):
        w = m.group(0)
        if w in det.LATIN_STOP or any(a <= m.start() < b for a, b in covered):
            continue
        key = index.get(w.lower())
        if key is not None:
            out.append(det.Span(m.start(), m.end(), "PERSON", w, 73, note=repr(key)))
    return out


def _collect_spans(text: str, cfg: MaskConfig) -> list[det.Span]:
    """Сырые спаны от всех детекторов, без разрешения перекрытий."""
    spans: list[det.Span] = []
    for _name, d in det.all_detectors():
        spans.extend(d(text))
    if cfg.custom_terms:
        spans.extend(det.custom_terms_detector(cfg.custom_terms)(text))
    if "PERSON" in cfg.labels:
        spans.extend(_person_spans(text, cfg))
    spans += _latin_repeat_spans(text, spans, cfg)

    allow = {a.strip().lower() for a in cfg.allowlist if a.strip()}
    spans = [s for s in spans if s.label in cfg.labels and s.value.strip().lower() not in allow]
    # то, что уже является тегом, не маскируем повторно
    tagged = [(m.start(), m.end()) for m in TAG_RE.finditer(text)]
    return [s for s in spans if not any(a <= s.start < b for a, b in tagged)]


def find_spans(text: str, cfg: MaskConfig | None = None) -> list[det.Span]:
    """Все найденные ПД в тексте, без перекрытий, в порядке следования.

    После разрешения перекрытий делается второй проход по «остаткам»: спан,
    проигравший более приоритетному соседу, мог полностью выпасть из выдачи.
    Пример: «ОКТМО 45000000\n101000, г. Москва, ул. Ленина…» —
    код ОКТМО перекрывал начало следующего адреса, и адрес терялся целиком.
    """
    cfg = cfg or MaskConfig()
    resolved = det.resolve_overlaps(_collect_spans(text, cfg))
    if not resolved:
        return resolved

    buf = list(text)
    for sp in resolved:
        buf[sp.start:sp.end] = " " * (sp.end - sp.start)
    leftovers = [s for s in _collect_spans("".join(buf), cfg)
                 if not any(s.start < r.end and r.start < s.end for r in resolved)]
    if leftovers:
        resolved = det.resolve_overlaps(resolved + leftovers)
    return resolved


# ------------------------------------------------------------------ маскировка


@dataclass
class MaskResult:
    text: str
    spans: list[det.Span]
    vault: Vault

    @property
    def replacements(self) -> int:
        return len(self.spans)


def _apply(text: str, spans: list[det.Span], vault: Vault) -> str:
    """Присвоить теги слева направо, подставить справа налево."""
    ordered = sorted(spans, key=lambda s: s.start)
    tags = [vault.assign(sp.label, sp.value,
                         key=(sp.note if (sp.label == "PERSON" and sp.note) else None),
                         hint=sp.hint)
            for sp in ordered]
    out = text
    for sp, tag in zip(reversed(ordered), reversed(tags)):
        out = out[:sp.start] + tag + out[sp.end:]
    return out


def mask_text(text: str, vault: Vault | None = None,
              cfg: MaskConfig | None = None) -> MaskResult:
    """Замаскировать одну строку текста."""
    cfg = cfg or MaskConfig()
    vault = vault if vault is not None else Vault(style=cfg.style)
    spans = find_spans(text, cfg)
    return MaskResult(_apply(text, spans, vault), spans, vault)


def build_person_index(units: list[str], cfg: MaskConfig) -> None:
    """Первый проход: собрать по всему документу карту «основа -> персона».

    Нужен, чтобы одиночная «Кузнецову» в одной ячейке склеилась с
    «Кузнецов Иван Петрович» в другой. Неоднозначные основы (две разные
    персоны с одной фамилией) помечаются None — такие слова маскируются,
    но отдельным тегом.
    """
    if "PERSON" not in cfg.labels:
        return
    idx = cfg.person_index
    for unit in units:
        if not unit or not unit.strip():
            continue
        for sp in det.d_latin_person(unit):
            try:
                key = ast.literal_eval(sp.note)
            except (ValueError, SyntaxError):
                continue
            for w in re.findall(r"[A-Z][a-z]+", sp.value):
                if not det._TAIL_RE.search(w):
                    continue
                low = w.lower()
                if low in cfg.latin_index and cfg.latin_index[low] != key:
                    cfg.latin_index[low] = None
                elif low not in cfg.latin_index:
                    cfg.latin_index[low] = key
    for unit in units:
        if not unit or not unit.strip():
            continue
        mentions = nru.find_person_mentions(unit, aggressive=cfg.aggressive_names)
        keys = _cluster_persons(mentions, idx)
        for m in mentions:
            k = keys[id(m)]
            if not (k[0] and (k[1] or k[2])):
                continue
            for word in (m.surname, m.first):
                if not word:
                    continue
                st = nru.stem(word)
                if st in idx and idx[st] != k:
                    idx[st] = None          # неоднозначно
                elif st not in idx:
                    idx[st] = k


def mask_units(units: list[str], vault: Vault | None = None,
               cfg: MaskConfig | None = None,
               contexts: list[str] | None = None) -> tuple[list[str], Vault, list[det.Span]]:
    """Замаскировать список фрагментов (абзацы, ячейки) общим сейфом.

    Общий сейф — обязательное условие: один и тот же человек в разных
    ячейках таблицы должен получить один и тот же тег.

    `contexts` — необязательные подсказки к каждому фрагменту (заголовок
    колонки таблицы). Ячейка «500100732259» сама по себе неотличима от
    случайного числа; с подсказкой «ИНН» она распознаётся уверенно.
    """
    cfg = cfg or MaskConfig()
    vault = vault if vault is not None else Vault(style=cfg.style)
    build_person_index(units, cfg)
    ctxs = contexts or [""] * len(units)
    out: list[str] = []
    all_spans: list[det.Span] = []
    for unit, ctx in zip(units, ctxs):
        if not unit or not unit.strip():
            out.append(unit)
            continue
        spans = find_spans_with_context(unit, ctx, cfg)
        all_spans.extend(spans)
        out.append(_apply(unit, spans, vault))
    return out, vault, all_spans


def find_spans_with_context(unit: str, context: str,
                            cfg: MaskConfig | None = None) -> list[det.Span]:
    """find_spans, но с виртуальным префиксом-подсказкой перед фрагментом."""
    if not context or not context.strip():
        return find_spans(unit, cfg)
    prefix = f"{context.strip()}: "
    shift = len(prefix)
    spans = []
    for sp in find_spans(prefix + unit, cfg):
        if sp.end <= shift:
            continue            # попало целиком в подсказку — игнорируем
        spans.append(det.Span(max(0, sp.start - shift), sp.end - shift, sp.label,
                              unit[max(0, sp.start - shift):sp.end - shift],
                              sp.priority, sp.note, sp.hint))
    return [sp for sp in spans if sp.start >= 0 and sp.value.strip()]


# ------------------------------------------------------- проверка на утечку

_PARANOID = (
    ("email-like", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("long-digit-run", re.compile(r"(?<!\d)\d{7,}(?!\d)")),
    ("phone-like", re.compile(r"\+\d[\d\s\-()]{7,}\d")),
)


@dataclass
class Finding:
    kind: str
    value: str
    position: int


def verify(text: str, cfg: MaskConfig | None = None, paranoid: bool = True) -> list[Finding]:
    """Что осталось в тексте после маскирования. Пусто => можно отправлять."""
    cfg = cfg or MaskConfig()
    found = [Finding(s.label, s.value, s.start) for s in find_spans(text, cfg)]
    if paranoid:
        stripped = TAG_RE.sub(" ", text)
        for kind, pat in _PARANOID:
            for m in pat.finditer(stripped):
                found.append(Finding(f"paranoid:{kind}", m.group(0), m.start()))
    # дедуп по (kind, value)
    seen: set[tuple[str, str]] = set()
    uniq: list[Finding] = []
    for f in found:
        sig = (f.kind, f.value)
        if sig not in seen:
            seen.add(sig)
            uniq.append(f)
    return uniq


class LeakGuardError(RuntimeError):
    """Поднимается, когда в тексте, готовом к отправке, остались ПД."""


def assert_clean(text: str, cfg: MaskConfig | None = None, paranoid: bool = True) -> None:
    residual = verify(text, cfg, paranoid=paranoid)
    if residual:
        preview = "; ".join(f"{f.kind}={f.value[:24]!r}" for f in residual[:6])
        raise LeakGuardError(
            f"обнаружено {len(residual)} незамаскированных фрагментов: {preview}")


# ------------------------------------------------------- обратная подстановка


def unmask_text(text: str, vault: Vault, mode: str = "canonical",
                state: dict | None = None) -> tuple[str, list[str]]:
    """Вернуть оригиналы вместо тегов.

    mode="canonical"  — по каждому тегу подставляется каноничная форма
                        (для ответа модели: там другой порядок и состав тегов).
    mode="sequential" — по журналу вхождений, символ-в-символ
                        (для восстановления нашего же замаскированного файла).

    `state` — общий словарь позиций для документов из нескольких фрагментов.
    Без него каждый вызов начинал бы журнал заново и подставлял в каждую
    ячейку первое вхождение тега.
    """
    unknown: list[str] = []
    if mode == "sequential":
        if state is None:
            state = {}
        if "queue" not in state:
            queue: dict[str, list[str]] = defaultdict(list)
            for occ in vault.occurrences:
                queue[occ["tag"]].append(occ["original"])
            state["queue"] = queue
            state["pos"] = defaultdict(int)
        queue, pos = state["queue"], state["pos"]

        def repl(m: re.Match) -> str:
            k = tag_key(m.group("label"), m.group("n"))
            items = queue.get(k)
            if items and pos[k] < len(items):
                val = items[pos[k]]
                pos[k] += 1
                return val
            ent = vault.entities.get(k)
            if ent:
                return ent.nominative or ent.canonical
            unknown.append(k)
            return m.group(0)
    else:
        def repl(m: re.Match) -> str:
            k = tag_key(m.group("label"), m.group("n"))
            ent = vault.entities.get(k)
            if ent is None:
                unknown.append(k)
                return m.group(0)
            return ent.nominative or ent.canonical

    return TAG_RE.sub(repl, text), unknown
