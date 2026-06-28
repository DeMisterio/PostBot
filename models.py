import datetime
import uuid
from sqlalchemy import Column, String, Integer, DateTime, JSON, Boolean, ForeignKey
from database import Base

def generate_uuid():
    return str(uuid.uuid4())

class AuthorProfile(Base):
    __tablename__ = "author_profile"
    
    author_id = Column(String, primary_key=True, index=True) # telegram_user_id
    openai_api_key = Column(String, nullable=True)
    github_token = Column(String, nullable=True)
    status = Column(String, default="onboarding_api_key") # onboarding_api_key, onboarding_github, onboarding_channel, active
    channel_id = Column(String, nullable=True)
    voice_and_rules = Column(JSON, default=dict)
    background = Column(JSON, default=dict)
    extensions = Column(JSON, default=dict)
    schedule_settings = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class ContentPlan(Base):
    __tablename__ = "content_plan"
    
    plan_id = Column(String, primary_key=True, default=generate_uuid, index=True)
    author_id = Column(String, ForeignKey("author_profile.author_id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String, default="awaiting_approval") # awaiting_approval, active, completed
    approved_at = Column(DateTime, nullable=True)
    items = Column(JSON, default=list)
    
    # Reminder state for pending items
    last_reminder_at = Column(DateTime, nullable=True)
    last_author_contact_at = Column(DateTime, nullable=True)
    reminder_phase = Column(Integer, default=1)

class AgentState(Base):
    __tablename__ = "agent_state"
    
    author_id = Column(String, primary_key=True)
    plan_item_id = Column(String)
    messages = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class PostsHistory(Base):
    __tablename__ = "posts_history"
    
    post_id = Column(String, primary_key=True, default=generate_uuid, index=True)
    plan_item_id = Column(String, index=True)
    message_id = Column(Integer)
    published_at = Column(DateTime, default=datetime.datetime.utcnow)
    type = Column(String)
    topic = Column(String)
    source_repo = Column(String, nullable=True)
    summary = Column(String)
    post_text = Column(String, nullable=True)
    image_ref = Column(String, nullable=True)
    had_image = Column(Boolean, default=False)
    stats = Column(JSON, default={"views": 0, "reactions": {}})
