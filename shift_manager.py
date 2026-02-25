"""
Модуль для управління змінами охоронців
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from database import get_session
from models import Shift, User, Event
from logger import logger
from guard_manager import get_guard_manager


class ShiftManager:
    """Клас для управління змінами"""
    
    def __init__(self):
        """Ініціалізація менеджера змін"""
        pass
    
    def create_shift(self, guard_id: int) -> Optional[int]:
        """
        Створення нової зміни
        
        Args:
            guard_id: Telegram ID охоронця
            
        Returns:
            ID створеної зміни або None при помилці
        """
        try:
            guard_manager = get_guard_manager()
            
            # Перевіряємо чи охоронець активний
            if not guard_manager.is_guard_active(guard_id):
                logger.log_error(f"Охоронець {guard_id} не активний")
                return None
            
            # Отримуємо об'єкт охоронця
            object_id = guard_manager.get_guard_object_id(guard_id)
            if not object_id:
                logger.log_error(f"У охоронця {guard_id} не встановлено об'єкт")
                return None
            
            # Перевіряємо чи немає активної зміни
            active_shift = self.get_active_shift(guard_id)
            if active_shift:
                logger.log_error(f"У охоронця {guard_id} вже є активна зміна")
                return None
            
            # Перевіряємо чи немає PENDING передачі на цьому об'єкті
            from handover_manager import get_handover_manager
            handover_manager = get_handover_manager()
            if handover_manager.has_pending_handover_on_object(guard_id, object_id):
                logger.log_error(f"У охоронця {guard_id} є PENDING передача на об'єкті {object_id}")
                return None
            
            # На об'єкті вже є активна зміна (іншого охоронця) — не дозволяємо відкрити другу без передачі
            active_on_object = self.get_active_shift_for_object(object_id)
            if active_on_object:
                logger.log_error(f"На об'єкті {object_id} вже є активна зміна #{active_on_object.get('id')} (охоронець {active_on_object.get('guard_id')})")
                return None
            
            with get_session() as session:
                shift = Shift(
                    guard_id=guard_id,
                    object_id=object_id,
                    start_time=datetime.now(),
                    status='ACTIVE'
                )
                session.add(shift)
                session.flush()
                shift_id = shift.id
                session.commit()
                
                logger.log_shift_created(guard_id, shift_id, object_id)
                return shift_id
        except Exception as e:
            logger.log_error(f"Помилка створення зміни: {e}")
            return None
    
    def complete_shift(self, shift_id: int) -> bool:
        """
        Завершення зміни
        
        Args:
            shift_id: ID зміни
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                shift = session.query(Shift).filter(Shift.id == shift_id).first()
                if not shift:
                    logger.log_error(f"Зміна {shift_id} не знайдена")
                    return False
                
                if shift.status != 'ACTIVE':
                    logger.log_error(f"Зміна {shift_id} не є активною")
                    return False
                
                shift.end_time = datetime.now()
                shift.status = 'COMPLETED'
                session.commit()
                
                logger.log_info(f"Завершено зміну {shift_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка завершення зміни: {e}")
            return False
    
    def mark_shift_handed_over(self, shift_id: int) -> bool:
        """
        Позначення зміни як переданої
        
        Args:
            shift_id: ID зміни
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                shift = session.query(Shift).filter(Shift.id == shift_id).first()
                if not shift:
                    return False
                
                shift.status = 'HANDED_OVER'
                if not shift.end_time:
                    shift.end_time = datetime.now()
                session.commit()
                
                logger.log_info(f"Зміна {shift_id} позначена як передана")
                return True
        except Exception as e:
            logger.log_error(f"Помилка позначення зміни як переданої: {e}")
            return False
    
    def get_active_shift(self, guard_id: int) -> Optional[Dict[str, Any]]:
        """
        Отримання активної зміни охоронця
        
        Args:
            guard_id: Telegram ID охоронця
            
        Returns:
            Словник з даними зміни або None
        """
        try:
            with get_session() as session:
                shift = session.query(Shift).filter(
                    Shift.guard_id == guard_id,
                    Shift.status == 'ACTIVE'
                ).first()
                
                if not shift:
                    return None
                
                return {
                    'id': shift.id,
                    'guard_id': shift.guard_id,
                    'object_id': shift.object_id,
                    'start_time': shift.start_time.isoformat(),
                    'status': shift.status
                }
        except Exception as e:
            logger.log_error(f"Помилка отримання активної зміни: {e}")
            return None
    
    def get_active_shift_for_object(self, object_id: int) -> Optional[Dict[str, Any]]:
        """
        Отримання активної зміни на об'єкті (будь-який охоронець).
        Використовується для перевірки: на об'єкті лише одна активна зміна.
        """
        try:
            with get_session() as session:
                shift = session.query(Shift).filter(
                    Shift.object_id == object_id,
                    Shift.status == 'ACTIVE'
                ).first()
                if not shift:
                    return None
                return {
                    'id': shift.id,
                    'guard_id': shift.guard_id,
                    'object_id': shift.object_id,
                    'start_time': shift.start_time.isoformat(),
                    'status': shift.status
                }
        except Exception as e:
            logger.log_error(f"Помилка отримання активної зміни на об'єкті: {e}")
            return None
    
    def get_shift(self, shift_id: int) -> Optional[Dict[str, Any]]:
        """
        Отримання інформації про зміну
        
        Args:
            shift_id: ID зміни
            
        Returns:
            Словник з даними зміни або None
        """
        try:
            with get_session() as session:
                shift = session.query(Shift).filter(Shift.id == shift_id).first()
                if not shift:
                    return None
                
                return {
                    'id': shift.id,
                    'guard_id': shift.guard_id,
                    'object_id': shift.object_id,
                    'start_time': shift.start_time.isoformat(),
                    'end_time': shift.end_time.isoformat() if shift.end_time else None,
                    'status': shift.status,
                    'created_at': shift.created_at.isoformat() if shift.created_at else None
                }
        except Exception as e:
            logger.log_error(f"Помилка отримання зміни: {e}")
            return None
    
    def get_shifts(
        self,
        guard_id: Optional[int] = None,
        object_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Отримання списку змін з фільтрами
        
        Args:
            guard_id: ID охоронця для фільтрації
            object_id: ID об'єкта для фільтрації
            start_date: Початкова дата
            end_date: Кінцева дата
            limit: Максимальна кількість записів
            
        Returns:
            Список змін
        """
        try:
            with get_session() as session:
                query = session.query(Shift)
                
                if guard_id:
                    query = query.filter(Shift.guard_id == guard_id)
                
                if object_id:
                    query = query.filter(Shift.object_id == object_id)
                
                if start_date:
                    query = query.filter(Shift.start_time >= start_date)
                
                if end_date:
                    query = query.filter(Shift.start_time <= end_date)
                
                query = query.order_by(Shift.start_time.desc())
                
                if limit:
                    query = query.limit(limit)
                
                shifts = query.all()
                
                return [
                    {
                        'id': shift.id,
                        'guard_id': shift.guard_id,
                        'object_id': shift.object_id,
                        'start_time': shift.start_time.isoformat(),
                        'end_time': shift.end_time.isoformat() if shift.end_time else None,
                        'status': shift.status
                    }
                    for shift in shifts
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання змін: {e}")
            return []
    
    def generate_shift_summary(self, shift_id: int) -> str:
        """
        Формування зведення подій зміни для передачі
        
        Args:
            shift_id: ID зміни
            
        Returns:
            Текст зведення
        """
        try:
            from event_manager import get_event_manager
            
            event_manager = get_event_manager()
            events = event_manager.get_shift_events(shift_id)
            
            with get_session() as session:
                shift = session.query(Shift).filter(Shift.id == shift_id).first()
                if not shift:
                    return "Зміна не знайдена"
                
                guard = session.query(User).filter(User.user_id == shift.guard_id).first()
                guard_name = guard.full_name if guard else f"ID: {shift.guard_id}"
                
                summary_lines = [
                    f"📋 Зведення зміни #{shift_id}",
                    f"👤 Охоронець: {guard_name}",
                    f"🕐 Початок: {shift.start_time.strftime('%d.%m.%Y %H:%M')}",
                    f"📊 Всього подій: {len(events)}",
                    ""
                ]
                
                if events:
                    summary_lines.append("📝 Події:")
                    event_types_ua = {
                        'INCIDENT': 'Інцидент',
                        'VISITOR': 'Відвідувач',
                        'DELIVERY': 'Доставка',
                        'ALARM': 'Тривога'
                    }
                    
                    for event in events:
                        event_type_ua = event_types_ua.get(event['event_type'], event['event_type'])
                        time_str = datetime.fromisoformat(event['created_at']).strftime('%H:%M')
                        summary_lines.append(f"  • {time_str} - {event_type_ua}: {event['description'][:100]}")
                else:
                    summary_lines.append("📝 Подій немає")
                
                return "\n".join(summary_lines)
        except Exception as e:
            logger.log_error(f"Помилка формування зведення: {e}")
            return f"Помилка формування зведення: {e}"
    
    def update_shift(
        self,
        shift_id: int,
        guard_id: Optional[int] = None,
        object_id: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        status: Optional[str] = None
    ) -> bool:
        """
        Редагування зміни
        
        Args:
            shift_id: ID зміни
            guard_id: Новий ID охоронця
            object_id: Новий ID об'єкта
            start_time: Новий час початку
            end_time: Новий час завершення
            status: Новий статус
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                shift = session.query(Shift).filter(Shift.id == shift_id).first()
                if not shift:
                    logger.log_error(f"Зміна {shift_id} не знайдена")
                    return False
                
                if guard_id is not None:
                    shift.guard_id = guard_id
                if object_id is not None:
                    shift.object_id = object_id
                if start_time is not None:
                    shift.start_time = start_time
                if end_time is not None:
                    shift.end_time = end_time
                if status is not None:
                    shift.status = status
                
                session.commit()
                logger.log_info(f"Оновлено зміну {shift_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка оновлення зміни: {e}")
            return False
    
    def delete_shift(self, shift_id: int) -> bool:
        """
        Видалення зміни
        
        Args:
            shift_id: ID зміни
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                shift = session.query(Shift).filter(Shift.id == shift_id).first()
                if not shift:
                    logger.log_error(f"Зміна {shift_id} не знайдена")
                    return False
                
                # Видаляємо зміну (події та передачі видаляться каскадно через foreign key)
                session.delete(shift)
                session.commit()
                logger.log_info(f"Видалено зміну {shift_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка видалення зміни: {e}")
            return False


# Глобальний екземпляр менеджера змін
_shift_manager: Optional[ShiftManager] = None


def get_shift_manager() -> ShiftManager:
    """Отримання глобального менеджера змін"""
    global _shift_manager
    if _shift_manager is None:
        _shift_manager = ShiftManager()
    return _shift_manager
