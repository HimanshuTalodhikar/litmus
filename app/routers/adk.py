"""
Chat endpoint — POST /adk/chat
Replaced Google ADK with direct OpenAI SDK calls to CodeMax.
"""
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.root_agent import chat

logger = structlog.get_logger()
router = APIRouter(prefix="/adk", tags=["adk"])


class ChatRequest(BaseModel):
    message: str
    user_id: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    session_id = req.session_id or str(uuid.uuid4())

    try:
        response_text = await chat(message=req.message, history=[])
        return ChatResponse(response=response_text, session_id=session_id)
    except Exception as e:
        logger.error("chat_error", error=str(e), user_id=req.user_id, session_id=session_id)
        raise HTTPException(status_code=500, detail=f"LLM error: {e}")
