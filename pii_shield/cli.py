# -*- coding: utf-8 -*-
"""Командный интерфейс pii-shield."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, llm
from .documents import UnsupportedFormat, open_document, supported_formats
from .masker import (
    DEFAULT_LABELS,
    LeakGuardError,
    MaskConfig,
    OPTIONAL_LABELS,
    mask_units,
    unmask_text,
    verify,
)
from .pipeline import ask_document, mask_document, unmask_document
from .vault import Vault

try:
    from rich.console import Console
    from rich.table import Table
    _console = Console()
except Exception:  # pragma: no cover
    _console = None


def _say(msg: str = "") -> None:
    if _console:
        _console.print(msg)
    else:
        print(msg)


def _err(msg: str) -> None:
    if _console:
        _console.print(f"[bold red]ошибка:[/] {msg}")
    else:
        print(f"ошибка: {msg}", file=sys.stderr)


def _read_list(path: str | None) -> list[str]:
    if not path:
        return []
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


def _passphrase(args) -> str | None:
    if getattr(args, "pass_env", None):
        val = os.environ.get(args.pass_env)
        if not val:
            raise SystemExit(f"переменная окружения {args.pass_env} пуста")
        return val
    return None


def _config(args) -> MaskConfig:
    cfg = MaskConfig(
        style=getattr(args, "style", "hash"),
        labels=set(DEFAULT_LABELS),
        aggressive_names=getattr(args, "aggressive", False),
        custom_terms=_read_list(getattr(args, "terms", None)),
        allowlist=_read_list(getattr(args, "allow", None)),
    )
    if getattr(args, "dates", False):
        cfg.enable("DATE")
    if getattr(args, "urls", False):
        cfg.enable("URL")
    for label in (getattr(args, "off", None) or "").upper().replace(",", " ").split():
        cfg.disable(label)
    return cfg


def _print_spans(spans, show_values: bool) -> None:
    if not spans:
        _say("[green]персональные данные не найдены[/]" if _console else "ПД не найдены")
        return
    if _console:
        table = Table(show_header=True, header_style="bold")
        table.add_column("тип", style="cyan", no_wrap=True)
        table.add_column("найдено", justify="right")
        if show_values:
            table.add_column("значения")
        by_label: dict[str, list[str]] = {}
        for s in spans:
            by_label.setdefault(s.label, []).append(s.value)
        for label, values in sorted(by_label.items(), key=lambda kv: -len(kv[1])):
            row = [label, str(len(values))]
            if show_values:
                uniq = list(dict.fromkeys(values))[:6]
                row.append(", ".join(uniq) + (" …" if len(set(values)) > 6 else ""))
            table.add_row(*row)
        _console.print(table)
    else:
        for s in spans:
            print(f"{s.label:12s} {s.value if show_values else '***'}")


# ------------------------------------------------------------------- команды


def cmd_scan(args) -> int:
    cfg = _config(args)
    doc = open_document(args.file)
    units = doc.read_units()
    masked, vault, spans = mask_units(units, Vault(style=cfg.style), cfg)
    _say(f"[bold]{args.file}[/] — фрагментов: {len(units)}, замен: {len(spans)}"
         if _console else f"{args.file}: фрагментов {len(units)}, замен {len(spans)}")
    _print_spans(spans, args.show)
    residual = [f for u in masked for f in verify(u, cfg)]
    if residual:
        _say(f"[yellow]внимание:[/] после маскирования осталось {len(residual)} подозрительных "
             f"фрагментов — проверьте: " + "; ".join(f"{f.kind}={f.value[:20]!r}" for f in residual[:5]))
    else:
        _say("[green]проверка чистоты пройдена — документ можно отправлять[/]"
             if _console else "проверка чистоты пройдена")
    return 0


def cmd_mask(args) -> int:
    cfg = _config(args)
    report = mask_document(args.file, out=args.out, cfg=cfg, vault_path=args.vault,
                           passphrase=_passphrase(args), pdf_redact=args.pdf_redact)
    _print_spans(report.spans, args.show)
    _say(f"замаскировано: [bold]{report.masked_path}[/]")
    _say(f"сейф:          [bold]{report.vault_path}[/]  (права 0600, не коммитить)")
    if report.residual:
        _err(f"осталось {len(report.residual)} подозрительных фрагментов — см. `pii-shield verify`")
        return 2
    _say("[green]проверка чистоты пройдена[/]" if _console else "проверка чистоты пройдена")
    return 0


def cmd_unmask(args) -> int:
    written, unknown = unmask_document(args.file, args.vault, out=args.out,
                                       mode=args.mode, passphrase=_passphrase(args))
    _say(f"восстановлено: [bold]{written}[/]")
    if unknown:
        _err(f"теги без записи в сейфе (оставлены как есть): {', '.join(unknown[:10])}")
    return 0


def cmd_verify(args) -> int:
    cfg = _config(args)
    doc = open_document(args.file)
    findings = [f for u in doc.read_units() for f in verify(u, cfg)]
    if not findings:
        _say("[green]чисто: персональных данных не обнаружено[/]" if _console else "чисто")
        return 0
    _err(f"обнаружено {len(findings)} фрагментов:")
    for f in findings[:40]:
        _say(f"  {f.kind:22s} {f.value[:60]!r}")
    return 1


def cmd_ask(args) -> int:
    cfg = _config(args)
    if args.dry_run:
        report = mask_document(args.file, cfg=cfg, vault_path=args.vault,
                               passphrase=_passphrase(args), write=args.keep)
        _print_spans(report.spans, args.show)
        _say("\n[bold]— текст, который был бы отправлен —[/]\n" if _console else "\n--- текст к отправке ---")
        _say(report.masked_text[:4000] + ("\n…" if len(report.masked_text) > 4000 else ""))
        _say(f"\nсейф: {report.vault_path}")
        return 0
    try:
        res = ask_document(args.file, args.prompt, provider=args.provider, model=args.model,
                           cfg=cfg, keep_masked=args.keep, vault_path=args.vault,
                           passphrase=_passphrase(args), max_tokens=args.max_tokens,
                           effort=args.effort, allow_unverified=args.force)
    except LeakGuardError as exc:
        _err(f"отправка заблокирована — {exc}")
        _say("уточните словари (--terms) или снимите блокировку осознанно флагом --force")
        return 3
    except llm.ProviderError as exc:
        _err(str(exc))
        return 4

    out = Path(args.out) if args.out else Path(args.file).with_suffix(".answer.md")
    out.write_text(res.answer, encoding="utf-8")
    _say(f"[dim]{res.response.provider}/{res.response.model} · замен: "
         f"{len(res.report.spans)} · токены: {res.response.usage}[/]")
    _say(f"ответ: [bold]{out}[/]")
    if res.unknown_tags:
        _err("модель придумала теги, которых нет в сейфе: " + ", ".join(res.unknown_tags[:10]))
    if args.html:
        from .htmlout import render_html
        html = render_html(res.answer, title=f"Ответ по документу {Path(args.file).name}",
                           subtitle=f"{res.response.provider} · {res.response.model}")
        hpath = out.with_suffix(".html")
        hpath.write_text(html, encoding="utf-8")
        _say(f"html:  [bold]{hpath}[/]")
        if args.open:
            os.system(f'open "{hpath}"')
    _say("")
    _say(res.answer)
    return 0


def cmd_report(args) -> int:
    from .review import build_review_html
    cfg = _config(args)
    html = build_review_html(args.file, cfg)
    out = Path(args.out) if args.out else Path(args.file).with_suffix(
        Path(args.file).suffix + ".review.html")
    out.write_text(html, encoding="utf-8")
    _say(f"ревью: [bold]{out}[/]")
    _say("[yellow]страница содержит оригиналы — только для локального просмотра[/]"
         if _console else "внимание: страница содержит оригиналы")
    if args.open:
        os.system(f'open "{out}"')
    return 0


def cmd_formats(args) -> int:
    _say("поддерживаемые расширения: " + ", ".join(supported_formats()))
    _say("метки по умолчанию: " + ", ".join(sorted(DEFAULT_LABELS)))
    _say("по флагу: " + ", ".join(sorted(OPTIONAL_LABELS)))
    _say("провайдеры: " + ", ".join(llm.PROVIDERS))
    return 0


def cmd_selftest(args) -> int:
    from .masker import mask_text
    sample = ("Иванов Иван Иванович, 12.03.1985 г.р., паспорт 45 12 345678, "
              "СНИЛС 112-233-445 95, тел. +7 (916) 123-45-67, iv.ivanov@example.ru, "
              "119991, г. Москва, ул. Ленина, д. 12, кв. 45. Иванову направлено письмо.")
    r = mask_text(sample)
    back, _ = unmask_text(r.text, r.vault, "sequential")
    ok = back == sample and not verify(r.text)
    _say(r.text)
    _say(f"round-trip: {'OK' if back == sample else 'ОШИБКА'} · "
         f"остаточных ПД: {len(verify(r.text))} · сущностей: {len(r.vault.entities)}")
    return 0 if ok else 1


# ------------------------------------------------------------------- парсер


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pii-shield",
        description="Локальное обезличивание документов до отправки в LLM и "
                    "обратная подстановка после ответа.")
    p.add_argument("--version", action="version", version=f"pii-shield {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--style", choices=("hash", "bracket", "angle"), default="hash",
                        help="формат тега: #PERSON_1# | [[PERSON_1]] | <PERSON_1>")
        sp.add_argument("--aggressive", action="store_true",
                        help="маскировать одиночные слова, похожие на фамилии")
        sp.add_argument("--dates", action="store_true", help="маскировать все даты, не только даты рождения")
        sp.add_argument("--urls", action="store_true", help="маскировать ссылки")
        sp.add_argument("--off", help="отключить метки, через запятую (напр. ORG,IP)")
        sp.add_argument("--terms", help="файл со списком дополнительных строк для маскирования")
        sp.add_argument("--allow", help="файл со списком строк, которые маскировать не нужно")
        sp.add_argument("--show", action="store_true", help="показывать сами значения ПД в отчёте")

    s = sub.add_parser("scan", help="показать, что будет замаскировано (файл не меняется)")
    s.add_argument("file"); common(s); s.set_defaults(func=cmd_scan)

    s = sub.add_parser("mask", help="создать обезличенную копию документа + сейф")
    s.add_argument("file"); s.add_argument("-o", "--out")
    s.add_argument("--vault", help="путь к файлу сейфа (по умолчанию рядом с исходником)")
    s.add_argument("--pass-env", help="имя переменной окружения с паролем шифрования сейфа")
    s.add_argument("--pdf-redact", action="store_true",
                   help="для PDF: физически вымарать текст и пересобрать PDF")
    common(s); s.set_defaults(func=cmd_mask)

    s = sub.add_parser("unmask", help="вернуть оригиналы по сейфу")
    s.add_argument("file"); s.add_argument("--vault", required=True)
    s.add_argument("-o", "--out")
    s.add_argument("--mode", choices=("sequential", "canonical"), default="sequential",
                   help="sequential — точное восстановление нашего файла; "
                        "canonical — для произвольного текста (ответа модели)")
    s.add_argument("--pass-env")
    s.set_defaults(func=cmd_unmask)

    s = sub.add_parser("verify", help="проверить, что в файле не осталось ПД")
    s.add_argument("file"); common(s); s.set_defaults(func=cmd_verify)

    s = sub.add_parser("ask", help="полный круг: обезличить -> отправить -> восстановить ответ")
    s.add_argument("file")
    s.add_argument("-p", "--prompt", required=True, help="что сделать с документом")
    s.add_argument("--provider", choices=llm.PROVIDERS, default="anthropic")
    s.add_argument("--model", help="переопределить модель провайдера")
    s.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"), default="high")
    s.add_argument("--max-tokens", type=int, default=16000)
    s.add_argument("-o", "--out", help="куда записать ответ (по умолчанию <файл>.answer.md)")
    s.add_argument("--vault")
    s.add_argument("--pass-env")
    s.add_argument("--keep", action="store_true", help="сохранить и обезличенную копию документа")
    s.add_argument("--dry-run", action="store_true", help="показать, что уйдёт, но не отправлять")
    s.add_argument("--force", action="store_true",
                   help="отправить, даже если контроль утечки не пройден (пишется в журнал)")
    s.add_argument("--html", action="store_true", help="сверстать ответ в HTML")
    s.add_argument("--open", action="store_true", help="открыть HTML после сборки")
    common(s); s.set_defaults(func=cmd_ask)

    s = sub.add_parser("report", help="HTML-ревью: что именно будет скрыто")
    s.add_argument("file"); s.add_argument("-o", "--out")
    s.add_argument("--open", action="store_true", help="открыть после сборки")
    common(s); s.set_defaults(func=cmd_report)

    s = sub.add_parser("formats", help="что поддерживается")
    s.set_defaults(func=cmd_formats)
    s = sub.add_parser("selftest", help="самопроверка на встроенном примере")
    s.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (UnsupportedFormat, FileNotFoundError, ValueError) as exc:
        _err(str(exc))
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
