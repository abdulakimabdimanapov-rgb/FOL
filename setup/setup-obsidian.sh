#!/bin/bash
# Obsidian Living Memory — Setup Script
# 
# Помогает подключить Obsidian как живую память для FOL.
# 
# Шаги:
#   1. Создаёт vault структуру (уже сделано)
#   2. Устанавливает плагин Local REST API (нужен GUI)
#   3. Копирует API ключ в .env
#   4. Проверяет подключение
#   5. Создаёт daily note
#
# Использование:
#   bash setup/setup-obsidian.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  Obsidian Living Memory — Setup${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# ─── Step 1: Check Obsidian is installed ───
echo -e "${YELLOW}[1/6]${NC} Проверка Obsidian..."

if [ -d "/Applications/Obsidian.app" ]; then
    echo -e "  ✅ Obsidian установлен"
else
    echo -e "  ❌ Obsidian не найден. Скачай: https://obsidian.md"
    exit 1
fi
echo ""

# ─── Step 2: Check vault structure ───
echo -e "${YELLOW}[2/6]${NC} Проверка vault структуры..."

VAULT_PATH="$HOME/Obsidian/FOL"
if [ -d "$VAULT_PATH" ]; then
    echo -e "  ✅ Vault найден: $VAULT_PATH"
    echo "  Папки:"
    for d in "$VAULT_PATH"/*/; do
        echo "    📁 $(basename "$d")"
    done
else
    echo -e "  📁 Создаю vault структуру..."
    mkdir -p "$VAULT_PATH"/{Profile,Projects,Knowledge,Goals,Ideas,Tasks,Decisions,Conversations,Daily,Episodic,Archive}
    echo -e "  ✅ Vault создан: $VAULT_PATH"
fi
echo ""

# ─── Step 3: Install plugin (GUI required) ───
echo -e "${YELLOW}[3/6]${NC} Установка плагина Local REST API..."

echo ""
echo -e "  ${CYAN}Нужно сделать в Obsidian (один раз):${NC}"
echo ""
echo "  1. Открой Obsidian"
echo "  2. Открой vault: File → Open vault → Open folder as vault"
echo "     → Выбери: ~/Obsidian/FOL"
echo "  3. Settings → Community plugins → Turn on community plugins"
echo "  4. Browse → Найди 'Local REST API' (by coddingtonbear)"
echo "  5. Install → Enable"
echo "  6. Settings → Local REST API → скопируй API Key"
echo ""

# Try to open Obsidian
echo -e "  ${YELLOW}Открыть Obsidian сейчас? (y/n)${NC}"
read -r OPEN_OBSIDIAN || true
if [ "$OPEN_OBSIDIAN" = "y" ] || [ "$OPEN_OBSIDIAN" = "Y" ]; then
    open "/Applications/Obsidian.app"
    echo -e "  ✅ Obsidian открыт"
fi
echo ""

# ─── Step 4: Get API Key ───
echo -e "${YELLOW}[4/6]${NC} Настройка API ключа..."

ENV_FILE="$REPO_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$REPO_DIR/.env.template" ]; then
        cp "$REPO_DIR/.env.template" "$ENV_FILE"
        echo -e "  📝 Создан .env из шаблона"
    else
        echo -e "  📝 Создан пустой .env"
        touch "$ENV_FILE"
    fi
fi

# Check if already configured
CURRENT_KEY=$(grep -E '^OBSIDIAN_API_KEY=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)
if [ -n "$CURRENT_KEY" ] && [ "$CURRENT_KEY" != "your-api-key-here" ]; then
    echo -e "  ✅ OBSIDIAN_API_KEY уже настроен: ${CURRENT_KEY:0:8}..."
else
    echo ""
    echo -e "  ${CYAN}Вставь API ключ из Obsidian:${NC}"
    echo "  (Settings → Local REST API → API Key)"
    echo ""
    echo -n "  API Key (ввод скрыт): "
    read -rs API_KEY || true
    echo ""  # newline after hidden input
    
    if [ -n "$API_KEY" ]; then
        # Update .env
        if grep -q '^OBSIDIAN_API_KEY=' "$ENV_FILE"; then
            sed -i '' "s/^OBSIDIAN_API_KEY=.*/OBSIDIAN_API_KEY=$API_KEY/" "$ENV_FILE"
        else
            echo "OBSIDIAN_API_KEY=$API_KEY" >> "$ENV_FILE"
        fi
        
        # Set OBSIDIAN_VAULT_PATH
        if grep -q '^OBSIDIAN_VAULT_PATH=' "$ENV_FILE"; then
            sed -i '' "s|^OBSIDIAN_VAULT_PATH=.*|OBSIDIAN_VAULT_PATH=$VAULT_PATH|" "$ENV_FILE"
        else
            echo "OBSIDIAN_VAULT_PATH=$VAULT_PATH" >> "$ENV_FILE"
        fi
        
        echo -e "  ✅ API ключ сохранён в .env"
    else
        echo -e "  ⚠️  API ключ не введён. Можно будет настроить позже в .env"
    fi
fi
echo ""

# ─── Step 5: Test connection ───
echo -e "${YELLOW}[5/6]${NC} Проверка подключения к Obsidian..."

# Source the .env to get the key
export OBSIDIAN_API_KEY=$(grep -E '^OBSIDIAN_API_KEY=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)
export OBSIDIAN_VAULT_PATH=$(grep -E '^OBSIDIAN_VAULT_PATH=' "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)

# Run Python test
PYTHON=""
for p in "/opt/homebrew/bin/python3.12" "/opt/homebrew/bin/python3" "/usr/local/bin/python3" "/usr/bin/python3"; do
    [ -x "$p" ] && { PYTHON="$p"; break; }
done

if [ -z "$PYTHON" ]; then
    echo -e "  ❌ Python 3 не найден"
    exit 1
fi

echo -e "  Использую: $PYTHON"

# Test using the obsidian module directly
$PYTHON -c "
import sys, os
sys.path.insert(0, '.')
sys.path.insert(0, 'orchestrator')

# Load .env
from dotenv import load_dotenv
load_dotenv('$REPO_DIR/.env')

from obsidian.client import check_connection
from obsidian.vault import init_vault
from obsidian.daily import ensure_daily_note

# Test connection
conn = check_connection()
if conn:
    print('  ✅ Obsidian vault connected!')
    
    # Init vault structure
    init_vault()
    print('  ✅ Vault structure initialised')
    
    # Create daily note
    path = ensure_daily_note()
    print(f'  ✅ Daily note created: {path}')
    
    print()
    print('  Живая память активна!')
else:
    print('  ❌ Cannot connect to Obsidian')
    print('  Проверь:')
    print('    - Obsidian открыт?')
    print('    - Vault ~/Obsidian/FOL открыт в Obsidian?')
    print('    - Плагин Local REST API включён?')
    print(f'    - API ключ правильный? (сейчас: {\"...\" + os.environ.get(\"OBSIDIAN_API_KEY\", \"\")[-4:] if os.environ.get(\"OBSIDIAN_API_KEY\", \"\") else \"пустой\"})')
" 2>&1 || echo -e "  ⚠️  Проверка не удалась (возможно не установлены зависимости)"

echo ""

# ─── Step 6: Final verification ───
echo -e "${YELLOW}[6/6]${NC} Финальная проверка..."

if [ -f "$ENV_FILE" ] && grep -q 'OBSIDIAN_API_KEY=' "$ENV_FILE" && [ "$(grep 'OBSIDIAN_API_KEY=' "$ENV_FILE" | cut -d'=' -f2)" != "" ]; then
    echo -e "  ✅ .env настроен: OBSIDIAN_API_KEY + OBSIDIAN_VAULT_PATH"
fi

if [ -d "$VAULT_PATH" ]; then
    echo -e "  ✅ Vault существует: $VAULT_PATH"
fi

if [ -d "/Applications/Obsidian.app" ]; then
    echo -e "  ✅ Obsidian установлен"
fi

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  Настройка завершена!${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
echo "  Что дальше:"
echo ""
echo "  🚀 Запусти orchestrator и проверь живую память:"
echo "     python3 orchestrator/server.py"
echo ""
echo "  В логах ты увидишь:"
echo "     [orchestrator] Obsidian vault connected"
echo "     [orchestrator] Daily note created: Daily/2026-07-27"
echo "     [orchestrator] Synced to Obsidian: identity.md, preferences.md"
echo ""
echo "  📝 Всё что ты делаешь теперь пишется в Obsidian:"
echo "     ~/Obsidian/FOL/Daily/YYYY-MM-DD.md"
echo "     ~/Obsidian/FOL/Episodic/events.md"
echo "     ~/Obsidian/FOL/Profile/identity.md"
echo ""
echo "  💡 Открой Obsidian, открой vault ~/Obsidian/FOL,"
echo "     и смотри как заметки создаются сами!"
echo ""
