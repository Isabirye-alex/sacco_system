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


DEFAULT_SEED_NEWS = [
    {
        "title": "SACCO AGM 2026 Scheduled",
        "content": "Annual General Meeting set for August 30th — all members expected to attend.",
        "category": "EVENT",
        "priority": "HIGH",
        "icon": "fa-bell",
    },
    {
        "title": "Q2 Dividends Approved",
        "content": "Q2 dividends of 14% approved and will be credited to share accounts by July 25th.",
        "category": "DIVIDEND",
        "priority": "HIGH",
        "icon": "fa-chart-line",
    },
    {
        "title": "Emergency Loan Limit Increased",
        "content": "Emergency loan limit increased to UGX 10,000,000 for active members.",
        "category": "ANNOUNCEMENT",
        "priority": "NORMAL",
        "icon": "fa-hand-holding-dollar",
    },
    {
        "title": "New Fixed Deposit Product",
        "content": "New Fixed Deposit product launched — earn up to 16% p.a. on savings above UGX 2M.",
        "category": "PRODUCT",
        "priority": "NORMAL",
        "icon": "fa-piggy-bank",
    },
    {
        "title": "Top Savers of Q2",
        "content": "Top Savers of Q2 will be awarded at the next member meeting — keep saving!",
        "category": "ANNOUNCEMENT",
        "priority": "NORMAL",
        "icon": "fa-trophy",
    },
    {
        "title": "Scheduled System Maintenance",
        "content": "System upgrade on Saturday 2:00–4:00 AM EAT. Portal may be temporarily unavailable.",
        "category": "ALERT",
        "priority": "URGENT",
        "icon": "fa-shield-halved",
    },
]


def seed_default_news_if_empty(db: Session):
    try:
        News.__table__.create(bind=db.get_bind(), checkfirst=True)
        if db.query(News).first() is None:
            now = datetime.utcnow()
            for item in DEFAULT_SEED_NEWS:
                news = News(
                    title=item["title"],
                    content=item["content"],
                    category=item["category"],
                    priority=item["priority"],
                    icon=item["icon"],
                    is_published=True,
                    published_at=now,
                )
                db.add(news)
            db.commit()
    except Exception:
        db.rollback()


@router.get("", response_model=List[NewsRead])
def list_published_news(
    category: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Get published Sacco news for members and public displays.
    """
    seed_default_news_if_empty(db)
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
    seed_default_news_if_empty(db)
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
