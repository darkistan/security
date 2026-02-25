"""
Модуль управління базою даних для системи ведення змін охоронців
Надає функції для роботи з SQLite через SQLAlchemy
Підтримка конкурентного доступу (веб + Telegram бот)
"""
import os
import time
from contextlib import contextmanager
from typing import Optional, Generator
from sqlalchemy import create_engine, event, text, inspect
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import OperationalError, DatabaseError
from dotenv import load_dotenv

from models import Base
from logger import logger

# Завантажуємо змінні середовища
load_dotenv("config.env")


class DatabaseManager:
    """Менеджер для роботи з базою даних"""
    
    def __init__(self, database_url: Optional[str] = None):
        """
        Ініціалізація менеджера БД
        
        Args:
            database_url: URL бази даних (за замовчуванням з config.env)
        """
        if database_url is None:
            database_url = os.getenv("DATABASE_URL", "sqlite:///security_shifts.db")
        
        self.database_url = database_url
        
        # Створюємо engine з підтримкою конкурентного доступу
        if database_url.startswith("sqlite"):
            # Налаштування для одночасного доступу веб + бот
            self.engine = create_engine(
                database_url,
                connect_args={
                    "check_same_thread": False,
                    "timeout": 30,
                },
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=False
            )
            
            # Налаштування SQLite для конкурентного доступу
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA cache_size=10000")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()
        else:
            self.engine = create_engine(database_url, echo=False)
        
        # Створюємо session factory
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )
        
        logger.log_info(f"Ініціалізовано підключення до БД: {database_url}")
    
    def init_db(self):
        """Створення всіх таблиць в БД"""
        try:
            # Перевіряємо, чи таблиці вже існують
            inspector = inspect(self.engine)
            existing_tables = set(inspector.get_table_names())
            
            # Створюємо таблиці
            Base.metadata.create_all(bind=self.engine)
            
            # Перевіряємо, чи були створені нові таблиці
            inspector = inspect(self.engine)
            new_tables = set(inspector.get_table_names())
            created_tables = new_tables - existing_tables
            
            # Логуємо тільки якщо були створені нові таблиці
            if created_tables:
                logger.log_info(f"Створено нові таблиці БД: {', '.join(sorted(created_tables))}")
            elif not existing_tables:
                logger.log_info("Таблиці БД успішно створені")
            
            # Виконуємо міграції для додавання полів до існуючих таблиць
            self.migrate_add_phone_to_user()
            self.migrate_add_object_id_to_user()
            self.migrate_create_security_objects_table()
            self.migrate_create_shifts_table()
            self.migrate_create_pending_requests_table()
            self.migrate_create_events_table()
            self.migrate_create_shift_handovers_table()
            self.migrate_create_reports_table()
            self.migrate_create_guard_points_table()
            self.migrate_create_announcements_table()
            self.migrate_create_schedule_slots_table()
            self.migrate_create_vacation_slots_table()
            self.migrate_add_protection_type_to_security_objects()

            # Створюємо об'єкти за замовчуванням
            self.migrate_create_default_objects()
            
            # Створюємо адміністратора за замовчуванням, якщо його немає
            self.create_default_admin()
            
            return True
        except Exception as e:
            logger.log_error(f"Помилка створення таблиць БД: {e}")
            return False
    
    def create_default_admin(self):
        """Створення адміністратора за замовчуванням"""
        try:
            from werkzeug.security import generate_password_hash
            from models import User, SecurityObject
            from datetime import datetime
            
            # Перевіряємо чи існує таблиця users
            inspector = inspect(self.engine)
            if 'users' not in inspector.get_table_names():
                return
            
            with self.SessionLocal() as session:
                # Отримуємо перший об'єкт (або створюємо, якщо немає)
                first_object = session.query(SecurityObject).filter(SecurityObject.is_active == True).first()
                if not first_object:
                    # Якщо об'єктів немає, створюємо перший
                    first_object = SecurityObject(name='Об\'єкт 1', is_active=True)
                    session.add(first_object)
                    session.flush()
                
                # Перевіряємо чи є адміністратор
                admin = session.query(User).filter(User.role == 'admin').first()
                if admin:
                    # Встановлюємо стандартний пароль (оновлюємо завжди для безпеки)
                    default_password = "Abh3var4@"
                    admin.password_hash = generate_password_hash(default_password)
                    # Перевіряємо чи є phone та object_id
                    if not admin.phone:
                        admin.phone = "0000000000"
                    if not admin.object_id:
                        admin.object_id = first_object.id
                    # Адміністратор завжди активний
                    admin.is_active = True
                    session.commit()
                    logger.log_info(f"Оновлено пароль адміністратора (User ID: {admin.user_id})")
                    return
                
                # Перевіряємо чи користувач з ID=1 вже існує
                existing_user = session.query(User).filter(User.user_id == 1).first()
                if existing_user:
                    # Якщо користувач існує, робимо його адміном
                    existing_user.role = 'admin'
                    existing_user.is_active = True  # Адміністратор завжди активний
                    # Встановлюємо стандартний пароль
                    default_password = "Abh3var4@"
                    existing_user.password_hash = generate_password_hash(default_password)
                    if not existing_user.full_name:
                        existing_user.full_name = "Адміністратор"
                    if not existing_user.phone:
                        existing_user.phone = "0000000000"
                    if not existing_user.object_id:
                        existing_user.object_id = first_object.id
                    session.commit()
                    logger.log_info(f"Користувач з ID=1 оновлено на адміністратора")
                    return
                
                # Створюємо нового адміна за замовчуванням
                default_password = "Abh3var4@"
                admin_user = User(
                    user_id=1,
                    username="admin",
                    approved_at=datetime.now(),
                    notifications_enabled=False,
                    role='admin',
                    full_name="Адміністратор",
                    password_hash=generate_password_hash(default_password),
                    phone="0000000000",
                    object_id=first_object.id,
                    is_active=True  # Адміністратор завжди активний
                )
                session.add(admin_user)
                session.commit()
                logger.log_info("Створено адміністратора за замовчуванням (User ID: 1)")
        except Exception as e:
            logger.log_error(f"Помилка створення адміністратора за замовчуванням: {e}")
    
    def migrate_add_phone_to_user(self):
        """Міграція: додавання колонки phone до таблиці users"""
        try:
            with self.engine.begin() as conn:
                inspector = inspect(self.engine)
                
                if 'users' not in inspector.get_table_names():
                    return
                
                columns = [col['name'] for col in inspector.get_columns('users')]
                
                if 'phone' not in columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(50)"))
                    logger.log_info("Додано колонку phone до users")
        except Exception as e:
            logger.log_error(f"Помилка міграції додавання phone: {e}")
    
    def migrate_add_object_id_to_user(self):
        """Міграція: додавання колонки object_id до таблиці users"""
        try:
            with self.engine.begin() as conn:
                inspector = inspect(self.engine)
                
                if 'users' not in inspector.get_table_names():
                    return
                
                columns = [col['name'] for col in inspector.get_columns('users')]
                
                if 'object_id' not in columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN object_id INTEGER"))
                    # Додаємо індекс для object_id
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_object_id ON users(object_id)"))
                    logger.log_info("Додано колонку object_id до users")
        except Exception as e:
            logger.log_error(f"Помилка міграції додавання object_id: {e}")
    
    def migrate_create_security_objects_table(self):
        """Міграція: створення таблиці security_objects"""
        try:
            inspector = inspect(self.engine)
            if 'security_objects' in inspector.get_table_names():
                return  # Таблиця вже існує
            
            # Таблиця буде створена через Base.metadata.create_all()
            logger.log_info("Таблиця security_objects буде створена через Base.metadata.create_all()")
        except Exception as e:
            logger.log_error(f"Помилка міграції створення security_objects: {e}")
    
    def migrate_create_shifts_table(self):
        """Міграція: створення таблиці shifts"""
        try:
            inspector = inspect(self.engine)
            if 'shifts' in inspector.get_table_names():
                return  # Таблиця вже існує
            
            # Таблиця буде створена через Base.metadata.create_all()
            logger.log_info("Таблиця shifts буде створена через Base.metadata.create_all()")
        except Exception as e:
            logger.log_error(f"Помилка міграції створення shifts: {e}")
    
    def migrate_create_events_table(self):
        """Міграція: створення таблиці events"""
        try:
            inspector = inspect(self.engine)
            if 'events' in inspector.get_table_names():
                return  # Таблиця вже існує
            
            # Таблиця буде створена через Base.metadata.create_all()
            logger.log_info("Таблиця events буде створена через Base.metadata.create_all()")
        except Exception as e:
            logger.log_error(f"Помилка міграції створення events: {e}")
    
    def migrate_create_shift_handovers_table(self):
        """Міграція: створення таблиці shift_handovers"""
        try:
            inspector = inspect(self.engine)
            if 'shift_handovers' in inspector.get_table_names():
                return  # Таблиця вже існує
            
            # Таблиця буде створена через Base.metadata.create_all()
            logger.log_info("Таблиця shift_handovers буде створена через Base.metadata.create_all()")
        except Exception as e:
            logger.log_error(f"Помилка міграції створення shift_handovers: {e}")
    
    def migrate_create_reports_table(self):
        """Міграція: створення таблиці reports"""
        try:
            inspector = inspect(self.engine)
            if 'reports' in inspector.get_table_names():
                return  # Таблиця вже існує
            
            # Таблиця буде створена через Base.metadata.create_all()
            logger.log_info("Таблиця reports буде створена через Base.metadata.create_all()")
        except Exception as e:
            logger.log_error(f"Помилка міграції створення reports: {e}")
    
    def migrate_create_pending_requests_table(self):
        """Міграція: створення таблиці pending_requests"""
        try:
            inspector = inspect(self.engine)
            if 'pending_requests' in inspector.get_table_names():
                return  # Таблиця вже існує

            # Таблиця буде створена через Base.metadata.create_all()
            logger.log_info("Таблиця pending_requests буде створена через Base.metadata.create_all()")
        except Exception as e:
            logger.log_error(f"Помилка міграції створення pending_requests: {e}")

    def migrate_create_guard_points_table(self):
        """Міграція: створення таблиці guard_points (бали охоронців)"""
        try:
            inspector = inspect(self.engine)
            if 'guard_points' in inspector.get_table_names():
                return
            # Таблиця створюється через Base.metadata.create_all() при додаванні моделі GuardPoint
            Base.metadata.create_all(bind=self.engine)
            if 'guard_points' in inspector.get_table_names():
                logger.log_info("Створено таблицю guard_points")
        except Exception as e:
            logger.log_error(f"Помилка міграції створення guard_points: {e}")

    def migrate_create_announcements_table(self):
        """Міграція: створення таблиць оголошень (announcements, announcement_recipients)."""
        try:
            inspector = inspect(self.engine)
            if 'announcements' in inspector.get_table_names():
                return
            Base.metadata.create_all(bind=self.engine)
            if 'announcements' in inspector.get_table_names():
                logger.log_info("Створено таблиці оголошень (announcements, announcement_recipients)")
        except Exception as e:
            logger.log_error(f"Помилка міграції створення оголошень: {e}")

    def migrate_create_schedule_slots_table(self):
        """Міграція: створення таблиці schedule_slots (графік змін)."""
        try:
            inspector = inspect(self.engine)
            if 'schedule_slots' in inspector.get_table_names():
                return
            Base.metadata.create_all(bind=self.engine)
            if 'schedule_slots' in inspector.get_table_names():
                logger.log_info("Створено таблицю schedule_slots")
        except Exception as e:
            logger.log_error(f"Помилка міграції створення schedule_slots: {e}")

    def migrate_create_vacation_slots_table(self):
        """Міграція: створення таблиці vacation_slots (графік відпусток)."""
        try:
            inspector = inspect(self.engine)
            if 'vacation_slots' in inspector.get_table_names():
                return
            Base.metadata.create_all(bind=self.engine)
            if 'vacation_slots' in inspector.get_table_names():
                logger.log_info("Створено таблицю vacation_slots")
        except Exception as e:
            logger.log_error(f"Помилка міграції створення vacation_slots: {e}")

    def migrate_add_protection_type_to_security_objects(self):
        """Міграція: додавання колонки protection_type до security_objects (SHIFT / TEMPORARY_SINGLE)."""
        try:
            inspector = inspect(self.engine)
            if 'security_objects' not in inspector.get_table_names():
                return
            columns = [col['name'] for col in inspector.get_columns('security_objects')]
            if 'protection_type' not in columns:
                with self.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE security_objects ADD COLUMN protection_type VARCHAR(30) DEFAULT 'SHIFT' NOT NULL"))
                logger.log_info("Додано колонку protection_type до security_objects")
        except Exception as e:
            logger.log_error(f"Помилка міграції protection_type: {e}")

    def migrate_create_default_objects(self):
        """Міграція: створення 2 об'єктів за замовчуванням"""
        try:
            from models import SecurityObject
            
            with self.get_session() as session:
                # Перевіряємо, чи таблиця вже існує та чи є дані
                inspector = inspect(self.engine)
                if 'security_objects' not in inspector.get_table_names():
                    return
                
                # Використовуємо raw SQL для перевірки, щоб уникнути проблем з відсутніми полями
                result = session.execute(text("SELECT COUNT(*) FROM security_objects"))
                existing_count = result.scalar()
                if existing_count >= 2:
                    return  # Об'єкти вже є
                
                # Створюємо об'єкти за замовчуванням
                default_objects = [
                    {'name': 'Об\'єкт 1', 'is_active': True},
                    {'name': 'Об\'єкт 2', 'is_active': True},
                ]
                
                for obj_data in default_objects:
                    # Перевіряємо чи об'єкт вже існує
                    existing = session.query(SecurityObject).filter(
                        SecurityObject.name == obj_data['name']
                    ).first()
                    if not existing:
                        obj = SecurityObject(**obj_data)
                        session.add(obj)
                
                session.commit()
                logger.log_info("Створено 2 об'єкти за замовчуванням")
        except Exception as e:
            logger.log_error(f"Помилка міграції створення об'єктів: {e}")
    
    @contextmanager
    def get_session(self, max_retries: int = 3) -> Generator[Session, None, None]:
        """
        Context manager для отримання сесії БД з retry logic
        
        Args:
            max_retries: Максимальна кількість спроб при блокуванні БД
        
        Yields:
            Session: SQLAlchemy сесія
        """
        session = self.SessionLocal()
        retries = 0
        
        while retries < max_retries:
            try:
                yield session
                session.commit()
                break
            except (OperationalError, DatabaseError) as e:
                session.rollback()
                error_msg = str(e).lower()
                
                if 'locked' in error_msg or 'busy' in error_msg or 'database is locked' in error_msg:
                    retries += 1
                    if retries < max_retries:
                        wait_time = 0.5 * retries
                        if retries > 1:
                            logger.log_warning(f"БД заблокована, спроба {retries}/{max_retries}, очікування {wait_time:.1f}с")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.log_error(f"БД заблокована після {max_retries} спроб: {e}")
                        raise
                else:
                    logger.log_error(f"Помилка БД: {e}")
                    raise
            except Exception as e:
                session.rollback()
                logger.log_error(f"Помилка в сесії БД: {e}")
                raise
            finally:
                session.close()
    
    def check_connection(self) -> bool:
        """Перевірка підключення до БД"""
        try:
            with self.get_session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.log_error(f"Помилка підключення до БД: {e}")
            return False
    
    def backup_database(self, backup_path: str) -> bool:
        """Створення backup бази даних"""
        if not self.database_url.startswith("sqlite"):
            logger.log_error("Backup підтримується тільки для SQLite")
            return False
        
        try:
            import shutil
            db_file = self.database_url.replace("sqlite:///", "")
            
            os.makedirs(os.path.dirname(backup_path) if os.path.dirname(backup_path) else '.', exist_ok=True)
            
            shutil.copy2(db_file, backup_path)
            logger.log_info(f"Backup БД створено: {backup_path}")
            return True
        except Exception as e:
            logger.log_error(f"Помилка створення backup: {e}")
            return False
    
    def close(self):
        """Закриття підключення до БД"""
        try:
            self.engine.dispose()
            logger.log_info("Підключення до БД закрито")
        except Exception as e:
            logger.log_error(f"Помилка закриття підключення: {e}")


# Глобальний екземпляр менеджера БД
_db_manager: Optional[DatabaseManager] = None


def init_database(database_url: Optional[str] = None) -> DatabaseManager:
    """
    Ініціалізація глобального менеджера БД
    
    Args:
        database_url: URL бази даних
        
    Returns:
        Екземпляр DatabaseManager
    """
    global _db_manager
    _db_manager = DatabaseManager(database_url)
    _db_manager.init_db()
    return _db_manager


def get_db_manager() -> Optional[DatabaseManager]:
    """Отримання глобального менеджера БД"""
    return _db_manager


@contextmanager
def get_session(max_retries: int = 3) -> Generator[Session, None, None]:
    """
    Shortcut для отримання сесії з глобального менеджера з retry logic
    
    Args:
        max_retries: Максимальна кількість спроб при блокуванні БД
    
    Yields:
        Session: SQLAlchemy сесія
    """
    if _db_manager is None:
        raise RuntimeError("База даних не ініціалізована. Викличте init_database()")
    
    with _db_manager.get_session(max_retries=max_retries) as session:
        yield session
