"""F08: thông báo."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, update

from app.api.deps import DB, CurrentUser
from app.models import Notification
from app.schemas.common import ORMModel
from app.services.notification_service import generate_due_notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(ORMModel):
    id: int
    type: str
    payload: dict
    is_read: bool
    created_at: datetime


class NotificationList(BaseModel):
    unread_count: int
    items: list[NotificationOut]


@router.get("", response_model=NotificationList)
def list_notifications(user: CurrentUser, db: DB, limit: int = 30):
    generate_due_notifications(db, user)
    items = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(min(limit, 100))
    ).all()
    unread = db.scalar(
        select(func.count()).where(Notification.user_id == user.id, Notification.is_read.is_(False))
    )
    return NotificationList(unread_count=unread or 0, items=[NotificationOut.model_validate(n) for n in items])


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: int, user: CurrentUser, db: DB):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thông báo")
    n.is_read = True
    db.commit()
    db.refresh(n)
    return n


@router.post("/read-all")
def mark_all_read(user: CurrentUser, db: DB):
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return {"ok": True}
