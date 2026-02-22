import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..utils.jwt import get_current_user_id
from ..services.embedding_service import EmbeddingService
from ..models.role import Role, UserRole
from ..models.chat import ChatLog, ChatLogStatus
from ..models.code_example import CodeExample
from ..schemas.chat import (
    CodeExampleCreate,
    CodeExampleUpdate,
    ReviewRequest,
    EmbedRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Admin dependency ---

def get_admin_user_id(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> int:
    """Verify the user has admin role."""
    is_admin = db.query(UserRole).join(Role).filter(
        UserRole.user_id == user_id, Role.name == "admin"
    ).first()
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


# === Code Example CRUD ===

@router.get("/code-examples")
async def list_code_examples(
    status: str = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """List code examples with optional status filter."""
    query = db.query(CodeExample)
    if status:
        query = query.filter(CodeExample.status == status)
    total = query.count()
    items = query.order_by(CodeExample.id.desc()).offset(skip).limit(limit).all()
    return {
        "items": [
            {
                "id": item.id,
                "question": item.question,
                "code": item.code,
                "description": item.description,
                "status": item.status,
                "has_embedding": item.embedding is not None,
                "source_chat_log_id": item.source_chat_log_id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in items
        ],
        "total": total,
    }


@router.post("/code-examples")
async def create_code_example(
    body: CodeExampleCreate,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """Create a new code example with synchronous embedding."""
    embedding_service = EmbeddingService(db)
    try:
        emb = embedding_service.get_embedding(body.question)
        emb_str = "[" + ",".join(str(v) for v in emb) + "]"
    except Exception as e:
        logger.warning(f"Embedding generation failed: {e}")
        emb_str = None

    example = CodeExample(
        question=body.question,
        code=body.code,
        description=body.description,
        created_by=admin_id,
        status="embedded" if emb_str else "active",
    )
    db.add(example)
    db.flush()

    # Set embedding via raw SQL (pgvector type)
    if emb_str:
        db.execute(
            text("UPDATE code_examples SET embedding = :emb\\:\\:vector WHERE id = :id"),
            {"emb": emb_str, "id": example.id},
        )

    db.commit()
    db.refresh(example)
    return {
        "id": example.id,
        "question": example.question,
        "status": example.status,
        "has_embedding": emb_str is not None,
    }


@router.put("/code-examples/{example_id}")
async def update_code_example(
    example_id: int,
    body: CodeExampleUpdate,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """Update a code example. Re-embeds if question changes."""
    example = db.query(CodeExample).filter(CodeExample.id == example_id).first()
    if not example:
        raise HTTPException(status_code=404, detail="Code example not found")

    question_changed = False
    if body.question is not None and body.question != example.question:
        example.question = body.question
        question_changed = True
    if body.code is not None:
        example.code = body.code
    if body.description is not None:
        example.description = body.description

    example.updated_at = datetime.utcnow()

    # Re-embed if question changed
    if question_changed:
        try:
            embedding_service = EmbeddingService(db)
            emb = embedding_service.get_embedding(example.question)
            emb_str = "[" + ",".join(str(v) for v in emb) + "]"
            db.execute(
                text("UPDATE code_examples SET embedding = :emb\\:\\:vector, status = 'embedded' WHERE id = :id"),
                {"emb": emb_str, "id": example.id},
            )
        except Exception as e:
            logger.warning(f"Re-embedding failed: {e}")
            # 임베딩 실패 시 active로 되돌려 DAG이 재처리하도록
            db.execute(
                text("UPDATE code_examples SET embedding = NULL, status = 'active' WHERE id = :id"),
                {"id": example.id},
            )

    db.commit()
    db.refresh(example)
    return {
        "id": example.id,
        "question": example.question,
        "status": example.status,
        "has_embedding": example.embedding is not None,
    }


@router.delete("/code-examples/{example_id}")
async def archive_code_example(
    example_id: int,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """임베딩 제거 + active로 되돌림 — 검색 대상에서 제외, DAG 재실행 시 재임베딩."""
    example = db.query(CodeExample).filter(CodeExample.id == example_id).first()
    if not example:
        raise HTTPException(status_code=404, detail="Code example not found")
    db.execute(
        text("UPDATE code_examples SET embedding = NULL, status = 'active', updated_at = :now WHERE id = :id"),
        {"now": datetime.utcnow(), "id": example.id},
    )
    db.commit()
    return {"id": example.id, "status": "active", "has_embedding": False}


# === Chat Log Review ===

@router.get("/chat-logs")
async def list_chat_logs(
    status: str = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """List chat logs with optional status filter."""
    query = db.query(ChatLog)
    if status:
        query = query.filter(ChatLog.status == status)
    total = query.count()
    items = query.order_by(ChatLog.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "items": [
            {
                "id": item.id,
                "user_id": item.user_id,
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


@router.post("/chat-logs/{log_id}/review")
async def review_chat_log(
    log_id: int,
    body: ReviewRequest,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """Approve or reject a liked chat log."""
    chat_log = db.query(ChatLog).filter(ChatLog.id == log_id).first()
    if not chat_log:
        raise HTTPException(status_code=404, detail="Chat log not found")

    if body.action == "approve":
        if chat_log.status not in (ChatLogStatus.LIKED.value, ChatLogStatus.REJECTED.value):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve from status '{chat_log.status}'"
            )
        chat_log.status = ChatLogStatus.APPROVED.value
    elif body.action == "reject":
        if chat_log.status not in (ChatLogStatus.LIKED.value, ChatLogStatus.APPROVED.value):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot reject from status '{chat_log.status}'"
            )
        chat_log.status = ChatLogStatus.REJECTED.value
    else:
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")

    db.commit()
    return {"id": chat_log.id, "status": chat_log.status}


@router.post("/chat-logs/{log_id}/embed")
async def embed_chat_log(
    log_id: int,
    body: EmbedRequest,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """Embed an approved chat log into code_examples."""
    chat_log = db.query(ChatLog).filter(ChatLog.id == log_id).first()
    if not chat_log:
        raise HTTPException(status_code=404, detail="Chat log not found")
    if chat_log.status != ChatLogStatus.APPROVED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Can only embed from APPROVED status, current: '{chat_log.status}'"
        )

    question = body.question or chat_log.question
    code = body.code or chat_log.generated_code
    if not code:
        raise HTTPException(status_code=400, detail="No code available to embed")
    description = body.description or ""

    # Generate embedding
    embedding_service = EmbeddingService(db)
    try:
        emb = embedding_service.get_embedding(question)
        emb_str = "[" + ",".join(str(v) for v in emb) + "]"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding generation failed: {e}")

    # Insert into code_examples
    example = CodeExample(
        question=question,
        code=code,
        description=description,
        created_by=admin_id,
        source_chat_log_id=chat_log.id,
        status="embedded",
    )
    db.add(example)
    db.flush()

    # Set embedding via raw SQL
    db.execute(
        text("UPDATE code_examples SET embedding = :emb\\:\\:vector WHERE id = :id"),
        {"emb": emb_str, "id": example.id},
    )

    # Update chat log status
    chat_log.status = ChatLogStatus.EMBEDDED.value
    db.commit()

    return {
        "chat_log_id": chat_log.id,
        "code_example_id": example.id,
        "status": chat_log.status,
    }


@router.post("/chat-logs/{log_id}/withdraw")
async def withdraw_embedding(
    log_id: int,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """Withdraw embedding: archive code_example, revert chat_log to APPROVED."""
    chat_log = db.query(ChatLog).filter(ChatLog.id == log_id).first()
    if not chat_log:
        raise HTTPException(status_code=404, detail="Chat log not found")
    if chat_log.status != ChatLogStatus.EMBEDDED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Can only withdraw from EMBEDDED status, current: '{chat_log.status}'"
        )

    # 임베딩 제거 + active로 되돌림
    example = (
        db.query(CodeExample)
        .filter(
            CodeExample.source_chat_log_id == chat_log.id,
            CodeExample.status == "embedded",
        )
        .first()
    )
    if example:
        db.execute(
            text("UPDATE code_examples SET embedding = NULL, status = 'active', updated_at = :now WHERE id = :id"),
            {"now": datetime.utcnow(), "id": example.id},
        )

    chat_log.status = ChatLogStatus.APPROVED.value
    db.commit()

    return {"chat_log_id": chat_log.id, "status": chat_log.status}
