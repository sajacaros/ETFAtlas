import logging
from typing import List, Dict, Any

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"


class EmbeddingService:
    def __init__(self, db: Session):
        self.db = db
        settings = get_settings()
        self._client = OpenAI(api_key=settings.openai_api_key)

    def get_embedding(self, text_input: str) -> List[float]:
        """단일 텍스트 임베딩 생성."""
        resp = self._client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text_input,
        )
        return resp.data[0].embedding

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """배치 임베딩 생성 (최대 2048개)."""
        resp = self._client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in resp.data]

    def find_similar_code_examples(self, question: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """질문과 유사한 Python 코드 예제 검색."""
        try:
            emb = self.get_embedding(question)
        except Exception as e:
            logger.warning(f"Embedding API failed: {e}")
            return []

        emb_str = "[" + ",".join(str(v) for v in emb) + "]"
        query = text(
            "SELECT question, code, description, "
            "embedding <=> :emb\\:\\:vector AS distance "
            "FROM code_examples "
            "ORDER BY embedding <=> :emb\\:\\:vector "
            "LIMIT :top_k"
        )
        try:
            rows = self.db.execute(query, {"emb": emb_str, "top_k": top_k})
            return [
                {"question": r.question, "code": r.code, "description": r.description}
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"code_examples pgvector search failed: {e}")
            return []

