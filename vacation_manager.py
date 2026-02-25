"""
Менеджер графіка відпусток охоронців: дні відпустки (охоронець + дата) на календарний місяць.
"""
import calendar
from datetime import date
from typing import Set, Tuple, List, Dict, Any, Optional

from database import get_session
from models import VacationSlot, User
from logger import logger

_vacation_manager: Optional["VacationManager"] = None


class VacationManager:
    """Управління днями відпустки (графік відпусток)."""

    def __init__(self) -> None:
        pass

    def get_slots_for_month(
        self, year: int, month: int, object_id: Optional[int] = None
    ) -> Set[Tuple[int, int]]:
        """Множина пар (guard_id, day) для заданого місяця. day — число дня (1–31)."""
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

                query = session.query(VacationSlot.guard_id, VacationSlot.vacation_date).filter(
                    VacationSlot.vacation_date >= first_day,
                    VacationSlot.vacation_date <= last_day,
                )
                rows = query.all()
                result = set()
                for guard_id, vacation_date in rows:
                    if guard_ids_filter is not None and guard_id not in guard_ids_filter:
                        continue
                    result.add((guard_id, vacation_date.day))
                return result
        except Exception as e:
            logger.log_error(f"Помилка get_slots_for_month (відпустки): {e}")
            return set()

    def set_slot(self, guard_id: int, vacation_date: date) -> bool:
        """Додати день відпустки (ігнорувати якщо вже є)."""
        try:
            with get_session() as session:
                existing = session.query(VacationSlot).filter(
                    VacationSlot.guard_id == guard_id,
                    VacationSlot.vacation_date == vacation_date,
                ).first()
                if existing:
                    return True
                session.add(VacationSlot(guard_id=guard_id, vacation_date=vacation_date))
                session.commit()
                return True
        except Exception as e:
            logger.log_error(f"Помилка set_slot (відпустки): {e}")
            return False

    def remove_slot(self, guard_id: int, vacation_date: date) -> bool:
        """Видалити день відпустки."""
        try:
            with get_session() as session:
                session.query(VacationSlot).filter(
                    VacationSlot.guard_id == guard_id,
                    VacationSlot.vacation_date == vacation_date,
                ).delete()
                session.commit()
                return True
        except Exception as e:
            logger.log_error(f"Помилка remove_slot (відпустки): {e}")
            return False

    def toggle_slot(self, guard_id: int, vacation_date: date) -> Optional[bool]:
        """Якщо день відпустки є — видалити; інакше — додати. Повертає новий стан (True/False) або None."""
        try:
            with get_session() as session:
                existing = session.query(VacationSlot).filter(
                    VacationSlot.guard_id == guard_id,
                    VacationSlot.vacation_date == vacation_date,
                ).first()
                if existing:
                    session.delete(existing)
                    session.commit()
                    return False
                session.add(VacationSlot(guard_id=guard_id, vacation_date=vacation_date))
                session.commit()
                return True
        except Exception as e:
            logger.log_error(f"Помилка toggle_slot (відпустки): {e}")
            return None

    def get_guards_for_schedule(self, object_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Список охоронців для сітки (всі або по object_id), відсортовані по ПІБ."""
        try:
            with get_session() as session:
                query = session.query(User).filter(User.is_active == True)
                if object_id is not None:
                    query = query.filter(User.object_id == object_id)
                users = query.order_by(User.full_name).all()
                return [
                    {"user_id": u.user_id, "full_name": u.full_name, "object_id": u.object_id}
                    for u in users
                ]
        except Exception as e:
            logger.log_error(f"Помилка get_guards_for_schedule (відпустки): {e}")
            return []


def get_vacation_manager() -> VacationManager:
    """Синглтон менеджера графіка відпусток."""
    global _vacation_manager
    if _vacation_manager is None:
        _vacation_manager = VacationManager()
    return _vacation_manager
