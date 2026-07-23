"""
Member Management Module: member profiles, next-of-kin, trusted contacts.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import MemberStatus
from app.models.base import TimestampMixin, UUIDPKMixin


class Member(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "members"

    member_number: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    national_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    phone_number: Mapped[str] = mapped_column(String(30), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    physical_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occupation: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    employer_id: Mapped[Optional[str]] = mapped_column(ForeignKey("employers.id"), nullable=True)

    status: Mapped[MemberStatus] = mapped_column(Enum(MemberStatus), default=MemberStatus.ACTIVE, nullable=False)
    date_joined: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    dormancy_notified_stage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user_account: Mapped[Optional["User"]] = relationship(back_populates="member", uselist=False) # type: ignore
    next_of_kin: Mapped[list["NextOfKin"]] = relationship(back_populates="member", cascade="all, delete-orphan")
    trusted_contacts: Mapped[list["TrustedContact"]] = relationship(
        back_populates="member", cascade="all, delete-orphan"
    )
    savings_accounts: Mapped[list["SavingsAccount"]] = relationship(back_populates="member") # type: ignore
    loan_applications: Mapped[list["LoanApplication"]] = relationship( # type: ignore
        back_populates="member", foreign_keys="LoanApplication.member_id"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class NextOfKin(Base, UUIDPKMixin):
    __tablename__ = "next_of_kin"

    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(30), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    member: Mapped["Member"] = relationship(back_populates="next_of_kin")


class TrustedContact(Base, UUIDPKMixin):
    __tablename__ = "trusted_contacts"

    member_id: Mapped[str] = mapped_column(ForeignKey("members.id"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(30), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    member: Mapped["Member"] = relationship(back_populates="trusted_contacts")
