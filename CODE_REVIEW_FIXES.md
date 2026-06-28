# Code Review: критические проблемы и требуемые исправления

Этот документ — результат ревью репозитория `PostBot_2` против спецификации `telegram_content_bot_prompts.md`. Каждый пункт включает: диагноз, как он был подтверждён (не предположение — реально воспроизведено), и конкретное требуемое исправление. Порядок — по убыванию критичности.

---

## 🔴 БЛОКИРУЮЩИЕ (проект не работает в текущем виде)

### 1. Проект не импортируется — `ImportError` на старте

**Диагноз:** смешение relative (`from .config import ...`) и absolute (`from database import ...`) импортов одних и тех же модулей в разных файлах, без единого `__init__.py` во всём дереве проекта.

**Подтверждено эмпирически:**
```
$ python3 main.py
Traceback (most recent call last):
  File "main.py", line 6, in <module>
    from database import engine, Base
  File "database.py", line 4, in <module>
    from .config import DATABASE_URL
ImportError: attempted relative import with no known parent package
```

**Где встречается:**
- `database.py`: `from .config import DATABASE_URL`
- `models.py`: `from .database import Base`
- `agents/instances.py`: `from .core import AgentCore`
- Все остальные файлы (`main.py`, `tools/executors.py`, `scheduler/tasks.py`, `bot/handlers.py`) используют **абсолютные** импорты (`from database import ...`, `from models import ...`)

**Требуемое исправление:** выбрать одну схему импортов и применить её везде. Рекомендация — раз проект запускается как `python main.py` из корня (не как установленный пакет), использовать **абсолютные импорты везде**, без точек. Заменить:
- `database.py`: `from .config import DATABASE_URL` → `from config import DATABASE_URL`
- `models.py`: `from .database import Base` → `from database import Base`
- `agents/instances.py`: `from .core import AgentCore` → `from agents.core import AgentCore`, `from .prompts import ...` → `from agents.prompts import ...`

После исправления — обязательно реально запустить `python3 main.py` (хотя бы до момента ошибки токена Telegram, что нормально без реального токена) и подтвердить, что импорт-цепочка проходит целиком.

---

### 2. Изменения статусов в `content_plan.items` не сохраняются в БД

**Диагноз:** паттерн `item["status"] = "X"; plan.items = list(plan.items); db.commit()` не сохраняет изменение. `list(plan.items)` создаёт новый список-обёртку, но элементы внутри — те же самые объекты-словари, и SQLAlchemy не обязательно детектит мутацию JSON-колонки таким способом надёжно во всех версиях.

**Подтверждено эмпирически** (минимальный repro на чистом SQLAlchemy 2.0.30, той же версии, что в requirements.txt):
```python
plan.items = [{"item_id": "abc", "status": "planned"}]
db.commit()
# ... в новой сессии:
plan.items[0]["status"] = "approved"
plan.items = list(plan.items)
db.commit()
# ... в ТРЕТЬЕЙ сессии:
print(plan.items)  # -> [{'item_id': 'abc', 'status': 'planned'}]  ← изменение НЕ сохранилось
```

**Где встречается (минимум 3 места):**
- `bot/handlers.py`, `handle_callback_query`, ветка `approve_post_*` (строки ~44-49)
- `scheduler/tasks.py`, `check_generation_queue` (строка ~17)
- Потенциально везде, где ожидается обновление статуса пункта плана после `publish_post`/`propose_post` (сейчас не реализовано, см. п.3 и п.4 — когда будет реализовано, там тоже нужно будет сохранять статус правильно)

**Последствия бага:**
- Нажатие кнопки "Утвердить" автором не сохраняется → guard в `publish_post` будет вечно отказывать, даже когда автор согласился
- `check_generation_queue` запускается каждые 10 минут (см. `main.py`) и **бесконечно повторно** находит один и тот же item со статусом `"planned"`, запуская `GenerationAgent` заново при каждом тике → неконтролируемый расход OpenAI API

**Требуемое исправление:** один из двух вариантов:
1. Использовать `sqlalchemy.orm.attributes.flag_modified(plan, "items")` сразу после мутации, явно:
   ```python
   from sqlalchemy.orm.attributes import flag_modified
   for item in plan.items:
       if item.get("item_id") == plan_item_id:
           item["status"] = "approved"
   flag_modified(plan, "items")
   db.commit()
   ```
2. Либо (более надёжно, рекомендуется) — пересобрать список полностью новыми словарями, а не мутировать существующие:
   ```python
   new_items = [
       {**item, "status": "approved"} if item.get("item_id") == plan_item_id else item
       for item in plan.items
   ]
   plan.items = new_items
   db.commit()
   ```

**После исправления — обязательно повторить мой repro-тест** (создать item, изменить статус, закоммитить, открыть НОВУЮ сессию, прочитать заново) и убедиться, что изменение видно. Не доверять одной и той же открытой сессии — она может показывать закешированное in-memory состояние независимо от того, что реально в БД.

---

### 3. `publish_post` не публикует ничего — закомментированный stub

**Диагноз:** в `tools/executors.py`, функция `publish_post` после прохождения guard'а на проверку `approved`-статуса не делает реального вызова Telegram API:
```python
# Execute Telegram API call here
# ...

# Update plan status to published
return json.dumps({"status": "success", "message": "Post published to channel."})
```
Это значит функция всегда лжёт об успехе, ничего не публикуя и не обновляя `posts_history`.

**Требуемое исправление:** реализовать реальный вызов через `python-telegram-bot` (например, через `Bot(token=config.TELEGRAM_BOT_TOKEN).send_message`/`send_photo` к `channel_id` из `author_profile`), и после успешной отправки:
1. Обновить статус соответствующего item в `content_plan.items` на `"published"` (используя безопасный паттерн из п.2)
2. Создать запись в `posts_history` с `message_id`, полученным из ответа Telegram API
3. Только после этого вернуть `{"status": "success", ...}` модели — текущий early-return без выполнения действия должен быть убран

---

### 4. `propose_post` не отправляет автору пост с кнопками

**Диагноз:** в `tools/executors.py`, функция `propose_post`:
```python
def propose_post(self, post_text: str, need_image: bool, image_prompt_or_request: str = None):
    plan_item_id = self.context.get("plan_item_id")
    if plan_item_id:
        # Here we'd update the item status to 'awaiting_approval'
        pass
    return json.dumps({"status": "success", "message": "Post proposed to author."})
```
Реальной отправки сообщения в Telegram с `InlineKeyboardMarkup` (кнопки `✅ Опубликовать / ✏️ Редактировать / ⏭ Пропустить`) не происходит — автор никогда не увидит интерфейс согласования.

**Требуемое исправление:** реализовать реальную отправку через `python-telegram-bot` в личный чат с автором (`author_id`/`chat_id` из контекста), с `InlineKeyboardMarkup`, содержащей три кнопки с `callback_data`, кодирующим `plan_item_id` и действие (например `approve_post_<id>`, `edit_post_<id>`, `skip_post_<id>` — обратить внимание, что в `handlers.py` сейчас обрабатывается только `approve_post_*`, остальные два варианта нужно тоже добавить в `handle_callback_query`). После отправки — обновить статус item на `"awaiting_approval"` тем же безопасным паттерном мутации из п.2.

---

## 🟠 СЕРЬЁЗНЫЕ РАСХОЖДЕНИЯ СО СПЕЦИФИКАЦИЕЙ

### 5. Используется не та модель, и `reasoning_effort` никогда не передаётся в API

**Диагноз:** `agents/core.py`:
```python
self.model = "gpt-4o"
...
response = client.chat.completions.create(
    model=self.model,
    messages=messages,
    tools=self.tools_schema,
    tool_choice="auto",
)
```
Согласованная модель — `gpt-5.5` с `reasoning_effort` (`high` для Planning, `medium` для Generation, `low`/`medium` для Chat — см. раздел 1 `telegram_content_bot_prompts.md`). `agents/instances.py` корректно передаёт `reasoning_effort="high"`/`"medium"`/`"low"` в конструктор `AgentCore`, но `core.py` сохраняет это значение в `self.reasoning_effort` и **никогда** не использует его при вызове API.

**Требуемое исправление:**
```python
self.model = "gpt-5.5"
...
response = client.chat.completions.create(
    model=self.model,
    messages=messages,
    tools=self.tools_schema,
    tool_choice="auto",
    reasoning_effort=self.reasoning_effort,
)
```
Проверить актуальный API-контракт для `reasoning_effort` в установленной версии SDK `openai==1.30.1` — возможно, потребуется обновление пакета, если параметр не поддерживается в этой версии. Если используется Responses API вместо Chat Completions — синтаксис параметра может отличаться, нужно сверить с документацией `platform.openai.com/docs/models/gpt-5.5`.

---

### 6. Terminal tools не останавливают агентный цикл

**Диагноз:** `agents/core.py`, после исполнения tool call:
```python
if func_name in ["submit_plan", "publish_post", "propose_patch", "ask_author", "propose_post"]:
    # ...
    pass
```
Комментарий честно признаёт, что нужно прерывать цикл, но код этого не делает — после `pass` `while`-цикл продолжается, модель может вызвать что угодно ещё, включая повторный вызов того же terminal tool.

**Требуемое исправление:**
```python
TERMINAL_TOOLS = {"submit_plan", "publish_post", "propose_patch", "propose_post"}

# внутри цикла, после исполнения tool call:
if func_name in TERMINAL_TOOLS:
    return result  # или сформировать финальный ответ модели на основе result и вернуть его
```
`ask_author` — отдельный случай, не terminal tool в классическом смысле (см. п.7) — он должен приостанавливать выполнение, а не завершать его так же, как `submit_plan`/`publish_post`.

---

### 7. `ask_author` не реализует настоящую асинхронную паузу

**Диагноз:** `tools/executors.py`:
```python
def ask_author(self, question: str):
    return json.dumps({"status": "paused", "message": "Sent question to author. Waiting for reply."})
```
Это просто текстовая заглушка. Реального сохранения состояния разговора (что именно за вопрос был задан, для какого `plan_item_id`, в ожидании ответа от какого `author_id`) и реальной паузы исполнения (выход из `agent.run()` с сохранением контекста для последующего продолжения при получении ответа в `handle_message`) — нет.

**Требуемое исправление:** это нетривиальная архитектурная доработка:
1. `ask_author` должен реально отправить вопрос в Telegram (через `Bot.send_message`)
2. Сохранить в БД "pending question" с привязкой к `plan_item_id` и текущему состоянию агентного диалога (messages list на момент паузы)
3. `agent.run()` должен вернуть управление (не зависать в `while`), пометив, что выполнение приостановлено
4. `handle_message` в `bot/handlers.py` должен проверять, есть ли pending question для этого автора, и если есть — не запускать `ChatAgent`, а продолжить приостановленный `GenerationAgent` с ответом автора как новым сообщением в сохранённой истории `messages`

Это связано с п.8 (логика напоминаний) — оба пункта требуют единого механизма "приостановленного состояния", который сейчас в проекте отсутствует полностью.

---

### 8. Логика напоминаний (30 минут → эскалация) и заморозки плана отсутствует

**Диагноз:** ни в `bot/handlers.py`, ни в `scheduler/tasks.py` нет:
- Таймера "напоминать каждые 30 минут первые 6-8 часов, потом реже"
- Сброса таймера при любом сообщении автора в чате
- Заморозки плана (не запускать генерацию следующего item, пока текущий не получил финальный статус `published`/`skipped`)

Это прямо противоречит согласованной спецификации (раздел 0 и раздел 7 документа `telegram_content_bot_prompts.md`), где явно зафиксировано: никакой принудительной публикации, план замораживается до ответа автора.

**Требуемое исправление:** добавить:
1. Поле в БД (например, в `ContentPlan` или отдельную таблицу) для хранения `last_reminder_at`, `last_author_contact_at`, `reminder_phase` для текущего pending item
2. Новую scheduler-задачу (например `check_reminders`, интервал 5-10 минут), которая проверяет items со статусом `awaiting_approval`, считает время с последнего напоминания/контакта, и либо шлёт напоминание (используя `reminder_interval_minutes_phase1`/`phase2`/`reminder_phase1_duration_hours` из `author_profile.schedule_settings`), либо ничего не делает, если рано
3. В `handle_message` — сброс `last_author_contact_at` на текущее время при **любом** входящем сообщении от автора, независимо от содержания
4. В `check_generation_queue` — добавить условие "не запускать генерацию следующего item, если есть item в статусе, отличном от финального" (сейчас там просто `for item in plan.items: if item.get("status") == "planned"` без такой проверки)

---

### 9. `check_generation_queue` не проверяет `planned_date` / lead time

**Диагноз:** `scheduler/tasks.py`:
```python
# Here we would check dates and lead times. 
# For MVP simulation, we just find the first 'planned' item and trigger GenerationAgent
for item in plan.items:
    if item.get("status") == "planned":
```
Никакой проверки на `planned_date` минус `generation_lead_time_hours` из `author_profile.schedule_settings` нет — генерация запускается на первый `planned`-item немедленно.

**Требуемое исправление:**
```python
from datetime import datetime, timedelta

# ...
profile = db.query(AuthorProfile).filter(AuthorProfile.author_id == author_id).first()
lead_hours = profile.schedule_settings.get("generation_lead_time_hours", 24)

for item in plan.items:
    if item.get("status") == "planned":
        planned_date = datetime.fromisoformat(item["planned_date"])
        if datetime.utcnow() >= planned_date - timedelta(hours=lead_hours):
            # запускать генерацию
            ...
```

---

## 🟡 МЕНЕЕ КРИТИЧНО (не блокирует MVP, но нужно знать)

10. `get_plan_item` в `tools/executors.py` читает данные из переданного `self.context`, а не из БД по `plan_item_id` — упрощение для MVP, само по себе не баг, но если контекст между запусками агента не передаётся правильно через `scheduler/tasks.py`, это может рассинхронизироваться с реальным состоянием БД. Стоит со временем заменить на реальный запрос к БД.

11. Полностью отсутствует реализация сбора `views` (через forward-self трюк) и `message_reaction_count` (через update listener) — раздел 7 спецификации. Этого функционала нет ни одной строкой кода. Нужен отдельный модуль (например `stats.py`) и обработчик `message_reaction_count` update в `main.py`.

12. `tool_choice="auto"` в `core.py` — не проблема, но стоит протестировать поведение `additionalProperties: false` без полного списка `required` для всех свойств в schemas.py при strict tool calling — некоторые версии OpenAI SDK требуют, чтобы при `additionalProperties: false` все свойства были в `required`. Сейчас, например, в `get_posts_history` свойство `limit` не в `required`, при этом `additionalProperties: false` — стоит протестировать реальным вызовом API, не падает ли он на этом.

---

## Рекомендованный порядок исправлений

1. Сначала пункт 1 (импорты) — без этого вообще ничего не запустить и не протестировать остальное
2. Затем пункт 2 (JSON-мутация) — это корень нескольких других проблем (3, 8, 9 косвенно зависят от корректного сохранения статусов)
3. Затем пункты 3-4 (реальная публикация и реальная отправка поста на согласование) — без них система не делает свою основную работу
4. Затем пункт 5 (модель и reasoning_effort) — простое исправление, но влияет на качество всех ответов
5. Затем пункты 6-9 — логика цикла и напоминаний
6. Пункты 10-12 — можно отложить на после первого работающего end-to-end прогона

После каждого блока исправлений рекомендую реально запускать сценарий (хотя бы локально с тестовым каналом/ботом), а не полагаться только на синтаксическую проверку — именно отсутствие реального запуска привело к тому, что предыдущая версия отчиталась о работающей системе, которая не проходит дальше третьей строчки `main.py`.
