# LOCAL_LLM_REMOVAL_PLAN — отказ FOL от локальных LLM

Дата: 2026-08-17
Статус: **аудит завершён, миграция — в реализации**
Политика: **FOL больше НЕ использует локальные LLM** (Ollama, MLX-инференс, локальные model files, локальный inference, локальные fallback providers). Никаких локальных LLM и «прогрева железа». Работа с AI — только через **Freebuff (primary Brain)** и **API-провайдеров (fallback)** через ключи в `.env`/системном хранилище секретов.

> ⚠️ Физические файлы моделей и Ollama **НЕ удаляются** на этом этапе. После миграции будет подготовлен `LLM_MIGRATION_REPORT.md` с точным списком и командами удаления — по отдельному подтверждению.

---

## 1. Найденные локальные LLM и где они используются

### Runtime (LLM-инференс)
| Компонент | Файл | Использование | Действие |
|---|---|---|---|
| MLX LLM backend | `fol/modules/llm/backends/mlx_backend.py` | импортирует `mlx_lm`, локальный инференс | **удалить** (единственный импортёр — `engine.py`) |
| LLMEngine | `fol/modules/llm/engine.py` | `_primary_backend` default `"mlx"`, MLX-бэкенд собирается всегда | **убрать MLX** из дефолтов и fallback-order |
| LiteLLMRouter | `fol/modules/llm/router.py` | `_LOCAL_PREFIXES = ("ollama/", "local/", "vllm/", "lm-studio")`, `is_local_model()`, chain включает локальные модели | **гейт**: локальные модели пропускаются, если не `FOL_ENABLE_LOCAL_LLM=1` (дефолт — выключено) |
| Legacy adapter | `analyze/_llm.py`, `analyze/_llm_async.py` | `_get_api_key_for_model` возвращает `"local"` для ollama/; цепочки fallback могут включать ollama | **гейт** в построении цепочки (тот же флаг) |
| Конфиг | `fol/config/settings.py` | `llm_backend: str = "mlx"`, `llm_model: "mlx-community/Llama-3.2-3B-Instruct-4bit"` | **дефолты → openrouter/облако**, mlx-модель убрать |
| Env | `.env.example`, `.env.template`, `.env`, `fol/.env.example`, `fol/.env` | `LLM_MODEL=ollama/llama3.2:3b` (шаблон), `LLM_FALLBACK_MODELS=...,ollama/llama3.2:3b` | **убрать ollama/mlx** из примеров и реальных `.env` |

### Не LLM — ОСТАВИТЬ
| Компонент | Файл | Почему остаётся |
|---|---|---|
| STT `mlx-whisper` | `fol/modules/input/voice/providers/mlx_whisper.py` | локальное распознавание речи, **не LLM** |
| `mlx` python-пакет | `requirements.txt` | требуется зависимостью `mlx-whisper` |
| BrainInterface | `fol/modules/llm/brain.py` | provider-agnostic контракт |
| FreebuffBrainAdapter | `fol/modules/llm/freebuff.py` + `brain_router.py` | primary Brain (уже реализован) |
| API-бэкенды | `openai_backend.py`, `anthropic_backend.py`, `gemini_backend.py` | fallback-провайдеры |
| Tools / Obsidian / Agents / Notch UI / Safety | — | не трогаем |

### Dashboard / диагностика (оставить, read-only)
- `dashboard/collector.py` — виджет статуса Ollama (health-probe, ничего не запускает). Оставляем как мониторинг; в отчёте пометим optional.
- `scripts/diagnose_responder.py` — проверка порта 11434. Оставляем (безвредно).

---

## 2. Что удалить из зависимостей
- `mlx-lm>=0.19.0` — из `requirements.txt`, `orchestrator/requirements.txt`, `build-pkg.sh` (пакет `mlx-lm` — LLM-инференс).
- НЕ удалять: `mlx>=0.19.0` (нужен `mlx-whisper`), `mlx-whisper>=0.4.0`.

## 3. Переменные окружения
- `LLM_MODEL`: убрать `ollama/...` как дефолт; примеры — только облачные (`openrouter/...`, `openai/...`, `anthropic/...`).
- `LLM_FALLBACK_MODELS`: убрать `ollama/...`.
- Новый флаг: `FOL_ENABLE_LOCAL_LLM` — по умолчанию **выключен**; локальные модели не попадают в цепочку, пока не выставлен явно (`1/true/yes`). (Инверсия прежнего `FOL_DISABLE_LOCAL_LLM`.)
- `FOL_BRAIN=current` → LiteLLMRouter (облако), `FOL_BRAIN=freebuff` → Freebuff-адаптер.
- API-ключи — только в `.env` / системном хранилище, в коде не хранятся (уже так).

## 4. Тесты, которые нужно изменить
- `fol/tests/modules/llm/test_engine.py` — убрать ожидания MLX-бэкенда (заменить на openrouter/openai-моки).
- `tests/test_llm.py`, `tests/test_llm_async.py` — проверки «ollama → local key» оставить (классификация), но цепочки с локальными моделями должны учитывать гейт.
- Добавить: тест `build_model_chain` с локальной моделью → пропущена по умолчанию; с `FOL_ENABLE_LOCAL_LLM=1` → включена.

## 5. Порядок реализации
1. `router.py`: гейт `FOL_ENABLE_LOCAL_LLM` в `build_model_chain` (+ docstring).
2. `engine.py`: убрать MLX-бэкенд и `"mlx"` из fallback-order; lazy-импорт не нужен — файл `mlx_backend.py` удаляется.
3. `fol/config/settings.py`: дефолты `llm_backend="openrouter"`, `llm_model` → облачный/пустой.
4. Env: `.env.example`, `.env.template`, `fol/.env.example`, реальные `.env` (убрать ollama/mlx; `FOL_BRAIN=current`).
5. Требования: `requirements.txt`, `orchestrator/requirements.txt`, `build-pkg.sh` — убрать `mlx-lm`.
6. `fol/scripts/install_models.sh` — только STT (mlx-whisper).
7. `analyze/_llm*.py` — гейт в цепочках.
8. Документация: README, docs/ARCHITECTURE, docs/PROJECT_DESCRIPTION, CLAUDE.md — политика «без локальных LLM».
9. Тесты + startup + отчёт.

## 6. Риски
- `mlx_backend.py` удаление: только `engine.py` и тесты ссылаются — обновить оба.
- `mlx` пакет остаётся (STT) — не путать с `mlx-lm`.
- Legacy-адаптеры: гейт только в построении цепочки, классификация (`"local"` key) не трогается.
- Физические модели не удаляются (см. выше).

## 7. Физические файлы моделей (для отчёта, НЕ удалять сейчас)
- Ollama: `~/.ollama/models/`
- MLX-кеши/модели: `~/.cache/mlx*`, `~/.fol/models/` (см. `fol/scripts/install_models.sh`)
- Команды оценки размера будут в `LLM_MIGRATION_REPORT.md`.
