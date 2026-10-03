import logging
from dataclasses import dataclass, field
from typing import List, Optional

from openai import OpenAI
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models.chat import ChatLog, ChatSession
from .chat_memory_prompt import REFINE_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

ANSWER_CLIP = 1500  # 맥락에 넣는 답변 길이 상한 (표가 길면 앞부분만으로 충분)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " …(생략)"


@dataclass
class Turn:
    question: str
    answer: str


@dataclass
class ConversationContext:
    """세션의 기억: 오래된 턴의 요약 + 최근 턴 원문."""
    summary: Optional[str] = None
    turns: List[Turn] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.summary and not self.turns

    def render(self) -> str:
        parts = []
        if self.summary:
            parts.append(f"[이전 대화 요약]\n{self.summary}")
        if self.turns:
            parts.append("[최근 대화]")
            parts.extend(f"사용자: {t.question}\n어시스턴트: {_clip(t.answer, ANSWER_CLIP)}" for t in self.turns)
        return "\n\n".join(parts)


def _turn(log: ChatLog) -> Turn:
    # 재작성된 질문이 있으면 그쪽이 맥락 없이도 읽힌다
    return Turn(question=log.refined_question or log.question, answer=log.answer)


class ChatMemory:
    """세션 히스토리 관리: 최근 window턴은 원문, 그 이전은 요약으로 유지하고 질문을 맥락으로 재작성한다."""

    def __init__(self, db: Session):
        self.db = db
        settings = get_settings()
        self._client = OpenAI(base_url=settings.llm_api_base, api_key=settings.llm_api_key)
        self._llm_model = settings.llm_model
        self.window = settings.chat_history_window

    def _complete(self, system: str, user: str, max_tokens: int) -> str:
        resp = self._client.chat.completions.create(
            model=self._llm_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            max_tokens=max_tokens,
            # 채팅마다 호출되는 보조 단계라 추론 없이 빠르게
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        return (resp.choices[0].message.content or "").strip()

    def _session_logs(self, session: ChatSession, after_id: int = 0) -> List[ChatLog]:
        return (
            self.db.query(ChatLog)
            .filter(ChatLog.session_id == session.id, ChatLog.id > after_id)
            .order_by(ChatLog.id)
            .all()
        )

    def load_context(self, session: ChatSession) -> ConversationContext:
        recent = (
            self.db.query(ChatLog)
            .filter(ChatLog.session_id == session.id)
            .order_by(ChatLog.id.desc())
            .limit(self.window)
            .all()
        )
        return ConversationContext(summary=session.summary, turns=[_turn(log) for log in reversed(recent)])

    def update_summary(self, session: ChatSession) -> bool:
        """window 밖으로 밀려났지만 아직 요약에 없는 턴을 기존 요약에 합친다. 갱신했으면 True.

        요약에 실패하면 summarized_until_log_id를 그대로 두어 다음 호출에서 다시 시도한다.
        """
        logs = self._session_logs(session, after_id=session.summarized_until_log_id or 0)
        pending = logs[:-self.window] if len(logs) > self.window else []
        if not pending:
            return False
        dialogue = "\n\n".join(
            f"사용자: {t.question}\n어시스턴트: {_clip(t.answer, ANSWER_CLIP)}" for t in map(_turn, pending)
        )
        user = f"## 기존 요약\n{session.summary or '(없음)'}\n\n## 새로 요약할 대화\n{dialogue}"
        try:
            summary = self._complete(SUMMARY_SYSTEM_PROMPT, user, max_tokens=800)
        except Exception as e:
            logger.warning(f"Chat summary failed (session {session.id}): {e}")
            return False
        if not summary:
            return False
        session.summary = summary
        session.summarized_until_log_id = pending[-1].id
        self.db.commit()
        return True

    def refine(self, question: str, context: ConversationContext) -> str:
        """대명사·생략을 대화 맥락으로 풀어 독립 질문으로 바꾼다. 맥락이 없거나 실패하면 원문."""
        if context.is_empty():
            return question
        user = f"## 대화 맥락\n{context.render()}\n\n## 마지막 질문\n{question}"
        try:
            refined = self._complete(REFINE_SYSTEM_PROMPT, user, max_tokens=256)
        except Exception as e:
            logger.warning(f"Question refine failed: {e}")
            return question
        refined = refined.removeprefix("출력:").strip().strip('"\'“”')
        # 빈 응답이나 답변을 늘어놓은 출력은 버린다
        if not refined or "\n" in refined or len(refined) > max(200, len(question) * 4):
            return question
        return refined
