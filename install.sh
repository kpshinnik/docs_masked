#!/usr/bin/env bash
# Установка docs-masked: зависимости, скилл, подсказка по MCP.
# Ничего не требует от root и ничего не удаляет без спроса.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$REPO_DIR/skills/docs-masked"
SKILL_DST="${DOCS_MASKED_SKILL_DIR:-$HOME/.claude/skills/docs-masked}"

DO_DEPS=1
DO_SKILL=1
USE_VENV=0

usage() {
  cat <<'TXT'
Использование: ./install.sh [флаги]

  --skill-only     только скопировать скилл, зависимости не ставить
  --deps-only      только зависимости, скилл не копировать
  --venv           поставить зависимости в ./.venv вместо пользовательского окружения
  --skill-dir DIR  куда положить скилл (по умолчанию ~/.claude/skills/docs-masked)
  --print-mcp      напечатать готовый фрагмент конфигурации MCP и выйти
  -h, --help       эта справка
TXT
}

print_mcp() {
  cat <<TXT
{
  "mcpServers": {
    "docs-masked": {
      "command": "python3",
      "args": ["$REPO_DIR/mcp_server.py"]
    }
  }
}
TXT
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skill-only) DO_DEPS=0; shift ;;
    --deps-only)  DO_SKILL=0; shift ;;
    --venv)       USE_VENV=1; shift ;;
    --skill-dir)  SKILL_DST="$2"; shift 2 ;;
    --print-mcp)  print_mcp; exit 0 ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "неизвестный флаг: $1" >&2; usage; exit 1 ;;
  esac
done

# --- python -----------------------------------------------------------------
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "нужен python3 (не найден)"; exit 1; }
"$PY" - <<'EOF' || { echo "нужен Python 3.10 или новее"; exit 1; }
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
EOF
echo "python: $("$PY" -V)"

# --- зависимости ------------------------------------------------------------
if [[ $DO_DEPS -eq 1 ]]; then
  if [[ $USE_VENV -eq 1 ]]; then
    "$PY" -m venv "$REPO_DIR/.venv"
    PY="$REPO_DIR/.venv/bin/python"
    echo "виртуальное окружение: $REPO_DIR/.venv"
  fi
  echo "ставлю зависимости…"
  if [[ $USE_VENV -eq 1 ]]; then
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -e "$REPO_DIR[all]"
  else
    "$PY" -m pip install --quiet --user -e "$REPO_DIR[all]" 2>/dev/null \
      || "$PY" -m pip install --quiet --break-system-packages --user -e "$REPO_DIR[all]" \
      || { echo; echo "не удалось поставить в пользовательское окружение."; \
           echo "повторите с флагом --venv:  ./install.sh --venv"; exit 1; }
  fi
fi

# --- скилл ------------------------------------------------------------------
if [[ $DO_SKILL -eq 1 ]]; then
  mkdir -p "$(dirname "$SKILL_DST")"
  if [[ -e "$SKILL_DST" && ! -L "$SKILL_DST" ]]; then
    echo "внимание: $SKILL_DST уже существует и будет перезаписан"
    read -r -p "продолжить? [y/N] " answer
    [[ "$answer" =~ ^[YyДд]$ ]] || { echo "скилл не тронут"; DO_SKILL=0; }
  fi
  if [[ $DO_SKILL -eq 1 ]]; then
    rm -rf "$SKILL_DST"
    cp -R "$SKILL_SRC" "$SKILL_DST"
    echo "скилл: $SKILL_DST"
  fi
fi

# --- проверка ---------------------------------------------------------------
echo
if "$PY" -c "import sys; sys.path.insert(0, '$REPO_DIR'); from pii_shield.cli import main; sys.exit(main(['selftest']))" >/dev/null 2>&1; then
  echo "самопроверка пройдена"
else
  echo "самопроверка не прошла — запустите вручную:"
  echo "  $PY -m pii_shield.cli selftest"
fi

cat <<TXT

Готово.

  Проверить документ:   docs-masked scan файл.docx
  Обезличить:           docs-masked mask файл.docx
  Полный круг:          docs-masked ask файл.docx -p "задача"

Чтобы подключить как MCP-сервер (работает в любом харнесе с поддержкой MCP),
добавьте в конфигурацию:

$(print_mcp)

Подробнее по конкретным харнесам: $REPO_DIR/docs/HARNESSES.md
TXT
