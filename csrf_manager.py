"""
Модуль для управління CSRF токенами
"""
import secrets
from typing import Dict, Optional
from datetime import datetime, timedelta

from logger import logger


class CSRFManager:
    """Клас для управління CSRF токенами"""
    
    def __init__(self):
        """Ініціалізація CSRF менеджера"""
        # Зберігаємо токени користувачів
        self.user_tokens: Dict[int, str] = {}
        self.token_expiry: Dict[int, datetime] = {}
        
        # Налаштування
        self.token_length = 8  # Довжина токена (мінімальна для Telegram)
        self.token_lifetime = 3600  # Час життя токена (секунди)
    
    def generate_token(self, user_id: int) -> str:
        """
        Генерація нового CSRF токена для користувача
        
        Args:
            user_id: ID користувача
            
        Returns:
            Згенерований токен
        """
        # Генеруємо безпечний токен
        token = secrets.token_urlsafe(self.token_length)
        
        # Зберігаємо токен та час закінчення
        self.user_tokens[user_id] = token
        self.token_expiry[user_id] = datetime.now() + timedelta(seconds=self.token_lifetime)
        
        logger.log_info(f"Згенеровано CSRF токен для користувача {user_id}")
        return token
    
    def validate_token(self, user_id: int, token: str) -> bool:
        """
        Валідація CSRF токена
        
        Args:
            user_id: ID користувача
            token: Токен для перевірки
            
        Returns:
            True якщо токен валідний
        """
        # Перевіряємо чи є токен для користувача
        if user_id not in self.user_tokens:
            logger.log_error(f"CSRF токен не знайдено для користувача {user_id}")
            return False
        
        # Перевіряємо чи не прострочений токен
        if datetime.now() > self.token_expiry[user_id]:
            logger.log_error(f"CSRF токен прострочений для користувача {user_id}")
            self._cleanup_user_token(user_id)
            return False
        
        # Перевіряємо чи токен співпадає
        if self.user_tokens[user_id] != token:
            logger.log_error(f"Невірний CSRF токен для користувача {user_id}")
            return False
        
        logger.log_info(f"CSRF токен валідний для користувача {user_id}")
        return True
    
    def get_user_token(self, user_id: int) -> Optional[str]:
        """
        Отримання поточного токена користувача
        
        Args:
            user_id: ID користувача
            
        Returns:
            Токен або None якщо не існує/прострочений
        """
        if user_id not in self.user_tokens:
            return None
        
        # Перевіряємо чи не прострочений токен
        if datetime.now() > self.token_expiry[user_id]:
            self._cleanup_user_token(user_id)
            return None
        
        return self.user_tokens[user_id]
    
    def refresh_token(self, user_id: int) -> str:
        """
        Оновлення токена користувача
        
        Args:
            user_id: ID користувача
            
        Returns:
            Новий токен
        """
        return self.generate_token(user_id)
    
    def _cleanup_user_token(self, user_id: int) -> None:
        """Видалення токена користувача"""
        if user_id in self.user_tokens:
            del self.user_tokens[user_id]
        if user_id in self.token_expiry:
            del self.token_expiry[user_id]
        logger.log_info(f"Видалено CSRF токен для користувача {user_id}")
    
    def cleanup_expired_tokens(self) -> None:
        """Очищення прострочених токенів"""
        current_time = datetime.now()
        expired_users = []
        
        for user_id, expiry_time in self.token_expiry.items():
            if current_time > expiry_time:
                expired_users.append(user_id)
        
        for user_id in expired_users:
            self._cleanup_user_token(user_id)
        
        if expired_users:
            logger.log_info(f"Очищено {len(expired_users)} прострочених CSRF токенів")
    
    def add_csrf_to_callback_data(self, user_id: int, callback_data: str) -> str:
        """
        Додавання CSRF токена до callback даних
        
        Args:
            user_id: ID користувача
            callback_data: Оригінальні callback дані
            
        Returns:
            Callback дані з CSRF токеном
        """
        token = self.get_user_token(user_id)
        if not token:
            token = self.generate_token(user_id)
        
        return f"{callback_data}|csrf:{token}"
    
    def extract_callback_data(self, user_id: int, callback_data: str, allow_refresh: bool = False) -> Optional[str]:
        """
        Витягування callback даних з перевіркою CSRF
        
        Args:
            user_id: ID користувача
            callback_data: Callback дані з токеном
            allow_refresh: Дозволити автоматичне оновлення токена (для активних чатів)
            
        Returns:
            Оригінальні callback дані або None якщо токен невалідний
        """
        if "|csrf:" not in callback_data:
            logger.log_error(f"CSRF токен не знайдено в callback даних для користувача {user_id}")
            return None
        
        data, token_part = callback_data.rsplit("|csrf:", 1)
        
        # Перевіряємо токен
        if not self.validate_token(user_id, token_part):
            # Якщо дозволено оновлення (для активних чатів) - оновлюємо токен
            if allow_refresh:
                logger.log_info(f"Автоматичне оновлення CSRF токена для користувача {user_id} (активний чат)")
                self.refresh_token(user_id)
                # Повертаємо дані без повторної перевірки, оскільки токен вже оновлено
                return data
            return None
        
        return data


# Глобальний екземпляр CSRF менеджера
csrf_manager = CSRFManager()
