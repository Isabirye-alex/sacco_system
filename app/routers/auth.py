"""
Authentication endpoints: registration, login (OAuth2 password flow),
token refresh, and password change.

Portal separation: the member portal and admin/staff portal each hit a
different login endpoint, and each rejects the wrong kind of account -
POST /login is staff-only, POST /member-login is member-only. This is
enforced here (not just hidden in the frontend) since the JWT itself is
role-agnostic once issued; without this check a member could always have
called /login directly and gotten into the staff-shaped frontend's API
calls (even if the UI didn't show them anything useful, they'd still hold
a valid token). The `portal` claim embedded in the token is also checked
on refresh, so a refreshed token can't cross from one portal to the other.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import UserRole
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.dependencies import get_current_user, get_optional_current_user
from app.models.user import User
from app.schemas.user import (
    PasswordChangeRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserRead,
)
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

STAFF_ROLES = (
    UserRole.ADMIN, UserRole.MANAGER, UserRole.LOAN_OFFICER, UserRole.ACCOUNTANT,
    UserRole.HR_OFFICER, UserRole.TELLER, UserRole.AUDITOR,
)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User | None = Depends(get_optional_current_user),
):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists.")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        member_id=payload.member_id,
    )
    db.add(user)
    db.flush()
    record_audit(
        db, actor_user_id=actor.id if actor else None, action="auth.user_register", entity_type="User",
        entity_id=user.id,
        details=f"Registered {user.email} as {user.role.value}" + (" (self-registered)" if not actor else ""),
    )
    db.commit()
    db.refresh(user)
    return user


def _authenticate(form_data: OAuth2PasswordRequestForm, db: Session) -> User:
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been deactivated.")
    return user


def _issue_tokens(user: User, portal: str) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, {"role": user.role.value, "portal": portal}),
        refresh_token=create_refresh_token(user.id, {"portal": portal}),
    )


@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Staff/admin portal login. Rejects member accounts."""
    user = _authenticate(form_data, db)
    if user.role == UserRole.MEMBER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is a member account - please sign in through the member portal instead.",
        )
    user.last_login = datetime.utcnow()
    db.commit()
    return _issue_tokens(user, portal="staff")


@router.post("/member-login", response_model=TokenResponse)
def member_login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Member portal login. Rejects staff accounts."""
    user = _authenticate(form_data, db)
    if user.role != UserRole.MEMBER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This is a staff account - please sign in through the admin portal instead.",
        )
    user.last_login = datetime.utcnow()
    db.commit()
    return _issue_tokens(user, portal="member")


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        claims = decode_token(payload.refresh_token)
        if claims.get("type") != "refresh":
            raise JWTError("Not a refresh token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token.")

    user = db.get(User, claims.get("sub"))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer active.")

    # Re-validate the portal boundary on every refresh too, in case a role
    # changed (e.g. a member account got promoted to staff) since the
    # original login - the old refresh token shouldn't silently carry the
    # old portal's access forward.
    portal = claims.get("portal", "staff")
    is_member_portal = portal == "member"
    if is_member_portal and user.role != UserRole.MEMBER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account can no longer use the member portal.")
    if not is_member_portal and user.role == UserRole.MEMBER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account can no longer use the staff portal.")

    return _issue_tokens(user, portal=portal)


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect.")
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()
