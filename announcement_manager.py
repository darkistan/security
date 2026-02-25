"""
Модуль для управління оголошеннями. Оголошення відправляються охоронцям у Telegram через Bot API.
"""
import os
import requests
from datetime import datetime
from typing import Dict, Any, List

from dotenv import load_dotenv
from database import get_session
from models import Announcement, AnnouncementRecipient, User
from logger import logger

load_dotenv("config.env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else None

_announcement_manager: Any = None


class AnnouncementManager:
    """Менеджер оголошень: створення, відправка в Telegram, історія, отримувачі, видалення."""

    def __init__(self) -> None:
        pass

    def send_announcement_to_users(
        self,
        recipient_user_ids: List[int],
        content: str,
        priority: str,
        author_id: int,
        author_username: str,
    ) -> Dict[str, Any]:
        """
        Відправка оголошення обраним охоронцям через Telegram Bot API.

        Returns:
            {'sent': int, 'failed': int, 'announcement_id': int or None}
        """
        if not TELEGRAM_BOT_TOKEN:
            logger.log_error("TELEGRAM_BOT_TOKEN не встановлено в config.env")
            return {"sent": 0, "failed": len(recipient_user_ids), "announcement_id": None}

        try:
            with get_session() as session:
                announcement = Announcement(
                    content=content,
                    author_id=author_id,
                    author_username=author_username or f"user_{author_id}",
                    priority=priority,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                    sent_at=datetime.now(),
                    recipient_count=len(recipient_user_ids),
                )
                session.add(announcement)
                session.flush()

                priority_emoji = {
                    "urgent": "🔴 ТЕРМІНОВЕ",
                    "important": "🟡 ВАЖЛИВЕ",
                    "normal": "📋 Оголошення",
                }.get(priority, "📋 Оголошення")
                message_text = f"{priority_emoji}\n\n{content}\n\n👤 Автор: @{author_username or 'admin'}"

                sent_count = 0
                failed_count = 0

                for recipient_id in recipient_user_ids:
                    try:
                        response = requests.post(
                            f"{TELEGRAM_API_URL}/sendMessage",
                            json={
                                "chat_id": recipient_id,
                                "text": message_text,
                                "parse_mode": "HTML",
                            },
                            timeout=10,
                        )

                        if response.status_code == 200:
                            status = "sent"
                            sent_count += 1
                        else:
                            try:
                                err = response.json()
                                error_code = err.get("error_code", 0)
                                error_description = err.get("description", "Unknown error")
                            except (ValueError, KeyError):
                                error_code = response.status_code
                                error_description = (response.text or "Unknown error")[:100]

                            if error_code == 403:
                                status = "blocked"
                            elif error_code == 400 and (
                                "chat not found" in (error_description or "").lower()
                                or "chat_id is empty" in (error_description or "").lower()
                            ):
                                status = "blocked"
                            else:
                                status = "failed"
                            failed_count += 1
                            if status == "failed":
                                logger.log_warning(
                                    f"Помилка відправки оголошення {announcement.id} користувачу {recipient_id}: {error_description}"
                                )

                        rec = AnnouncementRecipient(
                            announcement_id=announcement.id,
                            recipient_user_id=recipient_id,
                            sent_at=datetime.now(),
                            status=status,
                        )
                        session.add(rec)

                    except requests.exceptions.RequestException as e:
                        failed_count += 1
                        logger.log_error(f"Помилка відправки оголошення {announcement.id} користувачу {recipient_id}: {e}")
                        session.add(
                            AnnouncementRecipient(
                                announcement_id=announcement.id,
                                recipient_user_id=recipient_id,
                                sent_at=datetime.now(),
                                status="failed",
                            )
                        )

                announcement.recipient_count = sent_count
                session.commit()
                logger.log_info(f"Оголошення {announcement.id} відправлено: {sent_count} успішно, {failed_count} помилок")
                return {"sent": sent_count, "failed": failed_count, "announcement_id": announcement.id}

        except Exception as e:
            logger.log_error(f"Помилка відправки оголошення: {e}")
            return {"sent": 0, "failed": len(recipient_user_ids), "announcement_id": None}

    def get_announcement_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Історія відправлених оголошень."""
        try:
            with get_session() as session:
                announcements = (
                    session.query(Announcement)
                    .order_by(Announcement.created_at.desc())
                    .limit(limit)
                    .all()
                )
                result = []
                for ann in announcements:
                    result.append({
                        "id": ann.id,
                        "content": (ann.content[:100] + "...") if len(ann.content) > 100 else ann.content,
                        "author_username": ann.author_username,
                        "priority": ann.priority,
                        "sent_at": ann.sent_at,
                        "recipient_count": ann.recipient_count or 0,
                        "created_at": ann.created_at,
                    })
                return result
        except Exception as e:
            logger.log_error(f"Помилка отримання історії оголошень: {e}")
            return []

    def get_announcement_recipients(self, announcement_id: int) -> List[Dict[str, Any]]:
        """Список отримувачів оголошення зі статусом."""
        try:
            with get_session() as session:
                rows = (
                    session.query(AnnouncementRecipient, User)
                    .join(User, AnnouncementRecipient.recipient_user_id == User.user_id)
                    .filter(AnnouncementRecipient.announcement_id == announcement_id)
                    .all()
                )
                return [
                    {
                        "recipient_user_id": r.recipient_user_id,
                        "username": u.username,
                        "full_name": u.full_name,
                        "sent_at": r.sent_at,
                        "status": r.status,
                    }
                    for r, u in rows
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання отримувачів оголошення {announcement_id}: {e}")
            return []

    def delete_announcement(self, announcement_id: int) -> bool:
        """Видалення оголошення та записів отримувачів."""
        try:
            with get_session() as session:
                session.query(AnnouncementRecipient).filter(
                    AnnouncementRecipient.announcement_id == announcement_id
                ).delete()
                ann = session.query(Announcement).filter(Announcement.id == announcement_id).first()
                if ann:
                    session.delete(ann)
                    session.commit()
                logger.log_info(f"Видалено оголошення {announcement_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка видалення оголошення: {e}")
            return False

    def get_all_users_for_select(self) -> List[Dict[str, Any]]:
        """Список усіх охоронців (user_id, username, full_name) для вибору отримувачів."""
        try:
            with get_session() as session:
                users = session.query(User).filter(User.is_active == True).all()
                return [
                    {"user_id": u.user_id, "username": u.username or f"user_{u.user_id}", "full_name": u.full_name}
                    for u in users
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання списку користувачів: {e}")
            return []


def get_announcement_manager() -> AnnouncementManager:
    """Синглтон менеджера оголошень."""
    global _announcement_manager
    if _announcement_manager is None:
        _announcement_manager = AnnouncementManager()
    return _announcement_manager
