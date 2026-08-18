# Установка в разные харнесы

Инструмент подключается тремя независимыми способами. Выберите тот, что
поддерживает ваш агент — можно и несколько сразу.

| Способ | Кому подходит | Что даёт |
|---|---|---|
| **Скилл** | Claude Code, Claude.ai, Claude Desktop | Агент сам понимает, когда обезличивать, и знает весь порядок работы |
| **MCP-сервер** | любой агент с поддержкой MCP: Cursor, Windsurf, Codex CLI, Continue, Zed, Cline, Claude Desktop | Шесть инструментов: `mask_text`, `unmask_text`, `verify_text`, `scan_document`, `mask_document`, `unmask_document` |
| **CLI и правило в AGENTS.md** | всё остальное, включая агентов без MCP | Команды в терминале плюс текстовое правило, которое агент обязан соблюдать |

Общий первый шаг для всех вариантов:

```bash
git clone https://github.com/kpshinnik/docs_masked.git ~/.docs_masked/src
cd ~/.docs_masked/src
./install.sh
```

Дальше подставляйте `~/.docs_masked/src` там, где в примерах написано
`/путь/к/docs_masked`. Абсолютный путь можно получить командой `pwd`.

---

## Claude Code

### Вариант 1 — как плагин (ставит и скилл, и MCP-сервер сразу)

```
/plugin marketplace add kpshinnik/docs_masked
/plugin install docs-masked@docs-masked
```

### Вариант 2 — как скилл

`./install.sh` уже положил его в `~/.claude/skills/docs-masked`. Проверить:

```bash
ls ~/.claude/skills/docs-masked/SKILL.md
```

Скилл подхватывается при следующем запуске `claude`. Вызвать вручную:
`/docs-masked`.

### Вариант 3 — как MCP-сервер

```bash
claude mcp add docs-masked -- python3 ~/.docs_masked/src/mcp_server.py
```

Проверить: `claude mcp list`.

---

## Claude Desktop

Откройте конфигурацию:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Добавьте:

```json
{
  "mcpServers": {
    "docs-masked": {
      "command": "python3",
      "args": ["/путь/к/docs_masked/mcp_server.py"]
    }
  }
}
```

Перезапустите приложение.

---

## Cursor

Создайте `.cursor/mcp.json` в проекте или `~/.cursor/mcp.json` глобально:

```json
{
  "mcpServers": {
    "docs-masked": {
      "command": "python3",
      "args": ["/путь/к/docs_masked/mcp_server.py"]
    }
  }
}
```

Дополнительно скопируйте содержимое `templates/AGENTS-rule.md` в
`.cursor/rules/docs-masked.mdc` или в `AGENTS.md` проекта — так агент будет
знать не только *как*, но и *когда* обезличивать.

---

## Windsurf

`~/.codeium/windsurf/mcp_config.json`, тот же блок `mcpServers`, что и выше.

---

## Codex CLI

MCP-серверы описываются в `~/.codex/config.toml`:

```toml
[mcp_servers.docs-masked]
command = "python3"
args = ["/путь/к/docs_masked/mcp_server.py"]
```

Правило работы положите в `AGENTS.md` вашего проекта — Codex читает его сам:

```bash
cat /путь/к/docs_masked/templates/AGENTS-rule.md >> AGENTS.md
```

---

## Continue, Zed, Cline и другие

Все они принимают stdio-серверы MCP. Отличается только место, где лежит
конфигурация:

| Харнес | Где настраивается |
|---|---|
| Continue | `~/.continue/config.yaml`, раздел `mcpServers` |
| Zed | `settings.json`, раздел `context_servers` |
| Cline / Roo Code | `cline_mcp_settings.json` в настройках расширения |
| Прочие | ищите «MCP», «stdio server», «tools» |

Команда везде одна:

```
command: python3
args:    ["/путь/к/docs_masked/mcp_server.py"]
```

Расположение файлов конфигурации меняется от версии к версии — если пути выше
не совпали, смотрите документацию своего харнеса по слову MCP.

---

## Без агента: терминал и Python

```bash
docs-masked scan   договор.docx
docs-masked mask   договор.docx
docs-masked report договор.docx --open
docs-masked ask    договор.docx -p "Найди риски" --provider openai
```

```python
from pii_shield import ask_document
res = ask_document("договор.docx", "Составь резюме", provider="anthropic")
print(res.answer)
```

---

## Проверка, что всё работает

```bash
# инструмент на месте
docs-masked selftest

# MCP-сервер отвечает
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 /путь/к/docs_masked/mcp_server.py
```

Второй ответ должен содержать шесть инструментов. Если да — харнес их увидит.

---

## Частые проблемы

**`command not found: docs-masked`** — пакет поставлен, но каталог скриптов не
в `PATH`. Либо добавьте его (`python3 -m site --user-base`, подкаталог `bin`),
либо используйте `python3 -m pii_shield.cli` вместо имени команды.

**`externally-managed-environment` при установке** — так ведут себя системные
Python в свежих Linux и Homebrew. Ставьте в отдельное окружение:
`./install.sh --venv`, и указывайте в конфигурации MCP путь
`/путь/к/docs_masked/.venv/bin/python` вместо `python3`.

**MCP-сервер не появляется в списке** — почти всегда неверный абсолютный путь
или не тот интерпретатор. Проверьте командой из раздела выше: если она
печатает список инструментов, дело в конфигурации харнеса, а не в сервере.

**Не читается `.docx` или `.pdf`** — не поставлены необязательные зависимости:
`python3 -m pip install "docs-masked[docs]"` или `pip install -r requirements.txt`.

**Файлы `.doc` и `.rtf`** читаются через системный `textutil` и поэтому
работают только на macOS. На других системах конвертируйте в `.docx`.
