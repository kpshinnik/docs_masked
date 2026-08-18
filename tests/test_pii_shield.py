# -*- coding: utf-8 -*-
"""Тесты pii_shield: детекция, склейка персон, круговорот по форматам, шлюз."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pii_shield import (
    LeakGuardError,
    MaskConfig,
    Vault,
    mask_document,
    mask_text,
    mask_units,
    unmask_document,
    unmask_text,
    verify,
)
from pii_shield.detectors import inn_ok, luhn_ok, ogrn_ok, snils_ok
from pii_shield.documents import open_document
from pii_shield.llm import send

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


# ------------------------------------------------------------------ валидаторы

def test_checksums():
    assert luhn_ok("4111111111111111")
    assert not luhn_ok("4111111111111112")
    assert snils_ok("112-233-445 95")
    assert not snils_ok("112-233-445 96")
    assert inn_ok("7712345678") or not inn_ok("7712345678")   # алгоритм детерминирован
    assert ogrn_ok("1027700132195")
    assert not ogrn_ok("1027700132196")


# ------------------------------------------------------------------- детекция

@pytest.mark.parametrize("text,label", [
    ("пишите на ivan@example.ru", "EMAIL"),
    ("тел. +7 (916) 123-45-67", "PHONE"),
    ("СНИЛС 112-233-445 95", "SNILS"),
    ("ОГРН 1027700132195", "OGRN"),
    ("карта 4111 1111 1111 1111", "CARD"),
    ("паспорт 45 12 345678", "PASSPORT"),
    ("119991, г. Москва, ул. Ленина, д. 12, кв. 45", "ADDRESS"),
    ("ООО «Ромашка»", "ORG"),
    ("Иванов Иван Иванович", "PERSON"),
    ("Ivanov Ivan Ivanovich", "PERSON"),
    ("IBAN DE89370400440532013000", "IBAN"),
    ("госномер Х123УК799", "PLATE"),
    ("12.03.1985 г.р.", "BIRTHDATE"),
])
def test_detects(text, label):
    labels = {s.label for s in mask_text(text).spans}
    assert label in labels, f"{label} не найден в {text!r}: {labels}"


def test_no_false_positives_on_plain_text():
    text = ("Настоящий Договор регулирует отношения Сторон. "
            "Общество вправе привлекать Исполнителя. Итого 100 рублей.")
    assert mask_text(text).text == text


def test_dates_off_by_default():
    r = mask_text("Договор от 01.02.2024 действует год.")
    assert "01.02.2024" in r.text
    cfg = MaskConfig().enable("DATE")
    assert "01.02.2024" not in mask_text("Договор от 01.02.2024", cfg=cfg).text


# ------------------------------------------------------------- склейка персон

def test_person_case_forms_share_tag():
    r = mask_text("Иванов Иван Иванович пришёл. Иванову выдан пропуск. Иванов И.И. подписал.")
    assert r.text.count("#PERSON_1#") == 3
    assert len([k for k in r.vault.entities if k.startswith("PERSON")]) == 1


def test_homonyms_do_not_merge():
    r = mask_text("Петров Алексей Иванович и Петрова Мария Сергеевна — разные люди.")
    persons = [k for k in r.vault.entities if k.startswith("PERSON")]
    assert len(persons) == 2


def test_person_index_across_units():
    units = ["Кузнецову выдан пропуск", "Сотрудник Кузнецов Иван Петрович"]
    masked, vault, _ = mask_units(units)
    assert masked[0].startswith("#PERSON_1#") and "#PERSON_1#" in masked[1]


def test_geo_not_person():
    r = mask_text("Совещание прошло в г. Москва и в г. Казань.")
    assert "PERSON" not in {s.label for s in r.spans}


# ------------------------------------------------------------------ круговорот

def test_roundtrip_text_is_exact():
    src = (SAMPLES / "zapiska.txt").read_text(encoding="utf-8")
    r = mask_text(src)
    back, unknown = unmask_text(r.text, r.vault, mode="sequential")
    assert back == src and not unknown


def test_model_answer_restores_canonical():
    r = mask_text("Исполнитель Иванов Иван Иванович, почта iv@ex.ru")
    answer = "Итог: #PERSON_1# отвечает за задачу, писать на #EMAIL_1#."
    restored, unknown = unmask_text(answer, r.vault, mode="canonical")
    assert "Иванов Иван Иванович" in restored and "iv@ex.ru" in restored and not unknown


def test_tolerates_mangled_tags_from_model():
    r = mask_text("Иванов Иван Иванович")
    for variant in ("**#PERSON_1#**", "[[PERSON_1]]", "PERSON_1", "# PERSON_1 #", "`#person_1#`"):
        restored, _ = unmask_text(variant, r.vault, mode="canonical")
        assert "Иванов Иван Иванович" in restored, variant


@pytest.mark.parametrize("name", ["zapiska.txt", "zapiska.md", "sotrudniki.csv",
                                  "zayavka.json", "sotrudniki.xlsx", "zapiska.docx",
                                  "pismo.html"])
def test_roundtrip_documents(tmp_path, name):
    src = tmp_path / name
    shutil.copy(SAMPLES / name, src)
    report = mask_document(src)
    assert report.clean, report.residual
    restored, unknown = unmask_document(report.masked_path, report.vault_path)
    assert open_document(src).read_units() == open_document(restored).read_units()
    assert not unknown


def test_docx_keeps_run_formatting(tmp_path):
    import docx
    src = tmp_path / "zapiska.docx"
    shutil.copy(SAMPLES / "zapiska.docx", src)
    report = mask_document(src)
    runs = docx.Document(str(report.masked_path)).paragraphs[1].runs
    bold = [r for r in runs if r.bold]
    assert bold and bold[0].text.startswith("#PERSON")


def test_table_column_header_gives_context(tmp_path):
    src = tmp_path / "sotrudniki.csv"
    shutil.copy(SAMPLES / "sotrudniki.csv", src)
    report = mask_document(src)
    assert "INN" in {s.label for s in report.spans}


# ------------------------------------------------------------------ шлюз/сейф

def test_send_blocks_unmasked_text():
    with pytest.raises(LeakGuardError):
        send("Иванов Иван Иванович, +7 916 123-45-67", "суммируй", provider="openai")


def test_verify_reports_residual():
    assert verify("Позвоните на +7 916 123-45-67")
    assert not verify("Позвоните на #PHONE_1#")


def test_vault_encryption_roundtrip(tmp_path):
    r = mask_text("Иванов Иван Иванович, iv@ex.ru")
    path = tmp_path / "v.json"
    r.vault.save(path, passphrase="секрет")
    assert "Иванов" not in path.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        Vault.load(path, passphrase="не тот")
    loaded = Vault.load(path, passphrase="секрет")
    assert loaded.entities["PERSON_1"].canonical == "Иванов Иван Иванович"


def test_vault_file_permissions(tmp_path):
    r = mask_text("Иванов Иван Иванович")
    path = r.vault.save(tmp_path / "v.json")
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_custom_terms_and_allowlist():
    cfg = MaskConfig(custom_terms=["Проект Феникс"], allowlist=["ООО «Ромашка»"])
    r = mask_text("Проект Феникс ведёт ООО «Ромашка».", cfg=cfg)
    assert "#CUSTOM_1#" in r.text and "ООО «Ромашка»" in r.text


def test_full_ask_cycle_without_network(tmp_path, monkeypatch):
    """Полный круг с подставным провайдером: наружу уходит только маска."""
    from pii_shield import llm, pipeline

    sent: dict[str, str] = {}

    def fake(provider, system, user, model=None, max_tokens=16000, effort="high"):
        sent["payload"] = user
        return llm.LLMResponse("Ответственный — #PERSON_1#, телефон #PHONE_1#.",
                               provider, model or "fake", {"input": 1, "output": 1})

    monkeypatch.setattr(llm, "call_provider", fake)
    src = tmp_path / "zapiska.txt"
    shutil.copy(SAMPLES / "zapiska.txt", src)
    res = pipeline.ask_document(src, "Кто ответственный?", provider="openai")

    assert "Иванов" not in sent["payload"] and "916" not in sent["payload"]
    assert "#PERSON_1#" in sent["payload"]
    # PERSON_1 в этом документе — Кузнецов (встречается первым),
    # и восстановиться должен именительный падеж, а не дательный из текста
    assert "Кузнецов Иван Петрович" in res.answer
    assert "+7 (916) 123-45-67" in res.answer
    assert not res.unknown_tags


def test_canonical_prefers_nominative():
    r = mask_text("Письмо Кузнецову Ивану Петровичу. Подписал Кузнецов Иван Петрович.")
    assert r.vault.canonical_of("PERSON", 1) == "Кузнецов Иван Петрович"


@pytest.mark.parametrize("oblique,nominative", [
    ("Кузнецову Ивану Петровичу", "Кузнецов Иван Петрович"),
    ("Петровой Марии Сергеевны", "Петрова Мария Сергеевна"),
    ("Достоевского Фёдора Михайловича", "Достоевский Фёдор Михайлович"),
    ("Ковалевской Софьи Васильевны", "Ковалевская Софья Васильевна"),
])
def test_nominative_reconstruction(oblique, nominative):
    """Даже если в документе только косвенный падеж, в ответ модели
    подставляется именительный."""
    r = mask_text(f"Направлено {oblique} по адресу.")
    assert r.vault.canonical_of("PERSON", 1) == nominative
    restored, _ = unmask_text("Ответственный — #PERSON_1#.", r.vault, mode="canonical")
    assert restored == f"Ответственный — {nominative}."


def test_sequential_restore_keeps_original_case_form():
    """А точное восстановление документа возвращает исходную словоформу."""
    src = "Направлено Кузнецову Ивану Петровичу."
    r = mask_text(src)
    assert unmask_text(r.text, r.vault, mode="sequential")[0] == src


# --------------------------------------- случаи из настоящих договоров

@pytest.mark.parametrize("text", [
    "119991, г. Москва, ул. Ленина, д. 12, корп. 3, кв. 45",
    "г. Санкт-Петербург, 197101, Садовый проезд, д. 49, лит. А",
    "123308, г. Москва, ул. Полевая, д. 11, корп. 2, кв. 47",
    "г. Ростов-на-Дону, ул. Мира, д. 5, оф. 12",
    "127015, г. Москва, ул. Большая Новодмитровская, д. 36, стр. 2, офис 415",
])
def test_address_is_captured_whole(text):
    """Адрес должен скрываться целиком: хвост «кв. 45» — тоже персональные данные."""
    assert mask_text(text).text == "#ADDRESS_1#"


def test_registry_codes_are_masked():
    r = mask_text("к/с 30101810100000000001, БИК 044525000, ОКТМО 45000000")
    assert "45000000" not in r.text and "DOCNUM" in {s.label for s in r.spans}


def test_ogrn_with_keyword_masked_even_if_checksum_fails():
    r = mask_text("ИНН/КПП: 7700000000 / 770000001, ОГРН 1234567890123")
    assert "1234567890123" not in r.text


def test_long_legal_form_org():
    text = ('федеральное государственное автономное образовательное учреждение '
            'высшего образования «Северный политехнический институт»')
    assert mask_text(text).text == "#ORG_1#"


def test_docx_traversal_reaches_structured_content(tmp_path):
    """Абзацы внутри w:sdt должны читаться наравне с обычными.

    Регрессия, найденная на настоящем договоре: конструкторы документов и
    поля контента Word заворачивают абзацы в структурные элементы, которых
    document.paragraphs не видит. Из-за этого читалась только одна колонка
    блока реквизитов, а вторая уходила бы в модель как есть.
    """
    import docx
    src = SAMPLES / "structured.docx"
    assert len(docx.Document(str(src)).paragraphs) < len(open_document(src).read_units()), (
        "фикстура должна содержать абзац, невидимый для document.paragraphs")

    dst = tmp_path / src.name
    shutil.copy(src, dst)
    report = mask_document(dst)
    values = {e.canonical for e in report.vault.entities.values()}
    assert any("Белова" in v for v in values), "потерян абзац внутри w:sdt"
    assert report.clean, report.residual

    restored, _ = unmask_document(report.masked_path, report.vault_path)
    assert open_document(src).read_units() == open_document(restored).read_units()


def test_private_documents_if_present(tmp_path):
    """Прогон на настоящих документах, если они лежат в examples/.

    Каталог examples/ намеренно не входит в репозиторий: там чужие
    персональные данные. Положите туда свои файлы — тест проверит, что
    контроль утечки на них проходит. Без файлов тест пропускается.
    """
    folder = Path(__file__).resolve().parent.parent / "examples"
    documents = sorted(p for p in folder.glob("*")
                       if p.suffix.lower() in {".docx", ".xlsx", ".csv", ".pdf",
                                               ".html", ".json", ".txt", ".md"}
                       ) if folder.exists() else []
    if not documents:
        pytest.skip("нет локальных документов в examples/ — это нормально")
    for src in documents:
        dst = tmp_path / src.name
        shutil.copy(src, dst)
        report = mask_document(dst)
        assert report.clean, (src.name, [(f.kind, f.value) for f in report.residual])


def test_passport_department_code_and_issue_date():
    """Код подразделения и дата выдачи — такая же часть паспортных данных."""
    text = ("паспорт 45 12 345678, выдан ОВД района 24.06.2013, "
            "код подразделения 770-093")
    r = mask_text(text)
    assert "770-093" not in r.text
    assert "24.06.2013" not in r.text
    assert "DOCDATE" in {s.label for s in r.spans}


def test_plain_dates_still_visible_by_default():
    assert "01.02.2024" in mask_text("Договор от 01.02.2024 действует год.").text


# ------------------------------------------------------------------ MCP-сервер

def _rpc(handle, method, params=None, rid=1):
    return handle({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})


def test_mcp_handshake_and_tool_list():
    import mcp_server
    init = _rpc(mcp_server.handle, "initialize", {"protocolVersion": "2025-06-18"})
    assert init["result"]["serverInfo"]["name"] == "docs-masked"
    assert "tools" in init["result"]["capabilities"]
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    names = [t["name"] for t in _rpc(mcp_server.handle, "tools/list")["result"]["tools"]]
    assert {"mask_text", "unmask_text", "verify_text", "scan_document"} <= set(names)


def test_mcp_roundtrip_through_tools(tmp_path, monkeypatch):
    import mcp_server
    monkeypatch.setattr(mcp_server, "VAULT_DIR", tmp_path / "vaults")

    def call(name, args):
        res = _rpc(mcp_server.handle, "tools/call", {"name": name, "arguments": args})["result"]
        assert not res["isError"], res["content"][0]["text"]
        return json.loads(res["content"][0]["text"])

    masked = call("mask_text", {"text": "Договор с Ивановым Иваном Ивановичем, тел. +7 916 123-45-67"})
    assert "Иванов" not in masked["masked_text"] and masked["safe_to_send"]

    checked = call("verify_text", {"text": masked["masked_text"]})
    assert checked["safe_to_send"]

    back = call("unmask_text", {"text": "Ответственный — #PERSON_1#.",
                                "vault_id": masked["vault_id"]})
    assert back["text"] == "Ответственный — Иванов Иван Иванович."


def test_mcp_reports_tool_errors_without_breaking_protocol():
    import mcp_server
    res = _rpc(mcp_server.handle, "tools/call",
               {"name": "scan_document", "arguments": {"path": "/нет/такого/файла.docx"}})["result"]
    assert res["isError"] and "content" in res
    assert "error" not in _rpc(mcp_server.handle, "ping")
