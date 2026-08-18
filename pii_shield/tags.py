# -*- coding: utf-8 -*-
"""Формат тегов-заменителей и толерантный парсер для обратной подстановки.

Тег по умолчанию: #PERSON_1#  (стиль "hash").
Альтернативы: --tag-style bracket -> [[PERSON_1]] ; angle -> <PERSON_1>

Обратная подстановка намеренно ТОЛЕРАНТНА: модель часто возвращает тег
изменённым — теряет решётки, оборачивает в **жирный**, ставит пробелы,
меняет регистр, склеивает с пунктуацией. Мы ищем «ядро» тега (LABEL_N)
и восстанавливаем оригинал вместе с любой окружающей декорацией.
"""
from __future__ import annotations

import re
from typing import Iterable

#: Полный перечень меток. Добавление новой метки — только сюда.
LABELS = (
    "PERSON", "ORG", "EMAIL", "PHONE", "ADDRESS", "BIRTHDATE", "DATE",
    "PASSPORT", "SNILS", "INN", "OGRN", "KPP", "BIK", "ACCOUNT", "CARD", "DOCDATE",
    "IBAN", "POLICY", "LICENSE", "PLATE", "IP", "URL", "HANDLE", "LOGIN",
    "DOCNUM", "GEO", "CUSTOM",
)

TAG_STYLES = {
    "hash": "#{label}_{n}#",
    "bracket": "[[{label}_{n}]]",
    "angle": "<{label}_{n}>",
}
DEFAULT_STYLE = "hash"

_LABEL_ALT = "|".join(LABELS)

#: Ядро тега — то, что реально ищем при разборе ответа модели.
_CORE = rf"(?P<label>{_LABEL_ALT})\s*[_\-\s]?\s*(?P<n>\d{{1,6}})(?!\d)"

#: Декорация вокруг ядра: решётки, скобки, звёздочки markdown, кавычки, бэктики.
_OPEN = r"(?:(?:\*{1,3}|`{1,3}|\[\[|\[|<|«)\s*)?(?:#{1,2}\s*)?"
_CLOSE = r"(?:\s*#{1,2})?(?:\s*(?:\*{1,3}|`{1,3}|\]\]|\]|>|»))?"

TAG_RE = re.compile(_OPEN + _CORE + _CLOSE, re.IGNORECASE)

#: Строгий поиск — только канонические формы (используется в verify()).
STRICT_TAG_RE = re.compile(
    rf"(?:#(?:{_LABEL_ALT})_\d+#|\[\[(?:{_LABEL_ALT})_\d+\]\]|<(?:{_LABEL_ALT})_\d+>)"
)


def make_tag(label: str, n: int, style: str = DEFAULT_STYLE) -> str:
    if style not in TAG_STYLES:
        raise ValueError(f"неизвестный стиль тега: {style}")
    return TAG_STYLES[style].format(label=label.upper(), n=n)


def tag_key(label: str, n: int) -> str:
    """Каноничный ключ тега в хранилище: PERSON_1."""
    return f"{label.upper()}_{int(n)}"


def find_tags(text: str) -> Iterable[re.Match]:
    return TAG_RE.finditer(text)


def strip_tags(text: str) -> str:
    """Убрать все теги (для проверок), не подставляя оригиналы."""
    return TAG_RE.sub("", text)
