# LLM Migration Report

**Дата:** 2026-08-17
**Статус:** ✅ Завершено — FOL больше не использует локальные LLM
**План:** [`LOCAL_LLM_REMOVAL_PLAN.md`](LOCAL_LLM_REMOVAL_PLAN.md)

> **Позиция проекта:** FOL сознательно отказывается от локальных ИИ (Ollama,
> MLX-инференс, локальные model files, локальные fallback-провайдеры) — чтобы
> не греть ваше железо и не тратить ресурсы Mac. Весь reasoning идёт через
> API-провайдеров. **Единственное локальное исключение — `mlx-whisper` для
> STT** (распознавание голоса), потому что STT и LLM — разные вещи.

---

## 1. Что удалено из проекта

### Runtime (код)

| Файл | Изменение |
|------|-----------|
| `fol/modules/llm/backends/mlx_backend.py` | **Удалён** (MLX LLM-инференс) |
| `fol/modules/llm/engine.py` | Убран MLX-путь; `FOL_DISABLE_LOCAL_LLM` теперь не нужен — локальные модели исключены политикой всегда |
| `fol/modules/llm/router.py` | `_LOCAL_PREFIXES` (`ollama/`, `local/`, `vllm/`, `lm-studio`, MLX) **пропускаются по умолчанию** в `available_providers()` / `_model_chain()` — больше не используются и не попадают в цепочки |
| `fol/config/settings.py` | Убраны дефолты локальных моделей |
| `fol/scripts/install_models.sh` | Переписан: больше не скачивает модели; сообщает о политике |
| `requirements.txt`, `orchestrator/requirements.txt` | Убраны зависимости локального инференса (mlx-lm и т.п.) |
| `analyze/_llm.py`, `analyze/_llm_async.py` | Гейт локальных моделей в цепочках фолбэка (legacy-адаптеры) |

### Fallback-цепочки

- `LLM_FALLBACK_MODELS` с `ollama/…` — больше не имеет смысла: локальные
  префиксы отфильтровываются до построения цепочки.
- Проверка ключей: провайдер без API-ключа пропускается — поведение
  сохранено (fail-через, не fail-в-локальное).

### Конфигурация

- `.env.example`, `.env.template`, `fol/.env.example` — обновлены:
  - `LLM_MODEL` / `LLM_FALLBACK_MODELS` — только API-модели;
  - добавлен блок `FOL_BRAIN` (`current` | `freebuff` — `freebuff` честно
    отклоняется, см. `FOL_FREEBUFF_AUDIT.md`);
  - добавлены `FREEBUFF_*` (требования будущего подключения).

## 2. Что осталось (без изменений)

- ✅ `BrainInterface` — provider-independent абстракция (`brain.py`)
- ✅ `CurrentLLMAdapter` + `LiteLLMRouter` (OpenRouter / OpenAI / Anthropic /
  Gemini / … — cloud-only)
- ✅ `BrainRouter` — единая точка выбора мозга по `FOL_BRAIN`
- ✅ Agent System (6 агентов, билингвальный роутинг)
- ✅ Obsidian Memory, ContextEngine, SSE, Notch UI, voice (STT/TTS), proactive
- ✅ ToolRegistry + ConfirmationGate + RiskScorer (Safety Layer нетронут)
- ✅ `mlx-whisper` для STT (единственное локальное исключение — голос)
- ✅ FOL Core / orchestrator / agent-server

## 3. Какой Brain теперь используется

```
FOL
 ↓
BrainInterface  (chat / chat_stream / acomplete / classify / plan / select_tools / summarize / verify)
 ↓
BrainRouter (FOL_BRAIN)
 ├── current   ← DEFAULT, работает: CurrentLLMAdapter → LiteLLMRouter (cloud-only)
 └── freebuff  ← честно отклоняется (BrainConfigurationError): у Freebuff нет
                 программного интерфейса; молчаливого фолбэка нет
```

`FOL_BRAIN=current` — FOL работает абсолютно так же, как раньше, но локальные
модели исключены из цепочек. `FOL_BRAIN=freebuff` — не симулируется, падает с
понятной ошибкой `BrainConfigurationError`, пока Freebuff не предоставит API.

## 4. Какие API-провайдеры поддерживаются

| Провайдер | Префикс LiteLLM | Требуется |
|-----------|-----------------|-----------|
| OpenRouter | `openrouter/…` | `OPENROUTER_API_KEY` |
| OpenAI | `openai/…` | `OPENAI_API_KEY` |
| Anthropic | `anthropic/…` | `ANTHROPIC_API_KEY` |
| Gemini | `gemini/…` | `GEMINI_API_KEY` |
| … любые другие LiteLLM-провайдеры | | соответствующий ключ |

Модели без API-ключа пропускаются — цепочка фолбэка продолжает работать.

## 5. Какие локальные компоненты больше не нужны (вне проекта, на Mac)

✅ **Физические файлы УДАЛЕНЫ** (2026-08-17, после подтверждения):
`~/.ollama` (1.9G), `~/.cache/huggingface` (430M), `brew uninstall ollama`
(+зависимости mlx, python@3.14 — python@3.14 переустановлен). Сервер
`ollama serve` остановлен. Свободно: ~2.4G освобождено.

| Что | Где обычно | Размер (примерно) |
|-----|-----------|-------------------|
| Модели Ollama | `~/.ollama/models/` | 5–20 ГБ |
| Сам Ollama (приложение) | `/Applications/Ollama.app` | ~1 ГБ |
| Модели MLX | `~/.cache/huggingface/`, `~/.mlx/` | 1–10 ГБ |
| Кэш HuggingFace | `~/.cache/huggingface/` | зависит |

```bash
# Проверить занимаемое место (ничего не удаляет):
du -sh ~/.ollama 2>/dev/null; du -sh ~/.cache/huggingface 2>/dev/null

# Удаление — ТОЛЬКО когда вы готовы (отдельно от миграции кода):
# rm -rf ~/.ollama
# rm -rf "/Applications/Ollama.app"
# rm -rf ~/.cache/huggingface
```

## 6. Тесты

| Сьют | Результат |
|------|-----------|
| `fol/tests/` (включая router/engine/freebuff/brain) | ✅ **1073 passed** |
| `tests/test_llm.py`, `test_llm_async.py`, `test_llm_bridge.py` | ✅ **111 passed** |
| `swift build` (fol-app) | ✅ Build complete |
| Импорты + `get_brain('current'/'freebuff')` + orchestrator parse | ✅ OK |

Новые тесты политики: локальные префиксы (`ollama/…`, `local/…`) не попадают в
`available_providers()` / цепочки фолбэка; `FOL_BRAIN=freebuff` → честная
ошибка; включение локальных возможно только явным env-переопределением в
тестах механик фолбэка (autouse-фикстуры `tests/test_llm.py`).

## 7. Что дальше

1. (опционально) Удалить Ollama/модели с диска — см. §5, по отдельному
   подтверждению.
2. Подключение Freebuff — когда появится программный интерфейс
   (см. `FOL_FREEBUFF_AUDIT.md`: что именно требуется: `FREEBUFF_API_URL` +
   `FREEBUFF_API_TOKEN`; реализация в `fol/modules/llm/freebuff.py`).

---

*Миграция кода завершена. Железо больше не греется локальными LLM — только API.*
