# -*- coding: utf-8 -*-
"""Единственная точка выхода данных наружу.

Ни один модуль проекта не обращается к API напрямую: всё идёт через
`send()`, а он перед отправкой обязан прогнать текст через `assert_clean()`.
Снять проверку можно только явным `allow_unverified=True` — и это пишется
в журнал отправок.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .masker import LeakGuardError, MaskConfig, assert_clean

AUDIT_LOG = Path(os.environ.get("PII_SHIELD_LOG", Path.home() / ".pii_shield" / "egress.jsonl"))

DEFAULT_MODELS = {
    "anthropic": os.environ.get("PII_SHIELD_ANTHROPIC_MODEL", "claude-opus-5"),
    "openai": os.environ.get("PII_SHIELD_OPENAI_MODEL", "gpt-4o"),
    "deepseek": os.environ.get("PII_SHIELD_DEEPSEEK_MODEL", "deepseek-chat"),
    "ollama": os.environ.get("PII_SHIELD_OLLAMA_MODEL", "llama3.1"),
}

SYSTEM_PROMPT = (
    "Ты работаешь с документом, из которого предварительно удалены персональные "
    "данные. Вместо них стоят теги вида #PERSON_1#, #EMAIL_2#, #ADDRESS_1#. "
    "Каждый тег обозначает одну и ту же сущность по всему тексту.\n"
    "Правила:\n"
    "1. Сохраняй теги в ответе ДОСЛОВНО, символ в символ, включая решётки.\n"
    "2. Никогда не придумывай настоящие имена, адреса, телефоны вместо тегов.\n"
    "3. Не пытайся угадать, что скрыто за тегом.\n"
    "4. Если нужно сослаться на человека — используй его тег.\n"
    "Отвечай на русском языке, если пользователь не просит иного."
)


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None


class ProviderError(RuntimeError):
    pass


# ------------------------------------------------------------------ провайдеры


def _anthropic(system: str, user: str, model: str, max_tokens: int,
               effort: str = "high") -> LLMResponse:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise ProviderError("pip install anthropic") from exc
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or (Path.home() / ".config" / "anthropic").exists()):
        raise ProviderError(
            "нет учётных данных Anthropic: задайте ANTHROPIC_API_KEY или выполните `ant auth login`")
    client = anthropic.Anthropic()
    kwargs: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
    )
    msg = None
    try:
        with client.beta.messages.stream(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
        ) as stream:
            msg = stream.get_final_message()
    except Exception:
        # аккаунт без беты server-side fallback — обычный путь
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()

    if getattr(msg, "stop_reason", None) == "refusal":
        details = getattr(msg, "stop_details", None)
        raise ProviderError(f"модель отклонила запрос: {getattr(details, 'category', 'refusal')}")
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    usage = getattr(msg, "usage", None)
    return LLMResponse(text, "anthropic", model,
                       {"input": getattr(usage, "input_tokens", None),
                        "output": getattr(usage, "output_tokens", None)},
                       getattr(msg, "stop_reason", None))


def _openai_compatible(system: str, user: str, model: str, max_tokens: int,
                       provider: str, base_url: str | None, api_key: str | None) -> LLMResponse:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise ProviderError("pip install openai") from exc
    if not api_key:
        raise ProviderError(f"нет API-ключа для {provider}")
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    choice = resp.choices[0]
    usage = resp.usage
    return LLMResponse(choice.message.content or "", provider, model,
                       {"input": getattr(usage, "prompt_tokens", None),
                        "output": getattr(usage, "completion_tokens", None)},
                       choice.finish_reason)


PROVIDERS = ("anthropic", "openai", "deepseek", "ollama")


def call_provider(provider: str, system: str, user: str, model: str | None = None,
                  max_tokens: int = 16000, effort: str = "high") -> LLMResponse:
    provider = provider.lower()
    model = model or DEFAULT_MODELS.get(provider)
    if provider == "anthropic":
        return _anthropic(system, user, model, max_tokens, effort)
    if provider == "openai":
        return _openai_compatible(system, user, model, max_tokens, "openai", None,
                                  os.environ.get("OPENAI_API_KEY"))
    if provider == "deepseek":
        return _openai_compatible(system, user, model, max_tokens, "deepseek",
                                  os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                                  os.environ.get("DEEPSEEK_API_KEY"))
    if provider == "ollama":
        return _openai_compatible(system, user, model, max_tokens, "ollama",
                                  os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                                  "ollama")
    raise ProviderError(f"неизвестный провайдер: {provider}. Доступны: {', '.join(PROVIDERS)}")


# ------------------------------------------------------------------ шлюз


def _audit(entry: dict[str, Any]) -> None:
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def send(masked_text: str, instruction: str, provider: str = "anthropic",
         model: str | None = None, cfg: MaskConfig | None = None,
         max_tokens: int = 16000, effort: str = "high",
         allow_unverified: bool = False, system: str | None = None) -> LLMResponse:
    """Отправить УЖЕ замаскированный текст. Перед отправкой — контроль утечки."""
    guard_ok = True
    guard_error = ""
    try:
        assert_clean(masked_text, cfg)
    except LeakGuardError as exc:
        guard_ok = False
        guard_error = str(exc)
        if not allow_unverified:
            raise

    payload = f"{instruction.strip()}\n\n--- ДОКУМЕНТ ---\n{masked_text}"
    started = time.time()
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "provider": provider,
        "model": model or DEFAULT_MODELS.get(provider),
        "chars": len(payload),
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16],
        "guard_passed": guard_ok,
    }
    if not guard_ok:
        entry["guard_error"] = guard_error
        entry["forced"] = True
    try:
        resp = call_provider(provider, system or SYSTEM_PROMPT, payload, model, max_tokens, effort)
    except Exception as exc:
        entry.update(status="error", error=str(exc)[:300], seconds=round(time.time() - started, 2))
        _audit(entry)
        raise
    entry.update(status="ok", seconds=round(time.time() - started, 2), usage=resp.usage)
    _audit(entry)
    return resp
