"""
Модуль для управління балами охоронців (позитивні/негативні).
Адмін нараховує бали у веб-інтерфейсі; охоронець бачить баланс у боті.
"""
from typing import List, Optional, Dict, Any

from database import get_session
from models import GuardPoint, User
from logger import logger

# Максимальна довжина причини нарахування
REASON_MAX_LENGTH = 500

_points_manager: Optional["PointsManager"] = None


class PointsManager:
    """Менеджер балів охоронців."""

    def __init__(self) -> None:
        """Ініціалізація менеджера балів."""
        pass

    def get_balance(self, guard_id: int) -> int:
        """
        Поточний баланс балів охоронця (сума всіх points_delta).

        Args:
            guard_id: Telegram ID охоронця.

        Returns:
            Сума балів (може бути від'ємною).
        """
        try:
            with get_session() as session:
                from sqlalchemy import func
                result = session.query(func.coalesce(func.sum(GuardPoint.points_delta), 0)).filter(
                    GuardPoint.guard_id == guard_id
                ).scalar()
                return int(result) if result is not None else 0
        except Exception as e:
            logger.log_error(f"Помилка отримання балансу для {guard_id}: {e}")
            return 0

    def add_points(
        self,
        guard_id: int,
        points_delta: int,
        reason: Optional[str],
        created_by_id: int,
    ) -> bool:
        """
        Нарахування або зняття балів охоронцю.

        Args:
            guard_id: Telegram ID охоронця.
            points_delta: Зміна балів (додатні — бонус, від'ємні — штраф).
            reason: Причина (опціонально).
            created_by_id: Telegram/user_id того, хто нарахував (адмін).

        Returns:
            True якщо запис створено успішно.
        """
        if points_delta == 0:
            logger.log_warning("add_points: points_delta=0, ігноровано")
            return False
        try:
            with get_session() as session:
                guard = session.query(User).filter(
                    User.user_id == guard_id,
                    User.is_active == True,
                ).first()
                if not guard:
                    logger.log_error(f"Охоронець {guard_id} не знайдено або неактивний")
                    return False
                created_by = session.query(User).filter(User.user_id == created_by_id).first()
                if not created_by:
                    logger.log_error(f"Користувач {created_by_id} (хто нарахував) не знайдено")
                    return False
                reason_clean = None
                if reason and isinstance(reason, str):
                    reason_clean = reason.strip()[:REASON_MAX_LENGTH] or None
                record = GuardPoint(
                    guard_id=guard_id,
                    points_delta=points_delta,
                    reason=reason_clean,
                    created_by_id=created_by_id,
                )
                session.add(record)
                session.commit()
                logger.log_info(
                    f"Нараховано бали: guard_id={guard_id}, delta={points_delta}, by={created_by_id}"
                )
                return True
        except Exception as e:
            logger.log_error(f"Помилка нарахування балів: {e}")
            return False

    def get_point_by_id(self, point_id: int) -> Optional[Dict[str, Any]]:
        """
        Отримати один запис балів за id (для редагування).

        Returns:
            Словник з id, guard_id, guard_name, points_delta, reason, created_at, created_by_id, created_by_name або None.
        """
        try:
            with get_session() as session:
                gp = session.query(GuardPoint).filter(GuardPoint.id == point_id).first()
                if not gp:
                    return None
                guard = session.query(User).filter(User.user_id == gp.guard_id).first()
                created_by = session.query(User).filter(User.user_id == gp.created_by_id).first()
                return {
                    "id": gp.id,
                    "guard_id": gp.guard_id,
                    "guard_name": guard.full_name if guard else str(gp.guard_id),
                    "points_delta": gp.points_delta,
                    "reason": gp.reason or "",
                    "created_at": gp.created_at,
                    "created_by_id": gp.created_by_id,
                    "created_by_name": created_by.full_name if created_by else str(gp.created_by_id),
                }
        except Exception as e:
            logger.log_error(f"Помилка отримання запису балів {point_id}: {e}")
            return None

    def update_point(
        self,
        point_id: int,
        points_delta: int,
        reason: Optional[str],
    ) -> bool:
        """Редагувати запис балів (points_delta та/або reason)."""
        if points_delta == 0:
            return False
        try:
            with get_session() as session:
                gp = session.query(GuardPoint).filter(GuardPoint.id == point_id).first()
                if not gp:
                    logger.log_error(f"Запис балів {point_id} не знайдено")
                    return False
                gp.points_delta = points_delta
                if reason is not None:
                    gp.reason = reason.strip()[:REASON_MAX_LENGTH] or None if isinstance(reason, str) else None
                session.commit()
                logger.log_info(f"Оновлено запис балів id={point_id}, delta={points_delta}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка оновлення балів: {e}")
            return False

    def delete_point(self, point_id: int) -> bool:
        """Видалити запис балів (впливає на баланс охоронця)."""
        try:
            with get_session() as session:
                gp = session.query(GuardPoint).filter(GuardPoint.id == point_id).first()
                if not gp:
                    logger.log_error(f"Запис балів {point_id} не знайдено")
                    return False
                session.delete(gp)
                session.commit()
                logger.log_info(f"Видалено запис балів id={point_id}, guard_id={gp.guard_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка видалення балів: {e}")
            return False

    def get_history(
        self,
        guard_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Історія операцій з балами.

        Args:
            guard_id: Якщо задано — тільки для цього охоронця; інакше всі записи.
            limit: Максимальна кількість записів.

        Returns:
            Список словників: id, guard_id, guard_name, points_delta, reason, created_at, created_by_id, created_by_name.
        """
        try:
            with get_session() as session:
                query = (
                    session.query(GuardPoint, User.full_name.label("guard_name"))
                    .join(User, GuardPoint.guard_id == User.user_id)
                    .order_by(GuardPoint.created_at.desc())
                    .limit(limit)
                )
                if guard_id is not None:
                    query = query.filter(GuardPoint.guard_id == guard_id)
                rows = query.all()
                result = []
                for gp, guard_name in rows:
                    created_by = (
                        session.query(User)
                        .filter(User.user_id == gp.created_by_id)
                        .first()
                    )
                    created_by_name = created_by.full_name if created_by else str(gp.created_by_id)
                    result.append({
                        "id": gp.id,
                        "guard_id": gp.guard_id,
                        "guard_name": guard_name or "",
                        "points_delta": gp.points_delta,
                        "reason": gp.reason or "",
                        "created_at": gp.created_at,
                        "created_by_id": gp.created_by_id,
                        "created_by_name": created_by_name,
                    })
                return result
        except Exception as e:
            logger.log_error(f"Помилка отримання історії балів: {e}")
            return []


def get_points_manager() -> PointsManager:
    """Повертає єдиний екземпляр PointsManager."""
    global _points_manager
    if _points_manager is None:
        _points_manager = PointsManager()
    return _points_manager
