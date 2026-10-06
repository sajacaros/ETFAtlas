from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from datetime import datetime


# --- Chat Log ---
class ChatLogResponse(BaseModel):
    id: int
    question: str
    answer: str
    generated_code: Optional[str] = None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatLogListResponse(BaseModel):
    items: list[ChatLogResponse]
    total: int


class FeedbackRequest(BaseModel):
    status: str  # "liked" or "disliked"


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("제목을 입력하세요")
        return v


# --- Code Example ---
class CodeExampleResponse(BaseModel):
    id: int
    question: str
    code: str
    description: Optional[str] = None
    status: str
    has_embedding: bool
    source_chat_log_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CodeExampleListResponse(BaseModel):
    items: list[CodeExampleResponse]
    total: int


class CodeExampleCreate(BaseModel):
    question: str
    code: str
    description: Optional[str] = None


class CodeExampleUpdate(BaseModel):
    question: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None


class ETFTagsUpdate(BaseModel):
    tags: Optional[list[str]] = None  # None: 수동 지정 해제, []: 태그 없음으로 고정


# --- Admin Chat Log Review ---
class ReviewRequest(BaseModel):
    action: str  # "approve" or "reject"


class EmbedRequest(BaseModel):
    question: Optional[str] = None  # override original question
    code: Optional[str] = None  # override original code
    description: Optional[str] = None


# --- Admin Discord Settings ---
DISCORD_WEBHOOK_PREFIXES = (
    "https://discord.com/api/webhooks/",
    "https://discordapp.com/api/webhooks/",
)


class DiscordSettingsUpdate(BaseModel):
    enabled: bool
    threshold: float = Field(gt=0, le=100)
    # None: 기존 주소 유지, "": 주소 삭제
    webhook_url: Optional[str] = None

    @field_validator("webhook_url")
    @classmethod
    def check_webhook_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if v and not v.startswith(DISCORD_WEBHOOK_PREFIXES):
            raise ValueError("디스코드 웹훅 주소(https://discord.com/api/webhooks/...)만 입력할 수 있습니다")
        return v


# --- Admin AI Settings ---
class AISettingsUpdate(BaseModel):
    # 항목마다 None: 기존 값 유지, "": 지우고 서버 환경변수로 되돌림
    llm_api_base: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    embedding_api_base: Optional[str] = None
    embedding_api_key: Optional[str] = None
    embedding_model: Optional[str] = None

    @field_validator("*")
    @classmethod
    def strip(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v is not None else None

    @field_validator("llm_api_base", "embedding_api_base")
    @classmethod
    def check_api_base(cls, v: Optional[str]) -> Optional[str]:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("주소는 http:// 또는 https://로 시작해야 합니다")
        return v.rstrip("/") if v else v
