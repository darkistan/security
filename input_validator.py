"""
Модуль для валідації вхідних даних
"""
from typing import Dict, Any

from logger import logger


class InputValidator:
    """Клас для валідації вхідних даних"""
    
    def __init__(self):
        """Ініціалізація валідатора"""
        # Налаштування
        self.max_message_length = 1000  # Максимальна довжина повідомлення
        self.max_comment_length = 2000  # Максимальна довжина коментаря
        self.max_description_length = 2000  # Максимальна довжина опису події
    
    def validate_message_length(self, message: str) -> Dict[str, Any]:
        """
        Валідація довжини повідомлення
        
        Args:
            message: Повідомлення для перевірки
            
        Returns:
            Результат валідації
        """
        if not message:
            return {
                "valid": False,
                "message": "Повідомлення не може бути порожнім"
            }
        
        if len(message) > self.max_message_length:
            logger.log_error(f"Повідомлення занадто довге: {len(message)} символів")
            return {
                "valid": False,
                "message": f"Повідомлення занадто довге. Максимум {self.max_message_length} символів.",
                "current_length": len(message),
                "max_length": self.max_message_length
            }
        
        return {
            "valid": True,
            "message": "Повідомлення валідне"
        }
    
    def validate_event_type(self, event_type: str) -> Dict[str, Any]:
        """
        Валідація типу події
        
        Args:
            event_type: Тип події для перевірки
            
        Returns:
            Результат валідації
        """
        if not event_type:
            return {
                "valid": False,
                "message": "Тип події не може бути порожнім"
            }
        
        event_type = event_type.strip().upper()
        
        valid_types = ["INCIDENT", "POWER_OFF", "POWER_ON"]
        if event_type not in valid_types:
            logger.log_error(f"Невірний тип події: {event_type}")
            return {
                "valid": False,
                "message": "Невірний тип події"
            }
        
        return {
            "valid": True,
            "message": "Тип події валідний",
            "cleaned_event_type": event_type
        }
    
    def validate_event_description(self, description: str) -> Dict[str, Any]:
        """
        Валідація опису події
        
        Args:
            description: Опис події для перевірки
            
        Returns:
            Результат валідації
        """
        if not description:
            return {
                "valid": False,
                "message": "Опис події не може бути порожнім"
            }
        
        if len(description) > self.max_description_length:
            logger.log_error(f"Опис події занадто довгий: {len(description)} символів")
            return {
                "valid": False,
                "message": f"Опис події занадто довгий. Максимум {self.max_description_length} символів.",
                "current_length": len(description),
                "max_length": self.max_description_length
            }
        
        return {
            "valid": True,
            "message": "Опис події валідний",
            "cleaned_description": description.strip()
        }
    
    def validate_phone(self, phone: str) -> Dict[str, Any]:
        """
        Валідація номера телефону
        
        Args:
            phone: Номер телефону для перевірки
            
        Returns:
            Результат валідації
        """
        if not phone:
            return {
                "valid": False,
                "message": "Номер телефону не може бути порожнім"
            }
        
        phone = phone.strip()
        
        # Базова перевірка формату (мінімум 10 цифр)
        digits_only = ''.join(filter(str.isdigit, phone))
        if len(digits_only) < 10:
            return {
                "valid": False,
                "message": "Номер телефону повинен містити мінімум 10 цифр"
            }
        
        return {
            "valid": True,
            "message": "Номер телефону валідний",
            "cleaned_phone": phone
        }
    
    def validate_full_name(self, full_name: str) -> Dict[str, Any]:
        """
        Валідація ПІБ
        
        Args:
            full_name: ПІБ для перевірки
            
        Returns:
            Результат валідації
        """
        if not full_name:
            return {
                "valid": False,
                "message": "ПІБ не може бути порожнім"
            }
        
        full_name = full_name.strip()
        
        if len(full_name) < 3:
            return {
                "valid": False,
                "message": "ПІБ повинно містити мінімум 3 символи"
            }
        
        if len(full_name) > 200:
            return {
                "valid": False,
                "message": "ПІБ не може перевищувати 200 символів"
            }
        
        return {
            "valid": True,
            "message": "ПІБ валідне",
            "cleaned_full_name": full_name
        }
    
    def sanitize_input(self, text: str) -> str:
        """
        Санітизація вхідного тексту
        
        Args:
            text: Текст для санітизації
            
        Returns:
            Санітизований текст
        """
        if not text:
            return ""
        
        # Видаляємо зайві пробіли
        text = text.strip()
        
        # Обмежуємо довжину
        if len(text) > self.max_comment_length:
            text = text[:self.max_comment_length]
        
        return text
    
    def validate_role(self, role: str) -> bool:
        """
        Валідація ролі користувача
        
        Args:
            role: Роль для перевірки
            
        Returns:
            True якщо роль валідна, False інакше
        """
        if not role:
            return False
        
        valid_roles = ['admin', 'senior', 'guard']
        return role.lower() in valid_roles


# Глобальний екземпляр валідатора
input_validator = InputValidator()
