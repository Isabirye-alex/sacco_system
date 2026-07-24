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
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
    UserCreate,
    UserRead,
)
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

STAFF_ROLES = (
    UserRole.ADMIN, UserRole.MANAGER, UserRole.LOAN_OFFICER, UserRole.ACCOUNTANT,
    UserRole.HR_OFFICER, UserRole.TELLER, UserRole.AUDITOR,
)


from app.models.referral import Referral, ReferralStatus
from app.models.user import User, generate_unique_referral_code


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User | None = Depends(get_optional_current_user),
):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists.")
    
    unique_code = generate_unique_referral_code(db)
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        member_id=payload.member_id,
        referral_code=unique_code,
    )
    db.add(user)
    db.flush()

    if payload.ref:
        tier1_referrer = db.query(User).filter(User.referral_code == payload.ref.strip().upper()).first()
        if tier1_referrer:
            if tier1_referrer.id == user.id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Self-referral is not allowed.")
            
            tier1_ref = Referral(
                referrer_id=tier1_referrer.id,
                referred_user_id=user.id,
                tier=1,
                status=ReferralStatus.PENDING,
            )
            db.add(tier1_ref)

            tier2_lookup = db.query(Referral).filter(
                Referral.referred_user_id == tier1_referrer.id,
                Referral.tier == 1
            ).first()

            if tier2_lookup:
                tier2_ref = Referral(
                    referrer_id=tier2_lookup.referrer_id,
                    referred_user_id=user.id,
                    tier=2,
                    status=ReferralStatus.PENDING,
                )
                db.add(tier2_ref)

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


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record_audit(
        db, actor_user_id=current_user.id, action="auth.user_logout", entity_type="User",
        entity_id=current_user.id, details=f"User {current_user.email} logged out.",
    )
    db.commit()
    return {"message": "Logged out successfully."}


from app.services.totp_service import generate_provisioning_uri, generate_totp_secret, verify_totp_code

@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
def setup_2fa(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generates a new TOTP 2FA secret and provisioning URI for Google Authenticator / Authy.
    """
    secret = generate_totp_secret()
    provisioning_uri = generate_provisioning_uri(secret, current_user.email)
    
    current_user.totp_secret = secret
    db.commit()
    
    return TwoFactorSetupResponse(
        secret=secret,
        provisioning_uri=provisioning_uri,
        manual_entry_key=secret,
    )


@router.post("/2fa/enable", status_code=status.HTTP_200_OK)
def enable_2fa(
    payload: TwoFactorVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Verifies the first TOTP 6-digit code and enables 2FA for the user account.
    """
    if not current_user.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA setup must be initiated first.")

    if not verify_totp_code(current_user.totp_secret, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid 2FA verification code.")

    current_user.is_2fa_enabled = True
    record_audit(
        db, actor_user_id=current_user.id, action="auth.2fa_enabled", entity_type="User",
        entity_id=current_user.id, details=f"Two-factor authentication enabled for {current_user.email}.",
    )
    db.commit()
    return {"message": "2FA successfully enabled."}


@router.post("/2fa/disable", status_code=status.HTTP_200_OK)
def disable_2fa(
    payload: TwoFactorVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Disables 2FA after verifying a valid TOTP 6-digit code.
    """
    if not current_user.is_2fa_enabled or not current_user.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled for this account.")

    if not verify_totp_code(current_user.totp_secret, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid 2FA verification code.")

    current_user.is_2fa_enabled = False
    current_user.totp_secret = None
    record_audit(
        db, actor_user_id=current_user.id, action="auth.2fa_disabled", entity_type="User",
        entity_id=current_user.id, details=f"Two-factor authentication disabled for {current_user.email}.",
    )
    db.commit()
    return {"message": "2FA successfully disabled."}


@router.post("/2fa/verify", status_code=status.HTTP_200_OK)
def verify_2fa(
    payload: TwoFactorVerifyRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Verifies a TOTP 6-digit code during login or high-value actions.
    """
    if not current_user.is_2fa_enabled or not current_user.totp_secret:
        return {"valid": True, "message": "2FA is not required for this account."}

    if not verify_totp_code(current_user.totp_secret, payload.code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid 2FA verification code.")

    return {"valid": True, "message": "2FA code verified successfully."}

