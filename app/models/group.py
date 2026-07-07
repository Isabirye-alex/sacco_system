"""
Group Management Module: table-banking / chama-style member groups.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import GroupRole
from app.models.base import TimestampMixin, UUIDPKMixin


class MemberGroup(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "member_groups"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    memberships: Mapped[list["GroupMembership"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    contributions: Mapped[list["GroupContribution"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupMembership(Base, UUIDPKMixin):
    __tablename__ = "group_memberships"

    group_id: Mapped[str] = mapped_column(ForeignKey("member_groups.id"), nullable=False)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    role: Mapped[GroupRole] = mapped_column(Enum(GroupRole), default=GroupRole.MEMBER)
    joined_date: Mapped[date] = mapped_column(default=date.today)

    group: Mapped["MemberGroup"] = relationship(back_populates="memberships")


class GroupContribution(Base, UUIDPKMixin):
    __tablename__ = "group_contributions"

    group_id: Mapped[str] = mapped_column(ForeignKey("member_groups.id"), nullable=False)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    contribution_date: Mapped[date] = mapped_column(default=date.today)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False) # type: ignore

    group: Mapped["MemberGroup"] = relationship(back_populates="contributions")


class GroupLoanGuarantee(Base, UUIDPKMixin):
    __tablename__ = "group_loan_guarantees"

    group_id: Mapped[str] = mapped_column(ForeignKey("member_groups.id"), nullable=False)
    loan_id: Mapped[str] = mapped_column(ForeignKey("loan_applications.id"), nullable=False)
    amount_guaranteed: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
