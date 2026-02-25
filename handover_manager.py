"""
Модуль для управління передачами змін
"""
from datetime import datetime
from typing import List, Optional, Dict, Any

from database import get_session
from models import ShiftHandover, Shift, User
from logger import logger
from shift_manager import get_shift_manager
from guard_manager import get_guard_manager
from object_manager import get_object_manager


class HandoverManager:
    """Клас для управління передачами змін"""
    
    def __init__(self):
        """Ініціалізація менеджера передач"""
        pass
    
    def create_handover(
        self,
        shift_id: int,
        handover_by_id: int,
        handover_to_id: int
    ) -> Optional[int]:
        """
        Створення передачі зміни
        
        Args:
            shift_id: ID зміни
            handover_by_id: Telegram ID здавача
            handover_to_id: Telegram ID приймача
            
        Returns:
            ID створеної передачі або None при помилці
        """
        try:
            shift_manager = get_shift_manager()
            guard_manager = get_guard_manager()
            
            # Перевіряємо чи зміна існує та активна
            shift = shift_manager.get_shift(shift_id)
            if not shift:
                logger.log_error(f"Зміна {shift_id} не знайдена")
                return None
            
            if shift['status'] != 'ACTIVE':
                logger.log_error(f"Зміна {shift_id} не є активною")
                return None
            
            # Перевіряємо чи здавач є власником зміни
            if shift['guard_id'] != handover_by_id:
                logger.log_error(f"Здавач {handover_by_id} не є власником зміни {shift_id}")
                return None
            
            # Для об'єктів «один охоронець почасово» передача зміни заборонена
            object_manager = get_object_manager()
            obj = object_manager.get_object(shift['object_id'])
            if obj and obj.get('protection_type') == 'TEMPORARY_SINGLE':
                logger.log_error(f"Передача зміни заборонена для об'єкта {shift['object_id']} (тип почасово)")
                return None
            
            # Перевіряємо чи приймач активний
            if not guard_manager.is_guard_active(handover_to_id):
                logger.log_error(f"Приймач {handover_to_id} не активний")
                return None
            
            # Перевіряємо чи приймач не є адміністратором або контролером
            handover_to_guard = guard_manager.get_guard(handover_to_id)
            if handover_to_guard and handover_to_guard.get('role') == 'admin':
                logger.log_error(f"Неможливо передати зміну адміністратору {handover_to_id}")
                return None
            if handover_to_guard and handover_to_guard.get('role') == 'controller':
                logger.log_error(f"Неможливо передати зміну контролеру {handover_to_id}")
                return None
            
            # Перевіряємо чи здавач і приймач на одному об'єкті
            handover_by_obj = guard_manager.get_guard_object_id(handover_by_id)
            handover_to_obj = guard_manager.get_guard_object_id(handover_to_id)
            
            if handover_by_obj != handover_to_obj:
                logger.log_error(f"Здавач і приймач на різних об'єктах")
                return None
            
            # Формуємо зведення подій
            summary = shift_manager.generate_shift_summary(shift_id)
            
            with get_session() as session:
                handover = ShiftHandover(
                    shift_id=shift_id,
                    handover_by_id=handover_by_id,
                    handover_to_id=handover_to_id,
                    status='PENDING',
                    summary=summary
                )
                session.add(handover)
                session.flush()
                handover_id = handover.id
                session.commit()
                
                # Завершуємо зміну
                shift_manager.complete_shift(shift_id)
                shift_manager.mark_shift_handed_over(shift_id)
                
                logger.log_handover_created(handover_by_id, handover_id)
                return handover_id
        except Exception as e:
            logger.log_error(f"Помилка створення передачі: {e}")
            return None
    
    def accept_handover(
        self,
        handover_id: int,
        accepted_by_id: int,
        with_notes: bool = False,
        notes: Optional[str] = None
    ) -> bool:
        """
        Підтвердження передачі зміни
        
        Args:
            handover_id: ID передачі
            accepted_by_id: Telegram ID приймача
            with_notes: Чи є зауваження
            notes: Текст зауважень (якщо є)
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                handover = session.query(ShiftHandover).filter(
                    ShiftHandover.id == handover_id
                ).first()
                
                if not handover:
                    logger.log_error(f"Передача {handover_id} не знайдена")
                    return False
                
                if handover.status != 'PENDING':
                    logger.log_error(f"Передача {handover_id} вже підтверджена")
                    return False
                
                if handover.handover_to_id != accepted_by_id:
                    logger.log_error(f"Приймач {accepted_by_id} не є призначеним приймачем")
                    return False
                
                # Оновлюємо статус
                if with_notes and notes:
                    handover.status = 'ACCEPTED_WITH_NOTES'
                    handover.notes = notes.strip()
                else:
                    handover.status = 'ACCEPTED'
                
                handover.accepted_at = datetime.now()
                session.commit()
                
                logger.log_handover_accepted(accepted_by_id, handover_id, with_notes)
                
                # Якщо є зауваження - створюємо звіт
                if with_notes and notes:
                    from report_manager import get_report_manager
                    report_manager = get_report_manager()
                    report_manager.create_report_from_handover(handover_id)
                
                # Автоматично створюємо нову зміну для приймача
                shift_manager = get_shift_manager()
                new_shift_id = shift_manager.create_shift(accepted_by_id)
                if new_shift_id:
                    logger.log_info(f"Автоматично створено нову зміну {new_shift_id} для приймача {accepted_by_id} після прийняття передачі {handover_id}")
                
                return True
        except Exception as e:
            logger.log_error(f"Помилка підтвердження передачі: {e}")
            return False
    
    def cancel_handover(self, handover_id: int, cancelled_by_id: int, force: bool = False) -> bool:
        """
        Відміна передачі здавачем
        
        Args:
            handover_id: ID передачі
            cancelled_by_id: Telegram ID здавача
            force: Якщо True, дозволяє відмінити навіть прийняту передачу
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                handover = session.query(ShiftHandover).filter(
                    ShiftHandover.id == handover_id
                ).first()
                
                if not handover:
                    logger.log_error(f"Передача {handover_id} не знайдена")
                    return False
                
                if not force and handover.status != 'PENDING':
                    logger.log_error(f"Передача {handover_id} вже підтверджена, неможливо відмінити")
                    return False
                
                if handover.handover_by_id != cancelled_by_id:
                    logger.log_error(f"Здавач {cancelled_by_id} не є власником передачі {handover_id}")
                    return False
                
                shift_manager = get_shift_manager()
                
                # Якщо передача вже прийнята - видаляємо автоматично створену зміну приймача
                if handover.status in ('ACCEPTED', 'ACCEPTED_WITH_NOTES'):
                    active_shift = shift_manager.get_active_shift(handover.handover_to_id)
                    if active_shift:
                        # Видаляємо зміну приймача
                        shift_manager.delete_shift(active_shift['id'])
                        logger.log_info(f"Видалено зміну {active_shift['id']} приймача {handover.handover_to_id} при відміні передачі")
                    
                    # Видаляємо звіт, якщо він був створений
                    if handover.status == 'ACCEPTED_WITH_NOTES' and handover.report:
                        session.delete(handover.report)
                
                # Відновлюємо зміну до активного стану
                shift = shift_manager.get_shift(handover.shift_id)
                if shift:
                    shift_obj = session.query(Shift).filter(Shift.id == handover.shift_id).first()
                    if shift_obj:
                        shift_obj.status = 'ACTIVE'
                        shift_obj.end_time = None
                        session.flush()
                
                # Видаляємо передачу
                session.delete(handover)
                session.commit()
                
                logger.log_info(f"Передача {handover_id} відмінена здавачем {cancelled_by_id} (force={force})")
                return True
        except Exception as e:
            logger.log_error(f"Помилка відміни передачі: {e}")
            return False
    
    def reject_handover(self, handover_id: int, rejected_by_id: int, force: bool = False) -> bool:
        """
        Відміна прийняття передачі приймачем
        
        Args:
            handover_id: ID передачі
            rejected_by_id: Telegram ID приймача
            force: Якщо True, дозволяє відмінити навіть після заступу на зміну
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                handover = session.query(ShiftHandover).filter(
                    ShiftHandover.id == handover_id
                ).first()
                
                if not handover:
                    logger.log_error(f"Передача {handover_id} не знайдена")
                    return False
                
                if handover.status not in ('ACCEPTED', 'ACCEPTED_WITH_NOTES'):
                    logger.log_error(f"Передача {handover_id} не прийнята, неможливо відмінити прийняття")
                    return False
                
                if handover.handover_to_id != rejected_by_id:
                    logger.log_error(f"Приймач {rejected_by_id} не є призначеним приймачем передачі {handover_id}")
                    return False
                
                shift_manager = get_shift_manager()
                active_shift = shift_manager.get_active_shift(rejected_by_id)
                
                # Якщо приймач вже заступив на зміну
                if active_shift:
                    if not force:
                        logger.log_error(f"Приймач {rejected_by_id} вже заступив на зміну {active_shift['id']}, неможливо відмінити прийняття")
                        return False
                    
                    # Видаляємо зміну приймача
                    shift_manager.delete_shift(active_shift['id'])
                    logger.log_info(f"Видалено зміну {active_shift['id']} приймача {rejected_by_id} при відміні прийняття")
                
                # Видаляємо звіт, якщо він був створений (для ACCEPTED_WITH_NOTES)
                if handover.status == 'ACCEPTED_WITH_NOTES' and handover.report:
                    session.delete(handover.report)
                
                # Повертаємо статус до PENDING
                handover.status = 'PENDING'
                handover.accepted_at = None
                handover.notes = None
                
                session.commit()
                
                logger.log_info(f"Прийняття передачі {handover_id} відмінено приймачем {rejected_by_id} (force={force})")
                return True
        except Exception as e:
            logger.log_error(f"Помилка відміни прийняття передачі: {e}")
            return False
    
    def has_pending_handover_on_object(self, guard_id: int, object_id: int) -> bool:
        """
        Перевірка наявності PENDING передачі на об'єкті від охоронця
        
        Args:
            guard_id: Telegram ID охоронця
            object_id: ID об'єкта
            
        Returns:
            True якщо є PENDING передача на цьому об'єкті
        """
        try:
            with get_session() as session:
                # Знаходимо передачі від цього охоронця зі статусом PENDING
                handovers = session.query(ShiftHandover).join(Shift).filter(
                    ShiftHandover.handover_by_id == guard_id,
                    ShiftHandover.status == 'PENDING',
                    Shift.object_id == object_id
                ).all()
                
                return len(handovers) > 0
        except Exception as e:
            logger.log_error(f"Помилка перевірки PENDING передачі: {e}")
            return False
    
    def get_all_handovers_by_sender(self, handover_by_id: int, include_accepted: bool = True) -> List[Dict[str, Any]]:
        """
        Отримання всіх передач від здавача (включно з прийнятими)
        
        Args:
            handover_by_id: Telegram ID здавача
            include_accepted: Чи включати прийняті передачі
            
        Returns:
            Список передач
        """
        try:
            with get_session() as session:
                query = session.query(ShiftHandover).filter(
                    ShiftHandover.handover_by_id == handover_by_id
                )
                
                if not include_accepted:
                    query = query.filter(ShiftHandover.status == 'PENDING')
                
                handovers = query.order_by(ShiftHandover.handed_over_at.desc()).all()
                
                return [
                    {
                        'id': handover.id,
                        'shift_id': handover.shift_id,
                        'handover_by_id': handover.handover_by_id,
                        'handover_to_id': handover.handover_to_id,
                        'status': handover.status,
                        'summary': handover.summary,
                        'handed_over_at': handover.handed_over_at.isoformat()
                    }
                    for handover in handovers
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання передач здавача: {e}")
            return []
    
    def get_pending_handovers_by_sender(self, handover_by_id: int) -> List[Dict[str, Any]]:
        """
        Отримання очікуючих передач для здавача
        
        Args:
            handover_by_id: Telegram ID здавача
            
        Returns:
            Список очікуючих передач
        """
        try:
            with get_session() as session:
                handovers = session.query(ShiftHandover).filter(
                    ShiftHandover.handover_by_id == handover_by_id,
                    ShiftHandover.status == 'PENDING'
                ).order_by(ShiftHandover.handed_over_at.desc()).all()
                
                return [
                    {
                        'id': handover.id,
                        'shift_id': handover.shift_id,
                        'handover_by_id': handover.handover_by_id,
                        'handover_to_id': handover.handover_to_id,
                        'summary': handover.summary,
                        'handed_over_at': handover.handed_over_at.isoformat()
                    }
                    for handover in handovers
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання очікуючих передач здавача: {e}")
            return []
    
    def get_pending_handovers(self, handover_to_id: int) -> List[Dict[str, Any]]:
        """
        Отримання очікуючих передач для приймача
        
        Args:
            handover_to_id: Telegram ID приймача
            
        Returns:
            Список очікуючих передач
        """
        try:
            guard_manager = get_guard_manager()
            
            # Перевіряємо чи приймач не є адміністратором
            guard = guard_manager.get_guard(handover_to_id)
            if guard and guard.get('role') == 'admin':
                # Адміністратори не можуть приймати зміни
                return []
            
            object_id = guard_manager.get_guard_object_id(handover_to_id)
            
            if not object_id:
                return []
            
            with get_session() as session:
                # Отримуємо передачі тільки з об'єкта приймача
                handovers = session.query(ShiftHandover).join(Shift).filter(
                    ShiftHandover.handover_to_id == handover_to_id,
                    ShiftHandover.status == 'PENDING',
                    Shift.object_id == object_id
                ).order_by(ShiftHandover.handed_over_at.desc()).all()
                
                return [
                    {
                        'id': handover.id,
                        'shift_id': handover.shift_id,
                        'handover_by_id': handover.handover_by_id,
                        'handover_to_id': handover.handover_to_id,
                        'summary': handover.summary,
                        'handed_over_at': handover.handed_over_at.isoformat()
                    }
                    for handover in handovers
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання очікуючих передач: {e}")
            return []
    
    def get_handover(self, handover_id: int) -> Optional[Dict[str, Any]]:
        """
        Отримання інформації про передачу
        
        Args:
            handover_id: ID передачі
            
        Returns:
            Словник з даними передачі або None
        """
        try:
            with get_session() as session:
                handover = session.query(ShiftHandover).filter(
                    ShiftHandover.id == handover_id
                ).first()
                
                if not handover:
                    return None
                
                return {
                    'id': handover.id,
                    'shift_id': handover.shift_id,
                    'handover_by_id': handover.handover_by_id,
                    'handover_to_id': handover.handover_to_id,
                    'status': handover.status,
                    'summary': handover.summary,
                    'notes': handover.notes,
                    'handed_over_at': handover.handed_over_at.isoformat(),
                    'accepted_at': handover.accepted_at.isoformat() if handover.accepted_at else None
                }
        except Exception as e:
            logger.log_error(f"Помилка отримання передачі: {e}")
            return None
    
    def get_handovers(
        self,
        handover_by_id: Optional[int] = None,
        handover_to_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Отримання списку передач з фільтрами

        Args:
            handover_by_id: ID здавача для фільтрації
            handover_to_id: ID приймача для фільтрації
            status: Статус для фільтрації
            limit: Максимальна кількість записів
            offset: Зміщення для пагінації
        """
        try:
            with get_session() as session:
                query = session.query(ShiftHandover)

                if handover_by_id:
                    query = query.filter(ShiftHandover.handover_by_id == handover_by_id)

                if handover_to_id:
                    query = query.filter(ShiftHandover.handover_to_id == handover_to_id)

                if status:
                    query = query.filter(ShiftHandover.status == status)

                query = query.order_by(ShiftHandover.handed_over_at.desc())

                if offset:
                    query = query.offset(offset)
                if limit:
                    query = query.limit(limit)

                handovers = query.all()
                
                return [
                    {
                        'id': handover.id,
                        'shift_id': handover.shift_id,
                        'handover_by_id': handover.handover_by_id,
                        'handover_to_id': handover.handover_to_id,
                        'status': handover.status,
                        'summary': handover.summary[:200] + '...' if len(handover.summary) > 200 else handover.summary,
                        'notes': handover.notes,
                        'handed_over_at': handover.handed_over_at.isoformat(),
                        'accepted_at': handover.accepted_at.isoformat() if handover.accepted_at else None
                    }
                    for handover in handovers
                ]
        except Exception as e:
            logger.log_error(f"Помилка отримання передач: {e}")
            return []
    
    def update_handover(
        self,
        handover_id: int,
        summary: Optional[str] = None,
        notes: Optional[str] = None,
        status: Optional[str] = None
    ) -> bool:
        """
        Редагування передачі
        
        Args:
            handover_id: ID передачі
            summary: Новий текст зведення
            notes: Новий текст зауважень
            status: Новий статус
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                handover = session.query(ShiftHandover).filter(ShiftHandover.id == handover_id).first()
                if not handover:
                    logger.log_error(f"Передача {handover_id} не знайдена")
                    return False
                
                if summary is not None:
                    handover.summary = summary.strip()
                if notes is not None:
                    handover.notes = notes.strip() if notes.strip() else None
                if status is not None:
                    if status not in ('PENDING', 'ACCEPTED', 'ACCEPTED_WITH_NOTES'):
                        logger.log_error(f"Невірний статус передачі: {status}")
                        return False
                    handover.status = status
                
                session.commit()
                logger.log_info(f"Оновлено передачу {handover_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка оновлення передачі: {e}")
            return False
    
    def delete_handover(self, handover_id: int) -> bool:
        """
        Видалення передачі
        
        Args:
            handover_id: ID передачі
            
        Returns:
            True якщо успішно
        """
        try:
            with get_session() as session:
                handover = session.query(ShiftHandover).filter(ShiftHandover.id == handover_id).first()
                if not handover:
                    logger.log_error(f"Передача {handover_id} не знайдена")
                    return False
                
                # Видаляємо передачу (звіт видалиться каскадно через foreign key)
                session.delete(handover)
                session.commit()
                logger.log_info(f"Видалено передачу {handover_id}")
                return True
        except Exception as e:
            logger.log_error(f"Помилка видалення передачі: {e}")
            return False


# Глобальний екземпляр менеджера передач
_handover_manager: Optional[HandoverManager] = None


def get_handover_manager() -> HandoverManager:
    """Отримання глобального менеджера передач"""
    global _handover_manager
    if _handover_manager is None:
        _handover_manager = HandoverManager()
    return _handover_manager
