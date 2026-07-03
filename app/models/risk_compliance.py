"""
Risk & Compliance Module: risk flags and regulatory compliance reports.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import RiskFlagStatus, RiskFlagType
from app.models.base import TimestampMixin, UUIDPKMixin


class RiskFlag(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "risk_flags"

    flag_type: Mapped[RiskFlagType] = mapped_column(Enum(RiskFlagType), nullable=False)
    member_id: Mapped[Optional[str]] = mapped_column(ForeignKey("members.id"), nullable=True)
    loan_id: Mapped[Optional[str]] = mapped_column(ForeignKey("loan_applications.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RiskFlagStatus] = mapped_column(Enum(RiskFlagStatus), default=RiskFlagStatus.OPEN)
    resolved_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ComplianceReport(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "compliance_reports"

    report_type: Mapped[str] = mapped_column(String(80), nullable=False)  # e.g. sasra_quarterly, aml_str
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    generated_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    file_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted: Mapped[bool] = mapped_column(default=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
