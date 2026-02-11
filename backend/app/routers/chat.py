import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.chat_service import ChatService

router = APIRouter()


class ChatMessageItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessageItem] = []


class ToolCallItem(BaseModel):
    name: str
    arguments: str


class StepItem(BaseModel):
    step_number: int
    code: str
    observations: str
    tool_calls: List[ToolCallItem]
    error: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    steps: List[StepItem] = []


@router.post("/message", response_model=ChatResponse)
async def send_message(request: ChatRequest, db: Session = Depends(get_db)):
    try:
        chat_service = ChatService(db)
        history = [{"role": m.role, "content": m.content} for m in request.history]
        result = chat_service.chat(request.message, history)
        return ChatResponse(answer=result["answer"], steps=result["steps"])
    except Exception as e:
        return ChatResponse(answer=f"죄송합니다. 요청을 처리하는 중 오류가 발생했습니다: {str(e)}")


@router.post("/message/stream")
async def stream_message(request: ChatRequest, db: Session = Depends(get_db)):
    def event_generator():
        try:
            chat_service = ChatService(db)
            history = [{"role": m.role, "content": m.content} for m in request.history]
            for event in chat_service.chat_stream(request.message, history):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            error_event = {"type": "error", "data": {"message": str(e)}}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
