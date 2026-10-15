"""Регрессия: полные ФИО, которые детектор раньше пропускал в таблицах.

Все имена вымышленные. Случаи взяты из класса ошибок, найденного на выгрузке
активности сотрудников: имя совпало со стоп-словом, редкие имя/фамилия без
типовых суффиксов, формы «оглы/кызы», ячейка под заголовком «ФИО».
"""
import re

import pytest

from pii_shield.masker import mask_units
from pii_shield import names_ru as nru

TAG = re.compile(r"#PERSON_\d+#")


def _mask_cell(value: str, header: str = "ФИО") -> str:
    out, _vault, _spans = mask_units([value], contexts=[header])
    return out[0]


@pytest.mark.parametrize("fio", [
    "Сидоров Владимир Иванович",        # имя совпадает со стоп-словом (город)
    "Кузнецов Герман Петрович",         # то же
    "Вертинская Любовь Ааронова",       # редкое отчество без типового суффикса фамилии
    "Рашидов Эльчин Аликович оглы",     # тюркская форма
    "Мамедова Лейла Алиевна кызы",
])
def test_full_name_in_fio_column_is_fully_masked(fio):
    masked = _mask_cell(fio)
    assert TAG.fullmatch(masked.strip()), masked


@pytest.mark.parametrize("fio", [
    "Сидоров Владимир Иванович",
    "Иванова Хаджар Рашидовна",
])
def test_patronymic_anchors_three_capitalized_words_without_header(fio):
    mentions = nru.find_person_mentions(fio)
    assert len(mentions) == 1 and mentions[0].surface == fio


def test_ogly_form_is_one_mention():
    text = "Заявитель Рашидов Эльчин Аликович оглы подписал акт."
    ms = nru.find_person_mentions(text)
    assert len(ms) == 1 and ms[0].surface.endswith("оглы")


def test_same_person_gets_one_tag_across_cells():
    out, _v, _s = mask_units(["Рашидов Эльчин Аликович оглы", "Рашидов Эльчин Аликович оглы"],
                             contexts=["ФИО", "ФИО"])
    assert out[0] == out[1] and TAG.fullmatch(out[0])


@pytest.mark.parametrize("value, header", [
    ("Центр аналитики", "Отдел"),              # не заголовок ФИО
    ("Ведущий разработчик", "Должность"),
    ("Отдел продаж 2026", "ФИО"),              # цифры — не имя
    ("Менеджер", "ФИО"),                       # одно слово — не целая ячейка-человек
])
def test_header_rule_does_not_overmask(value, header):
    assert _mask_cell(value, header) == value
