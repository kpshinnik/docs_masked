# -*- coding: utf-8 -*-
"""Вёрстка ответа модели в самодостаточную HTML-страницу (светлая тема)."""
from __future__ import annotations

import html as _html
import re

CSS = """
:root{
  --paper:#F2F1F6;--card:#FFF;--ink:#221F38;--ink-soft:#635C82;--ink-faint:#8E88A8;
  --carbon:#4A34B8;--carbon-wash:#EFEBFB;--rule:#DEDAEA;--rule-soft:#EBE8F3;
  --display:"American Typewriter","Rockwell","Courier New",ui-monospace,monospace;
  --body:"Avenir Next","Avenir",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  --mono:"SF Mono","Menlo","Consolas",ui-monospace,monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--body);
  font-size:16.5px;line-height:1.62;-webkit-text-size-adjust:100%}
.page{max-width:840px;margin:0 auto;padding:56px 20px 88px}
.eyebrow{font-family:var(--mono);font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--ink-faint);margin:0 0 14px}
h1{font-family:var(--display);font-weight:400;font-size:clamp(30px,5vw,42px);line-height:1.08;
  letter-spacing:-.015em;margin:0 0 10px}
.sub{color:var(--ink-soft);margin:0 0 34px;font-family:var(--mono);font-size:12.5px;letter-spacing:.03em}
.body{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--carbon);
  border-radius:3px;padding:30px 32px;box-shadow:0 14px 34px -24px rgba(34,31,56,.5)}
h2{font-family:var(--display);font-weight:400;font-size:23px;margin:32px 0 10px;letter-spacing:-.01em}
h3{font-weight:600;font-size:17px;margin:26px 0 8px}
p{margin:.85em 0}
ul,ol{margin:.85em 0;padding-left:1.35em}
li{margin:.3em 0}
li::marker{color:var(--ink-faint)}
a{color:var(--carbon);text-decoration:none;border-bottom:1px solid rgba(74,52,184,.28)}
code{font-family:var(--mono);font-size:.875em;background:var(--carbon-wash);color:#382B84;
  padding:.1em .36em;border-radius:2px}
pre{background:var(--paper);border:1px solid var(--rule);border-radius:2px;padding:15px 17px;
  overflow-x:auto;font-size:13.5px;line-height:1.7}
pre code{background:none;padding:0;color:var(--ink)}
table{width:100%;border-collapse:collapse;margin:1.2em 0;font-size:14.5px}
th{text-align:left;font-family:var(--mono);font-size:11px;letter-spacing:.09em;text-transform:uppercase;
  color:var(--ink-faint);font-weight:500;padding:10px 12px;border-bottom:1px solid var(--rule)}
td{padding:10px 12px;border-top:1px solid var(--rule-soft);vertical-align:top}
blockquote{margin:1.2em 0;padding:2px 0 2px 16px;border-left:3px solid var(--rule);color:var(--ink-soft)}
.foot{margin-top:28px;font-family:var(--mono);font-size:11.5px;color:var(--ink-faint);letter-spacing:.03em}
:focus-visible{outline:2px solid var(--carbon);outline-offset:3px}
@media (max-width:620px){.body{padding:22px 18px}.page{padding-top:36px}}
@media print{body{background:#fff}.body{box-shadow:none;border:none;padding:0}.foot{display:none}}
"""


def _markdown(text: str) -> str:
    try:
        import markdown
        return markdown.markdown(
            text, extensions=["tables", "fenced_code", "sane_lists", "attr_list"])
    except ImportError:
        esc = _html.escape(text)
        return "".join(f"<p>{block}</p>" for block in re.split(r"\n{2,}", esc))


def render_html(answer_markdown: str, title: str = "Ответ модели",
                subtitle: str = "") -> str:
    """Собрать страницу с ответом. Всё внутри файла, внешних ресурсов нет."""
    body = _markdown(answer_markdown)
    sub = f'<p class="sub">{_html.escape(subtitle)}</p>' if subtitle else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{_html.escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
<main class="page">
  <p class="eyebrow">pii-shield · персональные данные восстановлены локально</p>
  <h1>{_html.escape(title)}</h1>
  {sub}
  <article class="body">{body}</article>
  <p class="foot">Файл самодостаточен и работает офлайн.</p>
</main>
</body>
</html>
"""
