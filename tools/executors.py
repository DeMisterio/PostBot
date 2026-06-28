import json
import requests
import datetime
from sqlalchemy.orm import Session
from models import AuthorProfile, ContentPlan, PostsHistory, AgentState
import config

class ToolExecutors:
    def __init__(self, db: Session, author_id: str, context: dict = None):
        self.db = db
        self.author_id = author_id
        self.context = context or {}

    def get_author_profile(self):
        profile = self.db.query(AuthorProfile).filter(AuthorProfile.author_id == self.author_id).first()
        if not profile:
            return json.dumps({"error": "Profile not found"})
        return json.dumps({
            "voice_and_rules": profile.voice_and_rules,
            "background": profile.background,
            "schedule_settings": profile.schedule_settings
        }, ensure_ascii=False)

    def get_posts_history(self, limit: int = 30):
        posts = self.db.query(PostsHistory).filter(PostsHistory.author_id == self.author_id).order_by(PostsHistory.published_at.desc()).limit(limit).all()
        history = []
        for p in posts:
            history.append({
                "post_id": p.post_id,
                "plan_item_id": p.plan_item_id,
                "text_summary": p.text_summary[:100] + "...",
                "published_at": p.published_at.isoformat() if p.published_at else None
            })
        return json.dumps(history, ensure_ascii=False)

    def list_github_repos(self):
        profile = self.db.query(AuthorProfile).filter(AuthorProfile.author_id == self.author_id).first()
        if not profile or not profile.github_token:
            return json.dumps({"error": "github_token_missing", "message": "GitHub PAT is not set for this author."})
            
        try:
            headers = {"Authorization": f"token {profile.github_token}", "Accept": "application/vnd.github.v3+json"}
            response = requests.get("https://api.github.com/user/repos", headers=headers, params={"sort": "updated", "per_page": 20})
            response.raise_for_status()
            repos = response.json()
            return json.dumps([
                {
                    "name": r["name"],
                    "full_name": r["full_name"],
                    "description": r["description"],
                    "language": r["language"],
                    "updated_at": r["updated_at"]
                } for r in repos
            ], ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def get_github_readme(self, repo_full_name: str):
        profile = self.db.query(AuthorProfile).filter(AuthorProfile.author_id == self.author_id).first()
        if not profile or not profile.github_token:
            return json.dumps({"error": "github_token_missing", "message": "GitHub PAT is not set for this author."})
            
        headers = {
            "Authorization": f"token {profile.github_token}",
            "Accept": "application/vnd.github.v3.raw"
        }
        try:
            response = requests.get(f"https://api.github.com/repos/{repo_full_name}/readme", headers=headers)
            response.raise_for_status()
            content = response.text
            return json.dumps({"readme": content[:4000]}, ensure_ascii=False) # Limit size for context window
        except Exception as e:
            return json.dumps({"error": str(e)})

    def get_github_repo_metadata(self, repo_full_name: str):
        profile = self.db.query(AuthorProfile).filter(AuthorProfile.author_id == self.author_id).first()
        if not profile or not profile.github_token:
            return json.dumps({"error": "github_token_missing", "message": "GitHub PAT is not set for this author."})
            
        headers = {"Authorization": f"token {profile.github_token}"}
        try:
            response = requests.get(f"https://api.github.com/repos/{repo_full_name}", headers=headers)
            response.raise_for_status()
            return json.dumps(response.json(), ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def submit_plan(self, items: list):
        plan = ContentPlan(
            items=items,
            status="awaiting_approval",
            author_id=self.author_id
        )
        self.db.add(plan)
        self.db.commit()
        return json.dumps({"status": "success", "plan_id": plan.plan_id, "message": "Plan submitted for approval."})

    def get_plan_item(self):
        plan_item_id = self.context.get("plan_item_id")
        if not plan_item_id:
            return json.dumps({"error": "No plan item context provided"})
        
        # In a real scenario, we'd fetch the specific item from the ContentPlan items array
        # For MVP, assuming context passes the full item dict.
        return json.dumps(self.context.get("plan_item", {}), ensure_ascii=False)

    def get_recent_posts(self):
        return self.get_posts_history(limit=5)

    def ask_author(self, question: str):
        # Send question to Telegram
        if config.TELEGRAM_BOT_TOKEN:
            requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": self.author_id, "text": question}
            )
        # We don't save AgentState here; core.py handles returning the paused state back to handle_message
        return json.dumps({"status": "paused", "message": "Sent question to author. Waiting for reply."})

    def propose_post(self, post_text: str, need_image: bool, image_prompt_or_request: str = None):
        plan_item_id = self.context.get("plan_item_id")
        if plan_item_id:
            plan = self.db.query(ContentPlan).filter(ContentPlan.status == "active", ContentPlan.author_id == self.author_id).first()
            if plan:
                plan.items = [
                    {**item, "status": "awaiting_approval"} if item.get("item_id") == plan_item_id else item
                    for item in plan.items
                ]
                self.db.commit()

            # Send to author via Telegram
            if config.TELEGRAM_BOT_TOKEN:
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "✅ Опубликовать", "callback_data": f"approve_post_{plan_item_id}"}],
                        [{"text": "✏️ Редактировать", "callback_data": f"edit_post_{plan_item_id}"}],
                        [{"text": "⏭ Пропустить", "callback_data": f"skip_post_{plan_item_id}"}]
                    ]
                }
                text = f"Предлагаю пост:\n\n{post_text}"
                if need_image:
                    text += f"\n\n[Требуется изображение: {image_prompt_or_request}]"
                    
                requests.post(
                    f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": self.author_id, "text": text, "reply_markup": keyboard}
                )

        return json.dumps({"status": "paused", "message": "Post proposed to author. Waiting for approval."})

    def publish_post(self, plan_item_id: str, post_text: str, image_ref: str = None):
        # CRITICAL: Server-side guard
        plan = self.db.query(ContentPlan).filter(ContentPlan.status == "active", ContentPlan.author_id == self.author_id).first()
        if not plan:
            return json.dumps({"error": "permission_denied", "reason": "No active plan."})
        
        item_approved = False
        target_item = None
        for item in plan.items:
            if item.get("item_id") == plan_item_id and item.get("status") == "approved":
                item_approved = True
                target_item = item
                break
                
        if not item_approved:
             return json.dumps({"error": "permission_denied", "reason": f"Plan item {plan_item_id} is not approved."})
             
        # Fetch author profile for channel_id
        profile = self.db.query(AuthorProfile).filter(AuthorProfile.author_id == self.author_id).first()
        channel_id = profile.channel_id if profile else None
        
        if not channel_id:
            return json.dumps({"error": "Missing channel_id in AuthorProfile"})

        # Execute Telegram API call here
        message_id = None
        if config.TELEGRAM_BOT_TOKEN:
            try:
                if image_ref:
                    res = requests.post(
                        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto",
                        json={"chat_id": channel_id, "photo": image_ref, "caption": post_text}
                    )
                else:
                    res = requests.post(
                        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                        json={"chat_id": channel_id, "text": post_text}
                    )
                res.raise_for_status()
                message_id = res.json().get("result", {}).get("message_id")
            except Exception as e:
                return json.dumps({"error": "telegram_api_error", "reason": str(e)})
        else:
            return json.dumps({"error": "telegram_api_error", "reason": "No bot token configured."})
        
        # Create PostsHistory record
        history = PostsHistory(
            plan_item_id=plan_item_id,
            message_id=message_id,
            type=target_item.get("type"),
            topic=target_item.get("title"),
            source_repo=target_item.get("source", {}).get("repo_full_name"),
            summary="Published via agent",
            had_image=bool(image_ref)
        )
        self.db.add(history)

        # Update plan status to published
        plan.items = [
            {**item, "status": "published"} if item.get("item_id") == plan_item_id else item
            for item in plan.items
        ]
        self.db.commit()
        
        return json.dumps({"status": "success", "message": "Post published to channel."})

    def get_current_plan(self):
        plan = self.db.query(ContentPlan).filter(ContentPlan.status.in_(["active", "awaiting_approval"]), ContentPlan.author_id == self.author_id).first()
        if not plan:
            return json.dumps({"status": "no_active_plan"})
        return json.dumps({"plan_id": plan.plan_id, "items": plan.items}, ensure_ascii=False)

    def get_pending_post_state(self):
        # Check if any plan item is in awaiting_approval state
        plan = self.db.query(ContentPlan).filter(ContentPlan.status == "active", ContentPlan.author_id == self.author_id).first()
        if not plan:
            return json.dumps({"status": "no_pending_posts"})
        
        pending_items = [i for i in plan.items if i.get("status") == "awaiting_approval"]
        if pending_items:
            return json.dumps({"pending_items": pending_items}, ensure_ascii=False)
        return json.dumps({"status": "no_pending_posts"})

    def propose_patch(self, target: str, patch: dict, human_summary: str):
        # Save patch to DB and ask user for confirmation
        return json.dumps({"status": "success", "message": "Patch proposed to author."})

    def execute(self, tool_name: str, arguments: dict):
        method = getattr(self, tool_name, None)
        if method:
            try:
                return method(**arguments)
            except TypeError as e:
                return json.dumps({"error": f"Invalid arguments for {tool_name}: {str(e)}"})
            except Exception as e:
                return json.dumps({"error": f"Execution failed: {str(e)}"})
        return json.dumps({"error": f"Tool {tool_name} not found"})
