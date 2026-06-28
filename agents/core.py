import json
from openai import OpenAI
import config
from tools.executors import ToolExecutors

class AgentCore:
    def __init__(self, system_prompt: str, tools_schema: list, max_tool_calls: int = 15, reasoning_effort: str = "medium"):
        self.system_prompt = system_prompt
        self.tools_schema = tools_schema
        self.max_tool_calls = max_tool_calls
        self.reasoning_effort = reasoning_effort
        # Model to use: gpt-4o as it supports tool calling natively
        # If testing with OpenAI's newer reasoning models that support tools, use o-series
        self.model = "gpt-5.5"

    def run(self, db, author_id: str, trigger_message: str, context: dict = None, previous_messages: list = None):
        from models import AuthorProfile
        profile = db.query(AuthorProfile).filter(AuthorProfile.author_id == author_id).first()
        if not profile or not profile.openai_api_key:
            return "Ошибка: Не найден OpenAI API Key для этого профиля."
            
        client = OpenAI(api_key=profile.openai_api_key)
        
        if previous_messages:
            messages = previous_messages + [{"role": "user", "content": trigger_message}]
        else:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": trigger_message}
            ]
        
        executor = ToolExecutors(db, author_id, context)
        tool_calls_count = 0
        
        TERMINAL_TOOLS = {"submit_plan", "publish_post", "propose_patch", "propose_post", "ask_author"}
        
        while tool_calls_count < self.max_tool_calls:
            try:
                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "tools": self.tools_schema,
                    "tool_choice": "auto"
                }
                
                # Only pass reasoning_effort if using a newer model/SDK that supports it
                # For standard GPT models or older SDKs, it will raise an error.
                if hasattr(client.chat.completions, "create") and self.model.startswith("o"):
                    kwargs["reasoning_effort"] = self.reasoning_effort

                response = client.chat.completions.create(**kwargs)
            except Exception as e:
                return f"Error communicating with OpenAI API: {str(e)}"
            
            message = response.choices[0].message
            messages.append(message)
            
            if not message.tool_calls:
                serializable_messages = []
                for m in messages:
                    if isinstance(m, dict):
                        serializable_messages.append(m)
                    else:
                        serializable_messages.append(m.model_dump(exclude_unset=True))
                
                # Keep system prompt + last 10 messages to avoid overflow
                if len(serializable_messages) > 11:
                    sys_prompt = [m for m in serializable_messages if m.get("role") == "system"]
                    serializable_messages = sys_prompt + serializable_messages[-10:]

                return {
                    "status": "completed",
                    "content": message.content,
                    "messages": serializable_messages
                }
            
            tool_calls_count += 1
            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                
                # Execute tool
                result = executor.execute(func_name, args)
                
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": func_name,
                    "content": str(result),
                })
                
                # Terminal tools check
                if func_name in TERMINAL_TOOLS:
                    # For ask_author and propose_post, return a special payload so caller knows to save state
                    if func_name in ["ask_author", "propose_post"]:
                        try:
                            res_json = json.loads(result)
                            if res_json.get("status") == "paused":
                                serializable_messages = []
                                for m in messages:
                                    if isinstance(m, dict):
                                        serializable_messages.append(m)
                                    else:
                                        serializable_messages.append(m.model_dump(exclude_unset=True))
                                
                                return {
                                    "status": "paused",
                                    "messages": serializable_messages,
                                    "plan_item_id": executor.context.get("plan_item_id")
                                }
                        except:
                            pass
                    return result

        return "Error: Maximum tool call limit reached."
