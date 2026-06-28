import logging
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters
from apscheduler.schedulers.background import BackgroundScheduler

import config
from database import engine, Base
from bot.handlers import handle_message, handle_callback_query, handle_start
from scheduler.tasks import check_generation_queue, check_planning_queue, check_reminders

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def init_db():
    Base.metadata.create_all(bind=engine)

def main():
    # 1. Init Database
    init_db()
    logging.info("Database initialized.")

    # 2. Setup Scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_generation_queue, 'interval', minutes=10)
    scheduler.add_job(check_planning_queue, 'interval', minutes=15)
    scheduler.add_job(check_reminders, 'interval', minutes=5)
    scheduler.start()
    logging.info("Scheduler started.")

    # 3. Setup Bot
    application = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    logging.info("Bot is starting polling...")
    try:
        application.run_polling()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.shutdown()

if __name__ == '__main__':
    main()
