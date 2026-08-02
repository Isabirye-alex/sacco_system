"""
Sacco News Endpoints: Public/Member listing and Admin management (CRUD).
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import UserRole
from app.dependencies import get_current_user, require_roles
from app.models.news import News
from app.models.user import User
from app.schemas.news import NewsCreate, NewsRead, NewsUpdate

router = APIRouter(prefix="/api/v1/news", tags=["Sacco News"])

STAFF_ROLES = (
    UserRole.ADMIN,
    UserRole.MANAGER,
    UserRole.LOAN_OFFICER,
    UserRole.ACCOUNTANT,
    UserRole.TELLER,
    UserRole.AUDITOR,
)


@router.get("", response_model=List[NewsRead])
def list_published_news(
    category: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Get published Sacco news for members and public displays.
    """
    now = datetime.utcnow()
    query = db.query(News).filter(News.is_published.is_(True))

    # Filter out expired news
    query = query.filter((News.expires_at.is_(None)) | (News.expires_at >= now))

    if category:
        query = query.filter(News.category.ilike(category))

    return query.order_by(News.published_at.desc()).limit(limit).all()


@router.get("/admin/all", response_model=List[NewsRead])
def list_all_news_for_admin(
    category: Optional[str] = Query(None),
    is_published: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
):
    """
    List all news items (including drafts and expired) for staff/admin dashboard.
    """
    query = db.query(News)
    if category:
        query = query.filter(News.category.ilike(category))
    if is_published is not None:
        query = query.filter(News.is_published.is_(is_published))

    return query.order_by(News.created_at.desc()).all()


@router.post("", response_model=NewsRead, status_code=status.HTTP_201_CREATED)
def create_news(
    payload: NewsCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
):
    """
    Post a new Sacco news item or announcement.
    """
    news_item = News(
        title=payload.title,
        content=payload.content,
        category=payload.category.upper(),
        priority=payload.priority.upper(),
        icon=payload.icon,
        is_published=payload.is_published,
        published_at=datetime.utcnow() if payload.is_published else datetime.utcnow(),
        expires_at=payload.expires_at,
        created_by_id=current_user.id,
    )
    db.add(news_item)
    db.commit()
    db.refresh(news_item)
    return news_item


@router.get("/{news_id}", response_model=NewsRead)
def get_news_detail(news_id: str, db: Session = Depends(get_db)):
    """
    Retrieve single news item by ID.
    """
    news_item = db.get(News, news_id)
    if not news_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News item not found.")
    return news_item


@router.patch("/{news_id}", response_model=NewsRead)
def update_news(
    news_id: str,
    payload: NewsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
):
    """
    Update news article details, priority, category, or publish status.
    """
    news_item = db.get(News, news_id)
    if not news_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News item not found.")

    data = payload.model_dump(exclude_unset=True)
    if "category" in data and data["category"]:
        data["category"] = data["category"].upper()
    if "priority" in data and data["priority"]:
        data["priority"] = data["priority"].upper()

    for field, val in data.items():
        setattr(news_item, field, val)

    db.commit()
    db.refresh(news_item)
    return news_item


@router.delete("/{news_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_news(
    news_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
):
    """
    Delete a news item.
    """
    news_item = db.get(News, news_id)
    if not news_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News item not found.")

    db.delete(news_item)
    db.commit()
    return None
