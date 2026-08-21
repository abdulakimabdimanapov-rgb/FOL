# CONVERSATION_UX_AUDIT — FOL как живой conversational assistant

> Дата: 2026-08-17. Этап: аудит перед реализацией «Conversational AI + Dynamic Island UX Overhaul».
> Метод: чтение кода (fol-app/, orchestrator/, fol/), прогон тестов, точечные проверки SSE/голоса/персистентности.
> Итог: **ядро диалога уже существует и работает** (история, follow-up, SSE, очередь, interrupt, barge-in). Проблемы — в **неполноте состояний UI, отсутствии элементов управления (Stop/Retry), паре гонок и пробелах follow-up**.

---

## 1. Ответы на вопросы аудита (spec §27)

| Вопрос | Ответ (по коду) |
|---|---|
| **Почему предыдущие сообщения «исчезали»?** | (а) `ChatMessage` жили только в памяти `ChatViewModel` — после рестарта приложения диалог обнулялся до приветствия; (б) авто-схлопывание стадии 1 через 3s после `complete` (`NotchOverlayController.handleTwinStateChange`) + компакт-пилюля показывает только время/точку — ответ «пропадал» визуально; (в) серверный `_conversation_history` — список в памяти процесса. **Исправлено в предыдущем этапе**: `ChatMessage` → Codable, история пишется в `~/.fol/chat_history.json` (debounce 1.5s) и восстанавливается; сервер инициализирует persistent store (`~/.fol/conversation_history.jsonl`) на старте; на стадии 2 после ответа панель не схлопывается. |
| **Где теряется conversation state?** | Явного объекта `ConversationState` (topic/task/mode/pending_action) нет — есть глобальный `_conversation_history` + `_conversation_store` (JSONL) + `current_job` (state machine). Follow-up контекст берётся из `_get_recent_history_sync(40)`. Найдена и исправлена гонка: store флашится асинхронно (`asyncio.create_task`), поэтому `_get_recent_history_sync` мог отдавать историю **без текущего сообщения** — теперь живая память в приоритете, store — fallback после рестарта. |
| **Почему follow-up иногда не работает?** | `resolve_followup()` (orchestrator/followup.py) переписывает **только сообщения с местоимениями** (`это`, `там`, `он`, `она`, `ещё`, `а теперь`, `продолжай`, «сделай так же», «какой из них», «первый», «последний»). Классический случай из спек-сценария — **«Какая самая важная?»** (без местоимения) — НЕ переписывается. Также нет ни одного теста на followup. |
| **Почему UI показывает «один ответ»?** | Полноценный таймлайн уже есть (`ChatView` рендерит все `messages`, сообщения не заменяются) — проблема была в персистентности и авто-схлопывании (см. выше). Дополнительно: 202-ответ сервера при очереди не парсится UI (SSE-парсер ждёт `event:`), хотя события очереди доходят через `/events`. |
| **Как реализован SSE?** | `POST /chat` → `StreamingResponse` с `event: state/token/activity/toolCall/toolProgress/toolResult/error/component/suggestion/ping`. Перед отправкой генератор оборачивается `sanitize_event_stream` (response_formatter): tool_call/tool_result выкидываются, JSON в токенах удерживается, ошибки humanize-ятся. UI: `SSESessionDelegate` (per-request /chat) + `EventsSSEDelegate` (persistent /events). Состояние `{"state": "cancelled"}` сервером **эмитится, но UI его не знает** — `TwinState` не имеет кейса `.cancelled`, событие молча игнорируется, интерфейс застревает в «thinking». |
| **Как UI получает activity/status?** | `activity`-события несут только `{category, label}` (санитизировано). `ChatViewModel.handleActivity` обновляет `taskProgress`, `currentToolAction` (VNC) и `statusText` (добавлен на прошлом этапе) → показывается в чате, на стадии 1 и в компакт-пилюле. Имена инструментов/аргументы/JSON в UI не попадают. |
| **Как TTS связан с новым сообщением?** | `sendMessage()` вызывает `audioManager.stopTTS()` (пользователь берёт слово), `startRecording()` тоже (`barge-in` уже работает — E2E шаг 7 покрыт). По `complete` — `speakLastTwinMessage()`. |
| **Почему дизайн не ощущается как Dynamic Island?** | Три стадии (0 компакт / 1 статус-мини / 2 полный чат) + peeping/dangling маскоты уже есть. Ощущение «мёртвости» давали: отсутствие живых статусов (исправлено — `statusText`), авто-схлопывание (исправлено), отсутствие состояний `listening` и `cancelled`, отсутствие кнопок Stop/Retry, отсутствие «Responding…» при потоке токенов. |

---

## 2. Найденные проблемы (приоритизировано)

| # | Проблема | Причина | Компонент | Статус |
|---|---|---|---|---|
| P1 | После interrupt UI застревает в «thinking» | `TwinState` не имеет `.cancelled`; событие `{"state":"cancelled"}` игнорируется | ChatViewModel, TwinState, NotchPanel, TwinCharacterView | **TODO** |
| P2 | Нет кнопки Stop/Cancel в UI | Серверный `POST /chat/interrupt` есть, UI его не вызывает | NotchViews, ChatViewModel | **TODO** |
| P3 | Нет Retry при ошибке | Ошибки выводятся как текст, действие не предлагается | ChatView, ChatViewModel | **TODO** |
| P4 | «Какая самая важная?» не резолвится | `resolve_followup` ловит только местоимения; короткий вопрос без местоимения не переписывается | followup.py | **TODO** |
| P5 | Нет тестов на followup | Файл тестов отсутствует | tests | **TODO** |
| P6 | Нет состояния «Listening…» / «Responding…» | Статусы не привязаны к голосу и к началу стрима токенов | ChatViewModel | **TODO** |
| P7 | 202-ответ очереди не парсится UI | SSE-парсер ждёт `event:`; тело 202 — JSON | ChatViewModel/SSESessionDelegate | Low (события очереди доходят через /events) |
| P8 | Диалог «по одному» (уже исправлено) | персистентность + авто-схлопывание | (предыдущий этап) | ✅ Done |
| P9 | Гонка store/memory (уже исправлено) | асинхронный flush store | server.py `_get_recent_history_sync` | ✅ Done |
| P10 | Повреждён `fol/modules/llm/router.py` внешним процессом | вставлен блок поверх `def _prepare_messages` | router.py | ✅ Fixed (восстановлен к HEAD) |

---

## 3. Предлагаемая архитектура (минимальные изменения, ничего не ломаем)

```
User
 ↓
sendMessage() / startRecording()
 ↓
ChatViewModel (UI state: twinState + statusText + messages)
 ↓
POST /chat (SSE) ──► orchestrator
                      ├─ resolve_followup(message, recent_history)   ← расширить
                      ├─ если занято → 202 + message_queue (broadcast через /events)
                      └─ run_agent_loop_streaming
                           ├─ state: thinking → working → complete | cancelled
                           ├─ activity: {category, label} → statusText
                           └─ token → appendTokenToCurrentTwinMessage
 ↓
UI: ChatView (таймлайн + статус + Stop/Retry) · Dynamic Island (стадии 0/1/2, статусы)
```

**Состояния Dynamic Island (целевые):**

| Состояние | Как реализуется | Триггер |
|---|---|---|
| `idle` | компакт-пилюля: время/точка | twinState == .idle |
| `listening` | statusText = "Listening…", waveform в пилюле | voiceState == .recording |
| `thinking` | statusText = "Thinking…", пульс точки | state event thinking |
| `planning` | statusText = "Planning…" (резерв) | activity без лейбла на старте |
| `working` | statusText из activity («Searching…» и т.д.) | activity events |
| `responding` | statusText = "Responding…" при первом токене | token event |
| `complete` | «Done» + галочка, гаснет через 2.5s | state event complete |
| `cancelled` | «Cancelled» + панель не сворачивается | state event cancelled (новый кейс TwinState) |
| `error` | дружелюбный текст + кнопка Retry | error event / сетевой сбой |

**Conversation state** — не вводим новый класс: `current_job` (state machine) + `_get_recent_history_sync` (контекст) + `resolve_followup` (разрешение ссылок) + `~/.fol/conversation_history.jsonl` (персистентность). Это уже единый путь; документально зафиксировать в ARCHITECTURE.

---

## 4. Порядок исправлений

1. **Server — followup**: правило «короткий вопрос без местоимения после содержательного ответа» → prepend контекста. Тесты `orchestrator/test_followup.py` (матрица: «Какая самая важная?», «это», «там», «он/она», «ещё», «а теперь», «продолжай», «сделай так же», «какой из них», «первый», «последний», негативные: приветствие, команда).
2. **App — состояния**: `TwinState` + `.cancelled`; обработка `{"state":"cancelled"}`; статусы «Listening…»/«Transcribing…» (голос) и «Responding…» (первый токен).
3. **App — Stop**: кнопка Stop в полном чате при thinking/working → `POST /chat/interrupt`.
4. **App — Retry**: под сообщением-ошибкой кнопка Retry → повтор последнего пользовательского сообщения.
5. Тесты/сборка: pytest (серверные + новые followup) + `swift build`.

---

## 5. Риски

- **Добавление кейса в `TwinState`** ломает все `switch` (AIStatusDot, TwinCharacterView, ChatViewModel, NotchOverlayController) — обновить все; иначе compile error (хорошо: компилятор поймает).
- **`cancelled` от сервера** приходит только на следующем шаге цикла; если поток уже завершился — состояние сбросится в `idle` (безопасно).
- **Retry** повторяет `lastSentText` — не должен повторяться при уже активной задаче (guard по twinState).
- **Follow-up prepend** может переписать осмысленный вопрос — правило строго консервативное: только короткие вопросительные (<6 слов, заканчивается на «?»), без командных глаголов (напиш/открой/создай/найди/сохран).
- Не трогаем ConfirmationGate/RiskScorer/агентов/память.

---

## 6. Необходимые тесты

| Область | Тесты |
|---|---|
| followup | короткий вопрос; все местоимения; негативные (greeting, команда, нет истории); truncation >400; idempotence (двойной prepend не накапливается) |
| cancel | `POST /chat/interrupt` → `interrupt_requested`, состояние `cancelled` в потоке (есть в test_server частично — расширить) |
| persistence | ✅ уже есть (`orchestrator/test_conversation_persistence.py`, 4 теста) |
| retry/queue | UI-уровень — swift build; серверная очередь уже покрыта (202) |
| SSE states | тест, что UI-маппинг не падает на `cancelled` (compile-time гарантия) |

Существующие тесты не удаляются; полный прогон в конце этапа.
