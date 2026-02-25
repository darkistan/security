"""
Модуль для генерації звітів при наявності зауважень
"""
from datetime import datetime
from typing import List, Optional, Dict, Any

from database import get_session
from models import Report, ShiftHandover, Shift, Event
from logger import logger


class ReportManager:
    """Клас для управління звітами"""
    
    def __init__(self):
        """Ініціалізація менеджера звітів"""
        pass
    
    def create_report_from_handover(self, handover_id: int) -> Optional[int]:
        """
        Створення звіту з передачі зміни (якщо є зауваження)
        
        Args:
            handover_id: ID передачі зміни
            
        Returns:
            ID створеного звіту або None
        """
        try:
            with get_session() as session:
                handover = session.query(ShiftHandover).filter(
                    ShiftHandover.id == handover_id
                ).first()
                
                if not handover:
                    logger.log_error(f"Передача {handover_id} не знайдена")
                    return None
                
                if handover.status != 'ACCEPTED_WITH_NOTES':
                    logger.log_error(f"Передача {handover_id} не має зауважень")
                    return None
                
                if not handover.notes:
                    logger.log_error(f"Передача {handover_id} не має тексту зауважень")
                    return None
                
                # Перевіряємо чи звіт вже існує
                existing_report = session.query(Report).filter(
                    Report.shift_handover_id == handover_id
                ).first()
                
                if existing_report:
                    logger.log_info(f"Звіт для передачі {handover_id} вже існує")
                    return existing_report.id
                
                # Отримуємо дані зміни
                shift = session.query(Shift).filter(Shift.id == handover.shift_id).first()
                if not shift:
                    logger.log_error(f"Зміна {handover.shift_id} не знайдена")
                    return None
                
                # Підраховуємо кількість подій
                events_count = session.query(Event).filter(
                    Event.shift_id == handover.shift_id
                ).count()
                
                # Створюємо звіт
                report = Report(
                    shift_handover_id=handover_id,
                    object_id=shift.object_id,
                    shift_start=shift.start_time,
                    shift_end=shift.end_time if shift.end_time else datetime.now(),
                    handover_by_id=handover.handover_by_id,
                    handover_to_id=handover.handover_to_id,
                    events_count=events_count,
                    notes=handover.notes
                )
                session.add(report)
                session.flush()
                report_id = report.id
                session.commit()
                
                logger.log_info(f"Створено звіт {report_id} для передачі {handover_id}")
                return report_id
        except Exception as e:
            logger.log_error(f"Помилка створення звіту: {e}")
            return None
    
    def get_report(self, report_id: int) -> Optional[Dict[str, Any]]:
        """
        Отримання інформації про звіт
        
        Args:
            report_id: ID звіту
            
        Returns:
            Словник з даними звіту або None
        """
        try:
            with get_session() as session:
                report = session.query(Report).filter(Report.id == report_id).first()
                if not report:
                    return None
                
                return {
                    'id': report.id,
                    'shift_handover_id': report.shift_handover_id,
                    'object_id': report.object_id,
                    'shift_start': report.shift_start.isoformat(),
                    'shift_end': report.shift_end.isoformat(),
                    'handover_by_id': report.handover_by_id,
                    'handover_to_id': report.handover_to_id,
                    'events_count': report.events_count,
                    'notes': report.notes,
                    'created_at': report.created_at.isoformat()
                }
        except Exception as e:
            logger.log_error(f"Помилка отримання звіту: {e}")
            return None
    
    def format_report_for_telegram(self, report_id: int) -> str:
        """
        Форматування звіту для відправки в Telegram
        
        Args:
            report_id: ID звіту
            
        Returns:
            Відформатований текст звіту
        """
        try:
            from guard_manager import get_guard_manager
            from object_manager import get_object_manager
            
            guard_manager = get_guard_manager()
            object_manager = get_object_manager()
            
            report = self.get_report(report_id)
            if not report:
                return "Звіт не знайдено"
            
            obj = object_manager.get_object(report['object_id'])
            obj_name = obj['name'] if obj else f"Об'єкт #{report['object_id']}"
            
            handover_by = guard_manager.get_guard(report['handover_by_id'])
            handover_to = guard_manager.get_guard(report['handover_to_id'])
            
            handover_by_name = handover_by['full_name'] if handover_by else f"ID: {report['handover_by_id']}"
            handover_to_name = handover_to['full_name'] if handover_to else f"ID: {report['handover_to_id']}"
            
            shift_start = datetime.fromisoformat(report['shift_start']).strftime('%d.%m.%Y %H:%M')
            shift_end = datetime.fromisoformat(report['shift_end']).strftime('%d.%m.%Y %H:%M')
            
            lines = [
                "📋 ЗВІТ ПРО ЗМІНУ З ЗАУВАЖЕННЯМИ",
                "",
                f"🏢 Об'єкт: {obj_name}",
                f"📅 Період: {shift_start} - {shift_end}",
                "",
                f"👤 Здавач: {handover_by_name}",
                f"👤 Приймач: {handover_to_name}",
                "",
                f"📊 Кількість подій: {report['events_count']}",
                "",
                "⚠️ ЗАУВАЖЕННЯ:",
                report['notes']
            ]
            
            return "\n".join(lines)
        except Exception as e:
            logger.log_error(f"Помилка форматування звіту: {e}")
            return f"Помилка форматування звіту: {e}"
    
    def get_reports(
        self,
        object_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Отримання списку звітів з фільтрами
        
        Args:
            object_id: ID об'єкта для фільтрації
            start_date: Початкова дата
            end_date: Кінцева дата
            limit: Максимальна кількість записів
            
        Returns:
            Список звітів
        """
        try:
            with get_session() as session:
                query = session.query(Report)
                
                if object_id:
                    query = query.filter(Report.object_id == object_id)
                
                if start_date:
                    query = query.filter(Report.created_at >= start_date)
                
                if end_date:
                    query = query.filter(Report.created_at <= end_date)
                
                query = query.order_by(Report.created_at.desc())

                if offset:
                    query = query.offset(offset)
                if limit:
                    query = query.limit(limit)

                reports = query.all()
                
                return [
                    {
                        'id': report.id,
                        'shift_handover_id': report.shift_handover_id,
                        'object_id': report.object_id,
                        'shift_start': report.shift_start.isoformat(),
                        'shift_end': report.shift_end.isoformat(),
                        'handover_by_id': report.handover_by_id,
                        'handover_to_id': report.handover_to_id,
                        'events_count': report.events_count,
                        'notes': report.notes[:200] + '...' if len(report.notes) > 200 else report.notes,
                        'created_at': report.created_at.isoformat()
                    }
                    for report in reports
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання звітів: {e}")
            return []
    
    def update_report(
        self,
        report_id: int,
        notes: Optional[str] = None
    ) -> bool:
        """
        Редагування звіту
        
        Args:
            report_id: ID звіту
            notes: Новий текст зауважень
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                report = session.query(Report).filter(Report.id == report_id).first()
                if not report:
                    logger.log_error(f"Звіт {report_id} не знайдено")
                    return False
                
                if notes is not None:
                    report.notes = notes.strip()
                
                session.commit()
                logger.log_info(f"Оновлено звіт {report_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка оновлення звіту: {e}")
            return False
    
    def delete_report(self, report_id: int) -> bool:
        """
        Видалення звіту
        
        Args:
            report_id: ID звіту
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                report = session.query(Report).filter(Report.id == report_id).first()
                if not report:
                    logger.log_error(f"Звіт {report_id} не знайдено")
                    return False
                
                session.delete(report)
                session.commit()
                logger.log_info(f"Видалено звіт {report_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка видалення звіту: {e}")
            return False


# Глобальний екземпляр менеджера звітів
_report_manager: Optional[ReportManager] = None


def get_report_manager() -> ReportManager:
    """Отримання глобального менеджера звітів"""
    global _report_manager
    if _report_manager is None:
        _report_manager = ReportManager()
    return _report_manager
