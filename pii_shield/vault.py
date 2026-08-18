# -*- coding: utf-8 -*-
"""Сейф соответствий «тег ↔ оригинал». Никогда не покидает локальную машину.

Файл сейфа пишется с правами 0600 и может быть зашифрован парольной фразой
(scrypt + Fernet). Без сейфа обратная подстановка невозможна — это и есть
точка, в которой персональные данные остаются под контролем.
"""
from __future__ import annotations

import base64
import json
import re
import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .tags import DEFAULT_STYLE, make_tag, tag_key

SCHEMA_VERSION = 2


_INITIAL_RE = re.compile(r"[А-ЯЁA-Z]\.")


def _hint_score(hint: str) -> tuple[int, int]:
    """Качество подсказки: сначала число полных слов, потом всего слов.

    «Петрова Мария Сергеевна» должна побеждать «Петрова М. С.»,
    иначе в ответ модели уедет форма с инициалами.
    """
    if not hint:
        return (0, 0)
    tokens = hint.split()
    full = sum(1 for t in tokens if not _INITIAL_RE.fullmatch(t))
    return (full, len(tokens))


@dataclass
class Entity:
    tag: str                      # PERSON_1
    label: str                    # PERSON
    canonical: str                # что подставлять обратно по умолчанию
    variants: list[str] = field(default_factory=list)
    count: int = 0
    #: реконструированная форма для подстановки в новый текст
    #: (для ФИО — именительный падеж). Пусто, если реконструкция не нужна.
    nominative: str = ""

    def observe(self, surface: str, hint: str = "") -> None:
        self.count += 1
        if surface not in self.variants:
            self.variants.append(surface)
        if hint and _hint_score(hint) > _hint_score(self.nominative):
            self.nominative = hint
        if self._score(surface) > self._score(self.canonical):
            self.canonical = surface

    def _score(self, surface: str) -> tuple:
        """Насколько форма годится в каноничные.

        Для ФИО берём вариант с наибольшим числом компонентов, а при равенстве —
        самый короткий: «Кузнецов Иван Петрович» короче, чем «Кузнецову Ивану
        Петровичу», то есть с высокой вероятностью это именительный падеж.
        Для остального просто самая полная запись.
        """
        if self.label == "PERSON":
            return (len(surface.split()), -len(surface))
        return (len(surface),)


class Vault:
    """Хранит соответствия и порядок вхождений."""

    def __init__(self, style: str = DEFAULT_STYLE) -> None:
        self.style = style
        self.entities: dict[str, Entity] = {}       # "PERSON_1" -> Entity
        self._by_key: dict[tuple[str, Any], str] = {}  # (label, key) -> "PERSON_1"
        self._counters: dict[str, int] = {}
        self.occurrences: list[dict[str, str]] = []  # порядок замен в документе
        self.meta: dict[str, Any] = {}

    # ---------------------------------------------------------------- запись
    def assign(self, label: str, surface: str, key: Any = None, hint: str = "") -> str:
        """Вернуть тег для значения, создав сущность при первой встрече."""
        label = label.upper()
        k = (label, key if key is not None else surface.strip().lower())
        tkey = self._by_key.get(k)
        if tkey is None:
            n = self._counters.get(label, 0) + 1
            self._counters[label] = n
            tkey = tag_key(label, n)
            self.entities[tkey] = Entity(tag=tkey, label=label, canonical=surface)
            self._by_key[k] = tkey
        ent = self.entities[tkey]
        ent.observe(surface, hint)
        self.occurrences.append({"tag": tkey, "original": surface})
        return make_tag(label, int(tkey.rsplit("_", 1)[1]), self.style)

    def rendered(self, tkey: str) -> str:
        label, n = tkey.rsplit("_", 1)
        return make_tag(label, int(n), self.style)

    # ---------------------------------------------------------------- чтение
    def canonical_of(self, label: str, n: int | str) -> str | None:
        """Форма для подстановки в новый текст (ответ модели)."""
        ent = self.entities.get(tag_key(label, int(n)))
        if ent is None:
            return None
        return ent.nominative or ent.canonical

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entities.values():
            out[e.label] = out.get(e.label, 0) + 1
        return dict(sorted(out.items()))

    def total_replacements(self) -> int:
        return len(self.occurrences)

    # --------------------------------------------------------- сериализация
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "style": self.style,
            "meta": self.meta,
            "entities": {k: asdict(v) for k, v in self.entities.items()},
            "occurrences": self.occurrences,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Vault":
        v = cls(style=data.get("style", DEFAULT_STYLE))
        v.meta = data.get("meta", {})
        for k, raw in data.get("entities", {}).items():
            ent = Entity(**raw)
            v.entities[k] = ent
            label, n = k.rsplit("_", 1)
            v._counters[label] = max(v._counters.get(label, 0), int(n))
            for surface in ent.variants or [ent.canonical]:
                v._by_key.setdefault((label, surface.strip().lower()), k)
        v.occurrences = data.get("occurrences", [])
        return v

    # ------------------------------------------------------------- файл/крипто
    def save(self, path: str | Path, passphrase: str | None = None) -> Path:
        path = Path(path)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=1)
        if passphrase:
            blob = _encrypt(payload, passphrase)
            body = json.dumps({"pii_shield": SCHEMA_VERSION, "encrypted": True, **blob},
                              ensure_ascii=False, indent=1)
        else:
            body = json.dumps({"pii_shield": SCHEMA_VERSION, "encrypted": False,
                               "data": json.loads(payload)}, ensure_ascii=False, indent=1)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.chmod(path, 0o600)
        return path

    @classmethod
    def load(cls, path: str | Path, passphrase: str | None = None) -> "Vault":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("encrypted"):
            if not passphrase:
                raise ValueError("сейф зашифрован — нужна парольная фраза (--passphrase-env)")
            data = json.loads(_decrypt(raw, passphrase))
        else:
            data = raw["data"]
        return cls.from_dict(data)


def _kdf(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(key)


def _encrypt(plaintext: str, passphrase: str) -> dict[str, str]:
    from cryptography.fernet import Fernet
    salt = secrets.token_bytes(16)
    token = Fernet(_kdf(passphrase, salt)).encrypt(plaintext.encode("utf-8"))
    return {"kdf": "scrypt-n32768-r8-p1",
            "salt": base64.b64encode(salt).decode(),
            "payload": token.decode()}


def _decrypt(blob: dict[str, Any], passphrase: str) -> str:
    from cryptography.fernet import Fernet, InvalidToken
    salt = base64.b64decode(blob["salt"])
    try:
        return Fernet(_kdf(passphrase, salt)).decrypt(blob["payload"].encode()).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("неверная парольная фраза для сейфа") from exc
