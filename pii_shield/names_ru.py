# -*- coding: utf-8 -*-
"""Морфология русских ФИО без внешних зависимостей.

Задачи модуля:
  * распознать ФИО в свободном тексте (полные, с инициалами, «Имя Фамилия»);
  * склеить падежные варианты одного человека в одну сущность
    («Иванов», «Иванову», «Иванова И.И.» -> один и тот же #PERSON_1#).

Стемминг намеренно грубый и детерминированный: русская словоизменительная
морфология суффиксальна, поэтому усечение до 3 финальных «флективных» букв
надёжно склеивает падежные формы и почти не склеивает разные фамилии.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

from .dictionaries import (
    CAPITALIZED_STOPWORDS,
    GEO_PREFIXES,
    PATRONYMIC_SUFFIXES,
    PERSON_TRIGGERS,
    RU_FIRST_NAMES,
    SURNAME_SUFFIXES,
)

# Буквы, которые в русском несут словоизменительную нагрузку в исходе слова.
_FLEX = set("аяуюеёиыоьймх")
_MIN_STEM = 3
_MAX_STRIP = 3


_PATR_M_RE = re.compile(r"^(.*?(?:ович|евич|ьевич|иевич|ич))(?:[аеуойм]{1,3})?$")
_PATR_F_RE = re.compile(r"^(.*?(?:овн|евн|ьевн|иевн|иничн|ичн))(?:[аыеуойю]{1,3})?$")
_SURN_OV_RE = re.compile(r"^(.*(?:ов|ев|ёв|ин|ын))(?:а|у|ым|е|ой|ою|ы|ых|ыми|ому|ого)?$")
_SURN_SK_RE = re.compile(r"^(.*(?:ск|цк))(?:ий|ый|ая|ого|ому|им|ом|ой|ою|ую|ие|ых|их|ими)?$")


def norm(word: str) -> str:
    return word.lower().replace("ё", "е")


def stem(word: str) -> str:
    """Падежно-инвариантная основа слова."""
    w = norm(word)
    for _ in range(_MAX_STRIP):
        if len(w) <= _MIN_STEM or w[-1] not in _FLEX:
            break
        w = w[:-1]
    return w


_NAME_STEMS = {stem(n) for n in RU_FIRST_NAMES}
_STOP_STEMS = {stem(w) for w in CAPITALIZED_STOPWORDS}


def is_first_name(word: str) -> bool:
    return stem(word) in _NAME_STEMS


def is_patronymic(word: str) -> bool:
    """Отчество в любом падеже: Иванович, Ивановича, Ильичу, Ивановны…"""
    w = norm(word)
    if len(w) < 6:
        return False
    if w.endswith(PATRONYMIC_SUFFIXES):
        return True
    return bool(_PATR_M_RE.match(w) or _PATR_F_RE.match(w))


def looks_like_surname(word: str) -> bool:
    """Фамилия в любом падеже — по продуктивным суффиксам."""
    w = norm(word)
    if len(w) < 4 or w in _STOP_STEMS or stem(word) in _STOP_STEMS:
        return False
    if is_patronymic(word):
        return False
    if w.endswith(SURNAME_SUFFIXES):
        return True
    # склонённые формы на -ов/-ев/-ин и -ский/-цкий
    return bool(_SURN_OV_RE.match(w) or _SURN_SK_RE.match(w))


def is_stopword(word: str) -> bool:
    return word in CAPITALIZED_STOPWORDS or stem(word) in _STOP_STEMS


# --- токенизация --------------------------------------------------------------

_TOK_RE = re.compile(
    r"(?P<init>[А-ЯЁ]\.)"
    r"|(?P<cap>[А-ЯЁ][а-яё]+(?:-[А-ЯЁа-яё][а-яё]+)?)"
    r"|(?P<low>[а-яё]+(?:-[а-яё]+)?\.?)"
    r"|(?P<lat>[A-Za-z][A-Za-z'’\-]*)"
    r"|(?P<num>\d+)"
)


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    start: int
    end: int


def tokenize(text: str) -> list[Token]:
    out: list[Token] = []
    for m in _TOK_RE.finditer(text):
        kind = m.lastgroup or "other"
        out.append(Token(kind, m.group(0), m.start(), m.end()))
    return out


def _adjacent(text: str, a: Token, b: Token) -> bool:
    """Токены идут подряд (только пробел/неразрывный пробел между ними)."""
    gap = text[a.end:b.start]
    return gap == "" or re.fullmatch(r"[  ]{1,2}", gap) is not None


def _preceded_by(text: str, tok: Token, words: tuple[str, ...]) -> bool:
    left = text[max(0, tok.start - 24):tok.start].lower().strip()
    if not left:
        return False
    tail = re.split(r"[\s,;(]+", left)
    return bool(tail) and tail[-1] in words


# --- упоминания людей ---------------------------------------------------------


@dataclass
class PersonMention:
    start: int
    end: int
    surface: str
    surname: str = ""
    first: str = ""
    patronymic: str = ""
    initials: tuple[str, ...] = ()
    confidence: float = 1.0

    @property
    def nominative(self) -> str:
        """ФИО в именительном падеже, восстановленное из этой словоформы."""
        return to_nominative(self.surname, self.first, self.patronymic, self.initials)

    @property
    def key(self) -> tuple[str, str, str]:
        """Ключ склейки персоны.

        С фамилией: (основа фамилии, инициал имени, инициал отчества) — так
        «Иванов И.И.» и «Иванову Ивану Ивановичу» дают один ключ.
        Без фамилии: ('', основа имени, основа отчества) — чтобы разные
        «Иван Петрович» и «Игорь Павлович» не слиплись по инициалам.
        """
        if self.surname:
            f = norm(self.first)[:1] if self.first else (
                self.initials[0].lower() if self.initials else "")
            p = norm(self.patronymic)[:1] if self.patronymic else (
                self.initials[1].lower() if len(self.initials) > 1 else "")
            return (stem(self.surname), f.replace("ё", "е"), p.replace("ё", "е"))
        return ("", stem(self.first) if self.first else "",
                stem(self.patronymic) if self.patronymic else "")


def _mk(text: str, toks: list[Token], i: int, j: int, **kw) -> PersonMention:
    return PersonMention(toks[i].start, toks[j].end, text[toks[i].start:toks[j].end], **kw)


def find_person_mentions(text: str, aggressive: bool = False) -> list[PersonMention]:
    toks = tokenize(text)
    out: list[PersonMention] = []
    n = len(toks)
    i = 0
    while i < n:
        t = toks[i]
        if t.kind not in ("cap", "init"):
            i += 1
            continue
        nxt = [toks[k] for k in range(i, min(i + 4, n))]
        adj = [True] + [_adjacent(text, nxt[k - 1], nxt[k]) for k in range(1, len(nxt))]

        def kinds(count: int) -> list[str]:
            return [x.kind for x in nxt[:count]] if len(nxt) >= count and all(adj[:count]) else []

        matched: PersonMention | None = None

        # 1. ТРИ заглавных слова с отчеством: Иванов Иван Иванович / Иван Иванович Иванов
        if kinds(3) == ["cap", "cap", "cap"]:
            a, b, c = nxt[0].text, nxt[1].text, nxt[2].text
            if not any(is_stopword(x) for x in (a, b, c)):
                if is_patronymic(c) and (is_first_name(b) or looks_like_surname(a)):
                    matched = _mk(text, toks, i, i + 2, surname=a, first=b, patronymic=c)
                elif is_patronymic(b):
                    matched = _mk(text, toks, i, i + 2, surname=c, first=a, patronymic=b)

        # 2. Фамилия И.И. / Фамилия И.
        if matched is None and kinds(3) == ["cap", "init", "init"]:
            a = nxt[0].text
            if not is_stopword(a) and (looks_like_surname(a) or _preceded_by(text, nxt[0], PERSON_TRIGGERS)):
                matched = _mk(text, toks, i, i + 2, surname=a,
                              initials=(nxt[1].text[0], nxt[2].text[0]))
        if matched is None and kinds(2) == ["cap", "init"]:
            a = nxt[0].text
            if not is_stopword(a) and looks_like_surname(a):
                matched = _mk(text, toks, i, i + 1, surname=a, initials=(nxt[1].text[0],))

        # 3. И.И. Фамилия / И. Фамилия
        if matched is None and kinds(3) == ["init", "init", "cap"]:
            c = nxt[2].text
            if not is_stopword(c) and (looks_like_surname(c) or _preceded_by(text, nxt[0], PERSON_TRIGGERS)):
                matched = _mk(text, toks, i, i + 2, surname=c,
                              initials=(nxt[0].text[0], nxt[1].text[0]))
        if matched is None and kinds(2) == ["init", "cap"]:
            c = nxt[1].text
            if not is_stopword(c) and looks_like_surname(c):
                matched = _mk(text, toks, i, i + 1, surname=c, initials=(nxt[0].text[0],))

        # 4. Имя Фамилия / Фамилия Имя / Имя Отчество
        if matched is None and kinds(2) == ["cap", "cap"]:
            a, b = nxt[0].text, nxt[1].text
            if not (is_stopword(a) or is_stopword(b)) and not _after_geo_prefix(text, nxt[0]):
                if is_first_name(a) and is_patronymic(b):
                    matched = _mk(text, toks, i, i + 1, first=a, patronymic=b)
                elif is_first_name(a) and looks_like_surname(b):
                    matched = _mk(text, toks, i, i + 1, first=a, surname=b)
                elif looks_like_surname(a) and is_first_name(b):
                    matched = _mk(text, toks, i, i + 1, surname=a, first=b)

        # 5. Одиночная фамилия после должности/обращения
        if matched is None and t.kind == "cap" and not is_stopword(t.text):
            if looks_like_surname(t.text) and not _after_geo_prefix(text, t):
                if _preceded_by(text, t, PERSON_TRIGGERS) or aggressive:
                    matched = _mk(text, toks, i, i, surname=t.text, confidence=0.6)

        if matched is not None:
            out.append(matched)
            while i < n and toks[i].start < matched.end:
                i += 1
        else:
            i += 1
    return out


def _after_geo_prefix(text: str, tok: Token) -> bool:
    left = text[max(0, tok.start - 12):tok.start].lower()
    return any(left.rstrip().endswith(p) for p in GEO_PREFIXES)


# --- восстановление именительного падежа ---------------------------------

#: мужские имена на -а/-я — исключения для определения пола
MALE_A_NAMES = {"никита", "илья", "кузьма", "фома", "лука", "савва", "данила",
                "гаврила", "мина", "сила", "фока"}


def _is_female_name(name: str) -> bool:
    return name.endswith(("а", "я")) and name not in MALE_A_NAMES


def _build_name_index() -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
    """Основа имени -> все именительные варианты, отдельно по родам.

    Одной основе может отвечать несколько имён («соф» — София и Софья,
    «федор» — Фёдор и Федор). Выбор между ними делается уже по конкретной
    словоформе, см. _first_nominative.
    """
    male: dict[str, list[str]] = {}
    female: dict[str, list[str]] = {}
    any_: dict[str, list[str]] = {}
    for name in sorted(RU_FIRST_NAMES):
        key = stem(name)
        target = female if _is_female_name(name) else male
        for table in (target, any_):
            table.setdefault(key, []).append(name.capitalize())
    return male, female, any_


_NAME_M, _NAME_F, _NAME_BY_STEM = _build_name_index()


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n

def _patronymic_nominative(word: str) -> tuple[str, str]:
    """Вернуть (именительный падеж, пол) для отчества."""
    w = word.lower()
    m = _PATR_M_RE.match(w)
    if m:
        return m.group(1).capitalize(), "m"
    m = _PATR_F_RE.match(w)
    if m:
        return (m.group(1) + "а").capitalize(), "f"
    return word, ""


def _surname_nominative(word: str, gender: str) -> str:
    """Фамилия в именительном падеже. Без известного рода не преобразуем:
    «Петрова» без имени и отчества может быть и женской формой,
    и родительным падежом от «Петров» — угадывать нельзя."""
    if not gender:
        return word if word[:1].isupper() else word.capitalize()
    w = word.lower()
    m = _SURN_OV_RE.match(w)
    if m:
        base = m.group(1)
        return (base + ("а" if gender == "f" else "")).capitalize()
    m = _SURN_SK_RE.match(w)
    if m:
        base = m.group(1)
        return (base + ("ая" if gender == "f" else "ий")).capitalize()
    return word if word[:1].isupper() else word.capitalize()


def _first_nominative(word: str, gender: str = "") -> str:
    """Именительный падеж имени по любой словоформе."""
    key = stem(word)
    table = {"m": _NAME_M, "f": _NAME_F}.get(gender)
    candidates = (table or {}).get(key) or _NAME_BY_STEM.get(key)
    if not candidates:
        return word.capitalize()
    if len(candidates) == 1:
        return candidates[0]
    low = word.lower()
    # «Софьи» ближе к «Софья», чем к «София»; «Фёдора» — к «Фёдор», не к «Федор»
    return max(candidates, key=lambda c: (_common_prefix(low, c.lower()), -len(c)))


def guess_gender(surname: str = "", first: str = "", patronymic: str = "") -> str:
    if patronymic:
        _, g = _patronymic_nominative(patronymic)
        if g:
            return g
    low = norm(surname)
    if low.endswith(("ой", "ою", "ая", "ей")):
        return "f"
    if first:
        key = stem(first)
        in_m, in_f = key in _NAME_M, key in _NAME_F
        if in_f and not in_m:
            return "f"
        if in_m and not in_f:
            return "m"
        if _is_female_name(norm(first)):
            return "f"
    return ""


def to_nominative(surname: str = "", first: str = "", patronymic: str = "",
                  initials: tuple[str, ...] = ()) -> str:
    """Собрать ФИО в именительном падеже из любой падежной формы.

    Нужно для обратной подстановки в ответ модели: если в документе человек
    упомянут только как «Кузнецову Ивану Петровичу», подставлять эту форму
    в новый текст неправильно — вернём «Кузнецов Иван Петрович».
    """
    gender = guess_gender(surname, first, patronymic)
    parts: list[str] = []
    if surname:
        parts.append(_surname_nominative(surname, gender))
    if first:
        parts.append(_first_nominative(first, gender))
    elif initials:
        parts.append(" ".join(f"{i.upper()}." for i in initials))
    if patronymic:
        parts.append(_patronymic_nominative(patronymic)[0])
    return " ".join(parts)


def find_repeat_mentions(text: str, known_stems: dict[str, tuple[str, str, str]],
                         covered: list[tuple[int, int]]) -> list[tuple[int, int, tuple[str, str, str]]]:
    """Второй проход: одиночные словоформы уже известных людей.

    `known_stems` — основа слова -> ключ персоны. Возвращает спаны, которые
    ещё не покрыты (`covered` — отсортированные интервалы первого прохода).
    """
    hits: list[tuple[int, int, tuple[str, str, str]]] = []
    for tok in tokenize(text):
        if tok.kind != "cap":
            continue
        if any(s <= tok.start < e for s, e in covered):
            continue
        key = known_stems.get(stem(tok.text))
        if key is not None:
            hits.append((tok.start, tok.end, key))
    return hits
