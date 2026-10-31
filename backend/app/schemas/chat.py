from pydantic import BaseModel, Field, field_validator
from typing import Literal


class FeedbackRequest(BaseModel):
    status: Literal["liked", "disliked"]


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("제목을 입력하세요")
        return v
