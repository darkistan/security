"""
Скрипт для встановлення пароля адміністратора
"""
import sys
import os

# Додаємо поточну директорію в Python path
if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

from database import init_database, get_session
from models import User
from werkzeug.security import generate_password_hash

if __name__ == '__main__':
    password = "Abh3var4@"
    
    print("Встановлення пароля адміністратора...")
    
    init_database()
    
    with get_session() as session:
        # Знаходимо адміністратора (User ID = 1 або роль = admin)
        admin = session.query(User).filter(
            (User.user_id == 1) | (User.role == 'admin')
        ).first()
        
        if not admin:
            print("Помилка: Адміністратор не знайдено!")
            print("Переконайтеся, що система була ініціалізована.")
            sys.exit(1)
        
        # Встановлюємо пароль
        admin.password_hash = generate_password_hash(password)
        admin.is_active = True  # Переконаємося, що адмін активний
        
        session.commit()
        
        print(f"✅ Пароль успішно встановлено для адміністратора:")
        print(f"   User ID: {admin.user_id}")
        print(f"   ПІБ: {admin.full_name}")
        print(f"   Пароль: {password}")
