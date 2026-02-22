from pydantic import BaseModel
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

    class Config:
        from_attributes = True


class ChatLogListResponse(BaseModel):
    items: list[ChatLogResponse]
    total: int


class FeedbackRequest(BaseModel):
    status: str  # "liked" or "disliked"


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

    class Config:
        from_attributes = True


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


# --- Admin Chat Log Review ---
class ReviewRequest(BaseModel):
    action: str  # "approve" or "reject"


class EmbedRequest(BaseModel):
    question: Optional[str] = None  # override original question
    code: Optional[str] = None  # override original code
    description: Optional[str] = None
