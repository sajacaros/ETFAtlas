import asyncio
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Callable, List, Optional, TypeVar
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from ..database import SessionLocal, get_db
from ..models.chat import ChatLog, ChatLogResult, ChatLogStatus, ChatSession, ChatSlot
from ..schemas.chat import FeedbackRequest, ChatSessionUpdate
from ..services.ai_config import load_ai_config
from ..services.answer import AnswerService
from ..services.chat_memory import ChatMemory
from ..utils.session import get_current_user_id
from ..utils.sse import DONE, sse_event, with_heartbeat
from ..utils.time import iso_utc, utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


SESSION_TITLE_LENGTH = 50
STREAM_ERROR = "답변 중 오류가 발생했습니다. 잠시 뒤 다시 질문해 주세요."  # 원인은 로그에만 남긴다

# 진행 중인 스트림의 중지 신호 ((user_id, session_id) → Event). uvicorn 단일 워커라 프로세스 메모리로 충분하다
_stop_events: dict[tuple[int, int], asyncio.Event] = {}

T = TypeVar("T")


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[int] = None  # 없으면 새 세션을 만든다
    refine: bool = True  # False면 맥락으로 질문을 재작성하지 않고 원문 그대로 답한다 ("원문으로 다시 묻기")


def _extract_generated_code(steps: List[dict]) -> Optional[str]:
    """성공한 도구 호출 순서를 한 줄씩 이어 붙인다 (승인 시 few-shot 예시로 사용)."""
    calls = [step["code"] for step in steps if step.get("code") and not step.get("error")]
    return "\n".join(calls) or None


def _in_session(work: Callable[[Session], T], session_factory: Callable[[], Session] = SessionLocal) -> T:
    """짧은 DB 작업 하나를 새 세션으로 (스트림 안에서 스레드로 부른다 — 답이 끝날 때까지 세션을 잡고 있지 않는다)."""
    db = session_factory()
    try:
        return work(db)
    finally:
        db.close()


def _own_log(db: Session, user_id: int, log_id: int) -> ChatLog:
    chat_log = db.query(ChatLog).filter(ChatLog.id == log_id).first()
    if not chat_log:
        raise HTTPException(status_code=404, detail="Chat log not found")
    if chat_log.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your chat log")
    return chat_log


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
    result: str,
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
        result=result,
    )
    db.add(chat_log)
    session.updated_at = utcnow()
    db.commit()
    db.refresh(chat_log)
    return chat_log.id


def _start_chat_log(db: Session, user_id: int, session: ChatSession, question: str) -> int:
    """답변을 만들기 전에 로그를 만든다 — 슬롯 내용이 이 로그 id에 붙어 저장되고, 프런트는 이 id로 가져간다."""
    chat_log = ChatLog(
        user_id=user_id, session_id=session.id, question=question, answer="",
        status=ChatLogStatus.PENDING.value, result=ChatLogResult.RUNNING.value,
    )
    db.add(chat_log)
    db.commit()
    db.refresh(chat_log)
    return chat_log.id


def _finish_chat_log(
    db: Session,
    chat_log_id: int,
    session: ChatSession,
    question: str,
    refined_question: Optional[str],
    answer: str,
    steps: List[dict],
    layout: Optional[dict],
    result: str,
) -> None:
    chat_log = db.get(ChatLog, chat_log_id)
    chat_log.refined_question = refined_question if refined_question != question else None
    chat_log.answer = answer
    chat_log.generated_code = _extract_generated_code(steps)
    chat_log.steps = steps or None
    chat_log.layout = layout
    chat_log.result = result
    session.updated_at = utcnow()
    db.commit()


@router.post("/message/stream")
def stream_message(
    request: ChatRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    # 세션 확인(404)과 새 세션은 스트림을 열기 전에 한다. 스트림 안에서는 이 요청 세션을 쓰지 않고
    # 필요할 때마다 짧게 연다 (LLM 답이 끝날 때까지 연결을 잡지 않고, 다른 스레드와 세션을 나누지 않게)
    session = _resolve_session(db, user_id, request.session_id, request.message)
    session_id, title = session.id, session.title

    stop_key = (user_id, session_id)
    stop = asyncio.Event()
    _stop_events[stop_key] = stop

    async def event_generator():
        try:
            async for chunk in with_heartbeat(_stream_events()):
                yield chunk
        finally:
            # 끝났거나 클라이언트가 끊었을 때 등록을 지운다 (같은 세션의 새 스트림이 덮어썼으면 그대로 둔다)
            if _stop_events.get(stop_key) is stop:
                del _stop_events[stop_key]

    async def _stream_events():
        yield sse_event({"type": "session", "data": {"session_id": session_id, "title": title}})
        answer = ""
        refined_question = None
        steps = []
        layout = None
        result = ChatLogResult.FAILED.value  # 답변 이벤트 없이 끝나면 실패
        chat_log_id = None
        config = None

        def prepare(db: Session):
            config = load_ai_config(db)
            memory = ChatMemory(db, config)
            chat_session = db.get(ChatSession, session_id)
            memory.update_summary(chat_session)  # 지난 요약이 실패했으면 여기서 따라잡는다
            context = memory.load_context(chat_session)
            # 맥락을 읽은 뒤에 만든다 — 먼저 만들면 답이 빈 이번 턴이 맥락에 끼어든다
            # memory는 질문 재작성(LLM)에만 다시 쓰이므로 이 세션이 닫혀도 된다
            return config, memory, context, _start_chat_log(db, user_id, chat_session, request.message)

        def finish(db: Session) -> int:
            chat_session = db.get(ChatSession, session_id)
            if chat_log_id is None:
                return _save_chat_log(
                    db, user_id, chat_session, request.message, refined_question, answer or "", steps, result
                )
            _finish_chat_log(
                db, chat_log_id, chat_session, request.message, refined_question, answer or "", steps, layout, result
            )
            return chat_log_id

        def summarize(db: Session) -> None:
            chat_session = db.get(ChatSession, session_id)
            if chat_session is not None:  # 그사이 세션을 지웠으면 요약할 것이 없다
                ChatMemory(db, config).update_summary(chat_session)

        # 동기 DB 작업은 스레드에서 돌려 이벤트 루프(다른 요청·스트림)를 막지 않는다
        try:
            config, memory, context, chat_log_id = await asyncio.to_thread(_in_session, prepare)
            service = AnswerService(config, memory=memory)
            async for event in service.stream(request.message, context, chat_log_id, stop, refine=request.refine):
                if event.get("type") == "refined_question":
                    refined_question = event["data"]["question"]
                elif event.get("type") == "step":
                    steps.append(event["data"])
                elif event.get("type") == "layout":
                    layout = event["data"]["layout"]
                elif event.get("type") == "answer":
                    answer = event["data"]["answer"]
                    result = event["data"]["result"]
                yield sse_event(event)
        except Exception:
            logger.exception("Chat stream error")
            result = ChatLogResult.FAILED.value
            yield sse_event({"type": "error", "data": {"message": STREAM_ERROR}})

        try:
            chat_log_id = await asyncio.to_thread(_in_session, finish)
            yield sse_event({"type": "chat_log_id", "data": {"chat_log_id": chat_log_id}})
        except Exception:
            logger.warning("Failed to save chat log", exc_info=True)

        # 답변을 보낸 뒤에 요약하므로 사용자는 기다리지 않는다
        if config is not None:
            try:
                await asyncio.to_thread(_in_session, summarize)
            except Exception:
                logger.warning("Failed to update chat summary", exc_info=True)

        yield DONE

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/sessions/{session_id}/stop", status_code=204)
async def stop_message(  # asyncio.Event는 스레드 안전하지 않으므로 루프에서 set한다
    session_id: int,
    user_id: int = Depends(get_current_user_id),
):
    """진행 중인 답변을 멈춘다. 실행 중인 도구는 결과까지 기다리고, 그다음 단계부터 실행하지 않는다."""
    stop = _stop_events.get((user_id, session_id))
    if stop is None:
        raise HTTPException(status_code=404, detail="No running chat in this session")
    stop.set()


# --- Sessions ---

def session_cursor(session: ChatSession) -> str:
    """세션 목록의 다음 페이지 위치: 마지막 항목의 (updated_at, id). 같은 시각에 바뀐 세션도 id로 순서가 정해진다."""
    return f"{session.updated_at.isoformat()}_{session.id}"


def parse_session_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        updated_at, session_id = cursor.rsplit("_", 1)
        return datetime.fromisoformat(updated_at), int(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cursor")


@router.get("/sessions")
def list_sessions(
    limit: int = Query(30, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="이전 응답의 next_cursor — 그 다음(더 오래된) 세션부터"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """내 대화 세션 목록 (최근 활동 순), 커서 페이징. next_cursor가 null이면 마지막 페이지."""
    query = db.query(ChatSession).filter(ChatSession.user_id == user_id)
    if cursor:
        updated_at, session_id = parse_session_cursor(cursor)
        query = query.filter(or_(
            ChatSession.updated_at < updated_at,
            and_(ChatSession.updated_at == updated_at, ChatSession.id < session_id),
        ))
    sessions = query.order_by(ChatSession.updated_at.desc(), ChatSession.id.desc()).limit(limit + 1).all()
    page = sessions[:limit]
    return {
        "items": [
            {"id": s.id, "title": s.title, "created_at": iso_utc(s.created_at), "updated_at": iso_utc(s.updated_at)}
            for s in page
        ],
        "next_cursor": session_cursor(page[-1]) if len(sessions) > limit else None,
    }


@router.get("/sessions/{session_id}")
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """세션의 전체 대화 (요약된 오래된 턴도 화면 표시용으로 모두 돌려준다)."""
    session = _get_own_session(db, user_id, session_id)
    logs = db.query(ChatLog).filter(ChatLog.session_id == session.id).order_by(ChatLog.id).all()
    slot_status: dict[int, dict[str, dict]] = {}
    log_ids = [log.id for log in logs if log.layout]
    if log_ids:
        for slot in db.query(ChatSlot).filter(ChatSlot.chat_log_id.in_(log_ids)).all():
            state = {"status": slot.status}
            if slot.message:
                state["message"] = slot.message
            slot_status.setdefault(slot.chat_log_id, {})[slot.slot_id] = state
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
                "layout": log.layout,
                "slots": slot_status.get(log.id, {}),
                "status": log.status,
                "result": log.result,
                "created_at": iso_utc(log.created_at),
            }
            for log in logs
        ],
    }


@router.patch("/sessions/{session_id}")
def rename_session(
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
def delete_session(
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
def toggle_feedback(
    log_id: int,
    request: FeedbackRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Toggle like/dislike on a chat log. Only allowed before admin action."""
    chat_log = _own_log(db, user_id, log_id)

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
def get_my_chat_logs(
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
                "created_at": iso_utc(item.created_at),
            }
            for item in items
        ],
        "total": total,
    }


@router.get("/logs/{log_id}/slots/{slot_id}")
def get_chat_slot(
    log_id: int,
    slot_id: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """답변 화면 한 영역의 내용. 스트림의 slot 완료 알림을 받거나 지난 대화를 열 때 가져간다."""
    _own_log(db, user_id, log_id)
    slot = db.get(ChatSlot, (log_id, slot_id))
    if not slot:
        raise HTTPException(status_code=404, detail="Slot not found")
    return {"id": slot.slot_id, "status": slot.status, "content": slot.content, "message": slot.message}


@router.get("/logs/{log_id}")
def get_chat_log(
    log_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Get a specific chat log detail."""
    chat_log = _own_log(db, user_id, log_id)
    return {
        "id": chat_log.id,
        "question": chat_log.question,
        "refined_question": chat_log.refined_question,
        "answer": chat_log.answer,
        "generated_code": chat_log.generated_code,
        "status": chat_log.status,
        "created_at": iso_utc(chat_log.created_at),
    }

