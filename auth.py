"""
Модуль авторизації для системи ведення змін охоронців
"""
from datetime import datetime
from typing import List, Optional, Dict, Any

from database import get_session
from models import User, SecurityObject, PendingRequest
from logger import logger


class AuthManager:
    """Клас для управління авторизацією користувачів через БД"""
    
    def __init__(self):
        """Ініціалізація менеджера авторизації"""
        pass
    
    def is_user_allowed(self, user_id: int) -> bool:
        """
        Перевірка чи дозволений користувач
        
        Args:
            user_id: ID користувача
            
        Returns:
            True якщо користувач дозволений та активний
        """
        try:
            with get_session() as session:
                user = session.query(User).filter(
                    User.user_id == user_id,
                    User.is_active == True
                ).first()
                return user is not None
        except Exception as e:
            logger.log_error(f"Помилка перевірки доступу користувача {user_id}: {e}")
            return False
    
    def is_admin(self, user_id: int) -> bool:
        """
        Перевірка чи користувач є адміністратором
        
        Args:
            user_id: ID користувача
            
        Returns:
            True якщо адміністратор
        """
        try:
            with get_session() as session:
                user = session.query(User).filter(User.user_id == user_id).first()
                return user.role == 'admin' if user else False
        except Exception as e:
            logger.log_error(f"Помилка перевірки ролі користувача {user_id}: {e}")
            return False
    
    def is_senior(self, user_id: int) -> bool:
        """
        Перевірка чи користувач є старшим
        
        Args:
            user_id: ID користувача
            
        Returns:
            True якщо старший або адміністратор
        """
        try:
            with get_session() as session:
                user = session.query(User).filter(User.user_id == user_id).first()
                if not user:
                    return False
                return user.role in ['senior', 'admin']
        except Exception as e:
            logger.log_error(f"Помилка перевірки ролі користувача {user_id}: {e}")
            return False
    
    def get_user_role(self, user_id: int) -> Optional[str]:
        """
        Отримання ролі користувача
        
        Args:
            user_id: ID користувача
            
        Returns:
            Роль користувача або None
        """
        try:
            with get_session() as session:
                user = session.query(User).filter(User.user_id == user_id).first()
                return user.role if user else None
        except Exception as e:
            logger.log_error(f"Помилка отримання ролі користувача {user_id}: {e}")
            return None
    
    def get_user_object_id(self, user_id: int) -> Optional[int]:
        """
        Отримання ID об'єкта користувача
        
        Args:
            user_id: ID користувача
            
        Returns:
            ID об'єкта або None
        """
        try:
            with get_session() as session:
                user = session.query(User).filter(User.user_id == user_id).first()
                return user.object_id if user else None
        except Exception as e:
            logger.log_error(f"Помилка отримання об'єкта користувача {user_id}: {e}")
            return None
    
    def get_user_full_name(self, user_id: int) -> Optional[str]:
        """
        Отримання ПІБ користувача
        
        Args:
            user_id: ID користувача
            
        Returns:
            ПІБ або None
        """
        try:
            with get_session() as session:
                user = session.query(User).filter(User.user_id == user_id).first()
                return user.full_name if user else None
        except Exception as e:
            logger.log_error(f"Помилка отримання ПІБ користувача {user_id}: {e}")
            return None
    
    def can_view_all_shifts(self, user_id: int) -> bool:
        """
        Перевірка чи користувач може переглядати всі зміни
        
        Args:
            user_id: ID користувача
            
        Returns:
            True якщо старший або адміністратор
        """
        return self.is_senior(user_id)
    
    def can_manage_guards(self, user_id: int) -> bool:
        """
        Перевірка чи користувач може управляти охоронцями
        
        Args:
            user_id: ID користувача
            
        Returns:
            True якщо адміністратор
        """
        return self.is_admin(user_id)
    
    def add_user_request(self, user_id: int, username: str) -> bool:
        """
        Додавання запиту на доступ
        
        Args:
            user_id: ID користувача
            username: Ім'я користувача
            
        Returns:
            True якщо запит додано
        """
        try:
            with get_session() as session:
                # Перевіряємо чи вже є запит
                existing = session.query(PendingRequest).filter(
                    PendingRequest.user_id == user_id
                ).first()
                
                if existing:
                    return False
                
                # Додаємо новий запит
                request = PendingRequest(
                    user_id=user_id,
                    username=username,
                    timestamp=datetime.now()
                )
                session.add(request)
                session.commit()
                
                logger.log_info(f"Додано запит на доступ від користувача {user_id} (@{username})")
                return True
                
        except Exception as e:
            logger.log_error(f"Помилка додавання запиту для {user_id}: {e}")
            return False
    
    def approve_user(
        self,
        user_id: int,
        username: str,
        object_id: Optional[int] = None,
        role: str = 'guard',
        full_name: Optional[str] = None,
        phone: Optional[str] = None
    ) -> bool:
        """
        Схвалення користувача
        
        Args:
            user_id: ID користувача
            username: Ім'я користувача
            object_id: ID об'єкта (опціонально)
            role: Роль користувача (за замовчуванням 'guard')
            full_name: ПІБ користувача (опціонально)
            phone: Телефон користувача (опціонально)
            
        Returns:
            True якщо користувач був схвалений
        """
        try:
            with get_session() as session:
                # Видаляємо з pending_requests
                session.query(PendingRequest).filter(
                    PendingRequest.user_id == user_id
                ).delete()
                
                # Перевіряємо чи вже існує
                existing = session.query(User).filter(User.user_id == user_id).first()
                if existing:
                    return False
                
                # Отримуємо перший об'єкт, якщо object_id не вказано
                if not object_id:
                    first_object = session.query(SecurityObject).filter(
                        SecurityObject.is_active == True
                    ).first()
                    if not first_object:
                        logger.log_error("Немає активних об'єктів для призначення користувачу")
                        return False
                    object_id = first_object.id
                
                # Перевіряємо чи об'єкт існує та активний
                obj = session.query(SecurityObject).filter(
                    SecurityObject.id == object_id,
                    SecurityObject.is_active == True
                ).first()
                if not obj:
                    logger.log_error(f"Об'єкт {object_id} не знайдено або неактивний")
                    return False
                
                # Встановлюємо значення за замовчуванням для обов'язкових полів
                if not phone:
                    phone = "0000000000"
                if not full_name:
                    full_name = username or f"Користувач {user_id}"
                
                # Додаємо до дозволених
                user = User(
                    user_id=user_id,
                    username=username,
                    approved_at=datetime.now(),
                    notifications_enabled=False,
                    role=role,
                    full_name=full_name,
                    phone=phone,
                    object_id=object_id,
                    is_active=True
                )
                session.add(user)
                session.commit()
                
                logger.log_info(f"Схвалено користувача {user_id} (@{username})")
                return True
                
        except Exception as e:
            logger.log_error(f"Помилка схвалення користувача {user_id}: {e}")
            return False
    
    def deny_user(self, user_id: int, username: str) -> bool:
        """
        Відхилення користувача
        
        Args:
            user_id: ID користувача
            username: Ім'я користувача
            
        Returns:
            True якщо запит був відхилений
        """
        try:
            with get_session() as session:
                deleted = session.query(PendingRequest).filter(
                    PendingRequest.user_id == user_id
                ).delete()
                session.commit()
                
                if deleted > 0:
                    logger.log_info(f"Відхилено запит на доступ від користувача {user_id} (@{username})")
                    return True
                return False
                
        except Exception as e:
            logger.log_error(f"Помилка відхилення користувача {user_id}: {e}")
            return False
    
    def get_pending_requests(self) -> List[Dict[str, Any]]:
        """
        Отримання списку очікуючих запитів
        
        Returns:
            Список запитів
        """
        try:
            with get_session() as session:
                requests = session.query(PendingRequest).all()
                return [
                    {
                        'user_id': req.user_id,
                        'username': req.username,
                        'timestamp': req.timestamp  # Повертаємо datetime об'єкт для використання в шаблонах
                    }
                    for req in requests
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання запитів: {e}")
            return []


# Глобальний екземпляр менеджера авторизації
auth_manager = AuthManager()
