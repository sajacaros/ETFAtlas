import logging
from typing import List, Dict, Any

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings
from .generalize_prompt import GENERALIZE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"


class EmbeddingService:
    def __init__(self, db: Session):
        self.db = db
        settings = get_settings()
        self._client = OpenAI(api_key=settings.openai_api_key)

    def generalize_question(self, question: str) -> str:
        """LLM으로 질문에서 특정 ETF/종목명을 제거하고 패턴만 남긴 일반화 질문 생성."""
        try:
            resp = self._client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": GENERALIZE_SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
                temperature=0,
                max_tokens=200,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"Question generalization failed: {e}")
            return question

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

    def find_similar_code_examples(
        self, question: str, top_k: int = 3, max_distance: float = 0.35,
        similarity_gap: float = 0.05,
    ) -> List[Dict[str, Any]]:
        """질문과 유사한 Python 코드 예제 검색.

        max_distance: 코사인 거리 임계값 (0.35 = 유사도 0.65 이상만 반환).
        similarity_gap: 1등과의 유사도 차이 허용 범위 (0.05 = 5%).
            1등 유사도 대비 이 값 이상 떨어지면 제외.
        """
        try:
            emb = self.get_embedding(question)
        except Exception as e:
            logger.warning(f"Embedding API failed: {e}")
            return []

        emb_str = "[" + ",".join(str(v) for v in emb) + "]"
        query = text(
            "SELECT id, question, question_generalized, code, description, "
            "embedding <=> :emb\\:\\:vector AS distance "
            "FROM code_examples "
            "WHERE status = 'embedded' "
            "AND embedding <=> :emb\\:\\:vector < :max_dist "
            "ORDER BY embedding <=> :emb\\:\\:vector "
            "LIMIT :top_k"
        )
        try:
            rows = self.db.execute(
                query, {"emb": emb_str, "top_k": top_k, "max_dist": max_distance},
            )
            results = [
                {
                    "id": r.id,
                    "question": r.question,
                    "question_generalized": r.question_generalized,
                    "code": r.code,
                    "description": r.description,
                    "distance": round(r.distance, 4),
                }
                for r in rows
            ]
            # 1등 대비 유사도 차이가 similarity_gap 이상이면 제외
            if results and similarity_gap > 0:
                best_distance = results[0]["distance"]
                results = [
                    r for r in results
                    if r["distance"] - best_distance <= similarity_gap
                ]
            return results
        except Exception as e:
            logger.warning(f"code_examples pgvector search failed: {e}")
            return []

