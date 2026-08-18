# -*- coding: utf-8 -*-
"""Страница ревью: что именно будет скрыто в документе и как это выглядит.

ВНИМАНИЕ: страница содержит оригинальные значения — она для локального
просмотра перед отправкой, а не для пересылки.
"""
from __future__ import annotations

import html as _html
from pathlib import Path

from .documents import open_document
from .htmlout import CSS as BASE_CSS
from .masker import MaskConfig, mask_units, verify
from .vault import Vault

EXTRA_CSS = """
.warn{background:#FDF0EC;border:1px solid #F0C9BE;border-left:3px solid #A6321F;
  border-radius:3px;padding:13px 16px;margin:0 0 26px;color:#7E2A1A;font-size:14.5px}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 26px;padding:0;list-style:none}
.stats li{font-family:var(--mono);font-size:12px;border:1px solid var(--rule);
  background:var(--card);border-radius:2px;padding:6px 11px;color:var(--ink-soft)}
.stats b{color:var(--carbon);font-weight:600}
.guard{font-family:var(--mono);font-size:12.5px;letter-spacing:.03em;margin:0 0 24px}
.guard.ok{color:#1C6A4C}.guard.bad{color:#A6321F}
.guard .led{display:inline-block;width:8px;height:8px;border-radius:50%;
  background:currentColor;margin-right:9px}
.pair{border-top:1px solid var(--rule-soft);padding:14px 0;display:grid;
  grid-template-columns:118px 1fr;gap:16px;align-items:start}
.pair:first-of-type{border-top:none}
.pair .tag{font-family:var(--mono);font-size:12.5px;font-weight:600;color:var(--carbon)}
.pair .val{margin:0;font-size:15px}
.pair .val .was{background:#1A1628;color:#1A1628;border-radius:2px;padding:0 3px;
  transition:color .15s}
.pair:hover .val .was,.pair .val .was:hover{color:#F2F1F6}
.pair .ctx{margin:5px 0 0;font-size:13px;color:var(--ink-faint);line-height:1.6}
.pair .ctx mark{background:var(--carbon-wash);color:var(--carbon);
  font-family:var(--mono);font-size:.92em;padding:0 3px;border-radius:2px}
.hint{font-family:var(--mono);font-size:11.5px;color:var(--ink-faint);margin:-14px 0 20px}
.preview{background:var(--paper);border:1px solid var(--rule);border-radius:2px;
  padding:16px 18px;font-family:var(--mono);font-size:12.5px;line-height:1.75;
  white-space:pre-wrap;max-height:520px;overflow:auto}
"""


def _ctx(unit: str, start: int, end: int, width: int = 58) -> str:
    left = _html.escape(unit[max(0, start - width):start]).replace("\n", " ")
    mid = _html.escape(unit[start:end]).replace("\n", " ")
    right = _html.escape(unit[end:end + width]).replace("\n", " ")
    dots_l = "…" if start > width else ""
    dots_r = "…" if end + width < len(unit) else ""
    return f"{dots_l}{left}<mark>{mid}</mark>{right}{dots_r}"


def build_review_html(path: str | Path, cfg: MaskConfig | None = None) -> str:
    cfg = cfg or MaskConfig()
    src = Path(path)
    doc = open_document(src)
    units = doc.read_units()
    masked, vault, spans = mask_units(units, Vault(style=cfg.style), cfg,
                                      contexts=doc.read_contexts())
    residual = [f for u in masked for f in verify(u, cfg)]

    by_label: dict[str, int] = {}
    for s in spans:
        by_label[s.label] = by_label.get(s.label, 0) + 1
    stats = "".join(f"<li>{l} <b>{n}</b></li>" for l, n in
                    sorted(by_label.items(), key=lambda kv: -kv[1]))

    # соответствия «тег — оригинал» с контекстом первой встречи
    first_ctx: dict[str, str] = {}
    for unit, mu in zip(units, masked):
        if unit == mu:
            continue
        for tkey, ent in vault.entities.items():
            if tkey in first_ctx:
                continue
            pos = mu.find(vault.rendered(tkey))
            if pos >= 0:
                first_ctx[tkey] = _ctx(mu, pos, pos + len(vault.rendered(tkey)))

    pairs = []
    for tkey, ent in vault.entities.items():
        variants = ", ".join(ent.variants[:4]) + (" …" if len(ent.variants) > 4 else "")
        nom = (f' <span class="ctx">→ в ответ подставится: '
               f'{_html.escape(ent.nominative)}</span>') if ent.nominative and ent.nominative != ent.canonical else ""
        pairs.append(
            f'<div class="pair"><div class="tag">{vault.rendered(tkey)}</div>'
            f'<div><p class="val"><span class="was">{_html.escape(variants)}</span></p>'
            f'<p class="ctx">{first_ctx.get(tkey, "")}</p>{nom}</div></div>')

    guard = ('<p class="guard ok"><span class="led"></span>контроль утечки пройден — '
             'документ можно отправлять</p>') if not residual else (
        '<p class="guard bad"><span class="led"></span>проверка не пройдена: ' +
        _html.escape("; ".join(f"{f.kind}={f.value[:26]}" for f in residual[:5])) + "</p>")

    preview = _html.escape("\n".join(u for u in masked if u.strip())[:14000])

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>Ревью маскирования — {_html.escape(src.name)}</title>
<style>{BASE_CSS}{EXTRA_CSS}</style>
</head>
<body>
<main class="page">
  <p class="eyebrow">pii-shield · ревью перед отправкой</p>
  <h1>{_html.escape(src.name)}</h1>
  <p class="sub">{len(units)} фрагментов · {len(spans)} замен · {len(vault.entities)} сущностей</p>

  <p class="warn"><b>Эта страница содержит оригинальные значения.</b>
     Она нужна, чтобы проверить полноту маскирования на своей машине.
     Не пересылайте её — в модель уходит только текст из блока «что уйдёт в модель».</p>

  {guard}
  <ul class="stats">{stats}</ul>

  <h2>Что скрыто</h2>
  <p class="hint">значения закрашены — наведите курсор, чтобы прочитать</p>
  <div class="body">{"".join(pairs)}</div>

  <h2>Что уйдёт в модель</h2>
  <div class="preview">{preview}</div>

  <p class="foot">pii-shield · страница самодостаточна и работает офлайн</p>
</main>
</body>
</html>
"""
