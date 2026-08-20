# AUDIT_REPORT — FOL

> **Дата:** 2026-08-10
> **Ветка:** v1.0-beta (6 коммитов поверх v1.0.0)
> **Метод:** живая проверка сервисов, прогон тестов, поиск по коду, сравнение с единым ТЗ.
> **Принцип:** не маскировать баги, а фиксировать реальное состояние каждого компонента.

---

## 0. Сводка

| Метрика | Значение |
|---|---|
| Код | FOL 22.5k строк / 189 файлов, fol-app 7.3k / 39, orchestrator 6.2k, Next.js 4.9k, obsidian 2.2k |
| Тесты | **1001 passed** (корневые) + **560 passed** (FOL) = **1561**, 0 failed |
| Swift build | ✅ Build complete |
| Сервисы | :8420 orchestrator ✅, :8421 agent ✅, :8754 FOL ✅, :8000 uvicorn ✅, :3000 Next.js свободен |
| Git | чистое дерево (кроме untracked Release/ и внешних папок), секреты в `.gitignore` |
| Установщик | `Release/Second-Self-1.0.0.pkg` (4.1M) ✅, приложение запущено |
| Симлинк | `~/second-self → Desktop/Fol` — сервисы читают тот же код, что мы правим ✅ |

**Главная философия уже работает:** FOL — это не набор команд, а ядро, которое понимает речь,
помнит контекст, видит экран, выполняет действия и отвечает естественно. Критичных багов,
ломающих базовый цикл, **нет**. Но по ТЗ не хватает целого слоя: **Safety / Audit Log**,
**Accessibility-основа** управления, **Observability**, транслитерация, единый Core.

---

## 1. Таблица аудита (Component | Status | Bugs | Risk | Priority | Action)

Статусы: ✅ готово · 🟡 частично · ❌ нет

| # | Компонент (ТЗ) | Статус | Найденные проблемы | Risk | Priority | Action |
|---|---|---|---|---|---|---|
| 1 | Архитектура / сервисы | 🟡 | 4 HTTP-точки (8420/8421/8754/8000) + Next.js дублируют FOL; нет единого Core-шлюза | M | P1 | Постепенная унификация: сделать FOL Core единственным мозгом, orchestrator — тонким фасадом |
| 2 | FOL Brain (пайплайн) | ✅ | Пайплайн полный: язык → интент → контекст → память → инструменты → безопасность(част.) → агент → финальный слой | L | — | — |
| 3 | Conversation Engine | ✅ | `ContextManager`: follow-up (RU+EN), извлечение темы, привязка в промпт; live-проверено | L | — | — |
| 4 | Memory System | 🟡 | Есть short-term/episodic/long-term/identity + ChromaDB vector + Obsidian v5 (починен). **Нет**: confidence, importance, expiration, conflict resolution, cleanup | M | P2 | Добавить метаданные памяти (важность/срок/источник) + cleanup |
| 5 | Tool System | 🟡 | 37 инструментов FOL + двухэтапный выбор в orchestrator (5–12). **Нет единого Tool Registry с risk_level 0–10** | M | P2 | Ввести `risk_level` в schema каждого инструмента; smart selection уже есть |
| 6 | Desktop Control | 🟡 | Открытие/закрытие/горячие клавиши/клики/Finder есть. **Управление через AppleScript System Events, НЕ через Accessibility API (UI tree)** | M | P2 | Добавить AXUIElement-слой (ui tree → поиск элемента → клик), скриншот оставить визуальным fallback'ом |
| 7 | Screen Awareness | ✅ | `context_engine` + vision: активное приложение, URL, текст с экрана, человеческий ответ («Сейчас открыт VS Code…») | L | — | — |
| 8 | Browser Agent | ✅ | Playwright (browser_interact) + cookie sync Chrome + Safari automation | L | — | — |
| 9 | LLM System | ✅ | Цепочка: primary → fallback → local (MLX/Ollama); 429/timeout/пустой ответ обрабатываются; не показывается пользователю | L | — | — |
| 10 | Final Response Layer | ✅ | `personality.py`: Done/Готово/JSON/XML tool-call вырезаются; естественные подтверждения по языку и интенту | L | — | — |
| 11 | Personality | ✅ | Спокойный/дружелюбный/уместный юмор, без роботизма | L | — | — |
| 12 | Языки | 🟡 | RU + EN + mixed ✅. **Транслитерация («privet otkroy safari») не обрабатывается** | L | P3 | Добавить translit-нормализацию перед роутингом |
| 13 | Voice | 🟡 | STT: mlx-whisper + speech_recognition fallback; TTS: macOS say + ElevenLabs (Swift). **VAD/Silero и локальный Piper не подключены** | M | P2 | VAD-фильтр + Piper local TTS как fallback к облаку |
| 14 | SwiftUI / Notch | ✅ | Notch, чат, голос, анимации, tool pills, VNC, approval-ready, активность-статусы (sanitized) | L | — | — |
| 15 | Safety System | ❌ | Есть `Permission` enum (LOW/MEDIUM/HIGH), но **нет risk_level 0–10, нет Approval Flow, нет UI подтверждения** | **H** | **P0** | Risk Engine + approval-карточка в Notch (разрешить/отменить) для удаление файла/отправка email/оплата |
| 16 | Audit Log | ❌ | **Полностью отсутствует** (grep: 0 совпадений) | M | P0 | Журнал: timestamp, tool, args, risk, approval, result — отдельный от чата |
| 17 | Agents | ✅ | General/Architect/Coder/Reviewer/Researcher/Memory + bilingual router + режимы (Companion/Assistant/Agent/Focus) | L | — | — |
| 18 | Productivity | 🟡 | Gmail (fetch/auth), Calendar, Tavily есть в `fetch/`, `auth/`, `analyze/`. **Google Docs нет** | M | P3 | Docs: поиск/чтение/создание |
| 19 | File System | 🟡 | `file_ops` (read/create/move/rename/search) + Finder открытие. Опасные операции без подтверждения | M | P2 | Связать с Approval Flow |
| 20 | Error Handling | 🟡 | 429/timeout скрыты; screen-ошибки человеческим текстом. **Raw exceptions в некоторых путях могут дойти до UI** | M | P2 | Аудит всех except-путей + humanize_error везде |
| 21 | Loop Protection | ✅ | Loop guard в orchestrator (повтор N раз → abort) | L | — | — |
| 22 | Testing | ✅ | 1561 тест, 0 failed; E2E-скрипты (verify_scenarios, e2e_check) есть | L | — | — |
| 23 | Installation | ✅ | `.pkg` 4.1M, устанавливается, сервисы поднимаются сами из .app | L | — | — |
| 24 | Автозапуск | 🟡 | LaunchAgent plist в `setup/`, .app стартует сервисы при открытии. **Login-item автозапуск не настроен** | L | P3 | Добавить Start at Login в SwiftUI |
| 25 | Privacy | ✅ | Ключи в `.env` (gitignored), Obsidian-ключ больше не в шаблоне; в чат не утекают tool args | L | — | — |
| 26 | Performance | 🟡 | FOL import 0.5s; **Accessibility-действие и voice-цикл <2s не замерены** | M | P2 | Замерить hot-path; кэш контекста |
| 27 | Plugin System | ✅ | `fol/modules/plugins/` (loader, manager, hooks, api) | L | — | — |
| 28 | Observability | ❌ | **Нет внутреннего журнала thought/plan/tool/result, отделённого от чата** — «охота за призраком done» | M | P0 | Внутренний trace-журнал каждого цикла (виден в dev-режиме) |
| 29 | Shell-команды | ✅ | Починен: длинный префикс первым, чистка «в терминале/пожалуйста/пунктуация», «запусти команду X» роутится (39 тестов) | L | — | — |

---

## 2. Что уже сделано (последние недели)

- **Obsidian Brain v5** — клиент переписан под Local REST API 5.0.2 (write JSON body, search `?query=`,
  PATCH fallback read→modify→write), vault развёрнут (папки, шаблоны, Profile, индексы), 12 тестов.
- **Context Conversation** — follow-up/тема/привязка в живом пути FOL.
- **Режимы** — Companion/Assistant/Agent/Focus голосом и текстом.
- **Final Response Layer** — XML+JSON tool-call вырезаются, естественные подтверждения.
- **Shell-команды** — длинный префикс первым, чистка мусора (39 тестов).
- **Модели** — автопереключение при 429/timeout/пустом ответе.
- **Безопасность секретов** — ключ Obsidian убран из `.env.template`.

## 3. Критические пробелы (P0 — до v1.0 Stable)

1. **Safety System** — нет risk_level, approval flow и UI подтверждения опасных действий.
2. **Audit Log** — нет журнала действий (безопасность + debugging).
3. **Observability** — нет trace-журнала цикла, отделённого от чата.

## 4. Важные пробелы (P1–P2)

- **Unified Core** — один шлюз вместо 3–4 HTTP-точек (поэтапно).
- **Accessibility API** — UI tree вместо «скриншот→vision→клик» для обычных действий.
- **Memory metadata** — confidence/importance/expiration/cleanup.
- **Tool risk_level 0–10** в schema.
- **Voice VAD/Piper** — локальный цикл голоса.
- **Error Handling** — humanize на всех путях.

## 5. Мелочи (P3)

- Транслитерация ввода.
- Google Docs.
- Start at Login.
- Замеры производительности hot-path.

---

## 6. Рекомендованный порядок работ (по ТЗ)

```
1. AUDIT            ✅ (этот документ)
2. FIX              → Safety+Audit+Observability (P0), затем P1-P2 баги
3. UNIFIED CORE     → FOL Core как единственный мозг, orchestrator-фасад
4. SCREEN           → Accessibility UI tree
5. MEMORY           → metadata + cleanup
6. VOICE            → VAD + Piper
7. AGENTS           → уже почти готово (dynamic-роутинг усиливается)
8. SAFETY           → риск/подтверждения в UI (после FIX-фундамента)
9. UI               → approval-карточки, состояния
10. INSTALLER       → автозапуск при логине
11. 1000+ TESTS     → уже 1561; добавить E2E сценарии S1–S15
12. v1.0 STABLE
```

*Каждый этап заканчивается: тесты → Swift build → живая проверка → коммит.*
