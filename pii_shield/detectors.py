# -*- coding: utf-8 -*-
"""Детекторы структурированных персональных данных (RU + международные).

Каждый детектор возвращает Span. Приоритет решает конфликты перекрытий:
чем выше число, тем «сильнее» детектор (при равном приоритете побеждает
более длинный спан).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterator

from .dictionaries import BIRTH_CONTEXT, LEGAL_FORMS

# ------------------------------------------------------------------ структуры


@dataclass
class Span:
    start: int
    end: int
    label: str
    value: str
    priority: int = 50
    note: str = ""
    #: подсказка для обратной подстановки (напр. ФИО в именительном падеже)
    hint: str = ""

    def __len__(self) -> int:  # noqa: D105
        return self.end - self.start


Detector = Callable[[str], Iterator[Span]]
_REGISTRY: list[tuple[str, Detector]] = []


def detector(name: str):
    def wrap(fn: Detector) -> Detector:
        _REGISTRY.append((name, fn))
        return fn
    return wrap


def all_detectors() -> list[tuple[str, Detector]]:
    return list(_REGISTRY)


# ------------------------------------------------------------------ валидаторы


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def luhn_ok(num: str) -> bool:
    d = _digits(num)
    if not 12 <= len(d) <= 19:
        return False
    total, alt = 0, False
    for ch in reversed(d):
        v = ord(ch) - 48
        if alt:
            v *= 2
            if v > 9:
                v -= 9
        total += v
        alt = not alt
    return total % 10 == 0


def snils_ok(num: str) -> bool:
    d = _digits(num)
    if len(d) != 11 or len(set(d[:9])) == 1:
        return False
    s = sum(int(d[i]) * (9 - i) for i in range(9))
    if s < 100:
        ctrl = s
    elif s in (100, 101):
        ctrl = 0
    else:
        s %= 101
        ctrl = 0 if s in (100, 101) else s
    return ctrl == int(d[9:])


def inn_ok(num: str) -> bool:
    d = _digits(num)
    if len(d) == 10:
        w = (2, 4, 10, 3, 5, 9, 4, 6, 8)
        c = sum(int(d[i]) * w[i] for i in range(9)) % 11 % 10
        return c == int(d[9])
    if len(d) == 12:
        w1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        w2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        c1 = sum(int(d[i]) * w1[i] for i in range(10)) % 11 % 10
        c2 = sum(int(d[i]) * w2[i] for i in range(11)) % 11 % 10
        return c1 == int(d[10]) and c2 == int(d[11])
    return False


def ogrn_ok(num: str) -> bool:
    d = _digits(num)
    if len(d) == 13:
        return int(d[:12]) % 11 % 10 == int(d[12])
    if len(d) == 15:
        return int(d[:14]) % 13 % 10 == int(d[14])
    return False


def iban_ok(s: str) -> bool:
    t = re.sub(r"\s", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", t):
        return False
    t = t[4:] + t[:4]
    conv = "".join(str(ord(c) - 55) if c.isalpha() else c for c in t)
    return int(conv) % 97 == 1


def _has_context(text: str, pos: int, words: tuple[str, ...], window: int = 42) -> bool:
    left = text[max(0, pos - window):pos].lower()
    return any(w in left for w in words)


# ------------------------------------------------------------------ детекторы

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}\b")


@detector("email")
def d_email(text: str) -> Iterator[Span]:
    for m in EMAIL_RE.finditer(text):
        yield Span(m.start(), m.end(), "EMAIL", m.group(0), 95)


URL_RE = re.compile(r"\bhttps?://[^\s<>\"')\]]+|\bwww\.[A-Za-z0-9.\-]+\.[A-Za-z]{2,12}[^\s<>\"')\]]*")


@detector("url")
def d_url(text: str) -> Iterator[Span]:
    for m in URL_RE.finditer(text):
        yield Span(m.start(), m.end(), "URL", m.group(0), 40)


HANDLE_RE = re.compile(r"(?<![\w@./])@[A-Za-z][A-Za-z0-9_]{3,31}\b")


@detector("handle")
def d_handle(text: str) -> Iterator[Span]:
    for m in HANDLE_RE.finditer(text):
        yield Span(m.start(), m.end(), "HANDLE", m.group(0), 85)


PHONE_CTX = ("тел", "phone", "моб", "факс", "fax", "whatsapp", "viber", "telegram", "звон", "call")
_PHONE_CAND = re.compile(r"(?<![\d\w])\+?[\d][\d \t\-()–—.]{7,22}\d(?![\d\w])")


@detector("phone")
def d_phone(text: str) -> Iterator[Span]:
    for m in _PHONE_CAND.finditer(text):
        raw = m.group(0)
        d = _digits(raw)
        if not 10 <= len(d) <= 15:
            continue
        plus = raw.lstrip().startswith("+")
        formatted = bool(re.search(r"[\s\-()]", raw.strip()))
        ru = len(d) == 11 and d[0] in "78"
        if not (plus or ru or (formatted and len(d) >= 10) or _has_context(text, m.start(), PHONE_CTX)):
            continue
        s, e = m.start(), m.end()
        while s < e and text[s] in " \t":
            s += 1
        yield Span(s, e, "PHONE", text[s:e], 88)


SNILS_RE = re.compile(r"(?<!\d)\d{3}[\- ]\d{3}[\- ]\d{3}[ \-]\d{2}(?!\d)|(?<!\d)\d{11}(?!\d)")


@detector("snils")
def d_snils(text: str) -> Iterator[Span]:
    for m in SNILS_RE.finditer(text):
        raw = m.group(0)
        ok = snils_ok(raw)
        ctx = _has_context(text, m.start(), ("снилс", "снилc", "страхов", "пенсион"))
        formatted = bool(re.search(r"[\-\s]", raw))
        if ok and (formatted or ctx):
            yield Span(m.start(), m.end(), "SNILS", raw, 94)
        elif ctx:
            # ключевое слово важнее контрольной суммы — иначе номер уедет
            # в телефоны и потеряет правильную метку
            yield Span(m.start(), m.end(), "SNILS", raw, 92)


INN_RE = re.compile(r"(?<!\d)\d{10}(?!\d)|(?<!\d)\d{12}(?!\d)")


@detector("inn")
def d_inn(text: str) -> Iterator[Span]:
    for m in INN_RE.finditer(text):
        raw = m.group(0)
        ctx = _has_context(text, m.start(), ("инн", "inn", "налогоплат"))
        ok = inn_ok(raw)
        if ctx:
            # при явном ключевом слове маскируем даже если контрольная сумма
            # не сошлась: это всё равно чей-то идентификатор.
            yield Span(m.start(), m.end(), "INN", raw, 90 if ok else 75)
        elif ok and len(raw) == 12:
            yield Span(m.start(), m.end(), "INN", raw, 70)


OGRN_RE = re.compile(r"(?<!\d)\d{13}(?!\d)|(?<!\d)\d{15}(?!\d)")


@detector("ogrn")
def d_ogrn(text: str) -> Iterator[Span]:
    for m in OGRN_RE.finditer(text):
        ok = ogrn_ok(m.group(0))
        ctx = _has_context(text, m.start(), ("огрн", "ogrn"))
        if ok or ctx:
            # ключевое слово важнее контрольного разряда: опечатка в документе
            # не повод оставить регистрационный номер открытым
            yield Span(m.start(), m.end(), "OGRN", m.group(0), 90 if ok else 75)


@detector("kpp")
def d_kpp(text: str) -> Iterator[Span]:
    for m in re.finditer(r"(?<!\d)\d{9}(?!\d)", text):
        if _has_context(text, m.start(), ("кпп",)):
            yield Span(m.start(), m.end(), "KPP", m.group(0), 92)
        elif _has_context(text, m.start(), ("бик",)) or m.group(0).startswith("04"):
            yield Span(m.start(), m.end(), "BIK", m.group(0), 92)


@detector("account")
def d_account(text: str) -> Iterator[Span]:
    for m in re.finditer(r"(?<!\d)\d{20}(?!\d)|(?<!\d)(?:\d{4}[ \-]){4}\d{4}(?!\d)", text):
        d = _digits(m.group(0))
        if len(d) == 20:
            yield Span(m.start(), m.end(), "ACCOUNT", m.group(0), 90)


CARD_RE = re.compile(r"(?<![\d\-])(?:\d[ \-]?){12,18}\d(?![\d\-])")


@detector("card")
def d_card(text: str) -> Iterator[Span]:
    for m in CARD_RE.finditer(text):
        d = _digits(m.group(0))
        if 13 <= len(d) <= 19 and luhn_ok(d):
            yield Span(m.start(), m.end(), "CARD", m.group(0), 93)


IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b")


@detector("iban")
def d_iban(text: str) -> Iterator[Span]:
    for m in IBAN_RE.finditer(text):
        if iban_ok(m.group(0)):
            yield Span(m.start(), m.end(), "IBAN", m.group(0), 93)


PASSPORT_RE = re.compile(r"(?<!\d)(\d{2} ?\d{2}) ?(?:№ ?)?(\d{6})(?!\d)")


@detector("passport")
def d_passport(text: str) -> Iterator[Span]:
    ctx_words = ("паспорт", "серия", "серии", "passport", "удостоверя", "документ")
    for m in PASSPORT_RE.finditer(text):
        spaced = " " in m.group(0)
        if spaced or _has_context(text, m.start(), ctx_words, 60):
            yield Span(m.start(), m.end(), "PASSPORT", m.group(0), 91)
    for m in re.finditer(r"\b\d{9}\b", text):
        if _has_context(text, m.start(), ("загранпаспорт", "заграничн")):
            yield Span(m.start(), m.end(), "PASSPORT", m.group(0), 91)
    # код подразделения — такая же часть паспортных данных, как серия и номер
    for m in re.finditer(r"(?:код\s+подразделения|к/п)[ \t]*[:№]?[ \t]*(\d{3}[ \-]?\d{3})",
                         text, re.IGNORECASE):
        yield Span(m.start(1), m.end(1), "PASSPORT", m.group(1), 92)


@detector("policy_oms")
def d_policy(text: str) -> Iterator[Span]:
    for m in re.finditer(r"(?<!\d)\d{16}(?!\d)", text):
        if _has_context(text, m.start(), ("полис", "омс", "дмс")):
            yield Span(m.start(), m.end(), "POLICY", m.group(0), 90)


@detector("driver_license")
def d_license(text: str) -> Iterator[Span]:
    pat = re.compile(r"(?<![\w])\d{2} ?[А-ЯЁ0-9]{2} ?\d{6}(?![\w])")
    for m in pat.finditer(text):
        if _has_context(text, m.start(), ("вод", "прав", "удостоверен", "в/у", "license"), 50):
            yield Span(m.start(), m.end(), "LICENSE", m.group(0), 89)


PLATE_RE = re.compile(r"(?<![\wА-ЯЁ])[АВЕКМНОРСТУХ] ?\d{3} ?[АВЕКМНОРСТУХ]{2} ?\d{2,3}(?![\wА-ЯЁ])")


@detector("plate")
def d_plate(text: str) -> Iterator[Span]:
    for m in PLATE_RE.finditer(text):
        yield Span(m.start(), m.end(), "PLATE", m.group(0), 87)


IP_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")


@detector("ip")
def d_ip(text: str) -> Iterator[Span]:
    for m in IP_RE.finditer(text):
        yield Span(m.start(), m.end(), "IP", m.group(0), 80)


MONTHS = ("январ", "феврал", "март", "апрел", "мая", "мае", "июн", "июл", "август",
          "сентябр", "октябр", "ноябр", "декабр")
DATE_RE = re.compile(
    r"(?<![\d.])\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}(?!\.?\d)"
    r"|(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)"
    r"|(?<![\w])\d{1,2}\s+(?:" + "|".join(MONTHS) + r")[а-яё]*\s+\d{4}(?:\s*г\.?(?:ода)?)?"
)


ISSUE_CONTEXT = ("выдан", "выдано", "выдана", "дата выдачи", "issued", "действителен до",
                 "срок действия", "зарегистрирован")


@detector("date")
def d_date(text: str) -> Iterator[Span]:
    for m in DATE_RE.finditer(text):
        after = text[m.end():m.end() + 30].lower()
        birth = (_has_context(text, m.start(), BIRTH_CONTEXT, 45)
                 or any(k in after[:18] for k in ("г.р", "года рожд", "г. р."))
                 or "рожд" in after[:22])
        if birth:
            yield Span(m.start(), m.end(), "BIRTHDATE", m.group(0), 86)
            continue
        # дата выдачи документа — часть паспортных данных, скрываем по умолчанию
        if _has_context(text, m.start(), ISSUE_CONTEXT, 90):
            yield Span(m.start(), m.end(), "DOCDATE", m.group(0), 84)
            continue
        yield Span(m.start(), m.end(), "DATE", m.group(0), 20)


_GEO = (r"(?:г|гор|город|с|село|д|дер|пос|пгт|ст|обл|край|р-н|район|респ|мкр)\.?\s*"
        r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁа-яё][а-яё]+)*")
_INDEX = r"(?<!\d)\d{6}(?!\d)"
#: город и индекс могут идти в любом порядке и повторяться
_LEAD = r"(?:(?:" + _INDEX + r"|" + _GEO + r"),?\s*){0,4}"
_MARK = (r"(?:ул|улица|пр-т|пр-кт|просп|проспект|пр|пер|переулок|ш|шоссе|б-р|бульвар"
         r"|наб|набережная|пл|площадь|проезд|тупик|линия|аллея)")
#: маркер улицы бывает и до названия («ул. Ленина»), и после («Садовый проезд»)
_STREET = (r"(?:" + _MARK + r"\.?\s*[А-ЯЁ0-9][^,;\n]{0,45}?"
           r"|[А-ЯЁ][А-Яа-яёЁ0-9\- ]{1,40}?\s+" + _MARK + r"\.?)")
_HOUSE = r"(?:д|дом|влд|вл)\.?\s*\d+[а-яА-ЯёЁ]?(?:[/\-]\d+[а-яА-Я]?)?"
_UNITS = "|".join(sorted(
    ["квартира", "корпус", "строение", "строен", "помещение", "помещ", "литера",
     "корп", "стр", "лит", "кв", "оф", "офис", "пом", "эт", "этаж", "к"],
    key=len, reverse=True))
_EXTRA = (r"(?:,?\s*(?:" + _UNITS + r")\.?\s*"
          r"(?:\d+[а-яА-ЯёЁ]?|[А-ЯЁа-яё](?![а-яё])))*")
ADDRESS_RE = re.compile(_LEAD + _STREET + r",?\s*" + _HOUSE + _EXTRA)
ADDRESS_SHORT_RE = re.compile(r"\b" + _INDEX + r",\s*(?:" + _GEO + r",?\s*){1,3}" + _STREET)


@detector("address")
def d_address(text: str) -> Iterator[Span]:
    seen: list[tuple[int, int]] = []
    for m in ADDRESS_RE.finditer(text):
        seen.append((m.start(), m.end()))
        yield Span(m.start(), m.end(), "ADDRESS", m.group(0), 84)
    for m in ADDRESS_SHORT_RE.finditer(text):
        if not any(s <= m.start() < e for s, e in seen):
            yield Span(m.start(), m.end(), "ADDRESS", m.group(0), 82)


_FORMS = "|".join(sorted(set(LEGAL_FORMS), key=len, reverse=True))
ORG_RE = re.compile(r"\b(?:" + _FORMS + r")\.?\s*[«\"'][^»\"'\n]{1,70}[»\"']")
#: развёрнутая организационно-правовая форма: «федеральное государственное … «Политехнический институт»»
ORG_LONG_RE = re.compile(
    r"(?:федеральн\w+|государственн\w+|муниципальн\w+|автономн\w+|бюджетн\w+|казённ\w+"
    r"|казенн\w+|обществ\w+|акционерн\w+|некоммерческ\w+|публичн\w+)"
    r"[^«»\n]{0,90}«[^»\n]{1,80}»", re.IGNORECASE)


@detector("org")
def d_org(text: str) -> Iterator[Span]:
    for m in ORG_RE.finditer(text):
        yield Span(m.start(), m.end(), "ORG", m.group(0), 78)
    for m in ORG_LONG_RE.finditer(text):
        yield Span(m.start(), m.end(), "ORG", m.group(0), 77)


REGISTRY_KEYWORDS = (r"(?:ОКТМО|ОКПО|ОКАТО|ОКОГУ|ОКФС|ОКОПФ|ОКВЭД|ОКУД|КБК|УИН|УИП"
                     r"|л/с|лиц\.?\s*сч[её]т[а-я]*|лицев\w*\s+сч[её]т[а-я]*"
                     r"|рег\.?\s*№|регистрационн\w+\s+номер)")
_REGISTRY_RE = re.compile(REGISTRY_KEYWORDS + r"[ \t]*[:№#\-]?[ \t]*(\d[\d \t.\-]{3,28}\d)",
                          re.IGNORECASE)


@detector("registry_code")
def d_registry_code(text: str) -> Iterator[Span]:
    """Коды из реквизитов: ОКТМО, ОКПО, КБК, лицевой счёт и подобные.

    Сами по себе это не персональные данные, но в связке с организацией и
    счётом они идентифицируют сторону — и без них текст не проходит
    параноидальную проверку.
    """
    for m in _REGISTRY_RE.finditer(text):
        yield Span(m.start(1), m.end(1), "DOCNUM", m.group(1).strip(), 92)


# ------------------------------------------------- латиница и транслит ФИО

LATIN_STOP = {
    "The", "This", "That", "And", "For", "With", "From", "Company", "Ltd", "Inc",
    "Corp", "Group", "Bank", "Street", "Avenue", "Road", "City", "Region", "State",
    "Russia", "Moscow", "Saint", "Petersburg", "Kazan", "Minsk", "Kiev", "Kyiv",
    "Almaty", "Astana", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December", "Monday",
    "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "Total", "Subject", "Date", "Number", "Address", "Phone", "Email", "Contract",
    "Agreement", "Attachment", "Note", "Page", "Section", "Article", "Chapter",
    "General", "Director", "Manager", "Chief", "Head", "Senior", "Junior", "Lead",
}
_TITLE = r"(?:Mr|Mrs|Ms|Miss|Dr|Prof|Sir)\.?"
_SLAVIC_TAIL = (r"(?:ovich|evich|ovna|evna|ich|ov|ova|ev|eva|yov|yova|in|ina|yn|yna"
                r"|sky|skiy|skaya|tsky|tskaya|enko|chuk|uk|yuk|yan|dze|shvili|adze)")
_LATIN_NAME_RUN = re.compile(r"\b[A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){1,2}\b")
_TITLED = re.compile(rf"\b{_TITLE}\s+[A-Z][a-z]{{1,20}}(?:\s+[A-Z][a-z]{{1,20}}){{0,2}}\b")
_TAIL_RE = re.compile(_SLAVIC_TAIL + r"$", re.IGNORECASE)


def _latin_key(words: list[str]) -> str:
    """Ключ склейки: слово со славянским исходом (обычно фамилия)."""
    for w in words:
        if _TAIL_RE.search(w) and not _TAIL_RE.fullmatch(w):
            return w.lower()
    return " ".join(w.lower() for w in words)


@detector("latin_person")
def d_latin_person(text: str) -> Iterator[Span]:
    seen: list[tuple[int, int]] = []
    for m in _TITLED.finditer(text):
        seen.append((m.start(), m.end()))
        words = re.sub(rf"^{_TITLE}\s+", "", m.group(0)).split()
        yield Span(m.start(), m.end(), "PERSON", m.group(0), 80,
                   note=repr(("latin", _latin_key(words), "", "")))
    for m in _LATIN_NAME_RUN.finditer(text):
        if any(a <= m.start() < b for a, b in seen):
            continue
        words = m.group(0).split()
        if any(w in LATIN_STOP for w in words):
            continue
        if not any(_TAIL_RE.search(w) for w in words):
            continue
        yield Span(m.start(), m.end(), "PERSON", m.group(0), 78,
                   note=repr(("latin", _latin_key(words), "", "")))


def custom_terms_detector(terms: list[str]) -> Detector:
    """Детектор пользовательских литералов (проектные имена, внутренние коды)."""
    cleaned = [t for t in (s.strip() for s in terms) if t]
    if not cleaned:
        return lambda text: iter(())
    pat = re.compile("|".join(re.escape(t) for t in sorted(cleaned, key=len, reverse=True)),
                     re.IGNORECASE)

    def _d(text: str) -> Iterator[Span]:
        for m in pat.finditer(text):
            yield Span(m.start(), m.end(), "CUSTOM", m.group(0), 99)
    return _d


# ------------------------------------------------------------------ разрешение


def resolve_overlaps(spans: list[Span]) -> list[Span]:
    """Убрать пересечения: сначала приоритет, затем длина, затем позиция."""
    ordered = sorted(spans, key=lambda s: (-s.priority, -len(s), s.start))
    kept: list[Span] = []
    for sp in ordered:
        if any(sp.start < k.end and k.start < sp.end for k in kept):
            continue
        kept.append(sp)
    kept.sort(key=lambda s: s.start)
    return kept
