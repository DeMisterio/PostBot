import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import datetime
from agents.instances import ChatAgent, GenerationAgent
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
            plan = db.query(ContentPlan).filter(ContentPlan.status == "active", ContentPlan.author_id == user_id).first()
            if plan:
                pending_item = next((item for item in plan.items if item.get("status") == "awaiting_approval"), None)
                if pending_item:
                    plan.items = [
                        {**item, "image_ref": file_id} if item.get("item_id") == pending_item["item_id"] else item
                        for item in plan.items
                    ]
                    db.commit()
                    await update.message.reply_text("Изображение получено и прикреплено к посту. Нажмите '✅ Опубликовать' на предложенном посте, чтобы продолжить.")
                    return
            await update.message.reply_text("Картинка получена, но сейчас нет поста, ожидающего согласования с картинкой.")
            return

        # 1. Reset last_author_contact_at for active plans
        plan = db.query(ContentPlan).filter(ContentPlan.status == "active", ContentPlan.author_id == user_id).first()
        if plan:
            plan.last_author_contact_at = datetime.datetime.utcnow()
            db.commit()

        # 2. Check for AgentState to resume GenerationAgent
        state = db.query(AgentState).filter(AgentState.author_id == user_id).first()
        if state:
            agent = GenerationAgent()
            ctx = {"plan_item_id": state.plan_item_id}
            response = agent.run(db=db, author_id=user_id, trigger_message=text, context=ctx, previous_messages=state.messages)
            db.delete(state)
            db.commit()
        else:
            # Default to ChatAgent for standard messages
            agent = ChatAgent()
            response = agent.run(db=db, author_id=user_id, trigger_message=text)

        # 3. Handle paused state
        if isinstance(response, dict) and response.get("status") == "paused":
            new_state = AgentState(
                author_id=user_id,
                plan_item_id=response.get("plan_item_id"),
                messages=response.get("messages")
            )
            db.add(new_state)
            db.commit()
            # Do not reply text because we already sent the question via tools
        else:
            await update.message.reply_text(response)
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
                
        elif data.startswith("approve_post_"):
            plan_item_id = data.split("_", 2)[2]
            plan = db.query(ContentPlan).filter(ContentPlan.status == "active", ContentPlan.author_id == user_id).first()
            if plan:
                plan.items = [
                    {**item, "status": "approved"} if item.get("item_id") == plan_item_id else item
                    for item in plan.items
                ]
                db.commit()
                
                # Wake up generation agent to actually publish
                state = db.query(AgentState).filter(AgentState.plan_item_id == plan_item_id).first()
                if state:
                    agent = GenerationAgent()
                    ctx = {"plan_item_id": plan_item_id}
                    agent.run(db=db, author_id=user_id, trigger_message="Пост согласован. Вызывай publish_post.", context=ctx, previous_messages=state.messages)
                    db.delete(state)
                    db.commit()
                    
                await query.edit_message_text(text="Post approved and published!")
    finally:
        db.close()
