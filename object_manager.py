"""
Модуль для управління об'єктами охорони
"""
from typing import List, Optional, Dict, Any

from database import get_session
from models import SecurityObject
from logger import logger


class ObjectManager:
    """Клас для управління об'єктами"""
    
    def __init__(self):
        """Ініціалізація менеджера об'єктів"""
        pass
    
    def get_object(self, object_id: int) -> Optional[Dict[str, Any]]:
        """
        Отримання інформації про об'єкт
        
        Args:
            object_id: ID об'єкта
            
        Returns:
            Словник з даними об'єкта або None
        """
        try:
            with get_session() as session:
                obj = session.query(SecurityObject).filter(SecurityObject.id == object_id).first()
                if not obj:
                    return None
                
                return {
                    'id': obj.id,
                    'name': obj.name,
                    'is_active': obj.is_active,
                    'protection_type': getattr(obj, 'protection_type', 'SHIFT'),
                    'created_at': obj.created_at.isoformat() if obj.created_at else None
                }
        except Exception as e:
            logger.log_error(f"Помилка отримання об'єкта: {e}")
            return None
    
    def get_all_objects(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """
        Отримання списку всіх об'єктів
        
        Args:
            active_only: Чи повертати тільки активні об'єкти
            
        Returns:
            Список об'єктів
        """
        try:
            with get_session() as session:
                query = session.query(SecurityObject)
                
                if active_only:
                    query = query.filter(SecurityObject.is_active == True)
                
                objects = query.order_by(SecurityObject.id).all()
                
                return [
                    {
                        'id': obj.id,
                        'name': obj.name,
                        'is_active': obj.is_active,
                        'protection_type': getattr(obj, 'protection_type', 'SHIFT'),
                        'created_at': obj.created_at.isoformat() if obj.created_at else None
                    }
                    for obj in objects
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання об'єктів: {e}")
            return []
    
    def update_object(
        self, object_id: int, name: Optional[str] = None, protection_type: Optional[str] = None
    ) -> bool:
        """
        Оновлення об'єкта (назва та/або тип охорони).
        Args:
            object_id: ID об'єкта
            name: Нова назва (опційно)
            protection_type: SHIFT або TEMPORARY_SINGLE (опційно)
        Returns:
            True якщо оновлено успішно
        """
        try:
            with get_session() as session:
                obj = session.query(SecurityObject).filter(SecurityObject.id == object_id).first()
                if not obj:
                    logger.log_error(f"Об'єкт {object_id} не знайдено")
                    return False
                if name is not None:
                    if not name.strip():
                        logger.log_error("Назва об'єкта не може бути порожньою")
                        return False
                    obj.name = name.strip()
                if protection_type is not None:
                    if protection_type not in ('SHIFT', 'TEMPORARY_SINGLE'):
                        logger.log_error(f"Невірний protection_type: {protection_type}")
                        return False
                    obj.protection_type = protection_type
                session.commit()
                logger.log_info(f"Оновлено об'єкт {object_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка оновлення об'єкта: {e}")
            return False

    def update_object_name(self, object_id: int, name: str) -> bool:
        """Оновлення лише назви об'єкта (зворотна сумісність)."""
        return self.update_object(object_id, name=name)
    
    def object_exists(self, object_id: int) -> bool:
        """
        Перевірка існування об'єкта
        
        Args:
            object_id: ID об'єкта
            
        Returns:
            True якщо об'єкт існує та активний
        """
        try:
            with get_session() as session:
                obj = session.query(SecurityObject).filter(
                    SecurityObject.id == object_id,
                    SecurityObject.is_active == True
                ).first()
                return obj is not None
        except Exception as e:
            logger.log_error(f"Помилка перевірки існування об'єкта: {e}")
            return False
    
    def delete_object(self, object_id: int) -> bool:
        """
        Видалення об'єкта
        
        Args:
            object_id: ID об'єкта
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                from models import User, Shift
                
                obj = session.query(SecurityObject).filter(SecurityObject.id == object_id).first()
                if not obj:
                    logger.log_error(f"Об'єкт {object_id} не знайдено")
                    return False
                
                # Перевіряємо чи є користувачі на цьому об'єкті
                users_count = session.query(User).filter(User.object_id == object_id).count()
                if users_count > 0:
                    logger.log_error(f"Неможливо видалити об'єкт {object_id}: є користувачі на цьому об'єкті")
                    return False
                
                # Перевіряємо чи є активні зміни на цьому об'єкті
                active_shifts = session.query(Shift).filter(
                    Shift.object_id == object_id,
                    Shift.status == 'ACTIVE'
                ).count()
                if active_shifts > 0:
                    logger.log_error(f"Неможливо видалити об'єкт {object_id}: є активні зміни на цьому об'єкті")
                    return False
                
                session.delete(obj)
                session.commit()
                logger.log_info(f"Видалено об'єкт {object_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка видалення об'єкта: {e}")
            return False


# Глобальний екземпляр менеджера об'єктів
_object_manager: Optional[ObjectManager] = None


def get_object_manager() -> ObjectManager:
    """Отримання глобального менеджера об'єктів"""
    global _object_manager
    if _object_manager is None:
        _object_manager = ObjectManager()
    return _object_manager
