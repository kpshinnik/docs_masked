#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP-сервер docs-masked: обезличивание документов как набор инструментов.

Транспорт — stdio, протокол — JSON-RPC 2.0 построчно, как требует спецификация
MCP. Реализация намеренно без зависимостей: сервер должен запускаться в любом
харнесе, где есть только python3, без установки SDK.

Инструменты:
    mask_text        текст -> текст с тегами + идентификатор сейфа
    unmask_text      текст с тегами + сейф -> оригиналы
    scan_document    что будет скрыто в файле (файл не меняется)
    mask_document    обезличенная копия файла + сейф
    unmask_document  восстановление файла по сейфу
    verify_text      проверка, что в тексте не осталось персональных данных

Сейфы лежат локально в ~/.docs_masked/vaults/ и никуда не отправляются.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pii_shield import (  # noqa: E402
    MaskConfig,
    Vault,
    mask_document,
    mask_text,
    unmask_document,
    unmask_text,
    verify,
)
from pii_shield.documents import open_document, supported_formats  # noqa: E402
from pii_shield.masker import mask_units  # noqa: E402

VAULT_DIR = Path(os.environ.get("DOCS_MASKED_HOME", Path.home() / ".docs_masked")) / "vaults"
PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "docs-masked", "version": "1.0.0"}


# --------------------------------------------------------------- хранение сейфов


def _save_vault(vault: Vault) -> str:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    vault_id = f"v{int(time.time())}-{uuid.uuid4().hex[:8]}"
    vault.save(VAULT_DIR / f"{vault_id}.json")
    return vault_id


def _load_vault(handle: str) -> Vault:
    """Принять и идентификатор сейфа, и путь к файлу сейфа."""
    candidate = VAULT_DIR / f"{handle}.json"
    path = candidate if candidate.exists() else Path(handle).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"сейф не найден: {handle}")
    return Vault.load(path)


def _config(args: dict[str, Any]) -> MaskConfig:
    cfg = MaskConfig(
        style=args.get("tag_style", "hash"),
        aggressive_names=bool(args.get("aggressive_names", False)),
        custom_terms=list(args.get("extra_terms") or []),
        allowlist=list(args.get("allowlist") or []),
    )
    if args.get("mask_all_dates"):
        cfg.enable("DATE")
    if args.get("mask_urls"):
        cfg.enable("URL")
    return cfg


def _summary(spans) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in spans:
        out[s.label] = out.get(s.label, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ------------------------------------------------------------------ инструменты


def t_mask_text(args: dict[str, Any]) -> dict[str, Any]:
    cfg = _config(args)
    result = mask_text(args["text"], cfg=cfg)
    residual = verify(result.text, cfg)
    vault_id = _save_vault(result.vault)
    return {
        "masked_text": result.text,
        "vault_id": vault_id,
        "replacements": len(result.spans),
        "by_type": _summary(result.spans),
        "safe_to_send": not residual,
        "residual": [{"kind": f.kind, "value": f.value} for f in residual],
    }


def t_unmask_text(args: dict[str, Any]) -> dict[str, Any]:
    vault = _load_vault(args["vault_id"])
    restored, unknown = unmask_text(args["text"], vault, args.get("mode", "canonical"))
    return {"text": restored, "unknown_tags": unknown}


def t_verify_text(args: dict[str, Any]) -> dict[str, Any]:
    findings = verify(args["text"], _config(args))
    return {
        "safe_to_send": not findings,
        "findings": [{"kind": f.kind, "value": f.value, "position": f.position}
                     for f in findings],
    }


def t_scan_document(args: dict[str, Any]) -> dict[str, Any]:
    cfg = _config(args)
    doc = open_document(Path(args["path"]).expanduser())
    units = doc.read_units()
    masked, vault, spans = mask_units(units, Vault(style=cfg.style), cfg,
                                      contexts=doc.read_contexts())
    residual = [f for u in masked for f in verify(u, cfg)]
    return {
        "fragments": len(units),
        "replacements": len(spans),
        "entities": len(vault.entities),
        "by_type": _summary(spans),
        "safe_to_send": not residual,
        "residual": [{"kind": f.kind, "value": f.value} for f in residual],
        # значения оригиналов сознательно не возвращаются: их незачем
        # поднимать в контекст модели
    }


def t_mask_document(args: dict[str, Any]) -> dict[str, Any]:
    cfg = _config(args)
    src = Path(args["path"]).expanduser()
    report = mask_document(src, out=args.get("out"), cfg=cfg,
                           vault_path=args.get("vault_path"),
                           pdf_redact=bool(args.get("pdf_redact", False)))
    return {
        "masked_path": str(report.masked_path),
        "vault_path": str(report.vault_path),
        "replacements": len(report.spans),
        "entities": len(report.vault.entities),
        "by_type": _summary(report.spans),
        "safe_to_send": report.clean,
        "residual": [{"kind": f.kind, "value": f.value} for f in report.residual],
        "masked_text": report.masked_text if args.get("include_text") else None,
    }


def t_unmask_document(args: dict[str, Any]) -> dict[str, Any]:
    written, unknown = unmask_document(Path(args["path"]).expanduser(),
                                       args["vault_path"], out=args.get("out"),
                                       mode=args.get("mode", "sequential"))
    return {"restored_path": str(written), "unknown_tags": unknown}


_COMMON = {
    "tag_style": {"type": "string", "enum": ["hash", "bracket", "angle"],
                  "description": "формат тега: #PERSON_1# | [[PERSON_1]] | <PERSON_1>"},
    "extra_terms": {"type": "array", "items": {"type": "string"},
                    "description": "дополнительные строки для маскирования"},
    "allowlist": {"type": "array", "items": {"type": "string"},
                  "description": "строки, которые маскировать не нужно"},
    "mask_all_dates": {"type": "boolean", "description": "скрывать все даты, не только даты рождения"},
    "mask_urls": {"type": "boolean", "description": "скрывать ссылки"},
    "aggressive_names": {"type": "boolean",
                         "description": "скрывать одиночные слова, похожие на фамилии"},
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "mask_text",
        "description": ("Заменить персональные данные в тексте на устойчивые теги "
                        "(#PERSON_1#, #PHONE_2#). Вызывай это ДО того, как отправишь "
                        "чужой текст куда-либо. Возвращает vault_id для обратной подстановки."),
        "inputSchema": {"type": "object", "required": ["text"],
                        "properties": {"text": {"type": "string"}, **_COMMON}},
        "handler": t_mask_text,
    },
    {
        "name": "unmask_text",
        "description": ("Вернуть оригиналы вместо тегов по сейфу. mode=canonical — для "
                        "ответа модели (ФИО в именительном падеже), mode=sequential — "
                        "точное восстановление ранее замаскированного текста."),
        "inputSchema": {"type": "object", "required": ["text", "vault_id"],
                        "properties": {
                            "text": {"type": "string"},
                            "vault_id": {"type": "string",
                                         "description": "идентификатор из mask_text или путь к файлу сейфа"},
                            "mode": {"type": "string", "enum": ["canonical", "sequential"]}}},
        "handler": t_unmask_text,
    },
    {
        "name": "verify_text",
        "description": ("Проверить, что в тексте не осталось персональных данных. "
                        "safe_to_send=false означает, что отправлять нельзя."),
        "inputSchema": {"type": "object", "required": ["text"],
                        "properties": {"text": {"type": "string"}, **_COMMON}},
        "handler": t_verify_text,
    },
    {
        "name": "scan_document",
        "description": ("Показать, что будет скрыто в файле: количество и типы находок. "
                        "Файл не изменяется, оригиналы значений не возвращаются. "
                        "Форматы: " + ", ".join(supported_formats())),
        "inputSchema": {"type": "object", "required": ["path"],
                        "properties": {"path": {"type": "string"}, **_COMMON}},
        "handler": t_scan_document,
    },
    {
        "name": "mask_document",
        "description": ("Создать обезличенную копию файла в том же формате и сейф "
                        "соответствий рядом. Для DOCX/XLSX сохраняется форматирование, "
                        "для PDF доступно физическое вымарывание (pdf_redact)."),
        "inputSchema": {"type": "object", "required": ["path"],
                        "properties": {
                            "path": {"type": "string"},
                            "out": {"type": "string", "description": "куда положить копию"},
                            "vault_path": {"type": "string"},
                            "pdf_redact": {"type": "boolean"},
                            "include_text": {"type": "boolean",
                                             "description": "вернуть замаскированный текст в ответе"},
                            **_COMMON}},
        "handler": t_mask_document,
    },
    {
        "name": "unmask_document",
        "description": "Восстановить оригиналы в ранее замаскированном файле по сейфу.",
        "inputSchema": {"type": "object", "required": ["path", "vault_path"],
                        "properties": {
                            "path": {"type": "string"},
                            "vault_path": {"type": "string"},
                            "out": {"type": "string"},
                            "mode": {"type": "string", "enum": ["sequential", "canonical"]}}},
        "handler": t_unmask_document,
    },
]

_BY_NAME = {t["name"]: t for t in TOOLS}


# ------------------------------------------------------------------ JSON-RPC


def _result(request_id: Any, payload: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "Прежде чем отправлять содержимое чужого документа в модель, "
                "прогони его через mask_text или mask_document, убедись что "
                "safe_to_send=true, и восстанови ответ через unmask_text."),
        })
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": [
            {k: v for k, v in t.items() if k != "handler"} for t in TOOLS]})
    if method == "tools/call":
        name = params.get("name")
        tool = _BY_NAME.get(name)
        if tool is None:
            return _error(request_id, -32602, f"неизвестный инструмент: {name}")
        try:
            payload = tool["handler"](params.get("arguments") or {})
            text = json.dumps(payload, ensure_ascii=False, indent=1)
            return _result(request_id, {"content": [{"type": "text", "text": text}],
                                        "isError": False})
        except Exception as exc:  # инструментальная ошибка, не протокольная
            return _result(request_id, {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True})
    if request_id is None:
        return None
    return _error(request_id, -32601, f"метод не поддерживается: {method}")


def main() -> int:
    stdin = sys.stdin
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
