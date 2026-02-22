import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.chat_service import ChatService
from ..utils.jwt import get_current_user_id
from ..models.chat import ChatLog, ChatLogStatus
from ..schemas.chat import FeedbackRequest

logger = logging.getLogger(__name__)

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
    chat_log_id: Optional[int] = None


def _extract_generated_code(steps: List[dict]) -> Optional[str]:
    """Extract the last successful code block from steps."""
    last_code = None
    for step in steps:
        if step.get("code") and not step.get("error"):
            last_code = step["code"]
    return last_code


def _save_chat_log(
    db: Session,
    user_id: int,
    question: str,
    answer: str,
    generated_code: Optional[str],
) -> int:
    """Save chat log and return its id."""
    chat_log = ChatLog(
        user_id=user_id,
        question=question,
        answer=answer,
        generated_code=generated_code,
        status=ChatLogStatus.PENDING.value,
    )
    db.add(chat_log)
    db.commit()
    db.refresh(chat_log)
    return chat_log.id


@router.post("/message", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    try:
        chat_service = ChatService(db)
        history = [{"role": m.role, "content": m.content} for m in request.history]
        result = chat_service.chat(request.message, history)
        generated_code = _extract_generated_code(result.get("steps", []))
        chat_log_id = _save_chat_log(
            db, user_id, request.message, result["answer"], generated_code
        )
        return ChatResponse(
            answer=result["answer"],
            steps=result["steps"],
            chat_log_id=chat_log_id,
        )
    except Exception as e:
        logger.exception("Chat message error")
        return ChatResponse(
            answer=f"죄송합니다. 요청을 처리하는 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/message/stream")
async def stream_message(
    request: ChatRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    def event_generator():
        answer = ""
        steps = []
        try:
            chat_service = ChatService(db)
            history = [{"role": m.role, "content": m.content} for m in request.history]
            for event in chat_service.chat_stream(request.message, history):
                if event.get("type") == "step":
                    steps.append(event["data"])
                elif event.get("type") == "answer":
                    answer = event["data"]["answer"]
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            error_event = {"type": "error", "data": {"message": str(e)}}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

        # Save chat log after stream completes
        try:
            generated_code = _extract_generated_code(steps)
            chat_log_id = _save_chat_log(
                db, user_id, request.message, answer or "", generated_code
            )
            chat_log_event = {"type": "chat_log_id", "data": {"chat_log_id": chat_log_id}}
            yield f"data: {json.dumps(chat_log_event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.warning(f"Failed to save chat log: {e}")

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# --- User Feedback & History (Phase 4) ---

@router.post("/logs/{log_id}/feedback")
async def toggle_feedback(
    log_id: int,
    request: FeedbackRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Toggle like/dislike on a chat log. Only allowed before admin action."""
    chat_log = db.query(ChatLog).filter(ChatLog.id == log_id).first()
    if not chat_log:
        raise HTTPException(status_code=404, detail="Chat log not found")
    if chat_log.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your chat log")

    # Only allow feedback change when status is PENDING/LIKED/DISLIKED
    allowed = {ChatLogStatus.PENDING.value, ChatLogStatus.LIKED.value, ChatLogStatus.DISLIKED.value}
    if chat_log.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Cannot change feedback after admin review"
        )

    if request.status not in (ChatLogStatus.LIKED.value, ChatLogStatus.DISLIKED.value):
        raise HTTPException(status_code=400, detail="Status must be 'liked' or 'disliked'")

    chat_log.status = request.status
    db.commit()
    db.refresh(chat_log)
    return {"id": chat_log.id, "status": chat_log.status}


@router.get("/logs/mine")
async def get_my_chat_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Get my chat log history with pagination."""
    query = db.query(ChatLog).filter(ChatLog.user_id == user_id)
    total = query.count()
    items = query.order_by(ChatLog.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "items": [
            {
                "id": item.id,
                "question": item.question,
                "answer": item.answer,
                "generated_code": item.generated_code,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
        "total": total,
    }


@router.get("/logs/{log_id}")
async def get_chat_log(
    log_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Get a specific chat log detail."""
    chat_log = db.query(ChatLog).filter(ChatLog.id == log_id).first()
    if not chat_log:
        raise HTTPException(status_code=404, detail="Chat log not found")
    if chat_log.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your chat log")
    return {
        "id": chat_log.id,
        "question": chat_log.question,
        "answer": chat_log.answer,
        "generated_code": chat_log.generated_code,
        "status": chat_log.status,
        "created_at": chat_log.created_at.isoformat(),
    }

