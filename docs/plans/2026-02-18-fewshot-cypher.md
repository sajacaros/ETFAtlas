# Few-Shot Cypher Example Selector Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** pgvector 유사도 검색으로 질문에 맞는 Cypher few-shot 예제를 동적으로 프롬프트에 주입하여 GraphQueryTool의 Cypher 생성 품질을 개선한다.

**Architecture:** `cypher_examples` 테이블에 100개 질문-Cypher 쌍 + 임베딩을 저장한다. ChatService 초기화 시 시드하고, 매 요청마다 질문을 임베딩 → pgvector cosine 검색 → Top-3 예제를 SYSTEM_PROMPT 뒤에 주입한다.

**Tech Stack:** PostgreSQL pgvector v0.8.0, OpenAI text-embedding-3-small (1536차원), pgvector Python 0.4.2, SQLAlchemy 2.0

**Design doc:** `docs/plans/2026-02-18-fewshot-cypher-design.md`

---

### Task 1: pgvector 확장 업그레이드 + DDL

**Files:**
- Modify: `docker/db/Dockerfile:22` — pgvector v0.7.0 → v0.8.0
- Create: `docker/db/init/02_cypher_examples.sql` — 테이블 + 인덱스
- Modify: `backend/requirements.txt` — 의존성 추가

**Step 1: Dockerfile pgvector 버전 업그레이드**

`docker/db/Dockerfile:22`에서:
```dockerfile
# 변경 전
RUN git clone --branch v0.7.0 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
# 변경 후
RUN git clone --branch v0.8.0 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
```

**Step 2: cypher_examples 테이블 DDL 생성**

`docker/db/init/02_cypher_examples.sql`:
```sql
-- Few-shot Cypher example store (pgvector)
CREATE TABLE IF NOT EXISTS cypher_examples (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    cypher TEXT NOT NULL,
    description TEXT,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cypher_examples_embedding
    ON cypher_examples USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
```

**Step 3: Python 의존성 추가**

`backend/requirements.txt`에 추가:
```
openai>=1.0
pgvector>=0.4.2
```

**Step 4: DB 컨테이너 재빌드하여 DDL 확인**

```bash
docker compose up -d --build db
docker compose exec db psql -U postgres -d etf_atlas -c "\d cypher_examples"
```
Expected: 테이블 구조 출력 (id, question, cypher, description, embedding, created_at)

**Step 5: 커밋**

```bash
git add docker/db/Dockerfile docker/db/init/02_cypher_examples.sql backend/requirements.txt
git commit -m "feat: add cypher_examples table with pgvector + upgrade pgvector to v0.8.0"
```

---

### Task 2: EmbeddingService 구현

**Files:**
- Create: `backend/app/services/embedding_service.py`

**Step 1: EmbeddingService 작성**

`backend/app/services/embedding_service.py`:
```python
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
```

**Step 2: 커밋**

```bash
git add backend/app/services/embedding_service.py
git commit -m "feat: add EmbeddingService with pgvector seed and similarity search"
```

---

### Task 3: 시드 데이터 (100개 질문-Cypher 쌍) 작성

**Files:**
- Create: `backend/app/data/cypher_examples.json`

**Step 1: data 디렉토리 생성 + JSON 작성**

`backend/app/data/cypher_examples.json` — 100개 예제를 카테고리별로 작성:

카테고리 구성:
- **보유종목 조회** (15개): ETF 보유종목 TOP N, 전체 보유종목, 특정 종목 비중
- **종목→ETF 역추적** (10개): 특정 종목 보유 ETF, 비중 높은 순
- **유사 ETF** (5개): 공통 보유종목 수, 비중 겹침 유사도
- **태그/테마** (15개): 태그별 ETF 조회, 태그 목록, 태그+조건 조합
- **운용사** (10개): 운용사별 ETF, 운용사 목록, 운용사+조건 조합
- **가격/수익률** (15개): ETF/Stock 가격 조회, 기간별 수익률, 시가총액
- **비교** (10개): 보수율 비교, 수익률 비교, 보유종목 겹침
- **복합 질의** (10개): 태그+보수율+수익률, 종목+ETF+운용사
- **즐겨찾기/사용자** (5개): 즐겨찾기 조회, admin 유저
- **변동 감지** (5개): 비중 변화, 신규편입/편출

각 예제의 Cypher는 반드시 다음 규칙을 따름:
1. RETURN은 단일 맵: `RETURN {key1: val1, key2: val2}`
2. HOLDS 최신 데이터: `WITH s, h ORDER BY h.date DESC` + `WITH s, head(collect(h)) as latest` 패턴
3. 문자열 리터럴은 작은따옴표

**Step 2: 커밋**

```bash
git add backend/app/data/cypher_examples.json
git commit -m "feat: add 100 cypher few-shot examples seed data"
```

---

### Task 4: ChatService 연동

**Files:**
- Modify: `backend/app/services/chat_service.py:1-9` — import 추가
- Modify: `backend/app/services/chat_service.py:584-633` — ChatService 클래스 수정

**Step 1: import 추가**

`chat_service.py` 상단에 추가:
```python
from .embedding_service import EmbeddingService
```

**Step 2: ChatService.__init__ 수정**

```python
class ChatService:
    def __init__(self, db: Session):
        self.db = db
        self._tag_names = self._load_tag_names()
        self._embedding_service = EmbeddingService(db)
        self._embedding_service.seed_if_empty()
        self._init_agent()
```

**Step 3: _build_prompt() 수정**

```python
    def _build_prompt(self, message: str, history: List[Dict[str, str]]) -> str:
        parts = [SYSTEM_PROMPT, ""]
        if self._tag_names:
            parts.append(f"## 사용 가능한 태그 목록\n{', '.join(self._tag_names)}\n")
        # few-shot 예제 주입
        examples = self._embedding_service.find_similar_examples(message, top_k=3)
        if examples:
            parts.append("## 참고 Cypher 쿼리 예시")
            for ex in examples:
                parts.append(f"Q: {ex['question']}\n```cypher\n{ex['cypher']}\n```")
            parts.append("")
        if history:
            parts.append("## 이전 대화:")
            for msg in history[-10:]:
                role = "사용자" if msg["role"] == "user" else "어시스턴트"
                parts.append(f"{role}: {msg['content']}")
            parts.append("")
        parts.append(f"## 현재 질문:\n{message}")
        return "\n".join(parts)
```

**Step 4: 커밋**

```bash
git add backend/app/services/chat_service.py
git commit -m "feat: integrate few-shot example selector into ChatService prompt"
```

---

### Task 5: 통합 테스트 — 빌드 및 동작 확인

**Step 1: 백엔드 + DB 컨테이너 재빌드**

```bash
docker compose up -d --build db backend
```

**Step 2: cypher_examples 테이블 확인**

```bash
docker compose exec db psql -U postgres -d etf_atlas -c "SELECT COUNT(*) FROM cypher_examples;"
```
Expected: 초기에는 0 (시드는 첫 채팅 요청 시 실행)

**Step 3: 채팅 API 호출로 시드 + few-shot 동작 확인**

```bash
curl -X POST http://localhost:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "삼성전자를 가장 많이 보유한 ETF는?", "history": []}'
```
Expected: 정상 응답, 로그에 "Seeding N cypher examples..." 출력 (최초 1회)

**Step 4: 시드 완료 후 테이블 확인**

```bash
docker compose exec db psql -U postgres -d etf_atlas -c "SELECT COUNT(*) FROM cypher_examples;"
```
Expected: 100

**Step 5: 커밋 (최종)**

```bash
git add -A
git commit -m "feat: complete few-shot cypher example selector with pgvector"
```
