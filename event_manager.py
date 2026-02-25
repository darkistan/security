"""
Модуль для управління подіями в журналі
"""
from datetime import datetime
from typing import List, Optional, Dict, Any

from database import get_session
from models import Event, Shift
from logger import logger
from input_validator import input_validator


class EventManager:
    """Клас для управління подіями"""
    
    def __init__(self):
        """Ініціалізація менеджера подій"""
        pass
    
    def create_event(
        self,
        shift_id: int,
        event_type: str,
        description: str,
        author_id: int
    ) -> Optional[int]:
        """
        Створення нової події
        
        Args:
            shift_id: ID зміни
            event_type: Тип події (INCIDENT, POWER_OFF, POWER_ON)
            description: Опис події
            author_id: Telegram ID автора
            
        Returns:
            ID створеної події або None при помилці
        """
        try:
            # Валідація типу події
            type_validation = input_validator.validate_event_type(event_type)
            if not type_validation['valid']:
                logger.log_error(f"Невірний тип події: {event_type}")
                return None
            event_type = type_validation['cleaned_event_type']
            # Для вимкнення/відновлення світла порожній опис замінюємо на фіксацію часу
            if event_type in ('POWER_OFF', 'POWER_ON') and (not description or not str(description).strip()):
                description = f"Фіксація часу: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            # Валідація опису
            desc_validation = input_validator.validate_event_description(description)
            if not desc_validation['valid']:
                logger.log_error("Невірний опис події")
                return None
            description = desc_validation['cleaned_description']
            
            with get_session() as session:
                # Перевіряємо чи існує зміна
                shift = session.query(Shift).filter(Shift.id == shift_id).first()
                if not shift:
                    logger.log_error(f"Зміна {shift_id} не знайдена")
                    return None
                
                # Створюємо подію
                event = Event(
                    shift_id=shift_id,
                    object_id=shift.object_id,
                    event_type=event_type,
                    description=description,
                    author_id=author_id
                )
                session.add(event)
                session.flush()
                event_id = event.id
                session.commit()
                
                logger.log_event_created(author_id, event_id, event_type)
                return event_id
        except Exception as e:
            logger.log_error(f"Помилка створення події: {e}")
            return None
    
    def get_event(self, event_id: int) -> Optional[Dict[str, Any]]:
        """
        Отримання інформації про подію
        
        Args:
            event_id: ID події
            
        Returns:
            Словник з даними події або None
        """
        try:
            with get_session() as session:
                event = session.query(Event).filter(Event.id == event_id).first()
                if not event:
                    return None
                
                return {
                    'id': event.id,
                    'shift_id': event.shift_id,
                    'object_id': event.object_id,
                    'event_type': event.event_type,
                    'description': event.description,
                    'author_id': event.author_id,
                    'created_at': event.created_at.isoformat()
                }
        except Exception as e:
            logger.log_error(f"Помилка отримання події: {e}")
            return None
    
    def get_shift_events(self, shift_id: int) -> List[Dict[str, Any]]:
        """
        Отримання подій зміни
        
        Args:
            shift_id: ID зміни
            
        Returns:
            Список подій
        """
        try:
            with get_session() as session:
                events = session.query(Event).filter(
                    Event.shift_id == shift_id
                ).order_by(Event.created_at.asc()).all()
                
                return [
                    {
                        'id': event.id,
                        'shift_id': event.shift_id,
                        'object_id': event.object_id,
                        'event_type': event.event_type,
                        'description': event.description,
                        'author_id': event.author_id,
                        'created_at': event.created_at.isoformat()
                    }
                    for event in events
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання подій зміни: {e}")
            return []
    
    def get_events(
        self,
        object_id: Optional[int] = None,
        event_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Отримання списку подій з фільтрами
        
        Args:
            object_id: ID об'єкта для фільтрації
            event_type: Тип події для фільтрації
            start_date: Початкова дата
            end_date: Кінцева дата
            limit: Максимальна кількість записів
            
        Returns:
            Список подій
        """
        try:
            with get_session() as session:
                query = session.query(Event)
                
                if object_id:
                    query = query.filter(Event.object_id == object_id)
                
                if event_type:
                    query = query.filter(Event.event_type == event_type)
                
                if start_date:
                    query = query.filter(Event.created_at >= start_date)
                
                if end_date:
                    query = query.filter(Event.created_at <= end_date)
                
                query = query.order_by(Event.created_at.desc())
                
                if limit:
                    query = query.limit(limit)
                
                events = query.all()
                
                return [
                    {
                        'id': event.id,
                        'shift_id': event.shift_id,
                        'object_id': event.object_id,
                        'event_type': event.event_type,
                        'description': event.description,
                        'author_id': event.author_id,
                        'created_at': event.created_at.isoformat()
                    }
                    for event in events
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання подій: {e}")
            return []
    
    def update_event(
        self,
        event_id: int,
        event_type: Optional[str] = None,
        description: Optional[str] = None
    ) -> bool:
        """
        Редагування події
        
        Args:
            event_id: ID події
            event_type: Новий тип події
            description: Новий опис події
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                event = session.query(Event).filter(Event.id == event_id).first()
                if not event:
                    logger.log_error(f"Подія {event_id} не знайдена")
                    return False
                
                if event_type is not None:
                    type_validation = input_validator.validate_event_type(event_type)
                    if not type_validation['valid']:
                        logger.log_error(f"Невірний тип події: {event_type}")
                        return False
                    event.event_type = type_validation['cleaned_event_type']
                
                if description is not None:
                    desc_validation = input_validator.validate_event_description(description)
                    if not desc_validation['valid']:
                        logger.log_error(f"Невірний опис події")
                        return False
                    event.description = desc_validation['cleaned_description']
                
                session.commit()
                logger.log_info(f"Оновлено подію {event_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка оновлення події: {e}")
            return False
    
    def delete_event(self, event_id: int) -> bool:
        """
        Видалення події
        
        Args:
            event_id: ID події
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                event = session.query(Event).filter(Event.id == event_id).first()
                if not event:
                    logger.log_error(f"Подія {event_id} не знайдена")
                    return False
                
                session.delete(event)
                session.commit()
                logger.log_info(f"Видалено подію {event_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка видалення події: {e}")
            return False


# Глобальний екземпляр менеджера подій
_event_manager: Optional[EventManager] = None


def get_event_manager() -> EventManager:
    """Отримання глобального менеджера подій"""
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager()
    return _event_manager
