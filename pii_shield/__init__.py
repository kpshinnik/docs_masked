# -*- coding: utf-8 -*-
"""pii_shield — локальное обезличивание документов перед отправкой в LLM.

Порядок работы всегда один:
    документ -> mask (локально) -> assert_clean -> модель -> unmask (локально)

Ключевые точки входа:
    pii_shield.mask_text / mask_units      — маскирование текста
    pii_shield.mask_document               — маскирование файла любого формата
    pii_shield.ask_document                — полный круг с обращением к модели
    pii_shield.unmask_text / unmask_document — обратная подстановка
"""
from .detectors import Span
from .masker import (
    DEFAULT_LABELS,
    OPTIONAL_LABELS,
    Finding,
    LeakGuardError,
    MaskConfig,
    MaskResult,
    assert_clean,
    find_spans,
    mask_text,
    mask_units,
    unmask_text,
    verify,
)
from .pipeline import AskResult, MaskReport, ask_document, mask_document, unmask_document
from .vault import Entity, Vault

__version__ = "1.0.0"
__all__ = [
    "Span", "MaskConfig", "MaskResult", "Finding", "LeakGuardError",
    "DEFAULT_LABELS", "OPTIONAL_LABELS",
    "mask_text", "mask_units", "unmask_text", "verify", "find_spans", "assert_clean",
    "mask_document", "unmask_document", "ask_document", "MaskReport", "AskResult",
    "Vault", "Entity", "__version__",
]
