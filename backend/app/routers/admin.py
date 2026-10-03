import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..utils.session import get_current_user_id
from ..services.embedding_service import EmbeddingService
from ..services.auth_service import AuthService, is_admin
from ..services.graph_service import GraphService
from ..services.member_service import MemberNotFoundError, MemberService, SelfActionError
from ..models.chat import ChatLog, ChatLogStatus
from ..models.code_example import CodeExample
from ..models.discord_setting import DiscordSetting
from ..models.invitation import Invitation
from ..models.user import User
from ..utils.time import utcnow
from ..schemas.chat import (
    CodeExampleCreate,
    CodeExampleUpdate,
    ReviewRequest,
    EmbedRequest,
    ETFTagsUpdate,
    DiscordSettingsUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Admin dependency ---

def get_admin_user_id(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> int:
    """Verify the user has admin role."""
    if not is_admin(db, user_id):
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
                "question_generalized": item.question_generalized,
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


@router.get("/code-examples/search")
async def search_similar_code_examples(
    q: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
    generalize: bool = Query(False),
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """유사도 기반 코드 예제 검색 (임베딩 테스트용)."""
    embedding_service = EmbeddingService(db)
    search_query = q
    query_generalized = None
    if generalize:
        query_generalized = embedding_service.generalize_question(q)
        search_query = query_generalized
    results = embedding_service.find_similar_code_examples(search_query, top_k=top_k, max_distance=1.0)
    return {"query": q, "query_generalized": query_generalized, "results": results}


@router.post("/code-examples")
async def create_code_example(
    body: CodeExampleCreate,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """Create a new code example with synchronous embedding."""
    embedding_service = EmbeddingService(db)
    question_generalized = embedding_service.generalize_question(body.question)
    try:
        emb = embedding_service.get_embedding(question_generalized)
        emb_str = "[" + ",".join(str(v) for v in emb) + "]"
    except Exception as e:
        logger.warning(f"Embedding generation failed: {e}")
        emb_str = None

    example = CodeExample(
        question=body.question,
        question_generalized=question_generalized,
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

    example.updated_at = utcnow()

    # Re-embed if question changed
    if question_changed:
        embedding_service = EmbeddingService(db)
        question_generalized = embedding_service.generalize_question(example.question)
        example.question_generalized = question_generalized
        try:
            emb = embedding_service.get_embedding(question_generalized)
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
        {"now": utcnow(), "id": example.id},
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

    # 맥락에 기대는 원문("그거 보수율은?")보다 재작성된 독립 질문이 예시로 쓸모 있다
    question = body.question or chat_log.refined_question or chat_log.question
    code = body.code or chat_log.generated_code
    if not code:
        raise HTTPException(status_code=400, detail="No code available to embed")
    description = body.description or ""

    # Generate embedding (using generalized question)
    embedding_service = EmbeddingService(db)
    question_generalized = embedding_service.generalize_question(question)
    try:
        emb = embedding_service.get_embedding(question_generalized)
        emb_str = "[" + ",".join(str(v) for v in emb) + "]"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding generation failed: {e}")

    # Insert into code_examples
    example = CodeExample(
        question=question,
        question_generalized=question_generalized,
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
            {"now": utcnow(), "id": example.id},
        )

    chat_log.status = ChatLogStatus.APPROVED.value
    db.commit()

    return {"chat_log_id": chat_log.id, "status": chat_log.status}


# === ETF Tags ===

@router.get("/etf-tags")
async def list_etf_tags(
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """전체 ETF와 태그, 선택 가능한 태그 목록."""
    graph = GraphService(db)
    return {"items": graph.get_etf_tag_overview(), "tags": graph.get_tag_names()}


@router.put("/etf-tags/{etf_code}")
async def update_etf_tags(
    etf_code: str,
    body: ETFTagsUpdate,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """ETF 태그 수동 지정(tags 리스트) 또는 해제(tags=null)."""
    graph = GraphService(db)
    if not graph.get_etf_tag_overview(etf_code):
        raise HTTPException(status_code=404, detail="ETF not found")
    if body.tags is not None:
        unknown = set(body.tags) - set(graph.get_tag_names())
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown tags: {sorted(unknown)}")
        body.tags = list(dict.fromkeys(body.tags))
    graph.set_manual_tags(etf_code, body.tags)
    return graph.get_etf_tag_overview(etf_code)[0]


# === Discord 알림 설정 ===

def _mask_webhook(url: str | None) -> str | None:
    """웹훅 주소는 비밀값 — 응답에는 끝 4자리만 남긴다."""
    if not url:
        return None
    return f"https://discord.com/api/webhooks/…{url[-4:]}"


def _discord_settings_response(setting: DiscordSetting | None) -> dict:
    if setting is None:
        return {"enabled": True, "threshold": 3.0, "webhook_url_masked": None, "configured": False}
    return {
        "enabled": setting.enabled,
        "threshold": setting.threshold,
        "webhook_url_masked": _mask_webhook(setting.webhook_url),
        "configured": True,
    }


@router.get("/settings/discord")
async def get_discord_settings(
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """디스코드 알림 설정. configured=false면 아직 웹에서 저장한 적 없음(DAG는 환경변수 사용)."""
    return _discord_settings_response(db.get(DiscordSetting, 1))


@router.put("/settings/discord")
async def update_discord_settings(
    body: DiscordSettingsUpdate,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    setting = db.get(DiscordSetting, 1)
    if setting is None:
        setting = DiscordSetting(id=1)
        db.add(setting)
    setting.enabled = body.enabled
    setting.threshold = body.threshold
    if body.webhook_url is not None:
        setting.webhook_url = body.webhook_url or None
    db.commit()
    db.refresh(setting)
    return _discord_settings_response(setting)


@router.post("/settings/discord/test")
async def test_discord_webhook(
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """저장된 웹훅 주소로 테스트 메시지를 보낸다."""
    import httpx

    setting = db.get(DiscordSetting, 1)
    if setting is None or not setting.webhook_url:
        raise HTTPException(status_code=400, detail="저장된 웹훅 주소가 없습니다")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                setting.webhook_url,
                json={"content": "✅ ETF Atlas 디스코드 알림 테스트 메시지입니다."},
            )
            resp.raise_for_status()
    except httpx.HTTPError as e:
        # 예외 메시지에 웹훅 주소(토큰 포함)가 들어가므로 종류만 남긴다
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
        logger.warning(f"Discord test failed: {type(e).__name__} status={status}")
        raise HTTPException(status_code=502, detail="디스코드 전송에 실패했습니다. 웹훅 주소를 확인하세요.")
    return {"ok": True}


# === Member Invitations ===

def _invitation_response(inv: Invitation, used_by_username: str | None) -> dict:
    if inv.used_at:
        status = "used"
    elif inv.expires_at <= utcnow():
        status = "expired"
    else:
        status = "active"
    return {
        "id": inv.id,
        "token": inv.token,
        "status": status,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "expires_at": inv.expires_at.isoformat(),
        "used_at": inv.used_at.isoformat() if inv.used_at else None,
        "used_by_username": used_by_username,
    }


@router.get("/invitations")
async def list_invitations(
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """최근 초대 링크 50개 (최신순)"""
    rows = (
        db.query(Invitation, User.username)
        .outerjoin(User, User.id == Invitation.used_by)
        .order_by(Invitation.created_at.desc())
        .limit(50)
        .all()
    )
    return [_invitation_response(inv, username) for inv, username in rows]


@router.post("/invitations", status_code=201)
async def create_invitation(
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    return _invitation_response(AuthService(db).create_invitation(admin_id), None)


@router.delete("/invitations/{invitation_id}", status_code=204)
async def delete_invitation(
    invitation_id: int,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """아직 쓰지 않은 초대를 취소한다. 사용된 초대는 가입 기록이라 남긴다."""
    inv = db.get(Invitation, invitation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if inv.used_at:
        raise HTTPException(status_code=409, detail="Invitation already used")
    db.delete(inv)
    db.commit()


# === Members ===

class MemberRoleUpdate(BaseModel):
    is_admin: bool


@router.get("/members")
async def list_members(
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    return MemberService(db).list_members()


@router.put("/members/{user_id}/role", status_code=204)
async def update_member_role(
    user_id: int,
    body: MemberRoleUpdate,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """관리자 권한 부여/회수. 자기 자신은 바꿀 수 없다 (관리자가 0명이 되지 않게)."""
    try:
        MemberService(db).set_admin(user_id, body.is_admin, admin_id)
    except SelfActionError:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    except MemberNotFoundError:
        raise HTTPException(status_code=404, detail="Member not found")


@router.post("/members/{user_id}/logout")
async def logout_member(
    user_id: int,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """회원의 모든 로그인 세션을 끊는다"""
    try:
        return {"revoked": MemberService(db).revoke_sessions(user_id)}
    except MemberNotFoundError:
        raise HTTPException(status_code=404, detail="Member not found")


@router.delete("/members/{user_id}", status_code=204)
async def delete_member(
    user_id: int,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    try:
        MemberService(db).delete_member(user_id, admin_id)
    except SelfActionError:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    except MemberNotFoundError:
        raise HTTPException(status_code=404, detail="Member not found")


@router.post("/members/{user_id}/password-reset", status_code=201)
async def create_password_reset(
    user_id: int,
    db: Session = Depends(get_db),
    admin_id: int = Depends(get_admin_user_id),
):
    """재설정 링크 토큰 발급. 토큰은 해시로만 저장하므로 이 응답에서만 볼 수 있다."""
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="Member not found")
    token, reset = AuthService(db).create_password_reset(user_id, admin_id)
    return {"token": token, "expires_at": reset.expires_at.isoformat()}
