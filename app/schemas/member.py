from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.core.enums import MemberStatus
from app.schemas.common import ORMBase


class NextOfKinCreate(BaseModel):
    full_name: str
    relationship_type: str
    phone_number: str
    email: Optional[EmailStr] = None


class NextOfKinRead(ORMBase):
    id: str
    full_name: str
    relationship_type: str
    phone_number: str
    email: Optional[EmailStr] = None


class TrustedContactCreate(BaseModel):
    full_name: str
    phone_number: str
    email: Optional[EmailStr] = None


class TrustedContactRead(ORMBase):
    id: str
    full_name: str
    phone_number: str
    email: Optional[EmailStr] = None


class MemberCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    national_id: str = Field(min_length=3, max_length=50)
    date_of_birth: Optional[date] = None
    phone_number: str = Field(min_length=7, max_length=30)
    email: Optional[EmailStr] = None
    physical_address: Optional[str] = None
    occupation: Optional[str] = None
    employer_id: Optional[str] = None
    next_of_kin: list[NextOfKinCreate] = []
    trusted_contacts: list[TrustedContactCreate] = []


class MemberUpdate(BaseModel):
    phone_number: Optional[str] = None
    email: Optional[EmailStr] = None
    physical_address: Optional[str] = None
    occupation: Optional[str] = None
    employer_id: Optional[str] = None
    status: Optional[MemberStatus] = None


class MemberRead(ORMBase):
    id: str
    member_number: str
    first_name: str
    last_name: str
    national_id: str
    date_of_birth: Optional[date] = None
    phone_number: str
    email: Optional[EmailStr] = None
    physical_address: Optional[str] = None
    occupation: Optional[str] = None
    status: MemberStatus
    date_joined: date
    last_activity_at: Optional[datetime] = None
    created_at: datetime


class MemberDetailRead(MemberRead):
    next_of_kin: list[NextOfKinRead] = []
    trusted_contacts: list[TrustedContactRead] = []
