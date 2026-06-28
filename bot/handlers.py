import json
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import datetime
from agents.instances import ChatAgent, GenerationAgent, PlanningAgent
from database import SessionLocal
from models import ContentPlan, AgentState, AuthorProfile

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    db = SessionLocal()
    try:
        profile = db.query(AuthorProfile).filter(AuthorProfile.author_id == user_id).first()
        if not profile:
            profile = AuthorProfile(author_id=user_id, status="onboarding_api_key")
            db.add(profile)
            db.commit()
            await update.message.reply_text("Привет! Я твой AI-помощник по созданию контента. Для начала работы мне нужен твой OpenAI API Key (начинается на sk-...). Пришли его в ответном сообщении.")
        elif profile.status == "onboarding_api_key":
            await update.message.reply_text("Жду твой OpenAI API Key.")
        elif profile.status == "onboarding_github":
            await update.message.reply_text("Жду твой GitHub Personal Access Token (PAT).")
        elif profile.status == "onboarding_channel":
            await update.message.reply_text("Жду ID или юзернейм твоего канала.")
        else:
            await update.message.reply_text("Твой профиль уже настроен! Просто напиши мне, чтобы начать работу.")
    finally:
        db.close()

async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    db = SessionLocal()
    try:
        profile = db.query(AuthorProfile).filter(AuthorProfile.author_id == user_id).first()
        if profile:
            db.delete(profile)
            db.query(ContentPlan).filter(ContentPlan.author_id == user_id).delete()
            db.query(PostsHistory).filter(PostsHistory.author_id == user_id).delete()
            db.commit()
            await update.message.reply_text("Ваш профиль и все данные полностью удалены. Отправьте /start, чтобы начать настройку заново.")
        else:
            await update.message.reply_text("Профиль не найден. Нажмите /start для настройки.")
    finally:
        db.close()

async def handle_get_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    db = SessionLocal()
    try:
        profile = db.query(AuthorProfile).filter(AuthorProfile.author_id == user_id).first()
        if not profile or not profile.openai_api_key:
            await update.message.reply_text("Сначала завершите настройку профиля через /start.")
            return
            
        # Принудительно закрываем старые планы, сбрасывая цикл
        old_plans = db.query(ContentPlan).filter(
            ContentPlan.author_id == user_id, 
            ContentPlan.status.in_(["active", "awaiting_approval"])
        ).all()
        for p in old_plans:
            p.status = "completed"
        db.commit()
            
        await update.message.reply_text("🔄 Сбрасываю цикл. Запускаю генерацию нового контент-плана... Это может занять около минуты.")
        
        def run_agent():
            agent = PlanningAgent()
            thread_db = SessionLocal()
            try:
                agent.run(db=thread_db, author_id=user_id, trigger_message="Generate new content plan.")
            except Exception as e:
                print(f"Critical error in PlanningAgent thread: {e}")
            finally:
                thread_db.close()
        asyncio.create_task(asyncio.to_thread(run_agent))
    finally:
        db.close()

async def handle_my_posts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    db = SessionLocal()
    try:
        from models import PostsHistory
        import datetime
        from datetime import timedelta
        
        # Get posts from last 7 days
        posts = db.query(PostsHistory).filter(
            PostsHistory.published_at >= datetime.datetime.utcnow() - timedelta(days=7)
        ).order_by(PostsHistory.published_at.desc()).all()
        
        if not posts:
            await update.message.reply_text("За последние 7 дней не было публикаций.")
            return
            
        keyboard = {"inline_keyboard": []}
        for post in posts:
            title = post.topic if post.topic else "Без названия"
            # Truncate title
            if len(title) > 30: title = title[:27] + "..."
            date_str = post.published_at.strftime("%d.%m %H:%M")
            keyboard["inline_keyboard"].append([{"text": f"[{date_str}] {title}", "callback_data": f"mypost_{post.post_id}"}])
            
        await update.message.reply_text("Вот список опубликованных постов за последние 7 дней:", reply_markup=keyboard)
    finally:
        db.close()

async def handle_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    db = SessionLocal()
    try:
        plan = db.query(ContentPlan).filter(
            ContentPlan.author_id == user_id,
            ContentPlan.status.in_(["active", "awaiting_approval"])
        ).first()
        
        if not plan:
            await update.message.reply_text("У вас нет активного плана. Используйте команду /get_plan, чтобы сгенерировать новый цикл.")
            return
            
        text_lines = [f"📋 **Ваш текущий контент-план** (Статус: {plan.status})\n"]
        for idx, item in enumerate(plan.items, 1):
            title = item.get("title", "Без названия")
            ptype = item.get("type", "пост")
            date = item.get("planned_date", "Не указана")
            status = item.get("status", "unknown")
            
            # Translate status to human readable emoji
            if status == "published":
                status_emoji = "✅ Опубликован"
            elif status == "generating":
                status_emoji = "⏳ Генерируется"
            elif status == "awaiting_approval":
                status_emoji = "📝 Ждет вашего решения"
            elif status == "planned":
                status_emoji = "📅 Запланирован"
            elif status == "skipped":
                status_emoji = "⏭ Пропущен"
            else:
                status_emoji = status
                
            text_lines.append(f"{idx}. {title} ({ptype})")
            text_lines.append(f"   Дата: {date} | Статус: {status_emoji}\n")
            
        if plan.status == "awaiting_approval":
            keyboard = {
                "inline_keyboard": [
                    [{"text": "✅ Утвердить план", "callback_data": f"approve_plan_{plan.plan_id}"}]
                ]
            }
            await update.message.reply_text("\n".join(text_lines), reply_markup=keyboard)
        else:
            await update.message.reply_text("\n".join(text_lines))
            
    finally:
        db.close()

async def handle_generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from scheduler.tasks import check_generation_queue
    db = SessionLocal()
    try:
        # Автоматический "ремонтник": если посты зависли в статусе generating (например, после краша), возвращаем их в planned
        plans = db.query(ContentPlan).filter(ContentPlan.status == "active").all()
        for p in plans:
            updated = False
            new_items = []
            for it in p.items:
                if it.get("status") == "generating" or not it.get("status"):
                    it["status"] = "planned"
                    updated = True
                new_items.append(it)
            if updated:
                p.items = new_items
        db.commit()
    finally:
        db.close()
        
    await update.message.reply_text("🚀 Размораживаю зависшие посты и ПРИНУДИТЕЛЬНО запускаю генерацию следующего поста... Это займет ~1 минуту.")
    asyncio.create_task(asyncio.to_thread(lambda: check_generation_queue(force=True)))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text or update.message.caption or ""

    db = SessionLocal()
    try:
        profile = db.query(AuthorProfile).filter(AuthorProfile.author_id == user_id).first()
        if not profile:
            profile = AuthorProfile(author_id=user_id, status="onboarding_api_key")
            db.add(profile)
            db.commit()
            await update.message.reply_text("Привет! Я твой AI-помощник по созданию контента. Для начала работы мне нужен твой OpenAI API Key (начинается на sk-...). Пришли его в ответном сообщении.")
            return
            
        if profile.status == "onboarding_api_key":
            profile.openai_api_key = text.strip()
            profile.status = "onboarding_github"
            db.commit()
            await update.message.reply_text("Супер. Теперь мне нужен твой GitHub Personal Access Token (PAT), чтобы я мог читать твои репозитории и генерировать посты на их основе. Если у тебя его нет, можешь создать его в настройках GitHub Developer Settings.")
            return

        if profile.status == "onboarding_github":
            profile.github_token = text.strip()
            profile.status = "onboarding_channel"
            db.commit()
            await update.message.reply_text("Принято! Теперь добавь меня администратором в свой Telegram канал и пришли его ID или юзернейм (например, @mychannel).")
            return
            
        if profile.status == "onboarding_channel":
            profile.channel_id = text.strip()
            profile.status = "active"
            db.commit()
            await update.message.reply_text("Настройка завершена! Расскажи, о чем твой канал и какой у него стиль, и мы начнем.")
            return

        if update.message.photo:
            file_id = update.message.photo[-1].file_id # highest res
            text = f"[Пользователь прикрепил изображение. ID: {file_id}]"
            
            state = db.query(AgentState).filter(AgentState.author_id == user_id).first()
            plan = db.query(ContentPlan).filter(ContentPlan.status == "active", ContentPlan.author_id == user_id).first()
            
            if state and state.plan_item_id and state.plan_item_id != "chat":
                if plan:
                    plan.items = [
                        {**item, "image_ref": file_id} if item.get("item_id") == state.plan_item_id else item
                        for item in plan.items
                    ]
                    db.commit()
            elif plan:
                pending_item = next((item for item in plan.items if item.get("status") == "awaiting_approval"), None)
                if pending_item:
                    plan.items = [
                        {**item, "image_ref": file_id} if item.get("item_id") == pending_item["item_id"] else item
                        for item in plan.items
                    ]
                    db.commit()
                    await update.message.reply_text("Изображение получено и прикреплено к посту. Выберите действие на предложенном посте, чтобы продолжить.")
                    return
                else:
                    await update.message.reply_text("Картинка получена, но сейчас нет поста, ожидающего ответа.")
                    return

        # 1. Reset last_author_contact_at for active plans
        plan = db.query(ContentPlan).filter(ContentPlan.status == "active", ContentPlan.author_id == user_id).first()
        if plan:
            plan.last_author_contact_at = datetime.datetime.utcnow()
            db.commit()

        # 2. Check for AgentState to resume GenerationAgent
        state = db.query(AgentState).filter(AgentState.author_id == user_id).first()
        if state and state.plan_item_id and state.plan_item_id != "chat":
            agent = GenerationAgent()
            ctx = {"plan_item_id": state.plan_item_id}
            response = agent.run(db=db, author_id=user_id, trigger_message=text, context=ctx, previous_messages=state.messages)
            db.delete(state)
            db.commit()
        else:
            # Default to ChatAgent for standard messages
            agent = ChatAgent()
            prev_msgs = state.messages if state else None
            if state:
                db.delete(state)
                db.commit()
            response = agent.run(db=db, author_id=user_id, trigger_message=text, previous_messages=prev_msgs)

        # 3. Handle state
        if isinstance(response, dict):
            if response.get("status") == "paused":
                new_state = AgentState(
                    author_id=user_id,
                    plan_item_id=response.get("plan_item_id"),
                    messages=response.get("messages")
                )
                db.add(new_state)
                db.commit()
                # Do not reply text because we already sent the question via tools
            elif response.get("status") == "completed":
                new_state = AgentState(
                    author_id=user_id,
                    plan_item_id="chat",
                    messages=response.get("messages")
                )
                db.add(new_state)
                db.commit()
                await update.message.reply_text(response.get("content"))
        else:
            await update.message.reply_text(str(response))
    finally:
        db.close()

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    user_id = str(update.effective_user.id)
    db = SessionLocal()
    try:
        if data.startswith("approve_plan_"):
            plan_id = data.split("_")[-1]
            plan = db.query(ContentPlan).filter(ContentPlan.plan_id == plan_id).first()
            if plan and plan.status == "awaiting_approval":
                plan.status = "active"
                db.commit()
                await query.edit_message_text(text="Plan approved! Generation agent will pick up items when due.")
            else:
                await query.edit_message_text(text="Plan not found or already processed.")
                
        elif data.startswith("publish_now_"):
            plan_item_id = data.split("_", 2)[2]
            plan = db.query(ContentPlan).filter(ContentPlan.status == "active", ContentPlan.author_id == user_id).first()
            if plan:
                plan.items = [
                    {**item, "status": "published"} if item.get("item_id") == plan_item_id else item
                    for item in plan.items
                ]
                db.commit()
                
                # Wake up generation agent to actually publish immediately
                state = db.query(AgentState).filter(AgentState.plan_item_id == plan_item_id).first()
                if state:
                    agent = GenerationAgent()
                    ctx = {"plan_item_id": plan_item_id}
                    agent.run(db=db, author_id=user_id, trigger_message="Пост согласован для немедленной публикации. Вызывай publish_post прямо сейчас.", context=ctx, previous_messages=state.messages)
                    db.delete(state)
                    db.commit()
                    
                await query.edit_message_text(text="🚀 Пост опубликован!")
                
        elif data.startswith("schedule_post_"):
            plan_item_id = data.split("_", 2)[2]
            plan = db.query(ContentPlan).filter(ContentPlan.status == "active", ContentPlan.author_id == user_id).first()
            if plan:
                planned_date_str = "неизвестно"
                plan.items = [
                    {**item, "status": "scheduled"} if item.get("item_id") == plan_item_id else item
                    for item in plan.items
                ]
                for item in plan.items:
                    if item.get("item_id") == plan_item_id:
                        planned_date_str = item.get("planned_date", "неизвестно")
                db.commit()
                await query.edit_message_text(text=f"📅 Пост одобрен и запланирован на публикацию: {planned_date_str}")
                
        elif data.startswith("mypost_"):
            post_id = data.split("_", 1)[1]
            from models import PostsHistory
            post = db.query(PostsHistory).filter(PostsHistory.post_id == post_id).first()
            if post:
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "🔄 Переопубликовать", "callback_data": f"republish_{post_id}"}],
                        [{"text": "🗑 Удалить с канала", "callback_data": f"deletepost_{post_id}"}],
                        [{"text": "🔙 Назад", "callback_data": "back_to_posts"}]
                    ]
                }
                text = f"📝 **{post.topic}**\n\n"
                text += f"Тип: {post.type}\n"
                text += f"Дата: {post.published_at.strftime('%Y-%m-%d %H:%M')}\n"
                if post.message_id:
                    text += f"ID сообщения: {post.message_id}\n"
                else:
                    text += f"⚠️ Ошибка: ID сообщения не сохранен.\n"
                    
                await query.edit_message_text(text=text, reply_markup=keyboard)
            else:
                await query.answer("Пост не найден.")
                
        elif data == "back_to_posts":
            from models import PostsHistory
            import datetime
            from datetime import timedelta
            posts = db.query(PostsHistory).filter(PostsHistory.published_at >= datetime.datetime.utcnow() - timedelta(days=7)).order_by(PostsHistory.published_at.desc()).all()
            if not posts:
                await query.edit_message_text("За последние 7 дней не было публикаций.")
            else:
                keyboard = {"inline_keyboard": []}
                for post in posts:
                    title = post.topic if post.topic else "Без названия"
                    if len(title) > 30: title = title[:27] + "..."
                    date_str = post.published_at.strftime("%d.%m %H:%M")
                    keyboard["inline_keyboard"].append([{"text": f"[{date_str}] {title}", "callback_data": f"mypost_{post.post_id}"}])
                await query.edit_message_text("Вот список опубликованных постов за последние 7 дней:", reply_markup=keyboard)
                
        elif data.startswith("deletepost_"):
            post_id = data.split("_", 1)[1]
            from models import PostsHistory
            post = db.query(PostsHistory).filter(PostsHistory.post_id == post_id).first()
            if post:
                profile = db.query(AuthorProfile).filter(AuthorProfile.author_id == user_id).first()
                if profile and profile.channel_id and post.message_id:
                    import requests, config
                    res = requests.post(
                        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/deleteMessage",
                        json={"chat_id": profile.channel_id, "message_id": post.message_id}
                    )
                    if res.status_code == 200:
                        db.delete(post)
                        db.commit()
                        await query.edit_message_text("🗑 Пост успешно удален с канала и из истории.")
                    else:
                        await query.answer(f"Ошибка удаления: {res.text}", show_alert=True)
                else:
                    await query.answer("Невозможно удалить: нет channel_id или message_id.", show_alert=True)
            else:
                await query.answer("Пост не найден.")
                
        elif data.startswith("republish_"):
            post_id = data.split("_", 1)[1]
            from models import PostsHistory
            post = db.query(PostsHistory).filter(PostsHistory.post_id == post_id).first()
            if post and post.post_text:
                profile = db.query(AuthorProfile).filter(AuthorProfile.author_id == user_id).first()
                if profile and profile.channel_id:
                    import requests, config
                    if post.image_ref:
                        res = requests.post(
                            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto",
                            json={"chat_id": profile.channel_id, "photo": post.image_ref, "caption": post.post_text}
                        )
                    else:
                        res = requests.post(
                            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                            json={"chat_id": profile.channel_id, "text": post.post_text}
                        )
                    if res.status_code == 200:
                        post.message_id = res.json().get("result", {}).get("message_id")
                        db.commit()
                        await query.edit_message_text("🚀 Пост переопубликован!")
                    else:
                        await query.answer(f"Ошибка публикации: {res.text}", show_alert=True)
                else:
                    await query.answer("Не настроен канал.", show_alert=True)
            else:
                await query.answer("Текст поста не сохранен в базе, переопубликовать невозможно.", show_alert=True)
                    
    finally:
        db.close()
