import datetime
import requests
import config
from database import SessionLocal
from models import ContentPlan, AuthorProfile
from agents.instances import GenerationAgent, PlanningAgent

def check_generation_queue():
    print("Scheduler: check_generation_queue running...")
    db = SessionLocal()
    try:
        plans = db.query(ContentPlan).filter(ContentPlan.status == "active").all()
        for plan in plans:
            frozen = False
            for item in plan.items:
                if item.get("status") in ["generating", "awaiting_approval"]:
                    frozen = True
                    break
            if frozen:
                continue

            profile = db.query(AuthorProfile).filter(AuthorProfile.author_id == plan.author_id).first()
            if not profile or not profile.openai_api_key:
                continue

            lead_hours = profile.schedule_settings.get("generation_lead_time_hours", 24) if profile.schedule_settings else 24
            
            for item in plan.items:
                if item.get("status") == "planned":
                    try:
                        planned_date_str = item.get("planned_date")
                        if planned_date_str:
                            try:
                                planned_date = datetime.datetime.fromisoformat(planned_date_str.replace('Z', '+00:00')).replace(tzinfo=None)
                            except ValueError:
                                planned_date = datetime.datetime.utcnow() # Fallback
                                
                            if datetime.datetime.utcnow() >= planned_date - datetime.timedelta(hours=lead_hours):
                                plan.items = [
                                    {**it, "status": "generating"} if it.get("item_id") == item.get("item_id") else it
                                    for it in plan.items
                                ]
                                db.commit()
                                
                                print(f"Triggering GenerationAgent for author {profile.author_id}")
                                agent = GenerationAgent()
                                context = {"plan_item_id": item["item_id"], "plan_item": item}
                                try:
                                    response = agent.run(db=db, author_id=profile.author_id, trigger_message="Generate post based on the current context.", context=context)
                                    print(f"GenerationAgent finished: {response}")
                                except Exception as e:
                                    print(f"GenerationAgent failed: {e}")
                                    plan_refresh = db.query(ContentPlan).filter(ContentPlan.plan_id == plan.plan_id).first()
                                    if plan_refresh:
                                        plan_refresh.items = [
                                            {**it, "status": "planned"} if it.get("item_id") == item.get("item_id") else it
                                            for it in plan_refresh.items
                                        ]
                                        db.commit()
                                break
                    except Exception as e:
                        print(f"Error parsing date {e}")
    finally:
        db.close()

def check_planning_queue():
    print("Scheduler: check_planning_queue running...")
    db = SessionLocal()
    try:
        profiles = db.query(AuthorProfile).filter(AuthorProfile.status == "active").all()
        for profile in profiles:
            if not profile.openai_api_key:
                continue
                
            active_plan = db.query(ContentPlan).filter(
                ContentPlan.author_id == profile.author_id,
                ContentPlan.status.in_(["active", "awaiting_approval"])
            ).first()
            
            needs_new_plan = False
            if not active_plan:
                needs_new_plan = True
            else:
                all_done = all(i.get("status") in ["published", "skipped"] for i in active_plan.items)
                if all_done:
                    active_plan.status = "completed"
                    db.commit()
                    needs_new_plan = True
                    
            if needs_new_plan:
                 print(f"Triggering PlanningAgent for {profile.author_id}...")
                 agent = PlanningAgent()
                 try:
                     response = agent.run(db=db, author_id=profile.author_id, trigger_message="Generate new content plan.")
                     print(f"PlanningAgent finished for {profile.author_id}: {response}")
                 except Exception as e:
                     print(f"PlanningAgent failed for {profile.author_id}: {e}")
    finally:
        db.close()

def check_reminders():
    print("Scheduler: check_reminders running...")
    db = SessionLocal()
    try:
        plans = db.query(ContentPlan).filter(ContentPlan.status == "active").all()
        for plan in plans:
            pending_item = next((item for item in plan.items if item.get("status") == "awaiting_approval"), None)
            if pending_item:
                profile = db.query(AuthorProfile).filter(AuthorProfile.author_id == plan.author_id).first()
                if not profile: continue
                
                settings = profile.schedule_settings or {}
                p1_int = settings.get("reminder_interval_minutes_phase1", 30)
                p2_int = settings.get("reminder_interval_minutes_phase2", 180)
                p1_dur = settings.get("reminder_phase1_duration_hours", 8)
                
                now = datetime.datetime.utcnow()
                last_contact = plan.last_author_contact_at or plan.created_at or now
                time_since_contact = now - last_contact
                
                if time_since_contact > datetime.timedelta(hours=p1_dur):
                    interval = p2_int
                else:
                    interval = p1_int
                    
                last_rem = plan.last_reminder_at or last_contact
                if now - last_rem > datetime.timedelta(minutes=interval):
                    if config.TELEGRAM_BOT_TOKEN:
                        try:
                            res = requests.post(
                                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                                json={"chat_id": profile.author_id, "text": "Напоминаю: пост ждет вашего решения! Нажмите кнопку на предложенном посте."}
                            )
                            res.raise_for_status()
                            plan.last_reminder_at = now
                            db.commit()
                        except Exception as e:
                            print(f"Failed to send reminder to Telegram for {profile.author_id}: {e}")
    finally:
        db.close()
