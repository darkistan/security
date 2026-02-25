"""
Модуль для управління охоронцями
"""
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

from database import get_session
from models import User, SecurityObject
from logger import logger
from input_validator import input_validator


class GuardManager:
    """Клас для управління охоронцями"""
    
    def __init__(self):
        """Ініціалізація менеджера охоронців"""
        pass
    
    def create_guard(
        self,
        user_id: int,
        username: str,
        full_name: str,
        phone: str,
        object_id: int
    ) -> bool:
        """
        Створення нового охоронця
        
        Args:
            user_id: Telegram ID користувача
            username: Username користувача
            full_name: ПІБ охоронця
            phone: Номер телефону
            object_id: ID об'єкта
            
        Returns:
            True якщо створено успішно
        """
        try:
            # Валідація даних
            name_validation = input_validator.validate_full_name(full_name)
            if not name_validation['valid']:
                logger.log_error(f"Невірне ПІБ: {full_name}")
                return False
            
            phone_validation = input_validator.validate_phone(phone)
            if not phone_validation['valid']:
                logger.log_error(f"Невірний телефон: {phone}")
                return False
            
            # Перевірка існування об'єкта
            with get_session() as session:
                obj = session.query(SecurityObject).filter(
                    SecurityObject.id == object_id,
                    SecurityObject.is_active == True
                ).first()
                if not obj:
                    logger.log_error(f"Об'єкт {object_id} не знайдено або неактивний")
                    return False
                
                # Перевірка чи користувач вже існує
                existing = session.query(User).filter(User.user_id == user_id).first()
                if existing:
                    logger.log_error(f"Користувач {user_id} вже існує")
                    return False
                
                # Створюємо охоронця
                guard = User(
                    user_id=user_id,
                    username=username,
                    full_name=name_validation['cleaned_full_name'],
                    phone=phone_validation['cleaned_phone'],
                    object_id=object_id,
                    role='guard',
                    is_active=True,
                    approved_at=datetime.now()
                )
                session.add(guard)
                session.commit()
                
                logger.log_info(f"Створено охоронця: {full_name} (User ID: {user_id})")
                return True
        except Exception as e:
            logger.log_error(f"Помилка створення охоронця: {e}")
            return False
    
    def update_guard(
        self,
        user_id: int,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
        object_id: Optional[int] = None,
        role: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Оновлення даних охоронця.

        Returns:
            (True, None) при успіху; (False, повідомлення_помилки) при помилці.
        """
        try:
            with get_session() as session:
                guard = session.query(User).filter(User.user_id == user_id).first()
                if not guard:
                    logger.log_error(f"Охоронець {user_id} не знайдено")
                    return (False, "Охоронця не знайдено")
                
                if full_name:
                    name_validation = input_validator.validate_full_name(full_name)
                    if not name_validation['valid']:
                        return (False, name_validation.get('message', 'Невірне ПІБ'))
                    guard.full_name = name_validation['cleaned_full_name']
                
                if phone:
                    phone_validation = input_validator.validate_phone(phone)
                    if not phone_validation['valid']:
                        return (False, phone_validation.get('message', 'Невірний номер телефону'))
                    guard.phone = phone_validation['cleaned_phone']
                
                if object_id:
                    obj = session.query(SecurityObject).filter(
                        SecurityObject.id == object_id,
                        SecurityObject.is_active == True
                    ).first()
                    if not obj:
                        logger.log_error(f"Об'єкт {object_id} не знайдено")
                        return (False, f"Об'єкт не знайдено або неактивний.")
                    guard.object_id = object_id
                
                if role:
                    role_valid = input_validator.validate_role(role)
                    if not role_valid:
                        logger.log_error(f"Невірна роль: {role}")
                        return (False, "Невірна роль.")
                    # Якщо користувач є адміністратором, не дозволяємо змінювати роль
                    if guard.role == 'admin' and role.lower() != 'admin':
                        logger.log_warning(f"Спроба змінити роль адміністратора {user_id} заблокована")
                        return (False, "Роль адміністратора не можна змінити.")
                    guard.role = role.lower()
                    # Якщо роль змінена на admin, автоматично активуємо
                    if role.lower() == 'admin':
                        guard.is_active = True
                
                session.commit()
                logger.log_info(f"Оновлено охоронця {user_id}")
                return (True, None)
        except Exception as e:
            logger.log_error(f"Помилка оновлення охоронця: {e}")
            return (False, "Помилка збереження. Спробуйте пізніше.")
    
    def activate_guard(self, user_id: int) -> bool:
        """
        Активація охоронця
        
        Args:
            user_id: Telegram ID користувача
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                guard = session.query(User).filter(User.user_id == user_id).first()
                if not guard:
                    return False
                
                guard.is_active = True
                session.commit()
                logger.log_info(f"Активовано охоронця {user_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка активації охоронця: {e}")
            return False
    
    def deactivate_guard(self, user_id: int) -> bool:
        """
        Деактивація охоронця
        
        Args:
            user_id: Telegram ID користувача
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                guard = session.query(User).filter(User.user_id == user_id).first()
                if not guard:
                    return False
                
                # Адміністратор не може бути деактивований
                if guard.role == 'admin':
                    logger.log_warning(f"Спроба деактивації адміністратора {user_id} заблокована")
                    return False
                
                guard.is_active = False
                session.commit()
                logger.log_info(f"Деактивовано охоронця {user_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка деактивації охоронця: {e}")
            return False
    
    def get_guard(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Отримання інформації про охоронця
        
        Args:
            user_id: Telegram ID користувача
            
        Returns:
            Словник з даними охоронця або None
        """
        try:
            with get_session() as session:
                guard = session.query(User).filter(User.user_id == user_id).first()
                if not guard:
                    return None
                
                return {
                    'user_id': guard.user_id,
                    'username': guard.username,
                    'full_name': guard.full_name,
                    'phone': guard.phone,
                    'object_id': guard.object_id,
                    'role': guard.role,
                    'is_active': guard.is_active,
                    'approved_at': guard.approved_at.isoformat() if guard.approved_at else None
                }
        except Exception as e:
            logger.log_error(f"Помилка отримання охоронця: {e}")
            return None
    
    def get_active_guards(self, object_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Отримання списку активних охоронців
        
        Args:
            object_id: ID об'єкта для фільтрації (опціонально)
            
        Returns:
            Список активних охоронців
        """
        try:
            with get_session() as session:
                query = session.query(User).filter(User.is_active == True)
                
                if object_id:
                    query = query.filter(User.object_id == object_id)
                
                guards = query.all()
                
                return [
                    {
                        'user_id': guard.user_id,
                        'username': guard.username,
                        'full_name': guard.full_name,
                        'phone': guard.phone,
                        'object_id': guard.object_id,
                        'role': guard.role
                    }
                    for guard in guards
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання активних охоронців: {e}")
            return []
    
    def get_all_guards(self) -> List[Dict[str, Any]]:
        """
        Отримання списку всіх охоронців
        
        Returns:
            Список всіх охоронців
        """
        try:
            with get_session() as session:
                guards = session.query(User).all()
                
                return [
                    {
                        'user_id': guard.user_id,
                        'username': guard.username,
                        'full_name': guard.full_name,
                        'phone': guard.phone,
                        'object_id': guard.object_id,
                        'role': guard.role,
                        'is_active': guard.is_active,
                        'approved_at': guard.approved_at.isoformat() if guard.approved_at else None
                    }
                    for guard in guards
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання охоронців: {e}")
            return []
    
    def is_guard_active(self, user_id: int) -> bool:
        """
        Перевірка чи охоронець активний
        
        Args:
            user_id: Telegram ID користувача
            
        Returns:
            True якщо активний
        """
        try:
            with get_session() as session:
                guard = session.query(User).filter(
                    User.user_id == user_id,
                    User.is_active == True
                ).first()
                return guard is not None
        except Exception as e:
            logger.log_error(f"Помилка перевірки активності охоронця: {e}")
            return False
    
    def get_guard_object_id(self, user_id: int) -> Optional[int]:
        """
        Отримання ID об'єкта охоронця
        
        Args:
            user_id: Telegram ID користувача
            
        Returns:
            ID об'єкта або None
        """
        try:
            with get_session() as session:
                guard = session.query(User).filter(User.user_id == user_id).first()
                return guard.object_id if guard else None
        except Exception as e:
            logger.log_error(f"Помилка отримання об'єкта охоронця: {e}")
            return None


# Глобальний екземпляр менеджера охоронців
_guard_manager: Optional[GuardManager] = None


def get_guard_manager() -> GuardManager:
    """Отримання глобального менеджера охоронців"""
    global _guard_manager
    if _guard_manager is None:
        _guard_manager = GuardManager()
    return _guard_manager
