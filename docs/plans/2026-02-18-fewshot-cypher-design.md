# Few-Shot Cypher Example Selector 설계

## 개요

GraphQueryTool의 Cypher 생성 품질을 개선하기 위해, pgvector 기반 유사도 검색으로 질문에 맞는 few-shot 예제를 동적으로 프롬프트에 주입한다.

## 결정 사항

| 항목 | 결정 |
|------|------|
| 적용 범위 | GraphQueryTool만 (전용 도구는 기존대로) |
| 임베딩 모델 | OpenAI text-embedding-3-small (1536차원) |
| 예제 관리 | 코드에 시드 데이터 (JSON 파일) |
| Top-K | 3개 |
| 접근 방식 | `_build_prompt()`에서 임베딩 검색 → 프롬프트 주입 |

## 데이터 모델

### `cypher_examples` 테이블

```sql
CREATE TABLE cypher_examples (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    cypher TEXT NOT NULL,
    description TEXT,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_cypher_examples_embedding
    ON cypher_examples USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
```

### 시드 데이터

`backend/app/data/cypher_examples.json` — 100개 질문-Cypher 쌍.

## 컴포넌트

### EmbeddingService (`backend/app/services/embedding_service.py`)

```python
class EmbeddingService:
    def __init__(self, db: Session)
    def get_embedding(self, text: str) -> list[float]
    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]
    def find_similar_examples(self, question: str, top_k: int = 3) -> list[dict]
    def seed_if_empty(self)
```

- `seed_if_empty()`: `cypher_examples` 테이블이 비어있으면 JSON 로드 → 배치 임베딩 → INSERT
- `find_similar_examples()`: 질문 임베딩 → pgvector cosine 검색 → Top-K 반환

### ChatService 변경

```python
class ChatService:
    def __init__(self, db):
        self._tag_names = self._load_tag_names()
        self._embedding_service = EmbeddingService(db)
        self._embedding_service.seed_if_empty()
        self._init_agent()

    def _build_prompt(self, message, history):
        parts = [SYSTEM_PROMPT, ""]
        # 태그 목록 (기존)
        if self._tag_names:
            parts.append(f"## 사용 가능한 태그 목록\n{...}\n")
        # ★ few-shot 예제 주입 (신규)
        examples = self._embedding_service.find_similar_examples(message, top_k=3)
        if examples:
            parts.append("## 참고 Cypher 쿼리 예시")
            for ex in examples:
                parts.append(f"Q: {ex['question']}\n```cypher\n{ex['cypher']}\n```")
            parts.append("")
        # 이전 대화 + 현재 질문 (기존)
        ...
```

## 프롬프트 주입 흐름

```
사용자 질문
    ↓
OpenAI embedding API (1회 호출)
    ↓
pgvector cosine similarity 검색 (Top-3)
    ↓
SYSTEM_PROMPT 뒤에 few-shot 예제 주입
    ↓
LLM이 예제를 참고하여 Cypher 생성
```

GraphQueryTool description의 정적 쿼리 패턴 4개는 유지 (기본 패턴 안전망).

## 파일 변경 범위

### 신규

| 파일 | 역할 |
|------|------|
| `docker/db/init/02_cypher_examples.sql` | 테이블 DDL + ivfflat 인덱스 |
| `backend/app/services/embedding_service.py` | EmbeddingService |
| `backend/app/data/cypher_examples.json` | 100개 시드 데이터 |

### 수정

| 파일 | 변경 |
|------|------|
| `docker/db/Dockerfile` | pgvector v0.7.0 → v0.8.0 |
| `backend/requirements.txt` | `openai>=1.0`, `pgvector>=0.4.2` 추가 |
| `backend/app/services/chat_service.py` | EmbeddingService 연동, `_build_prompt()` few-shot 주입 |

### 변경 없음

- GraphQueryTool 클래스 (정적 예시 유지)
- 기존 도구들, Airflow DAG, 프론트엔드
