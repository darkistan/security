"""
Модуль логування для системи ведення змін охоронців
Підтримує запис логів у файл та SQLite базу даних
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Optional


class BotLogger:
    """Клас для логування дій системи (файл + БД)"""
    
    def __init__(self, log_file: str = "logs.txt", log_level: str = "INFO", use_db: bool = True):
        """
        Ініціалізація логера
        
        Args:
            log_file: Шлях до файлу логів
            log_level: Рівень логування
            use_db: Чи використовувати БД для логування
        """
        self.log_file = log_file
        self.use_db = use_db
        self.logger = logging.getLogger("security_shifts_system")
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        # Налаштування форматування
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Файловий хендлер
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # Консольний хендлер
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
    
    def _save_to_db(self, level: str, message: str, user_id: Optional[int] = None, command: Optional[str] = None):
        """
        Збереження логу в БД
        
        Args:
            level: Рівень логу (INFO, WARNING, ERROR, SECURITY)
            message: Повідомлення
            user_id: ID користувача (опціонально)
            command: Команда (опціонально)
        """
        if not self.use_db:
            return
        
        try:
            # Імпортуємо тут щоб уникнути circular imports
            from database import get_session, get_db_manager
            from models import Log
            
            # Перевіряємо чи БД ініціалізована
            if get_db_manager() is None:
                return  # БД ще не готова - пропускаємо
            
            with get_session() as session:
                log = Log(
                    timestamp=datetime.now(),
                    level=level,
                    message=message,
                    user_id=user_id,
                    command=command
                )
                session.add(log)
                session.commit()
        except Exception as e:
            # Не логуємо помилку БД у БД (щоб уникнути рекурсії)
            pass
    
    def log_access_request(self, user_id: int, username: str) -> None:
        """Логування запиту на доступ"""
        message = f"UserID: {user_id} | Username: @{username} | Дія: Запит на доступ"
        self.logger.info(message)
        self._save_to_db('INFO', message, user_id, 'access_request')
    
    def log_access_granted(self, user_id: int, username: str) -> None:
        """Логування надання доступу"""
        message = f"UserID: {user_id} | Username: @{username} | Дія: Доступ надано"
        self.logger.info(message)
        self._save_to_db('INFO', message, user_id, 'access_granted')
    
    def log_access_denied(self, user_id: int, username: str) -> None:
        """Логування відмови в доступі"""
        message = f"UserID: {user_id} | Username: @{username} | Дія: Доступ відхилено"
        self.logger.info(message)
        self._save_to_db('INFO', message, user_id, 'access_denied')
    
    def log_shift_created(self, user_id: int, shift_id: int, object_id: int) -> None:
        """Логування створення зміни"""
        message = f"UserID: {user_id} | Створено зміну ID: {shift_id} | Об'єкт: {object_id}"
        self.logger.info(message)
        self._save_to_db('INFO', message, user_id, 'shift_created')
    
    def log_event_created(self, user_id: int, event_id: int, event_type: str) -> None:
        """Логування створення події"""
        message = f"UserID: {user_id} | Створено подію ID: {event_id} | Тип: {event_type}"
        self.logger.info(message)
        self._save_to_db('INFO', message, user_id, 'event_created')
    
    def log_handover_created(self, user_id: int, handover_id: int) -> None:
        """Логування створення передачі зміни"""
        message = f"UserID: {user_id} | Створено передачу зміни ID: {handover_id}"
        self.logger.info(message)
        self._save_to_db('INFO', message, user_id, 'handover_created')
    
    def log_handover_accepted(self, user_id: int, handover_id: int, with_notes: bool) -> None:
        """Логування прийняття передачі зміни"""
        notes_text = "з зауваженнями" if with_notes else "без зауважень"
        message = f"UserID: {user_id} | Прийнято передачу зміни ID: {handover_id} ({notes_text})"
        self.logger.info(message)
        self._save_to_db('INFO', message, user_id, 'handover_accepted')
    
    def log_admin_approve(self, admin_id: int, approved_user_id: int, username: str) -> None:
        """Логування схвалення користувача адміном"""
        message = f"AdminID: {admin_id} | СХВАЛЕНО доступ для UserID: {approved_user_id} (@{username})"
        self.logger.info(message)
        self._save_to_db('INFO', message, admin_id, 'admin_approve')
    
    def log_admin_deny(self, admin_id: int, denied_user_id: int, username: str) -> None:
        """Логування відхилення користувача адміном"""
        message = f"AdminID: {admin_id} | ВІДХИЛЕНО доступ для UserID: {denied_user_id} (@{username})"
        self.logger.info(message)
        self._save_to_db('INFO', message, admin_id, 'admin_deny')
    
    def log_unauthorized_access_attempt(self, user_id: int, command: str) -> None:
        """Логування спроб неавторизованого доступу"""
        message = f"НЕАВТОРИЗОВАНИЙ ДОСТУП | UserID: {user_id} | Команда: {command}"
        self.logger.warning(message)
        self._save_to_db('SECURITY', message, user_id, command)
    
    def log_csrf_attack(self, user_id: int, callback_data: str) -> None:
        """Логування CSRF атак"""
        message = f"CSRF АТАКА | UserID: {user_id} | Callback: {callback_data[:50]}..."
        self.logger.warning(message)
        self._save_to_db('SECURITY', message, user_id, 'csrf_attack')
    
    def log_csrf_expired_token(self, user_id: int, callback_data: str) -> None:
        """Логування застарілого CSRF токену"""
        message = f"Невірний CSRF токен для користувача {user_id} | Callback: {callback_data[:50]}..."
        self.logger.error(message)
        self._save_to_db('SECURITY', message, user_id, 'csrf_expired_token')
    
    def log_info(self, message: str, user_id: Optional[int] = None) -> None:
        """Логування інформаційних повідомлень"""
        self.logger.info(message)
        self._save_to_db('INFO', message, user_id)
    
    def log_warning(self, message: str, user_id: Optional[int] = None) -> None:
        """Логування попереджень"""
        self.logger.warning(message)
        self._save_to_db('WARNING', message, user_id)
    
    def log_error(self, error: str, user_id: Optional[int] = None) -> None:
        """Логування помилок"""
        if user_id:
            message = f"UserID: {user_id} | Помилка: {error}"
        else:
            message = f"Помилка: {error}"
        
        self.logger.error(message)
        self._save_to_db('ERROR', message, user_id)
    
    def clean_old_logs(self, days: int = 30) -> int:
        """
        Очищення старих логів з БД
        
        Args:
            days: Скільки днів зберігати логи
            
        Returns:
            Кількість видалених записів
        """
        if not self.use_db:
            return 0
        
        try:
            from database import get_session
            from models import Log
            
            cutoff_date = datetime.now() - timedelta(days=days)
            
            with get_session() as session:
                deleted = session.query(Log).filter(Log.timestamp < cutoff_date).delete()
                session.commit()
                
                if deleted > 0:
                    self.log_info(f"Видалено {deleted} старих записів логів")
                
                return deleted
        except Exception as e:
            self.logger.error(f"Помилка очищення старих логів: {e}")
            return 0


# Глобальний екземпляр логера
logger = BotLogger()
