"""
SQLAlchemy моделі для системи ведення змін охоронців
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class PendingRequest(Base):
    """Модель запитів на доступ"""
    __tablename__ = 'pending_requests'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(100))
    timestamp = Column(DateTime, default=datetime.now)
    
    def __repr__(self):
        return f"<PendingRequest(user_id={self.user_id}, username='{self.username}')>"


class User(Base):
    """Модель користувача (охоронця) з доступом до системи"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, unique=True, nullable=False, index=True)  # Telegram ID
    username = Column(String(100))
    approved_at = Column(DateTime, default=datetime.now)
    notifications_enabled = Column(Boolean, default=False)
    role = Column(String(20), default='guard', index=True)  # guard, senior, controller, admin
    full_name = Column(String(200), nullable=False)  # ПІБ (обов'язкове)
    password_hash = Column(String(255), nullable=True)  # Для веб-доступу
    phone = Column(String(50), nullable=False)  # Телефон (обов'язкове)
    object_id = Column(Integer, ForeignKey('security_objects.id'), nullable=False, index=True)  # Об'єкт (обов'язкове)
    is_active = Column(Boolean, default=True, index=True)  # Активний/деактивований
    
    # Relationships
    security_object = relationship('SecurityObject', backref='guards')
    
    def __repr__(self):
        return f"<User(user_id={self.user_id}, username='{self.username}', role='{self.role}', object_id={self.object_id})>"


class SecurityObject(Base):
    """Модель об'єкта охорони"""
    __tablename__ = 'security_objects'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, index=True)  # Назва об'єкта
    is_active = Column(Boolean, default=True, index=True)
    protection_type = Column(String(30), default='SHIFT', nullable=False)  # SHIFT — позмінна, TEMPORARY_SINGLE — один охоронець почасово
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def __repr__(self):
        return f"<SecurityObject(id={self.id}, name='{self.name}', is_active={self.is_active})>"


class Shift(Base):
    """Модель зміни охоронця"""
    __tablename__ = 'shifts'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    guard_id = Column(Integer, ForeignKey('users.user_id'), nullable=False, index=True)
    object_id = Column(Integer, ForeignKey('security_objects.id'), nullable=False, index=True)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=True, index=True)
    status = Column(String(20), default='ACTIVE', nullable=False, index=True)  # ACTIVE, COMPLETED, HANDED_OVER
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    guard = relationship('User', foreign_keys=[guard_id], backref='shifts')
    security_object = relationship('SecurityObject', backref='shifts')
    events = relationship('Event', back_populates='shift', cascade='all, delete-orphan')
    handovers = relationship('ShiftHandover', back_populates='shift', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<Shift(id={self.id}, guard_id={self.guard_id}, object_id={self.object_id}, status='{self.status}')>"


class Event(Base):
    """Модель події в журналі"""
    __tablename__ = 'events'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    shift_id = Column(Integer, ForeignKey('shifts.id', ondelete='CASCADE'), nullable=False, index=True)
    object_id = Column(Integer, ForeignKey('security_objects.id'), nullable=False, index=True)
    event_type = Column(String(20), nullable=False, index=True)  # INCIDENT, POWER_OFF, POWER_ON
    description = Column(Text, nullable=False)  # Текст опису
    author_id = Column(Integer, ForeignKey('users.user_id'), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    
    # Relationships
    shift = relationship('Shift', back_populates='events')
    security_object = relationship('SecurityObject', backref='events')
    author = relationship('User', foreign_keys=[author_id], backref='events')
    
    def __repr__(self):
        return f"<Event(id={self.id}, shift_id={self.shift_id}, event_type='{self.event_type}', created_at='{self.created_at}')>"


class ShiftHandover(Base):
    """Модель передачі зміни"""
    __tablename__ = 'shift_handovers'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    shift_id = Column(Integer, ForeignKey('shifts.id', ondelete='CASCADE'), nullable=False, index=True)
    handover_by_id = Column(Integer, ForeignKey('users.user_id'), nullable=False, index=True)  # Здавач
    handover_to_id = Column(Integer, ForeignKey('users.user_id'), nullable=False, index=True)  # Приймач
    status = Column(String(30), default='PENDING', nullable=False, index=True)  # PENDING, ACCEPTED, ACCEPTED_WITH_NOTES
    summary = Column(Text, nullable=False)  # Зведення подій
    notes = Column(Text, nullable=True)  # Зауваження (якщо є)
    handed_over_at = Column(DateTime, default=datetime.now, index=True)
    accepted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    
    # Relationships
    shift = relationship('Shift', back_populates='handovers')
    handover_by = relationship('User', foreign_keys=[handover_by_id], backref='handovers_sent')
    handover_to = relationship('User', foreign_keys=[handover_to_id], backref='handovers_received')
    report = relationship('Report', back_populates='handover', uselist=False, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<ShiftHandover(id={self.id}, shift_id={self.shift_id}, status='{self.status}')>"


class Report(Base):
    """Модель звіту при наявності зауважень"""
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    shift_handover_id = Column(Integer, ForeignKey('shift_handovers.id', ondelete='CASCADE'), nullable=False, unique=True, index=True)
    object_id = Column(Integer, ForeignKey('security_objects.id'), nullable=False, index=True)
    shift_start = Column(DateTime, nullable=False)
    shift_end = Column(DateTime, nullable=False)
    handover_by_id = Column(Integer, ForeignKey('users.user_id'), nullable=False, index=True)
    handover_to_id = Column(Integer, ForeignKey('users.user_id'), nullable=False, index=True)
    events_count = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=False)  # Текст зауважень
    created_at = Column(DateTime, default=datetime.now, index=True)
    
    # Relationships
    handover = relationship('ShiftHandover', back_populates='report')
    security_object = relationship('SecurityObject', backref='reports')
    handover_by = relationship('User', foreign_keys=[handover_by_id], backref='reports_sent')
    handover_to = relationship('User', foreign_keys=[handover_to_id], backref='reports_received')
    
    def __repr__(self):
        return f"<Report(id={self.id}, shift_handover_id={self.shift_handover_id}, events_count={self.events_count})>"


class Log(Base):
    """Системні логи"""
    __tablename__ = 'logs'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.now, index=True)
    level = Column(String(20), nullable=False, index=True)  # INFO, WARNING, ERROR, SECURITY
    message = Column(Text, nullable=False)
    user_id = Column(Integer, index=True)
    command = Column(String(100))
    
    def __repr__(self):
        return f"<Log(level='{self.level}', timestamp='{self.timestamp}')>"


class GuardPoint(Base):
    """Модель нарахування балів охоронцю (позитивні/негативні). Баланс = сума points_delta по guard_id."""
    __tablename__ = 'guard_points'

    id = Column(Integer, primary_key=True, autoincrement=True)
    guard_id = Column(Integer, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    points_delta = Column(Integer, nullable=False)  # додатні — бонус, від'ємні — штраф
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    created_by_id = Column(Integer, ForeignKey('users.user_id'), nullable=False, index=True)

    guard = relationship('User', foreign_keys=[guard_id], backref='points_records')
    created_by = relationship('User', foreign_keys=[created_by_id], backref='points_given')

    def __repr__(self):
        return f"<GuardPoint(id={self.id}, guard_id={self.guard_id}, points_delta={self.points_delta})>"


class Announcement(Base):
    """Модель оголошення (відправка охоронцям у Telegram)."""
    __tablename__ = 'announcements'

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    author_id = Column(Integer, nullable=False)
    author_username = Column(String(100))
    priority = Column(String(20), default='normal')  # normal, important, urgent
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    sent_at = Column(DateTime)
    recipient_count = Column(Integer, default=0)

    def __repr__(self):
        return f"<Announcement(id={self.id}, priority='{self.priority}', sent_at='{self.sent_at}')>"


class AnnouncementRecipient(Base):
    """Модель отримувача оголошення (охоронець)."""
    __tablename__ = 'announcement_recipients'

    id = Column(Integer, primary_key=True, autoincrement=True)
    announcement_id = Column(Integer, ForeignKey('announcements.id', ondelete='CASCADE'), nullable=False, index=True)
    recipient_user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False, index=True)
    sent_at = Column(DateTime, default=datetime.now, index=True)
    status = Column(String(20), default='sent')  # sent, failed, blocked

    def __repr__(self):
        return f"<AnnouncementRecipient(announcement_id={self.announcement_id}, recipient_user_id={self.recipient_user_id}, status='{self.status}')>"


class ScheduleSlot(Base):
    """Запланована зміна охоронця на календарну дату (графік змін). Один слот = один охоронець, один день."""
    __tablename__ = 'schedule_slots'
    __table_args__ = (UniqueConstraint('guard_id', 'slot_date', name='uq_schedule_slot_guard_date'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    guard_id = Column(Integer, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    slot_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now)

    guard = relationship('User', foreign_keys=[guard_id], backref='schedule_slots')

    def __repr__(self):
        return f"<ScheduleSlot(guard_id={self.guard_id}, slot_date='{self.slot_date}')>"


class VacationSlot(Base):
    """День відпустки охоронця (графік відпусток). Один запис = охоронець у відпустці в цей день."""
    __tablename__ = 'vacation_slots'
    __table_args__ = (UniqueConstraint('guard_id', 'vacation_date', name='uq_vacation_slot_guard_date'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    guard_id = Column(Integer, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    vacation_date = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now)

    guard = relationship('User', foreign_keys=[guard_id], backref='vacation_slots')

    def __repr__(self):
        return f"<VacationSlot(guard_id={self.guard_id}, vacation_date='{self.vacation_date}')>"


class ActiveSession(Base):
    """Модель активної сесії користувача у веб-інтерфейсі"""
    __tablename__ = 'active_sessions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    session_id = Column(String(255), unique=True, nullable=False, index=True)
    ip_address = Column(String(50), nullable=False)
    user_agent = Column(String(500), nullable=True)
    login_time = Column(DateTime, default=datetime.now, nullable=False)
    last_activity = Column(DateTime, default=datetime.now, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    user = relationship('User', backref='active_sessions')
    
    def __repr__(self):
        return f"<ActiveSession(user_id={self.user_id}, session_id='{self.session_id[:20]}...', ip='{self.ip_address}', is_active={self.is_active})>"
