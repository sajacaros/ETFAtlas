"""few-shot 예시(code_examples·layout_examples)의 임베딩 저장. 관리자 화면에서 만들거나 고칠 때 바로 임베딩한다."""
import logging
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..utils.time import utcnow
from .embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

ExampleTable = Literal["code_examples", "layout_examples"]


def vector_literal(embedding: list[float]) -> str:
    """pgvector 입력 형식 '[0.1,0.2,...]'"""
    return "[" + ",".join(str(v) for v in embedding) + "]"


def embed_example(db: Session, table: ExampleTable, example_id: int, question_generalized: str,
                  service: EmbeddingService | None = None) -> bool:
    """임베딩해 저장하고 embedded로 둔다. 실패하면 비우고 active로 두어 embed_code_examples DAG가 다시 처리하게 한다."""
    try:
        embedding = (service or EmbeddingService(db)).get_embedding(question_generalized)
    except Exception as e:
        logger.warning("%s %s embedding failed: %s", table, example_id, e)
        clear_embedding(db, table, example_id, touch=False)
        return False
    # embedding 컬럼이 pgvector 타입이라 ORM이 아니라 SQL로 넣는다
    db.execute(
        text(f"UPDATE {table} SET embedding = :emb\\:\\:vector, status = 'embedded' WHERE id = :id"),
        {"emb": vector_literal(embedding), "id": example_id},
    )
    return True


def clear_embedding(db: Session, table: ExampleTable, example_id: int, touch: bool = True) -> None:
    """임베딩을 지우고 active로 — 검색 대상에서 빠지고, DAG가 다시 돌면 재임베딩된다."""
    db.execute(
        text(f"UPDATE {table} SET embedding = NULL, status = 'active'"
             + (", updated_at = :now" if touch else "") + " WHERE id = :id"),
        {"now": utcnow(), "id": example_id} if touch else {"id": example_id},
    )
