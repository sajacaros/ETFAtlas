import asyncio
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.chat_service import ChatService
from ..utils.session import get_current_user_id
from ..utils.time import utcnow
from ..models.chat import ChatLog, ChatLogStatus, ChatSession
from ..schemas.chat import FeedbackRequest, ChatSessionUpdate

logger = logging.getLogger(__name__)

router = APIRouter()


SESSION_TITLE_LENGTH = 50


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[int] = None  # 없으면 새 세션을 만든다


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
    refined_question: Optional[str] = None
    steps: List[StepItem] = []
    chat_log_id: Optional[int] = None
    session_id: Optional[int] = None


def _extract_generated_code(steps: List[dict]) -> Optional[str]:
    """성공한 도구 호출 순서를 한 줄씩 이어 붙인다 (승인 시 few-shot 예시로 사용)."""
    calls = [step["code"] for step in steps if step.get("code") and not step.get("error")]
    return "\n".join(calls) or None


def _get_own_session(db: Session, user_id: int, session_id: int) -> ChatSession:
    session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == user_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


def _resolve_session(db: Session, user_id: int, session_id: Optional[int], message: str) -> ChatSession:
    """요청한 세션을 찾거나, 없으면 첫 질문을 제목으로 새 세션을 만든다."""
    if session_id is not None:
        return _get_own_session(db, user_id, session_id)
    title = message.strip().replace("\n", " ")[:SESSION_TITLE_LENGTH] or "새 대화"
    session = ChatSession(user_id=user_id, title=title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _save_chat_log(
    db: Session,
    user_id: int,
    session: ChatSession,
    question: str,
    refined_question: Optional[str],
    answer: str,
    steps: List[dict],
) -> int:
    """Save chat log into the session and return its id."""
    chat_log = ChatLog(
        user_id=user_id,
        session_id=session.id,
        question=question,
        refined_question=refined_question if refined_question != question else None,
        answer=answer,
        generated_code=_extract_generated_code(steps),
        steps=steps or None,
        status=ChatLogStatus.PENDING.value,
    )
    db.add(chat_log)
    session.updated_at = utcnow()
    db.commit()
    db.refresh(chat_log)
    return chat_log.id


@router.post("/message", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    session = _resolve_session(db, user_id, request.session_id, request.message)
    try:
        chat_service = ChatService(db)
        memory = chat_service.memory
        await asyncio.to_thread(memory.update_summary, session)  # 지난 요약이 실패했으면 여기서 따라잡는다
        context = memory.load_context(session)
        result = await chat_service.chat(request.message, context)
        chat_log_id = _save_chat_log(
            db, user_id, session, request.message, result["refined_question"],
            result["answer"], result.get("steps", []),
        )
        await asyncio.to_thread(memory.update_summary, session)
        return ChatResponse(
            answer=result["answer"],
            refined_question=result["refined_question"],
            steps=result["steps"],
            chat_log_id=chat_log_id,
            session_id=session.id,
        )
    except Exception as e:
        logger.exception("Chat message error")
        return ChatResponse(
            answer=f"죄송합니다. 요청을 처리하는 중 오류가 발생했습니다: {str(e)}",
            session_id=session.id,
        )


@router.post("/message/stream")
async def stream_message(
    request: ChatRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    # 세션 확인(404)은 스트림을 열기 전에 한다
    session = _resolve_session(db, user_id, request.session_id, request.message)

    def sse(event: dict) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def event_generator():
        yield sse({"type": "session", "data": {"session_id": session.id, "title": session.title}})
        answer = ""
        refined_question = None
        steps = []
        memory = None
        try:
            chat_service = ChatService(db)
            memory = chat_service.memory
            await asyncio.to_thread(memory.update_summary, session)  # 지난 요약이 실패했으면 여기서 따라잡는다
            context = memory.load_context(session)
            async for event in chat_service.chat_stream(request.message, context):
                if event.get("type") == "refined_question":
                    refined_question = event["data"]["question"]
                elif event.get("type") == "step":
                    steps.append(event["data"])
                elif event.get("type") == "answer":
                    answer = event["data"]["answer"]
                yield sse(event)
        except Exception as e:
            yield sse({"type": "error", "data": {"message": str(e)}})

        # Save chat log after stream completes
        try:
            chat_log_id = _save_chat_log(
                db, user_id, session, request.message, refined_question, answer or "", steps
            )
            yield sse({"type": "chat_log_id", "data": {"chat_log_id": chat_log_id}})
        except Exception as e:
            logger.warning(f"Failed to save chat log: {e}")

        # 답변을 보낸 뒤에 요약하므로 사용자는 기다리지 않는다
        if memory is not None:
            try:
                await asyncio.to_thread(memory.update_summary, session)
            except Exception as e:
                logger.warning(f"Failed to update chat summary: {e}")

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# --- Sessions ---

@router.get("/sessions")
async def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """내 대화 세션 목록 (최근 활동 순)."""
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {"id": s.id, "title": s.title, "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat()}
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """세션의 전체 대화 (요약된 오래된 턴도 화면 표시용으로 모두 돌려준다)."""
    session = _get_own_session(db, user_id, session_id)
    logs = db.query(ChatLog).filter(ChatLog.session_id == session.id).order_by(ChatLog.id).all()
    return {
        "id": session.id,
        "title": session.title,
        "summary": session.summary,
        "messages": [
            {
                "id": log.id,
                "question": log.question,
                "refined_question": log.refined_question,
                "answer": log.answer,
                "steps": log.steps or [],
                "status": log.status,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
    }


@router.patch("/sessions/{session_id}")
async def rename_session(
    session_id: int,
    body: ChatSessionUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    session = _get_own_session(db, user_id, session_id)
    session.title = body.title
    db.commit()
    return {"id": session.id, "title": session.title}


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """세션을 지운다. 로그는 관리자 검수용으로 남고 session_id만 비워진다."""
    session = _get_own_session(db, user_id, session_id)
    db.delete(session)
    db.commit()


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
                "refined_question": item.refined_question,
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
        "refined_question": chat_log.refined_question,
        "answer": chat_log.answer,
        "generated_code": chat_log.generated_code,
        "status": chat_log.status,
        "created_at": chat_log.created_at.isoformat(),
    }

