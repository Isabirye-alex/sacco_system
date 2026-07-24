"""
Reusable FastAPI dependencies: current authenticated user and role-based
access control (RBAC) guards.
"""
from typing import Iterable, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import UserRole
from app.core.security import decode_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    x_portal: Optional[str] = Header(default=None, alias="X-Portal"),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise credentials_exception
        user_id: str = payload.get("sub") # type: ignore
        if user_id is None: # type: ignore
            raise credentials_exception
        
        token_portal = payload.get("portal")
        if x_portal and token_portal and x_portal.lower() != token_portal.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Token issued for '{token_portal}' portal cannot be used on '{x_portal}' portal.",
            )
    except JWTError:
        raise credentials_exception

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception

    # Enforce strict cross-portal protection based on user role and token portal claim
    if token_portal == "staff" and user.role == UserRole.MEMBER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Member accounts are not permitted to use staff portal tokens.",
        )
    if token_portal == "member" and user.role != UserRole.MEMBER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff accounts are not permitted to use member portal tokens.",
        )

    return user



def require_roles(*allowed_roles: Iterable[UserRole]):
    """
    Dependency factory for RBAC. Usage:
        current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER))
    """

    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role.value}' is not permitted to perform this action.",
            )
        return current_user

    return _checker


def get_optional_current_user(
    authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Like get_current_user, but returns None instead of raising when no (or
    an invalid) bearer token is present. Used on endpoints that are
    intentionally public (e.g. self-registration) but still want to
    attribute the action to an actor when one happens to be logged in
    (e.g. an admin creating a staff account from the admin portal).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        user = db.get(User, payload.get("sub"))
        return user if (user and user.is_active) else None
    except JWTError:
        return None


def get_current_active_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator privileges required.")
    return current_user
