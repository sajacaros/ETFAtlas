import json
import logging
from pathlib import Path
from typing import List, Dict, Any

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings

logger = logging.getLogger(__name__)

EXAMPLES_JSON = Path(__file__).resolve().parent.parent / "data" / "cypher_examples.json"
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

    def find_similar_examples(self, question: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """질문과 유사한 Cypher 예제 검색."""
        try:
            emb = self.get_embedding(question)
        except Exception as e:
            logger.warning(f"Embedding API failed: {e}")
            return []

        emb_str = "[" + ",".join(str(v) for v in emb) + "]"
        query = text(
            "SELECT question, cypher, description, "
            "embedding <=> :emb\\:\\:vector AS distance "
            "FROM cypher_examples "
            "ORDER BY embedding <=> :emb\\:\\:vector "
            "LIMIT :top_k"
        )
        try:
            rows = self.db.execute(query, {"emb": emb_str, "top_k": top_k})
            return [
                {"question": r.question, "cypher": r.cypher, "description": r.description}
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"pgvector search failed: {e}")
            return []

    def seed_if_empty(self):
        """cypher_examples 테이블이 비어있으면 시드 데이터 적재."""
        count = self.db.execute(text("SELECT COUNT(*) FROM cypher_examples")).scalar()
        if count and count > 0:
            return

        if not EXAMPLES_JSON.exists():
            logger.warning(f"Seed file not found: {EXAMPLES_JSON}")
            return

        examples = json.loads(EXAMPLES_JSON.read_text(encoding="utf-8"))
        if not examples:
            return

        logger.info(f"Seeding {len(examples)} cypher examples...")
        questions = [ex["question"] for ex in examples]
        embeddings = self.get_embeddings_batch(questions)

        for ex, emb in zip(examples, embeddings):
            emb_str = "[" + ",".join(str(v) for v in emb) + "]"
            self.db.execute(
                text(
                    "INSERT INTO cypher_examples (question, cypher, description, embedding) "
                    "VALUES (:question, :cypher, :description, :emb\\:\\:vector)"
                ),
                {
                    "question": ex["question"],
                    "cypher": ex["cypher"],
                    "description": ex.get("description", ""),
                    "emb": emb_str,
                },
            )
        self.db.commit()
        logger.info(f"Seeded {len(examples)} cypher examples")
