# Установка

## Требования

- Python 3.10 или новее
- Для форматов документов: `python-docx`, `openpyxl`, `PyMuPDF`, `beautifulsoup4`
- Для обращения к моделям: `anthropic` и/или `openai`

Ядро (детекция, маскирование, сейф, обратная подстановка) работает на одной
стандартной библиотеке — зависимости нужны только конкретным форматам и
провайдерам.

## Обычная установка

```bash
git clone https://github.com/kpshinnik/docs_masked.git ~/.docs_masked/src
cd ~/.docs_masked/src
./install.sh
```

Скрипт поставит зависимости, положит скилл в `~/.claude/skills/docs-masked`,
прогонит самопроверку и напечатает готовый фрагмент конфигурации MCP.

Флаги: `--venv` (отдельное окружение), `--skill-only`, `--deps-only`,
`--skill-dir DIR`, `--print-mcp`.

## Через pip

```bash
pip install "git+https://github.com/kpshinnik/docs_masked.git#egg=docs-masked[all]"
```

Даёт команды `docs-masked` и `pii-shield`. Скилл и MCP-сервер при таком
способе не устанавливаются — для них нужен клон репозитория.

## Без установки

Всё работает прямо из клона:

```bash
git clone https://github.com/kpshinnik/docs_masked.git
cd docs_masked
pip install -r requirements.txt
python3 -m pii_shield.cli selftest
```

## Проверка

```bash
docs-masked selftest        # круговорот на встроенном примере
python3 -m pytest tests/ -q # полный набор тестов
```

Два теста помечаются как пропущенные — они рассчитаны на настоящие договоры,
которых в репозитории нет и не будет.

## Ключи провайдеров

| Провайдер | Переменная |
|---|---|
| Anthropic | `ANTHROPIC_API_KEY` (или вход через `ant auth login`) |
| OpenAI | `OPENAI_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Ollama | ключ не нужен, по умолчанию `http://localhost:11434/v1` |

Ключи нужны только команде `ask`. Маскирование, проверка и обратная
подстановка работают полностью офлайн.

## Обновление

```bash
cd ~/.docs_masked/src && git pull && ./install.sh
```

## Удаление

```bash
pip uninstall docs-masked
rm -rf ~/.claude/skills/docs-masked ~/.docs_masked
```

Уберите блок `docs-masked` из конфигурации MCP своего харнеса. Сейфы
(`*.vault.json`) лежат рядом с вашими документами — удалите их отдельно, если
они больше не нужны.
