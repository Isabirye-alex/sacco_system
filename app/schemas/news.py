"""
News Module Schemas
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.schemas.common import TimestampedRead


class NewsBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    content: str = Field(..., min_length=5)
    category: str = Field(default="ANNOUNCEMENT", max_length=50)
    priority: str = Field(default="NORMAL", max_length=20)
    icon: str = Field(default="fa-bell", max_length=50)
    is_published: bool = True
    expires_at: Optional[datetime] = None


class NewsCreate(NewsBase):
    pass


class NewsUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=255)
    content: Optional[str] = Field(None, min_length=5)
    category: Optional[str] = Field(None, max_length=50)
    priority: Optional[str] = Field(None, max_length=20)
    icon: Optional[str] = Field(None, max_length=50)
    is_published: Optional[bool] = None
    expires_at: Optional[datetime] = None


class NewsRead(TimestampedRead):
    title: str
    content: str
    category: str
    priority: str
    icon: str
    is_published: bool
    published_at: datetime
    expires_at: Optional[datetime] = None
    created_by_id: Optional[str] = None
