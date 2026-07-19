"""
Branch Module: minimal multi-branch support. Added because the admin
portal's dashboard shipped with a fake "branch" filter that deterministically
hashed each member's UUID into one of three hardcoded branch names with no
real backend concept behind it - meaning "filter by Kampala Branch" was
just showing a random ~33% subset of members with zero relationship to
where they actually bank. That's a serious problem for a real financial
dashboard, so this makes it a real, assignable field instead.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class Branch(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "branches"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
