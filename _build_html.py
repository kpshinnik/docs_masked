#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка README.html из README.md — самодостаточная страница, светлая тема.

Оформление: «карбонная копия» — бумага с фиолетовым подтоном, машинописный
дисплейный шрифт, а подпись страницы — полоса вымарывания, из-под которой
проступает тег. Ровно то, что делает сам инструмент.
"""
from __future__ import annotations

import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "README.md"
OUT = ROOT / "README.html"

CSS = """
:root{
  --paper:#F2F1F6;      /* бумага */
  --card:#FFFFFF;
  --ink:#221F38;        /* карбонные чернила */
  --ink-soft:#635C82;
  --ink-faint:#8E88A8;
  --carbon:#4A34B8;     /* акцент */
  --carbon-wash:#EFEBFB;
  --redact:#1A1628;     /* полоса вымарывания */
  --ok:#1C6A4C;
  --alert:#A6321F;
  --rule:#DEDAEA;
  --rule-soft:#EBE8F3;
  --display:"American Typewriter","Rockwell","Courier New",ui-monospace,monospace;
  --body:"Avenir Next","Avenir",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  --mono:"SF Mono","Menlo","Consolas",ui-monospace,monospace;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--paper);color:var(--ink);
  font-family:var(--body);font-size:16.5px;line-height:1.62;
  font-feature-settings:"kern" 1;text-rendering:optimizeLegibility;
}
.page{max-width:840px;margin:0 auto;padding:0 20px 96px}

/* ---------- шапка ---------- */
.hero{padding:64px 0 8px}
.eyebrow{
  font-family:var(--mono);font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--ink-faint);margin:0 0 18px;
}
h1.title{
  font-family:var(--display);font-size:clamp(38px,7vw,60px);line-height:1;
  letter-spacing:-.018em;margin:0 0 18px;font-weight:400;
}
h1.title .dot{color:var(--carbon)}
.lede{font-size:clamp(18px,2.4vw,21px);line-height:1.45;margin:0 0 8px;max-width:30em;color:var(--ink)}
.sub{color:var(--ink-soft);max-width:34em;margin:.5em 0 0}

/* ---------- подпись страницы: полоса вымарывания ---------- */
.strip{
  margin:40px 0 12px;background:var(--card);border:1px solid var(--rule);
  border-radius:3px;box-shadow:0 1px 0 var(--rule-soft),0 14px 34px -22px rgba(34,31,56,.5);
  overflow:hidden;
}
.strip-head,.strip-foot{
  display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
  padding:10px 18px;font-family:var(--mono);font-size:11.5px;
  letter-spacing:.06em;color:var(--ink-faint);
}
.strip-head{border-bottom:1px solid var(--rule-soft)}
.strip-foot{border-top:1px solid var(--rule-soft);color:var(--ok);letter-spacing:.03em}
.strip-foot .led{
  display:inline-block;width:7px;height:7px;border-radius:50%;
  background:var(--ok);margin-right:8px;vertical-align:1px;
}
.rows{padding:6px 0}
.row{
  display:grid;grid-template-columns:86px 1fr;gap:16px;align-items:baseline;
  padding:12px 18px;
}
.row + .row{border-top:1px dashed var(--rule)}
.rlabel{
  font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--ink-faint);
}
.row.out .rlabel{color:var(--carbon)}
.line{margin:0;font-size:15.5px;line-height:1.9}
.line b{font-family:var(--mono);font-weight:600;font-size:.9em;color:var(--carbon)}

.pii{position:relative;display:inline-block}
.pii::after{
  content:"";position:absolute;inset:-2px -1.5px;background:var(--redact);
  border-radius:1.5px;transform:scaleX(0);transform-origin:left center;
  animation:wipe .55s cubic-bezier(.65,0,.2,1) calc(.5s + var(--i) * .28s) forwards;
}
@keyframes wipe{to{transform:scaleX(1)}}
.row.out{animation:rise .6s cubic-bezier(.2,.7,.3,1) 1.55s both}
@keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.strip-foot{animation:appear .5s ease 2.1s both}
@keyframes appear{from{opacity:0}to{opacity:1}}
@media (prefers-reduced-motion:reduce){
  .pii::after{animation:none;transform:scaleX(1)}
  .row.out,.strip-foot{animation:none}
}

/* ---------- навигация ---------- */
.toc{
  display:flex;flex-wrap:wrap;gap:7px;margin:34px 0 8px;padding:0;list-style:none;
}
.toc a{
  display:inline-block;padding:5px 11px;border:1px solid var(--rule);border-radius:2px;
  background:var(--card);color:var(--ink-soft);text-decoration:none;
  font-family:var(--mono);font-size:12px;letter-spacing:.02em;
}
.toc a:hover{border-color:var(--carbon);color:var(--carbon)}

/* ---------- содержимое ---------- */
.content{margin-top:6px}
h2{
  font-family:var(--display);font-weight:400;font-size:26px;line-height:1.2;
  letter-spacing:-.01em;margin:48px 0 14px;padding-top:22px;
  border-top:1px solid var(--rule);position:relative;
}
h2::before{
  content:"";position:absolute;top:-1px;left:0;width:44px;height:2px;background:var(--carbon);
}
h3{font-family:var(--body);font-weight:600;font-size:17px;margin:30px 0 8px;letter-spacing:-.005em}
p{margin:.85em 0}
a{color:var(--carbon);text-decoration:none;border-bottom:1px solid rgba(74,52,184,.28)}
a:hover{border-bottom-color:var(--carbon)}
strong{font-weight:600}
ul,ol{margin:.85em 0;padding-left:1.35em}
li{margin:.32em 0}
li::marker{color:var(--ink-faint)}
hr{border:none;border-top:1px solid var(--rule);margin:44px 0}

code{
  font-family:var(--mono);font-size:.875em;background:var(--carbon-wash);
  color:#382B84;padding:.1em .36em;border-radius:2px;
}
pre{
  background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--carbon);
  border-radius:2px;padding:16px 18px;overflow-x:auto;margin:1.2em 0;
  font-size:13.5px;line-height:1.7;
}
pre code{background:none;color:var(--ink);padding:0;font-size:inherit}

table{
  width:100%;border-collapse:collapse;margin:1.3em 0;font-size:14.5px;
  background:var(--card);border:1px solid var(--rule);
}
thead th{
  text-align:left;font-family:var(--mono);font-size:11px;letter-spacing:.09em;
  text-transform:uppercase;color:var(--ink-faint);font-weight:500;
  padding:11px 14px;border-bottom:1px solid var(--rule);
}
td{padding:11px 14px;border-top:1px solid var(--rule-soft);vertical-align:top}
tbody tr:hover{background:#FAF9FD}
td code{font-size:.86em;white-space:nowrap}
td:first-child{white-space:nowrap}
.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}

blockquote{
  margin:1.3em 0;padding:2px 0 2px 18px;border-left:3px solid var(--rule);
  color:var(--ink-soft);
}

footer.foot{
  margin-top:72px;padding-top:20px;border-top:1px solid var(--rule);
  font-family:var(--mono);font-size:11.5px;color:var(--ink-faint);letter-spacing:.03em;
  display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;
}

:focus-visible{outline:2px solid var(--carbon);outline-offset:3px;border-radius:2px}

@media (max-width:620px){
  body{font-size:16px}
  .hero{padding-top:44px}
  .row{grid-template-columns:1fr;gap:6px;padding:12px 14px}
  .line{font-size:14.5px;line-height:2}
  .opt{display:none}                     /* демо-строка не переносится в кашу */
  .eyebrow{font-size:10.5px;letter-spacing:.1em}
  h2{font-size:22px;margin-top:44px}
  td:first-child{white-space:normal}
  .strip-head{font-size:10.5px}
}

@media print{
  body{background:#fff;font-size:11pt}
  .page{max-width:100%;padding:0}
  .toc,.strip-foot{display:none}
  .pii::after{transform:scaleX(1)}
  .row.out{animation:none;opacity:1}
  .strip,pre,table{box-shadow:none;break-inside:avoid}
  h2{break-after:avoid}
  a{color:var(--ink);border:none}
}
"""

HERO = """
<header class="hero">
  <p class="eyebrow">локально · обратимо · без сети до проверки</p>
  <h1 class="title">docs-masked<span class="dot">.</span></h1>
  <p class="lede">Документ не уходит в модель, пока в нём есть люди.</p>
  <p class="sub">Персональные данные заменяются устойчивыми тегами на вашей машине.
     Наружу уходит только текст с тегами. Ответ модели восстанавливается локально
     по сейфу соответствий. Работает как скилл для Claude Code, как MCP-сервер для
     любого другого агента и как обычная утилита командной строки.</p>

  <figure class="strip">
    <div class="strip-head"><span>договор.docx · строка 14</span><span>маскирование</span></div>
    <div class="rows">
      <div class="row">
        <span class="rlabel">в файле</span>
        <p class="line">Исполнитель:
          <span class="pii" style="--i:0">Иванов Иван Иванович</span>, тел.
          <span class="pii" style="--i:1">+7 (916) 123-45-67</span><span class="opt">,
          <span class="pii" style="--i:2">iv.ivanov@example.ru</span></span></p>
      </div>
      <div class="row out">
        <span class="rlabel">в модель</span>
        <p class="line">Исполнитель: <b>#PERSON_1#</b>, тел. <b>#PHONE_1#</b><span class="opt">, <b>#EMAIL_1#</b></span></p>
      </div>
    </div>
    <div class="strip-foot"><span><span class="led"></span>контроль утечки пройден · 3 замены · сейф записан локально</span></div>
  </figure>
</header>
"""


def build() -> Path:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "toc", "attr_list"])
    body = md.convert(SRC.read_text(encoding="utf-8"))

    # всё до первого раздела уезжает в шапку — иначе дублировалось бы
    first_section = body.find("<h2")
    if first_section > 0:
        body = body[first_section:]

    body = body.replace("<table>", '<div class="table-wrap"><table>').replace(
        "</table>", "</table></div>")

    def walk(items):
        for item in items:
            if item["level"] == 2:
                yield item
            yield from walk(item.get("children", []))

    nav = "".join(f'<li><a href="#{i["id"]}">{i["name"]}</a></li>' for i in walk(md.toc_tokens))

    html = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>docs-masked — обезличивание документов перед отправкой в модель</title>
<style>{CSS}</style>
</head>
<body>
<main class="page">
{HERO}
<nav aria-label="Разделы"><ul class="toc">{nav}</ul></nav>
<div class="content">
{body}
</div>
<footer class="foot">
  <span>docs-masked 1.0 · MIT</span>
  <span>github.com/kpshinnik/docs_masked</span>
</footer>
</main>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(build())
