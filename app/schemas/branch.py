from typing import Optional

from pydantic import BaseModel

from app.schemas.common import ORMBase


class BranchCreate(BaseModel):
    name: str
    code: str
    address: Optional[str] = None
    phone_number: Optional[str] = None


class BranchUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    phone_number: Optional[str] = None
    is_active: Optional[bool] = None


class BranchRead(ORMBase):
    id: str
    name: str
    code: str
    address: Optional[str] = None
    phone_number: Optional[str] = None
    is_active: bool
