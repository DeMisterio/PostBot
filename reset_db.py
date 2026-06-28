from database import engine, Base
# Импортируем все модели, чтобы SQLAlchemy знала, какие таблицы удалять и создавать
from models import AuthorProfile, ContentPlan, PostsHistory, AgentState

def reset_database():
    print("⚠️  Внимание: Удаление всех данных...")
    Base.metadata.drop_all(bind=engine)
    
    print("✅ Создание чистых таблиц...")
    Base.metadata.create_all(bind=engine)
    
    print("🎉 База данных полностью обнулена!")

if __name__ == "__main__":
    confirm = input("Вы уверены, что хотите удалить ВСЕ данные всех пользователей? (y/n): ")
    if confirm.lower() == 'y':
        reset_database()
    else:
        print("Отмена.")
