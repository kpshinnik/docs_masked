# -*- coding: utf-8 -*-
"""Сценарии верхнего уровня: файл -> маска -> модель -> обратная подстановка."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import llm
from .detectors import Span
from .documents import DocumentAdapter, PdfAdapter, open_document
from .masker import (
    MaskConfig,
    assert_clean,
    mask_units,
    unmask_text,
    verify,
)
from .vault import Vault


@dataclass
class MaskReport:
    source: Path
    masked_path: Path | None
    vault_path: Path | None
    vault: Vault
    spans: list[Span]
    masked_units: list[str] = field(default_factory=list)
    residual: list[Any] = field(default_factory=list)

    @property
    def masked_text(self) -> str:
        return "\n".join(self.masked_units)

    @property
    def clean(self) -> bool:
        return not self.residual


def mask_document(path: str | Path, out: str | Path | None = None,
                  cfg: MaskConfig | None = None,
                  vault_path: str | Path | None = None,
                  passphrase: str | None = None,
                  write: bool = True,
                  pdf_redact: bool = False) -> MaskReport:
    """Обезличить документ на диске. Возвращает отчёт и заполненный сейф."""
    cfg = cfg or MaskConfig()
    doc: DocumentAdapter = open_document(path)
    units = doc.read_units()
    masked, vault, spans = mask_units(units, Vault(style=cfg.style), cfg,
                                      contexts=doc.read_contexts())
    vault.meta = {"source": str(Path(path).resolve()), "units": len(units),
                  "replacements": len(spans)}

    residual = [f for u in masked for f in verify(u, cfg)]

    masked_path: Path | None = None
    if write:
        target = Path(out) if out else doc.default_out()
        if pdf_redact and isinstance(doc, PdfAdapter):
            pairs = [(occ["original"], vault.rendered(occ["tag"])) for occ in vault.occurrences]
            masked_path = doc.redact(pairs, target)
        else:
            masked_path = doc.write_units(masked, target)

    vpath: Path | None = None
    if vault_path is not False:
        vpath = Path(vault_path) if vault_path else Path(path).with_suffix(
            Path(path).suffix + ".vault.json")
        vault.save(vpath, passphrase)

    return MaskReport(Path(path), masked_path, vpath, vault, spans, masked, residual)


def unmask_document(path: str | Path, vault_path: str | Path,
                    out: str | Path | None = None, mode: str = "sequential",
                    passphrase: str | None = None) -> tuple[Path, list[str]]:
    """Вернуть оригиналы в файл, замаскированный этим же инструментом."""
    vault = Vault.load(vault_path, passphrase)
    doc = open_document(path)
    units = doc.read_units()
    restored: list[str] = []
    unknown: list[str] = []
    state: dict = {}
    for u in units:
        text, unk = unmask_text(u, vault, mode, state)
        restored.append(text)
        unknown.extend(unk)
    target = Path(out) if out else Path(path).with_name(
        Path(path).stem.replace(".masked", "") + ".restored" + Path(path).suffix)
    written = doc.write_units(restored, target)
    return written, sorted(set(unknown))


@dataclass
class AskResult:
    answer: str
    answer_masked: str
    report: MaskReport
    response: llm.LLMResponse
    unknown_tags: list[str]


def ask_document(path: str | Path, instruction: str, provider: str = "anthropic",
                 model: str | None = None, cfg: MaskConfig | None = None,
                 keep_masked: bool = False, vault_path: str | Path | None = None,
                 passphrase: str | None = None, max_tokens: int = 16000,
                 effort: str = "high", allow_unverified: bool = False) -> AskResult:
    """Полный круг: обезличить -> проверить -> отправить -> восстановить ответ."""
    cfg = cfg or MaskConfig()
    report = mask_document(path, cfg=cfg, vault_path=vault_path,
                           passphrase=passphrase, write=keep_masked)
    masked_text = report.masked_text
    if not allow_unverified:
        assert_clean(masked_text, cfg)      # барьер №1 — до формирования запроса
    response = llm.send(masked_text, instruction, provider=provider, model=model,
                        cfg=cfg, max_tokens=max_tokens, effort=effort,
                        allow_unverified=allow_unverified)   # барьер №2 — внутри send()
    answer, unknown = unmask_text(response.text, report.vault, mode="canonical")
    return AskResult(answer, response.text, report, response, unknown)
