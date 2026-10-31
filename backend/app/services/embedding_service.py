import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from .ai_config import AIConfig, load_ai_config
from .generalize_prompt import GENERALIZE_SYSTEM_PROMPT
from .llm import complete, openai_client

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, db: Session, config: Optional[AIConfig] = None):
        """config를 이미 읽었으면 넘긴다. 클라이언트는 설정별로 캐시해 두고 쓴다 (llm.openai_client)."""
        self.db = db
        config = config or load_ai_config(db)
        self._client = openai_client(config.llm_api_base, config.llm_api_key)
        self._embed_client = openai_client(config.embedding_api_base, config.embedding_api_key)
        self._llm_model = config.llm_model
        self._embedding_model = config.embedding_model  # 768차원 (code_examples.embedding)

    def generalize_question(self, question: str) -> str:
        """LLM으로 질문에서 특정 ETF/종목명을 제거하고 패턴만 남긴 일반화 질문 생성."""
        try:
            # 고유명사 치환이라 추론 없이도 결과가 같고, 채팅마다 호출되므로 빠른 쪽을 쓴다
            return complete(self._client, self._llm_model, GENERALIZE_SYSTEM_PROMPT, question, max_tokens=512) or question
        except Exception as e:
            logger.warning(f"Question generalization failed: {e}")
            return question

    def get_embedding(self, text_input: str) -> List[float]:
        """단일 텍스트 임베딩 생성."""
        resp = self._embed_client.embeddings.create(
            model=self._embedding_model,
            input=text_input,
        )
        return resp.data[0].embedding

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """배치 임베딩 생성 (최대 2048개)."""
        resp = self._embed_client.embeddings.create(
            model=self._embedding_model,
            input=texts,
        )
        return [item.embedding for item in resp.data]

    def find_similar_code_examples(
        self, question: str, top_k: int = 3, max_distance: float = 0.35,
        similarity_gap: float = 0.05,
    ) -> List[Dict[str, Any]]:
        """질문과 유사한 해결 절차 예시(도구 호출 순서) 검색.

        max_distance: 코사인 거리 임계값 (0.35 = 유사도 0.65 이상만 반환).
        similarity_gap: 1등과의 유사도 차이 허용 범위 (0.05 = 5%).
            1등 유사도 대비 이 값 이상 떨어지면 제외.
        """
        return self._find_similar("code_examples", "code", question, top_k, max_distance, similarity_gap)

    def find_similar_layout_examples(
        self, question: str, top_k: int = 3, max_distance: float = 0.35,
        similarity_gap: float = 0.05,
    ) -> List[Dict[str, Any]]:
        """질문과 유사한 화면 설계 예시(슬롯 계획) 검색. 인자는 find_similar_code_examples와 같다."""
        return self._find_similar("layout_examples", "plan", question, top_k, max_distance, similarity_gap)

    def _find_similar(
        self, table: str, body: str, question: str, top_k: int, max_distance: float, similarity_gap: float,
    ) -> List[Dict[str, Any]]:
        """table/body는 코드에서만 넘기는 고정 이름이다 (쿼리 문자열에 직접 들어간다)."""
        try:
            emb = self.get_embedding(question)
        except Exception as e:
            logger.warning(f"Embedding API failed: {e}")
            return []

        emb_str = "[" + ",".join(str(v) for v in emb) + "]"
        query = text(
            f"SELECT id, question, question_generalized, {body}, description, "
            "embedding <=> :emb\\:\\:vector AS distance "
            f"FROM {table} "
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
                    body: getattr(r, body),
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
            logger.warning(f"{table} pgvector search failed: {e}")
            return []

