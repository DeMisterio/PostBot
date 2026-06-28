from agents.core import AgentCore
from agents.prompts import PLANNING_PROMPT, GENERATION_PROMPT, CHAT_PROMPT
from tools.schemas import PLANNING_TOOLS, GENERATION_TOOLS, CHAT_TOOLS

class PlanningAgent(AgentCore):
    def __init__(self):
        super().__init__(
            system_prompt=PLANNING_PROMPT,
            tools_schema=PLANNING_TOOLS,
            max_tool_calls=15,
            reasoning_effort="high"
        )

class GenerationAgent(AgentCore):
    def __init__(self):
        super().__init__(
            system_prompt=GENERATION_PROMPT,
            tools_schema=GENERATION_TOOLS,
            max_tool_calls=8,
            reasoning_effort="medium"
        )

class ChatAgent(AgentCore):
    def __init__(self):
        super().__init__(
            system_prompt=CHAT_PROMPT,
            tools_schema=CHAT_TOOLS,
            max_tool_calls=5,
            reasoning_effort="low"
        )
