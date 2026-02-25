"""
Менеджер графіка змін охоронців: заплановані слоти (охоронець + дата) на календарний місяць.
"""
import calendar
from datetime import date, datetime
from typing import Set, Tuple, List, Dict, Any, Optional

from database import get_session
from models import ScheduleSlot, User
from logger import logger

_schedule_manager: Optional["ScheduleManager"] = None


class ScheduleManager:
    """Управління запланованими слотами змін (графік)."""

    def __init__(self) -> None:
        pass

    def get_slots_for_month(
        self, year: int, month: int, object_id: Optional[int] = None
    ) -> Set[Tuple[int, int]]:
        """
        Повертає множину пар (guard_id, day) для заданого місяця.
        day — число дня в місяці (1–31). Якщо object_id задано — тільки охоронці цього об'єкта.
        """
        try:
            first_day = date(year, month, 1)
            _, last_day_num = calendar.monthrange(year, month)
            last_day = date(year, month, last_day_num)

            with get_session() as session:
                guard_ids_filter = None
                if object_id is not None:
                    guard_ids_filter = {
                        u.user_id for u in session.query(User.user_id).filter(
                            User.object_id == object_id,
                            User.is_active == True,
                        ).all()
                    }
                    if not guard_ids_filter:
                        return set()

                query = session.query(ScheduleSlot.guard_id, ScheduleSlot.slot_date).filter(
                    ScheduleSlot.slot_date >= first_day,
                    ScheduleSlot.slot_date <= last_day,
                )
                rows = query.all()
                result = set()
                for guard_id, slot_date in rows:
                    if guard_ids_filter is not None and guard_id not in guard_ids_filter:
                        continue
                    result.add((guard_id, slot_date.day))
                return result
        except Exception as e:
            logger.log_error(f"Помилка get_slots_for_month: {e}")
            return set()

    def set_slot(self, guard_id: int, slot_date: date) -> bool:
        """Додати слот (ігнорувати якщо вже є)."""
        try:
            with get_session() as session:
                existing = session.query(ScheduleSlot).filter(
                    ScheduleSlot.guard_id == guard_id,
                    ScheduleSlot.slot_date == slot_date,
                ).first()
                if existing:
                    return True
                session.add(ScheduleSlot(guard_id=guard_id, slot_date=slot_date))
                session.commit()
                return True
        except Exception as e:
            logger.log_error(f"Помилка set_slot: {e}")
            return False

    def remove_slot(self, guard_id: int, slot_date: date) -> bool:
        """Видалити слот."""
        try:
            with get_session() as session:
                session.query(ScheduleSlot).filter(
                    ScheduleSlot.guard_id == guard_id,
                    ScheduleSlot.slot_date == slot_date,
                ).delete()
                session.commit()
                return True
        except Exception as e:
            logger.log_error(f"Помилка remove_slot: {e}")
            return False

    def toggle_slot(self, guard_id: int, slot_date: date) -> Optional[bool]:
        """
        Якщо слот є — видалити; інакше — додати.
        Повертає новий стан: True якщо після дії слот є, False якщо немає; None при помилці.
        """
        try:
            with get_session() as session:
                existing = session.query(ScheduleSlot).filter(
                    ScheduleSlot.guard_id == guard_id,
                    ScheduleSlot.slot_date == slot_date,
                ).first()
                if existing:
                    session.delete(existing)
                    session.commit()
                    return False
                session.add(ScheduleSlot(guard_id=guard_id, slot_date=slot_date))
                session.commit()
                return True
        except Exception as e:
            logger.log_error(f"Помилка toggle_slot: {e}")
            return None

    def get_guards_for_schedule(
        self, object_id: Optional[int] = None, exclude_admin: bool = False
    ) -> List[Dict[str, Any]]:
        """Список охоронців для сітки (всі або по object_id). Контролери не включаються. exclude_admin — не включати admin."""
        try:
            with get_session() as session:
                query = session.query(User).filter(
                    User.is_active == True,
                    User.role.in_(['guard', 'senior', 'admin']),
                )
                if object_id is not None:
                    query = query.filter(User.object_id == object_id)
                if exclude_admin:
                    query = query.filter(User.role != 'admin')
                users = query.order_by(User.full_name).all()
                return [
                    {"user_id": u.user_id, "full_name": u.full_name, "object_id": u.object_id}
                    for u in users
                ]
        except Exception as e:
            logger.log_error(f"Помилка get_guards_for_schedule: {e}")
            return []


def get_schedule_manager() -> ScheduleManager:
    """Синглтон менеджера графіка."""
    global _schedule_manager
    if _schedule_manager is None:
        _schedule_manager = ScheduleManager()
    return _schedule_manager
