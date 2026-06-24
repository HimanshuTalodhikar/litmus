"""
Product Copilot Root Agent.
Phase 1B: Minimal version with an echo tool for testing.
"""

from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from app.adk.vertex_gemini import VertexGemini
from app.config import get_settings

settings = get_settings()


def echo(text: str) -> str:
    """Echo the input text back. Use for testing the ADK setup."""
    return f"Echoed: {text}"


echo_tool = FunctionTool(func=echo)


root_agent = Agent(
    name="product_copilot_root",
    model=VertexGemini(model="gemini-2.0-flash"),
    description="Product Copilot — answers product questions and captures feature requests",
    instruction="""You are the Product Copilot assistant.

Your current capabilities (Phase 1B):
- Echo test messages
- Answer general questions conversationally

Always be helpful, concise, and accurate. If asked about product features, answer based on your training knowledge or say you don't have that information yet.
""",
    tools=[echo_tool],
)
