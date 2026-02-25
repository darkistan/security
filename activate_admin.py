"""
Скрипт для активації адміністратора
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

if __name__ == '__main__':
    print("Активація адміністратора...")
    
    init_database()
    
    with get_session() as session:
        # Знаходимо всіх адміністраторів
        admins = session.query(User).filter(User.role == 'admin').all()
        
        if not admins:
            print("Адміністраторів не знайдено.")
        else:
            for admin in admins:
                admin.is_active = True
                print(f"Активовано адміністратора: User ID {admin.user_id}, ПІБ: {admin.full_name}")
            
            session.commit()
            print(f"\nАктивовано {len(admins)} адміністраторів.")
