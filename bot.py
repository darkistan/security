#!/usr/bin/env python3
"""
Telegram бот для системи ведення змін охоронців
"""
import os
import sys
import asyncio
import logging
import warnings
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Додаємо поточну директорію в Python path
if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.error import Conflict, TimedOut, NetworkError, RetryAfter, BadRequest

from auth import auth_manager
from logger import logger
from csrf_manager import csrf_manager
from input_validator import input_validator
from database import init_database, get_session
from models import User
from shift_manager import get_shift_manager
from event_manager import get_event_manager
from handover_manager import get_handover_manager
from guard_manager import get_guard_manager
from object_manager import get_object_manager
from report_manager import get_report_manager
from points_manager import get_points_manager
from schedule_manager import get_schedule_manager
import calendar
from datetime import datetime, date

# Завантажуємо змінні середовища
load_dotenv("config.env")

# Конфігурація
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Глобальні змінні для зберігання стану створення
shift_creation_state: Dict[int, Dict[str, Any]] = {}
event_creation_state: Dict[int, Dict[str, Any]] = {}
handover_state: Dict[int, Dict[str, Any]] = {}

# Константи для пагінації
SHIFTS_PER_PAGE = 5  # Кількість змін на сторінку

# Назви місяців українською (нижній регістр) для графіка в боті; індекс 0 не використовується
MONTH_NAMES_UA = (
    '', 'січень', 'лютий', 'березень', 'квітень', 'травень', 'червень',
    'липень', 'серпень', 'вересень', 'жовтень', 'листопад', 'грудень'
)


async def safe_edit_message_text(query, text: str, reply_markup=None, parse_mode='HTML', **kwargs):
    """
    Безпечне редагування повідомлення з обробкою застарілих queries
    
    Args:
        query: CallbackQuery об'єкт
        text: Текст повідомлення
        reply_markup: Клавіатура (опціонально)
        parse_mode: Режим парсингу (за замовчуванням HTML)
        **kwargs: Інші параметри для edit_message_text
        
    Returns:
        True якщо успішно, False якщо query застарів
    """
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs)
        return True
    except BadRequest as e:
        error_msg = str(e).lower()
        if 'query is too old' in error_msg or 'query id is invalid' in error_msg:
            try:
                await query.answer("⏰ Запит застарів. Будь ласка, оновіть меню.", show_alert=False)
            except:
                pass
            return False
        else:
            logger.log_error(f"Помилка редагування повідомлення: {e}")
            try:
                await query.answer("❌ Помилка оновлення повідомлення.", show_alert=False)
            except:
                pass
            return False
    except Exception as e:
        logger.log_error(f"Помилка редагування повідомлення: {e}")
        try:
            await query.answer("❌ Помилка оновлення повідомлення.", show_alert=False)
        except:
            pass
        return False


def create_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """
    Створення головного меню залежно від ролі (guard, senior, controller, admin).
    """
    buttons = []
    
    if not auth_manager.is_user_allowed(user_id):
        buttons.append([InlineKeyboardButton("🔐 Запросити доступ", callback_data="request_access")])
        return InlineKeyboardMarkup(buttons)
    
    guard_manager = get_guard_manager()
    guard = guard_manager.get_guard(user_id)
    role = (guard or {}).get('role', 'guard')
    
    # Контролер: «Хто зараз на зміні», «Графік роботи» (без блоку «Ваші робочі дні»), «Головне меню»
    if role == 'controller':
        buttons.append([InlineKeyboardButton("👥 Хто зараз на зміні", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "who_on_shift"))])
        buttons.append([InlineKeyboardButton("📅 Графік роботи", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "view_schedule"))])
        buttons.append([InlineKeyboardButton("🏠 Головне меню", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "main_menu"))])
        return InlineKeyboardMarkup(buttons)
    
    # guard, senior, admin — меню охоронця (для senior та admin додаємо «Хто зараз на зміні»)
    shift_manager = get_shift_manager()
    active_shift = shift_manager.get_active_shift(user_id)
    object_id = guard_manager.get_guard_object_id(user_id) if guard_manager else None
    active_on_object = shift_manager.get_active_shift_for_object(object_id) if object_id else None
    object_manager = get_object_manager()
    obj = object_manager.get_object(object_id) if object_id else None
    protection_type = (obj or {}).get('protection_type', 'SHIFT')
    is_temporary_single = protection_type == 'TEMPORARY_SINGLE'

    handover_manager = get_handover_manager()
    all_sent = handover_manager.get_all_handovers_by_sender(user_id, include_accepted=True)
    pending_sent = [h for h in all_sent if h['status'] == 'PENDING']
    pending_to_me = handover_manager.get_pending_handovers(user_id)

    if not active_shift and not active_on_object and not pending_sent and not pending_to_me:
        buttons.append([InlineKeyboardButton("🟢 Заступив на зміну", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "start_shift"))])

    buttons.append([InlineKeyboardButton("📝 Журнал подій", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "add_event"))])

    if is_temporary_single:
        if active_shift:
            buttons.append([InlineKeyboardButton("🔴 Завершити зміну", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "end_shift"))])
    else:
        if active_shift:
            buttons.append([InlineKeyboardButton("🔄 Передати зміну", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "handover_shift"))])
        if not active_shift and not pending_sent:
            buttons.append([InlineKeyboardButton("✅ Прийняти зміну", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "accept_handover"))])
        if pending_sent:
            buttons.append([InlineKeyboardButton("❌ Відмінити передачу", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "cancel_my_handover"))])

    buttons.append([InlineKeyboardButton("📋 Мої зміни", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "my_shifts"))])
    # Графік роботи — тільки для охоронця та старшого, завжди доступний
    if role in ('guard', 'senior'):
        buttons.append([InlineKeyboardButton("📅 Графік роботи", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "view_schedule"))])
    # Старший та адмін — кнопка «Хто зараз на зміні»
    if role in ('senior', 'admin'):
        buttons.append([InlineKeyboardButton("👥 Хто зараз на зміні", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "who_on_shift"))])
    buttons.append([InlineKeyboardButton("🏠 Головне меню", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "main_menu"))])
    
    return InlineKeyboardMarkup(buttons)


def get_shift_status_line(user_id: int) -> str:
    """Короткий рядок статусу зміни та балів для відображення у всіх меню (порожній для неавторизованих)."""
    if not auth_manager.is_user_allowed(user_id):
        return ""
    guard_manager = get_guard_manager()
    guard = guard_manager.get_guard(user_id)
    role = (guard or {}).get('role', 'guard')

    # Контролер: шапка без зміни — бали, система, об'єкт, роль
    if role == 'controller' and guard:
        object_manager = get_object_manager()
        obj = object_manager.get_object(guard['object_id'])
        obj_name = obj['name'] if obj else f"Об'єкт #{guard['object_id']}"
        balance = get_points_manager().get_balance(user_id)
        if balance > 0:
            bal_str = f"🟢 +{balance}"
        elif balance < 0:
            bal_str = f"🔴 {balance}"
        else:
            bal_str = "0"
        return (
            f"📊 Бали: {bal_str}\n"
            f"👮 <b>Система ведення змін охоронців</b>  🏢 <b>Об'єкт:</b> {obj_name}  <b>Контролер:</b>\n\n"
        )

    shift_manager = get_shift_manager()
    active_shift = shift_manager.get_active_shift(user_id)
    lines = []
    if active_shift:
        t = datetime.fromisoformat(active_shift['start_time']).strftime('%H:%M')
        lines.append(f"🟢 <b>Ваша зміна активна</b> (№{active_shift['id']}, з {t})")
    else:
        lines.append("⚪ <b>Зараз ви не на зміні</b>")
    balance = get_points_manager().get_balance(user_id)
    if balance > 0:
        lines.append(f"📊 Бали: 🟢 +{balance}")
    elif balance < 0:
        lines.append(f"📊 Бали: 🔴 {balance}")
    else:
        lines.append("📊 Бали: 0")
    return "\n".join(lines) + "\n\n"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /start - головне меню"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    
    keyboard = create_menu_keyboard(user_id)
    
    if auth_manager.is_user_allowed(user_id):
        guard_manager = get_guard_manager()
        guard = guard_manager.get_guard(user_id)

        if guard and (guard.get('role') == 'controller'):
            # Контролер: шапка вже в get_shift_status_line, тут лише підпис та дія
            message_text = f"👤 <b>Контролер:</b> {guard['full_name']}\n\nОберіть дію:"
            message_text = get_shift_status_line(user_id) + message_text
        elif guard:
            object_manager = get_object_manager()
            obj = object_manager.get_object(guard['object_id'])
            obj_name = obj['name'] if obj else f"Об'єкт #{guard['object_id']}"

            message_text = (
                f"👮 <b>Система ведення змін охоронців</b>\n\n"
                f"👤 <b>Охоронець:</b> {guard['full_name']}\n"
                f"🏢 <b>Об'єкт:</b> {obj_name}\n\n"
            )
            shift_manager = get_shift_manager()
            active_shift = shift_manager.get_active_shift(user_id)

            if active_shift:
                start_time = datetime.fromisoformat(active_shift['start_time']).strftime('%d.%m.%Y %H:%M')
                duration = datetime.now() - datetime.fromisoformat(active_shift['start_time'])
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                message_text += (
                    f"🟢 <b>Активна зміна</b>\n"
                    f"🆔 ID: #{active_shift['id']}\n"
                    f"🕐 Початок: {start_time}\n"
                    f"⏱️ Тривалість: {hours} год. {minutes} хв.\n\n"
                )
            else:
                message_text += "⚪ Активної зміни немає\n\n"
            message_text += "Оберіть дію:"
            message_text = get_shift_status_line(user_id) + message_text
        else:
            message_text = "👮 <b>Система ведення змін охоронців</b>\n\n"
            message_text = get_shift_status_line(user_id) + message_text + "Оберіть дію:"
    else:
        message_text = (
            "🔐 <b>Доступ до системи</b>\n\n"
            "Для отримання доступу натисніть кнопку 'Запросити доступ'.\n"
            "Ваш запит буде відправлено адміністратору."
        )
    
    await update.message.reply_text(message_text, reply_markup=keyboard, parse_mode='HTML')


async def start_shift_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка натискання 'Заступив на зміну'"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if not auth_manager.is_user_allowed(user_id):
        await query.edit_message_text("❌ У вас немає доступу до системи.")
        return
    
    guard_manager = get_guard_manager()
    
    # Перевіряємо чи охоронець активний
    if not guard_manager.is_guard_active(user_id):
        await query.edit_message_text("❌ Ваш обліковий запис деактивовано. Зверніться до адміністратора.")
        return
    
    # Перевіряємо чи є об'єкт у профілі
    object_id = guard_manager.get_guard_object_id(user_id)
    if not object_id:
        await query.edit_message_text("❌ У вашому профілі не встановлено об'єкт. Зверніться до адміністратора.")
        return
    
    # Перевіряємо чи немає активної зміни
    shift_manager = get_shift_manager()
    active_shift = shift_manager.get_active_shift(user_id)
    if active_shift:
        await query.edit_message_text("⚠️ У вас вже є активна зміна. Спочатку завершіть поточну зміну.")
        return
    
    # Перевіряємо чи немає PENDING передачі на цьому об'єкті
    handover_manager = get_handover_manager()
    if handover_manager.has_pending_handover_on_object(user_id, object_id):
        message_text = (
            "⚠️ <b>Неможливо створити нову зміну</b>\n\n"
            "Ви передали зміну, яка очікує підтвердження. "
            "Нова зміна на цьому об'єкті буде доступна після прийняття або відміни передачі.\n\n"
            "Використайте кнопку '❌ Відмінити передачу' в головному меню, якщо потрібно скасувати передачу."
        )
        keyboard = create_menu_keyboard(user_id)
        await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)
        return
    
    # Створюємо зміну
    shift_id = shift_manager.create_shift(user_id)
    if shift_id:
        object_manager = get_object_manager()
        obj = object_manager.get_object(object_id)
        obj_name = obj['name'] if obj else f"Об'єкт #{object_id}"
        
        message_text = (
            f"✅ <b>Зміна розпочата!</b>\n\n"
            f"🆔 <b>ID зміни:</b> #{shift_id}\n"
            f"🏢 <b>Об'єкт:</b> {obj_name}\n"
            f"🕐 <b>Початок:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Тепер ви можете додавати події до журналу."
        )
    else:
        message_text = "❌ Помилка створення зміни. Спробуйте пізніше."
    
    keyboard = create_menu_keyboard(user_id)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


async def end_shift_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка натискання 'Завершити зміну' (режим один охоронець почасово)."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not auth_manager.is_user_allowed(user_id):
        await query.edit_message_text("❌ У вас немає доступу до системи.")
        return
    shift_manager = get_shift_manager()
    active_shift = shift_manager.get_active_shift(user_id)
    if not active_shift:
        keyboard = create_menu_keyboard(user_id)
        await safe_edit_message_text(query, get_shift_status_line(user_id) + "❌ У вас немає активної зміни.", reply_markup=keyboard)
        return
    object_manager = get_object_manager()
    obj = object_manager.get_object(active_shift['object_id'])
    if not obj or obj.get('protection_type') != 'TEMPORARY_SINGLE':
        keyboard = create_menu_keyboard(user_id)
        await safe_edit_message_text(
            query,
            get_shift_status_line(user_id) + "❌ Завершення зміни доступне лише для об'єктів з типом «Один охоронець почасово».",
            reply_markup=keyboard,
        )
        return
    success = shift_manager.complete_shift(active_shift['id'])
    if success:
        end_str = datetime.now().strftime('%d.%m.%Y %H:%M')
        message_text = (
            f"✅ <b>Зміну завершено</b>\n\n"
            f"🆔 ID зміни: #{active_shift['id']}\n"
            f"🕐 Завершення: {end_str}"
        )
    else:
        message_text = "❌ Помилка завершення зміни. Спробуйте пізніше."
    keyboard = create_menu_keyboard(user_id)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


async def add_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка натискання 'Журнал подій'"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if not auth_manager.is_user_allowed(user_id):
        await query.edit_message_text("❌ У вас немає доступу до системи.")
        return
    
    # Перевіряємо наявність активної зміни
    shift_manager = get_shift_manager()
    active_shift = shift_manager.get_active_shift(user_id)
    if not active_shift:
        await query.edit_message_text("❌ У вас немає активної зміни. Спочатку заступіть на зміну.")
        return
    
    # Показуємо вибір типу події: Інцидент, Вимкнення світла, Відновлення світла
    buttons = [
        [InlineKeyboardButton("⚠️ Інцидент", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "event_type:INCIDENT"))],
        [InlineKeyboardButton("💡 Вимкнення світла", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "event_type:POWER_OFF"))],
        [InlineKeyboardButton("🔆 Відновлення світла", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "event_type:POWER_ON"))],
        [InlineKeyboardButton("🏠 Головне меню", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "main_menu"))]
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    
    message_text = (
        f"📝 <b>Журнал подій охоронця</b>\n\n"
        f"🆔 <b>Зміна:</b> #{active_shift['id']}\n\n"
        f"Оберіть тип події:"
    )
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


async def event_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка вибору типу події"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Витягуємо тип події з callback_data
    callback_data = csrf_manager.extract_callback_data(user_id, query.data)
    if not callback_data:
        await query.answer("❌ Помилка безпеки. Спробуйте ще раз.", show_alert=True)
        return
    
    if not callback_data.startswith("event_type:"):
        return
    
    event_type = callback_data.split(":", 1)[1]
    
    # Перевіряємо наявність активної зміни
    shift_manager = get_shift_manager()
    active_shift = shift_manager.get_active_shift(user_id)
    if not active_shift:
        await query.edit_message_text("❌ У вас немає активної зміни.")
        return
    
    # Зберігаємо стан
    event_creation_state[user_id] = {
        'shift_id': active_shift['id'],
        'event_type': event_type
    }
    
    event_types_ua = {
        'INCIDENT': 'Інцидент',
        'POWER_OFF': 'Вимкнення світла',
        'POWER_ON': 'Відновлення світла',
    }
    
    # Вимкнення/відновлення світла — підтвердження перед записом, фіксація часу автоматично
    if event_type in ('POWER_OFF', 'POWER_ON'):
        confirm_btn = InlineKeyboardButton("✅ Так", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, f"event_confirm:{event_type}"))
        cancel_btn = InlineKeyboardButton("❌ Ні", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "cancel_event"))
        keyboard = InlineKeyboardMarkup([[confirm_btn], [cancel_btn]])
        message_text = (
            f"📝 <b>{event_types_ua.get(event_type, event_type)}</b>\n\n"
            f"Підтвердити запис? Час буде зафіксовано автоматично."
        )
        await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)
        return
    
    message_text = (
        f"📝 <b>Додавання події</b>\n\n"
        f"Тип: {event_types_ua.get(event_type, event_type)}\n\n"
        f"Додайте текст опису події (нештатна ситуація або поломка):"
    )
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка текстових повідомлень (опис події або зауваження)"""
    user_id = update.message.from_user.id
    text = update.message.text

    # Перевіряємо чи це опис події
    if user_id in event_creation_state:
        await handle_event_description(update, context)
        return

    # Перевіряємо чи це зауваження для передачі
    if user_id in handover_state:
        await handle_handover_notes(update, context)
        return

    # Текст надіслано не в контексті очікуваного вводу — відповідь із підказкою та контактами
    message_text = (
        "⚠️ <b>Це повідомлення не буде доставлено та оброблено.</b>\n\n"
        "Будь ласка, користуйтесь лише кнопками бота нижче. "
        "Щоб відкрити головне меню — натисніть /start.\n\n"
    )
    with get_session() as session:
        contacts = (
            session.query(User)
            .filter(User.role.in_(['senior', 'controller']), User.is_active == True)
            .order_by(User.role.desc(), User.full_name)
            .all()
        )
        if contacts:
            message_text += "📞 <b>Для прямого зв'язку використовуйте контакти старшого та контролера:</b>\n"
            role_ua = {'senior': 'Старший', 'controller': 'Контролер'}
            for u in contacts:
                name = (u.full_name or '').strip() or '—'
                phone = (u.phone or '').strip() or '—'
                message_text += f"• {role_ua.get(u.role, u.role)}: {name} — {phone}\n"
        else:
            message_text += "📞 <b>Для прямого зв'язку</b> — контакти старшого та контролера не налаштовані.\n"

    keyboard = create_menu_keyboard(user_id)
    await update.message.reply_text(message_text, reply_markup=keyboard, parse_mode='HTML')


async def handle_event_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка введення опису події"""
    user_id = update.message.from_user.id
    
    if user_id not in event_creation_state:
        return
    
    description = update.message.text
    
    state = event_creation_state[user_id]
    shift_id = state['shift_id']
    event_type = state['event_type']
    
    # Створюємо подію
    event_manager = get_event_manager()
    event_id = event_manager.create_event(shift_id, event_type, description, user_id)
    
    if event_id:
        await notify_event_to_seniors_and_controllers(context, event_id)
        event_types_ua = {
            'INCIDENT': 'Інцидент',
            'POWER_OFF': 'Вимкнення світла',
            'POWER_ON': 'Відновлення світла',
        }
        
        message_text = (
            f"✅ <b>Подію додано до журналу!</b>\n\n"
            f"🆔 <b>ID події:</b> #{event_id}\n"
            f"📋 <b>Тип:</b> {event_types_ua.get(event_type, event_type)}\n"
            f"📝 <b>Опис:</b> {description[:100]}{'...' if len(description) > 100 else ''}"
        )
    else:
        message_text = "❌ Помилка додавання події. Спробуйте пізніше."
    
    # Очищаємо стан
    if user_id in event_creation_state:
        del event_creation_state[user_id]
    
    keyboard = create_menu_keyboard(user_id)
    await update.message.reply_text(get_shift_status_line(user_id) + message_text, reply_markup=keyboard, parse_mode='HTML')


async def handover_shift_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка натискання 'Передати зміну'"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if not auth_manager.is_user_allowed(user_id):
        await query.edit_message_text("❌ У вас немає доступу до системи.")
        return
    
    # Перевіряємо наявність активної зміни
    shift_manager = get_shift_manager()
    active_shift = shift_manager.get_active_shift(user_id)
    if not active_shift:
        await query.edit_message_text("❌ У вас немає активної зміни.")
        return
    
    # Отримуємо список активних охоронців з того ж об'єкта
    guard_manager = get_guard_manager()
    object_id = guard_manager.get_guard_object_id(user_id)
    guards = guard_manager.get_active_guards(object_id)
    
    # Виключаємо себе, адміністраторів та контролерів зі списку
    guards = [g for g in guards if g['user_id'] != user_id and g['role'] != 'admin' and g['role'] != 'controller']
    
    if not guards:
        await query.edit_message_text("❌ Немає доступних приймачів на вашому об'єкті.")
        return
    
    # Формуємо кнопки з приймачами
    buttons = []
    for guard in guards:
        button_text = f"👤 {guard['full_name']}"
        callback_data = csrf_manager.add_csrf_to_callback_data(user_id, f"select_handover_to:{guard['user_id']}")
        buttons.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    buttons.append([InlineKeyboardButton("🏠 Головне меню", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "main_menu"))])
    keyboard = InlineKeyboardMarkup(buttons)
    
    message_text = (
        f"🔄 <b>Передача зміни</b>\n\n"
        f"🆔 <b>Зміна:</b> #{active_shift['id']}\n\n"
        f"Оберіть приймача зміни:"
    )
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


async def select_handover_to_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка вибору приймача зміни"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Витягуємо ID приймача з callback_data
    callback_data = csrf_manager.extract_callback_data(user_id, query.data)
    if not callback_data:
        await query.answer("❌ Помилка безпеки. Спробуйте ще раз.", show_alert=True)
        return
    
    if not callback_data.startswith("select_handover_to:"):
        return
    
    handover_to_id = int(callback_data.split(":", 1)[1])
    
    # Перевіряємо наявність активної зміни
    shift_manager = get_shift_manager()
    active_shift = shift_manager.get_active_shift(user_id)
    if not active_shift:
        await query.edit_message_text("❌ У вас немає активної зміни.")
        return
    
    # Створюємо передачу
    handover_manager = get_handover_manager()
    handover_id = handover_manager.create_handover(active_shift['id'], user_id, handover_to_id)
    
    if handover_id:
        guard_manager = get_guard_manager()
        handover_to = guard_manager.get_guard(handover_to_id)
        handover_to_name = handover_to['full_name'] if handover_to else f"ID: {handover_to_id}"
        
        message_text = (
            f"✅ <b>Зміну передано!</b>\n\n"
            f"🆔 <b>ID передачі:</b> #{handover_id}\n"
            f"👤 <b>Приймач:</b> {handover_to_name}\n\n"
            f"Очікується підтвердження від приймача."
        )
    else:
        message_text = "❌ Помилка передачі зміни. Спробуйте пізніше."
    
    keyboard = create_menu_keyboard(user_id)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


async def accept_handover_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка натискання 'Прийняти зміну'"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if not auth_manager.is_user_allowed(user_id):
        await query.edit_message_text("❌ У вас немає доступу до системи.")
        return
    
    # Отримуємо очікуючі передачі
    handover_manager = get_handover_manager()
    pending_handovers = handover_manager.get_pending_handovers(user_id)
    
    if not pending_handovers:
        await query.edit_message_text("📭 У вас немає очікуючих передач.")
        return
    
    # Показуємо список передач
    buttons = []
    for handover in pending_handovers[:10]:  # Максимум 10 передач
        guard_manager = get_guard_manager()
        handover_by = guard_manager.get_guard(handover['handover_by_id'])
        handover_by_name = handover_by['full_name'] if handover_by else f"ID: {handover['handover_by_id']}"
        
        time_str = datetime.fromisoformat(handover['handed_over_at']).strftime('%d.%m %H:%M')
        button_text = f"#{handover['shift_id']} від {handover_by_name} ({time_str})"
        callback_data = csrf_manager.add_csrf_to_callback_data(user_id, f"view_handover:{handover['id']}")
        buttons.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    
    buttons.append([InlineKeyboardButton("🏠 Головне меню", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "main_menu"))])
    keyboard = InlineKeyboardMarkup(buttons)
    
    message_text = (
        f"✅ <b>Прийняття зміни</b>\n\n"
        f"Оберіть передачу для перегляду:"
    )
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


async def view_handover_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка перегляду передачі"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Витягуємо ID передачі з callback_data
    callback_data = csrf_manager.extract_callback_data(user_id, query.data)
    if not callback_data:
        await query.answer("❌ Помилка безпеки. Спробуйте ще раз.", show_alert=True)
        return
    
    if not callback_data.startswith("view_handover:"):
        return
    
    handover_id = int(callback_data.split(":", 1)[1])
    
    # Отримуємо інформацію про передачу
    handover_manager = get_handover_manager()
    handover = handover_manager.get_handover(handover_id)
    
    if not handover or handover['handover_to_id'] != user_id:
        await query.edit_message_text("❌ Передача не знайдена або ви не є приймачем.")
        return
    
    guard_manager = get_guard_manager()
    handover_by = guard_manager.get_guard(handover['handover_by_id'])
    handover_by_name = handover_by['full_name'] if handover_by else f"ID: {handover['handover_by_id']}"
    
    message_text = (
        f"📋 <b>Зведення зміни</b>\n\n"
        f"{handover['summary']}\n\n"
        f"👤 <b>Здавач:</b> {handover_by_name}\n"
        f"🕐 <b>Передано:</b> {datetime.fromisoformat(handover['handed_over_at']).strftime('%d.%m.%Y %H:%M')}"
    )
    
    buttons = []
    
    # Якщо передача очікує підтвердження
    if handover['status'] == 'PENDING':
        buttons.append([InlineKeyboardButton("✅ Прийняв", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, f"accept_handover_ok:{handover_id}"))])
        buttons.append([InlineKeyboardButton("⚠️ Прийняв із зауваженнями", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, f"accept_handover_notes:{handover_id}"))])
    
    buttons.append([InlineKeyboardButton("🏠 Головне меню", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "main_menu"))])
    keyboard = InlineKeyboardMarkup(buttons)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


async def accept_handover_ok_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка підтвердження передачі без зауважень"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Витягуємо ID передачі з callback_data
    callback_data = csrf_manager.extract_callback_data(user_id, query.data)
    if not callback_data:
        await query.answer("❌ Помилка безпеки. Спробуйте ще раз.", show_alert=True)
        return
    
    if not callback_data.startswith("accept_handover_ok:"):
        return
    
    handover_id = int(callback_data.split(":", 1)[1])
    
    # Підтверджуємо передачу
    handover_manager = get_handover_manager()
    success = handover_manager.accept_handover(handover_id, user_id, with_notes=False)
    
    if success:
        await notify_handover_completed_to_seniors_and_controllers(context, handover_id)
        shift_manager = get_shift_manager()
        active_shift = shift_manager.get_active_shift(user_id)
        if active_shift:
            message_text = (
                "✅ <b>Зміну прийнято!</b>\n\n"
                f"Передача завершена успішно.\n"
                f"🆔 <b>Ваша нова зміна:</b> #{active_shift['id']}"
            )
        else:
            message_text = (
                "✅ <b>Зміну прийнято!</b>\n\n"
                "Передача завершена успішно.\n\n"
                "⚠️ <b>Увага!</b> Нова зміна створена автоматично. "
                "Перевірте статус в меню '📋 Мої зміни'."
            )
    else:
        message_text = "❌ Помилка підтвердження передачі. Спробуйте пізніше."
    
    keyboard = create_menu_keyboard(user_id)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)
    if success:
        await notify_handover_parties_after_accept(context, handover_id, user_id)


async def accept_handover_notes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка підтвердження передачі з зауваженнями"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Витягуємо ID передачі з callback_data
    callback_data = csrf_manager.extract_callback_data(user_id, query.data)
    if not callback_data:
        await query.answer("❌ Помилка безпеки. Спробуйте ще раз.", show_alert=True)
        return
    
    if not callback_data.startswith("accept_handover_notes:"):
        return
    
    handover_id = int(callback_data.split(":", 1)[1])
    
    # Зберігаємо стан для введення зауважень
    handover_state[user_id] = {'handover_id': handover_id}
    
    message_text = (
        "⚠️ <b>Прийняття з зауваженнями</b>\n\n"
        "Введіть текст зауважень:"
    )
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text)


async def handle_handover_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка введення зауважень"""
    user_id = update.message.from_user.id
    
    if user_id not in handover_state:
        return
    
    notes = update.message.text
    
    state = handover_state[user_id]
    handover_id = state['handover_id']
    
    # Підтверджуємо передачу з зауваженнями
    handover_manager = get_handover_manager()
    success = handover_manager.accept_handover(handover_id, user_id, with_notes=True, notes=notes)
    
    if success:
        await notify_handover_completed_to_seniors_and_controllers(context, handover_id)
        # Створюємо звіт та відправляємо детальний звіт адміністраторам
        report_manager = get_report_manager()
        report_id = report_manager.create_report_from_handover(handover_id)
        if report_id:
            await send_report_to_admins(context, report_id)
        shift_manager = get_shift_manager()
        active_shift = shift_manager.get_active_shift(user_id)
        if active_shift:
            message_text = (
                "✅ <b>Зміну прийнято з зауваженнями!</b>\n\n"
                f"Передача завершена. Звіт сформовано та відправлено адміністраторам.\n"
                f"🆔 <b>Ваша нова зміна:</b> #{active_shift['id']}"
            )
        else:
            message_text = (
                "✅ <b>Зміну прийнято з зауваженнями!</b>\n\n"
                "Передача завершена. Звіт сформовано та відправлено адміністраторам.\n\n"
                "⚠️ <b>Увага!</b> Нова зміна створена автоматично. "
                "Перевірте статус в меню '📋 Мої зміни'."
            )
    else:
        message_text = "❌ Помилка підтвердження передачі. Спробуйте пізніше."
    
    # Очищаємо стан
    if user_id in handover_state:
        del handover_state[user_id]
    
    keyboard = create_menu_keyboard(user_id)
    await update.message.reply_text(get_shift_status_line(user_id) + message_text, reply_markup=keyboard, parse_mode='HTML')
    if success:
        await notify_handover_parties_after_accept(context, handover_id, user_id)


async def cancel_my_handover_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка відміни передачі здавачем"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if not auth_manager.is_user_allowed(user_id):
        await query.edit_message_text("❌ У вас немає доступу до системи.")
        return
    
    # Отримуємо очікуючі передачі від цього користувача
    handover_manager = get_handover_manager()
    pending_sent = handover_manager.get_pending_handovers_by_sender(user_id)
    
    if not pending_sent:
        await query.edit_message_text("📭 У вас немає очікуючих передач для відміни.")
        return
    
    # Якщо передача одна - відміняємо одразу
    if len(pending_sent) == 1:
        handover_id = pending_sent[0]['id']
        success = handover_manager.cancel_handover(handover_id, user_id)
        
        if success:
            guard_manager = get_guard_manager()
            handover_to = guard_manager.get_guard(pending_sent[0]['handover_to_id'])
            handover_to_name = handover_to['full_name'] if handover_to else f"ID: {pending_sent[0]['handover_to_id']}"
            
            message_text = (
                f"✅ <b>Передачу відмінено!</b>\n\n"
                f"🆔 <b>ID передачі:</b> #{handover_id}\n"
                f"👤 <b>Приймач:</b> {handover_to_name}\n\n"
                f"Ваша зміна повернута до активного стану."
            )
        else:
            message_text = "❌ Помилка відміни передачі. Спробуйте пізніше."
        
        keyboard = create_menu_keyboard(user_id)
        await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)
    else:
        # Якщо передач кілька - показуємо список для вибору
        buttons = []
        for handover in pending_sent[:10]:
            guard_manager = get_guard_manager()
            handover_to = guard_manager.get_guard(handover['handover_to_id'])
            handover_to_name = handover_to['full_name'] if handover_to else f"ID: {handover['handover_to_id']}"
            
            time_str = datetime.fromisoformat(handover['handed_over_at']).strftime('%d.%m %H:%M')
            button_text = f"#{handover['shift_id']} → {handover_to_name} ({time_str})"
            callback_data = csrf_manager.add_csrf_to_callback_data(user_id, f"cancel_handover_confirm:{handover['id']}")
            buttons.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
        buttons.append([InlineKeyboardButton("🏠 Головне меню", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "main_menu"))])
        keyboard = InlineKeyboardMarkup(buttons)
        
        message_text = (
            f"❌ <b>Відміна передачі</b>\n\n"
            f"Оберіть передачу для відміни:"
        )
        await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


async def cancel_handover_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробка підтвердження відміни конкретної передачі"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Витягуємо ID передачі з callback_data
    callback_data = csrf_manager.extract_callback_data(user_id, query.data)
    if not callback_data:
        await query.answer("❌ Помилка безпеки. Спробуйте ще раз.", show_alert=True)
        return
    
    if not callback_data.startswith("cancel_handover_confirm:"):
        return
    
    handover_id = int(callback_data.split(":", 1)[1])
    
    if not auth_manager.is_user_allowed(user_id):
        await query.edit_message_text("❌ У вас немає доступу до системи.")
        return
    
    handover_manager = get_handover_manager()
    handover = handover_manager.get_handover(handover_id)
    
    if not handover or handover['handover_by_id'] != user_id:
        await query.edit_message_text("❌ Передача не знайдена або ви не є здавачем.")
        return
    
    # Відміняємо тільки PENDING передачі (прийняті передачі не можна відміняти через бот)
    if handover['status'] != 'PENDING':
        keyboard = create_menu_keyboard(user_id)
        await safe_edit_message_text(query, get_shift_status_line(user_id) + "❌ Можна відмінити тільки передачі, які очікують підтвердження.", reply_markup=keyboard)
        return
    
    success = handover_manager.cancel_handover(handover_id, user_id, force=False)
    
    if success:
        guard_manager = get_guard_manager()
        handover_to = guard_manager.get_guard(handover['handover_to_id'])
        handover_to_name = handover_to['full_name'] if handover_to else f"ID: {handover['handover_to_id']}"
        
        if force:
            message_text = (
                f"✅ <b>Передачу відмінено!</b>\n\n"
                f"🆔 <b>ID передачі:</b> #{handover_id}\n"
                f"👤 <b>Приймач:</b> {handover_to_name}\n\n"
                f"Зміна приймача видалена, ваша зміна повернута до активного стану."
            )
        else:
            message_text = (
                f"✅ <b>Передачу відмінено!</b>\n\n"
                f"🆔 <b>ID передачі:</b> #{handover_id}\n"
                f"👤 <b>Приймач:</b> {handover_to_name}\n\n"
                f"Ваша зміна повернута до активного стану."
            )
    else:
        message_text = "❌ Помилка відміни передачі. Спробуйте пізніше."
    
    keyboard = create_menu_keyboard(user_id)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


# Функція відміни прийняття передачі прибрана з інтерфейсу охоронців
# Залишена для можливого використання адміністраторами через веб-інтерфейс
# async def reject_handover_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     """Обробка відміни прийняття передачі приймачем"""
#     ...


# Функція виправлення передачі прибрана з інтерфейсу охоронців
# Залишена для можливого використання адміністраторами через веб-інтерфейс
# async def fix_my_handover_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     """Обробка виправлення передачі здавачем (показ всіх передач)"""
#     ...


async def send_report_to_admins(context: ContextTypes.DEFAULT_TYPE, report_id: int) -> None:
    """Відправка детального звіту (з зауваженнями) адміністраторам, старшим та контролерам (у Telegram)."""
    try:
        report_manager = get_report_manager()
        report_text = report_manager.format_report_for_telegram(report_id)
        
        with get_session() as session:
            recipients = session.query(User).filter(
                User.role.in_(['admin', 'senior', 'controller']),
                User.is_active == True
            ).all()
            
            for u in recipients:
                try:
                    await context.bot.send_message(
                        chat_id=u.user_id,
                        text=report_text,
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.log_error(f"Помилка відправки звіту користувачу {u.user_id}: {e}")
    except Exception as e:
        logger.log_error(f"Помилка відправки звітів: {e}")


async def notify_handover_completed_to_seniors_and_controllers(
    context: ContextTypes.DEFAULT_TYPE, handover_id: int
) -> None:
    """Надіслати старшим та контролерам короткий звіт про завершену передачу зміни (формат: Здавач / Приймач / Передано / Прийнято / Події)."""
    try:
        handover_manager = get_handover_manager()
        handover = handover_manager.get_handover(handover_id)
        if not handover or handover['status'] not in ('ACCEPTED', 'ACCEPTED_WITH_NOTES'):
            return
        guard_manager = get_guard_manager()
        handover_by = guard_manager.get_guard(handover['handover_by_id'])
        handover_to = guard_manager.get_guard(handover['handover_to_id'])
        handover_by_name = handover_by['full_name'] if handover_by else f"ID: {handover['handover_by_id']}"
        handover_to_name = handover_to['full_name'] if handover_to else f"ID: {handover['handover_to_id']}"
        handed_str = datetime.fromisoformat(handover['handed_over_at']).strftime('%d.%m.%Y %H:%M')
        accepted_str = (
            datetime.fromisoformat(handover['accepted_at']).strftime('%d.%m.%Y %H:%M')
            if handover.get('accepted_at') else "—"
        )
        summary = (handover.get('summary') or "").strip() or "—"
        notes = (handover.get('notes') or "").strip()
        text = (
            "📋 <b>Передача зміни завершена</b>\n\n"
            f"<b>Здавач:</b> {handover_by_name}\n"
            f"<b>Приймач:</b> {handover_to_name}\n"
            f"<b>Передано:</b> {handed_str}\n"
            f"<b>Прийнято:</b> {accepted_str}\n"
            f"<b>Події:</b>\n{summary}"
        )
        if notes:
            text += f"\n\n<b>Зауваження:</b>\n{notes}"
        with get_session() as session:
            recipients = session.query(User).filter(
                User.role.in_(['senior', 'controller']),
                User.is_active == True
            ).all()
            for u in recipients:
                try:
                    await context.bot.send_message(chat_id=u.user_id, text=text, parse_mode='HTML')
                except Exception as e:
                    logger.log_error(f"Помилка відправки звіту передачі користувачу {u.user_id}: {e}")
    except Exception as e:
        logger.log_error(f"Помилка сповіщення старших/контролерів про передачу: {e}")


async def notify_handover_parties_after_accept(
    context: ContextTypes.DEFAULT_TYPE, handover_id: int, receiver_user_id: int
) -> None:
    """Окремі повідомлення приймачу (підтвердження) та здавачу (зміна прийнята)."""
    try:
        handover_manager = get_handover_manager()
        handover = handover_manager.get_handover(handover_id)
        if not handover:
            return
        sender_id = handover['handover_by_id']
        receiver_msg = (
            "✅ <b>Ви все зробили правильно.</b>\n\n"
            "Зміну прийнято успішно, передача завершена."
        )
        try:
            await context.bot.send_message(chat_id=receiver_user_id, text=receiver_msg, parse_mode='HTML')
        except Exception as e:
            logger.log_error(f"Сповіщення приймачу передачі: {e}")
        sender_msg = (
            "✅ <b>Вашу зміну прийнято</b>\n\n"
            "Приймач підтвердив передачу зміни."
        )
        if sender_id != receiver_user_id:
            try:
                await context.bot.send_message(chat_id=sender_id, text=sender_msg, parse_mode='HTML')
            except Exception as e:
                logger.log_error(f"Сповіщення здавачу передачі: {e}")
    except Exception as e:
        logger.log_error(f"notify_handover_parties_after_accept: {e}")


async def notify_event_to_seniors_and_controllers(context: ContextTypes.DEFAULT_TYPE, event_id: int) -> None:
    """Надіслати сповіщення про нову подію старшим та контролерам."""
    try:
        event_manager = get_event_manager()
        event = event_manager.get_event(event_id)
        if not event:
            return
        shift_manager = get_shift_manager()
        shift = shift_manager.get_shift(event['shift_id'])
        if not shift:
            return
        object_manager = get_object_manager()
        obj = object_manager.get_object(event['object_id'])
        object_name = obj['name'] if obj else f"Об'єкт #{event['object_id']}"
        guard_manager = get_guard_manager()
        guard = guard_manager.get_guard(shift['guard_id'])
        guard_name = guard['full_name'] if guard else f"ID:{shift['guard_id']}"
        event_types_ua = {'INCIDENT': 'Інцидент', 'POWER_OFF': 'Вимкнення світла', 'POWER_ON': 'Відновлення світла'}
        type_ua = event_types_ua.get(event['event_type'], event['event_type'])
        time_str = datetime.fromisoformat(event['created_at']).strftime('%d.%m.%Y %H:%M')
        desc = (event.get('description') or '').strip()
        text = (
            f"📝 <b>Нова подія</b>\n\n"
            f"📋 Тип: {type_ua}\n"
            f"🏢 Об'єкт: {object_name}\n"
            f"👤 Охоронець: {guard_name}\n"
            f"🕐 Час: {time_str}\n"
        )
        if desc:
            text += f"\n📄 <b>Опис:</b>\n{desc}"
        else:
            text += "\n📄 <b>Опис:</b> —"
        with get_session() as session:
            recipients = session.query(User).filter(
                User.role.in_(['senior', 'controller']),
                User.is_active == True
            ).all()
            for u in recipients:
                try:
                    await context.bot.send_message(chat_id=u.user_id, text=text, parse_mode='HTML')
                except Exception as e:
                    logger.log_error(f"Помилка відправки сповіщення про подію користувачу {u.user_id}: {e}")
    except Exception as e:
        logger.log_error(f"Помилка сповіщення старших/контролерів про подію: {e}")


async def my_shifts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    """Обробка натискання 'Мої зміни'"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if not auth_manager.is_user_allowed(user_id):
        await query.edit_message_text("❌ У вас немає доступу до системи.")
        return
    
    shift_manager = get_shift_manager()
    shifts = shift_manager.get_shifts(guard_id=user_id, limit=None)
    
    total_shifts = len(shifts)
    total_pages = (total_shifts + SHIFTS_PER_PAGE - 1) // SHIFTS_PER_PAGE if total_shifts > 0 else 0
    
    if total_shifts == 0:
        message_text = "📋 <b>Мої зміни</b>\n\nУ вас ще немає змін."
        keyboard = create_menu_keyboard(user_id)
        await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)
        return
    
    # Витягуємо сторінку
    start_idx = page * SHIFTS_PER_PAGE
    end_idx = start_idx + SHIFTS_PER_PAGE
    page_shifts = shifts[start_idx:end_idx]
    
    message_lines = [f"📋 <b>Мої зміни ({total_shifts})</b>"]
    if total_pages > 1:
        message_lines.append(f"<i>Сторінка {page + 1} з {total_pages}</i>")
    message_lines.append("")
    
    status_ua = {
        'ACTIVE': '🟢 Активна',
        'COMPLETED': '✅ Завершена',
        'HANDED_OVER': '🔄 Передана'
    }
    
    # Сортуємо зміни: спочатку активні, потім за датою (новіші першими)
    page_shifts_sorted = sorted(
        page_shifts,
        key=lambda s: (s['status'] != 'ACTIVE', datetime.fromisoformat(s['start_time'])),
        reverse=True
    )
    
    for shift in page_shifts_sorted:
        start_time = datetime.fromisoformat(shift['start_time']).strftime('%d.%m.%Y %H:%M')
        status_text = status_ua.get(shift['status'], shift['status'])
        
        # Виділяємо активну зміну
        if shift['status'] == 'ACTIVE':
            duration = datetime.now() - datetime.fromisoformat(shift['start_time'])
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            message_lines.append(
                f"\n━━━━━━━━━━━━━━━━━━━━\n"
                f"🟢 <b>АКТИВНА ЗМІНА</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 <b>ID:</b> #{shift['id']}\n"
                f"🕐 <b>Початок:</b> {start_time}\n"
                f"⏱️ <b>Тривалість:</b> {hours} год. {minutes} хв.\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
        else:
            # Для неактивних змін показуємо простий формат
            end_time_str = ""
            if shift.get('end_time'):
                end_time = datetime.fromisoformat(shift['end_time']).strftime('%d.%m.%Y %H:%M')
                end_time_str = f" | Завершено: {end_time}"
            
            message_lines.append(f"🆔 #{shift['id']} | {status_text} | {start_time}{end_time_str}")
    
    message_text = "\n".join(message_lines)
    
    # Формуємо кнопки пагінації
    buttons = []
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, f"my_shifts:{page - 1}")))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперед ▶️", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, f"my_shifts:{page + 1}")))
        if nav_buttons:
            buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("🏠 Головне меню", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "main_menu"))])
    keyboard = InlineKeyboardMarkup(buttons)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


async def event_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Підтвердження запису події «Вимкнення світла» / «Відновлення світла» з фіксацією часу."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    callback_data = csrf_manager.extract_callback_data(user_id, query.data)
    if not callback_data or not callback_data.startswith("event_confirm:"):
        return
    event_type = callback_data.split(":", 1)[1]
    if event_type not in ("POWER_OFF", "POWER_ON"):
        return
    if user_id not in event_creation_state:
        await query.edit_message_text(get_shift_status_line(user_id) + "❌ Сесія закінчилась. Оберіть дію з меню.")
        keyboard = create_menu_keyboard(user_id)
        await query.edit_message_reply_markup(reply_markup=keyboard)
        return
    state = event_creation_state[user_id]
    shift_id = state["shift_id"]
    desc = f"Фіксація часу: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    event_manager = get_event_manager()
    event_id = event_manager.create_event(shift_id, event_type, desc, user_id)
    del event_creation_state[user_id]
    if event_id:
        await notify_event_to_seniors_and_controllers(context, event_id)
    event_types_ua = {"POWER_OFF": "Вимкнення світла", "POWER_ON": "Відновлення світла"}
    if event_id:
        msg = (
            f"✅ <b>Подію додано!</b>\n\n"
            f"🆔 ID: #{event_id}\n"
            f"📋 Тип: {event_types_ua.get(event_type, event_type)}\n"
            f"🕐 {desc}"
        )
    else:
        msg = "❌ Помилка запису. Спробуйте пізніше."
    keyboard = create_menu_keyboard(user_id)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + msg, reply_markup=keyboard)


async def cancel_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Скасування створення події"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id in event_creation_state:
        del event_creation_state[user_id]
    
    keyboard = create_menu_keyboard(user_id)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + "❌ Створення події скасовано.", reply_markup=keyboard)


async def cancel_handover_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Скасування передачі зміни"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    keyboard = create_menu_keyboard(user_id)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + "❌ Передача зміни скасована.", reply_markup=keyboard)


async def cancel_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Скасування прийняття зміни"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    keyboard = create_menu_keyboard(user_id)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + "❌ Прийняття зміни скасовано.", reply_markup=keyboard)


async def who_on_shift_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Екран «Хто зараз на зміні» — список активних змін по об'єктах."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    shift_manager = get_shift_manager()
    active_list = shift_manager.get_all_active_shifts()
    
    if not active_list:
        message_text = "👥 <b>Хто зараз на зміні</b>\n\nЗараз ніхто не на зміні."
    else:
        from collections import OrderedDict
        by_object = OrderedDict()
        for s in active_list:
            oname = s['object_name']
            if oname not in by_object:
                by_object[oname] = []
            t = datetime.fromisoformat(s['start_time']).strftime('%H:%M')
            line = f"  • {s['guard_name']} (з {t})"
            if s.get('guard_phone'):
                line += f" — {s['guard_phone']}"
            by_object[oname].append(line)
        lines = ["👥 <b>Хто зараз на зміні</b>\n"]
        for obj_name, guards in by_object.items():
            lines.append(f"<b>🏢 {obj_name}</b>")
            lines.extend(guards)
            lines.append("")
        message_text = "\n".join(lines).strip()
    
    buttons = [[InlineKeyboardButton("🔄 Оновити", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "who_on_shift"))]]
    buttons.append([InlineKeyboardButton("🏠 Головне меню", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "main_menu"))])
    keyboard = InlineKeyboardMarkup(buttons)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


def _short_name(full_name: str) -> str:
    """Повертає підпис для графіка: прізвище та ім'я (якщо є). Один токен — як є; два і більше — «Прізвище Ім'я»."""
    parts = (full_name or "").strip().split()
    if not parts:
        return "—"
    if len(parts) >= 2:
        return f"{parts[-1]} {parts[0]}"
    return parts[0]


async def schedule_month_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показ графіка змін на поточний місяць по об'єкту користувача (охоронець/старший)."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    guard_manager = get_guard_manager()
    object_id = guard_manager.get_guard_object_id(user_id)
    if not object_id:
        msg = "У вашому профілі не встановлено об'єкт."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "main_menu"))]])
        await safe_edit_message_text(query, get_shift_status_line(user_id) + msg, reply_markup=keyboard)
        return

    year = date.today().year
    month = date.today().month
    schedule_mgr = get_schedule_manager()
    guards = schedule_mgr.get_guards_for_schedule(object_id=object_id)
    slots_set = schedule_mgr.get_slots_for_month(year, month, object_id=object_id)

    guard_names: Dict[int, str] = {g["user_id"]: _short_name(g["full_name"]) for g in guards}
    # Доповнити іменами тих, хто є в слотах, але не в списку охоронців (наприклад інший об'єкт/роль)
    for (gid, _) in slots_set:
        if gid not in guard_names:
            g = guard_manager.get_guard(gid)
            if g and g.get("full_name"):
                guard_names[gid] = _short_name(g["full_name"])

    month_name = MONTH_NAMES_UA[month] if 1 <= month <= 12 else ""
    title = f"📅 <b>Графік роботи на {month_name} {year}</b>"

    my_days = sorted([day for gid, day in slots_set if gid == user_id])
    lines = [title, ""]
    if my_days:
        lines.append(f"Ваші робочі дні: {', '.join(str(d) for d in my_days)}")
        lines.append("")

    _, days_in_month = calendar.monthrange(year, month)
    lines.append("По днях:")
    for day in range(1, days_in_month + 1):
        guard_ids_this_day = [gid for (gid, d) in slots_set if d == day]
        if not guard_ids_this_day:
            lines.append(f"{day}: —")
        else:
            names = [("Ви" if gid == user_id else guard_names.get(gid, "?")) for gid in guard_ids_this_day]
            names_sorted = sorted(names, key=lambda x: (0 if x == "Ви" else 1, x))
            lines.append(f"{day}: {', '.join(names_sorted)}")

    if not guards and not slots_set:
        message_text = title + "\n\nГрафік на місяць порожній."
    else:
        message_text = "\n".join(lines)

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data=csrf_manager.add_csrf_to_callback_data(user_id, "main_menu"))]])
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Повернення до головного меню"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    guard_manager = get_guard_manager()
    guard = guard_manager.get_guard(user_id)
    
    if guard:
        object_manager = get_object_manager()
        obj = object_manager.get_object(guard['object_id'])
        obj_name = obj['name'] if obj else f"Об'єкт #{guard['object_id']}"
        
        message_text = (
            f"👮 <b>Система ведення змін охоронців</b>\n\n"
            f"👤 <b>Охоронець:</b> {guard['full_name']}\n"
            f"🏢 <b>Об'єкт:</b> {obj_name}\n\n"
            f"Оберіть дію:"
        )
    else:
        message_text = "👮 <b>Система ведення змін охоронців</b>\n\nОберіть дію:"
    
    keyboard = create_menu_keyboard(user_id)
    await safe_edit_message_text(query, get_shift_status_line(user_id) + message_text, reply_markup=keyboard)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробник всіх callback запитів"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Обробка запиту на доступ - дозволяємо неавторизованим користувачам
    if query.data == "request_access":
        username = query.from_user.username or f"user_{user_id}"
        if auth_manager.add_user_request(user_id, username):
            await query.answer("✅ Ваш запит на доступ відправлено адміністратору.", show_alert=True)
            await safe_edit_message_text(query, "✅ Ваш запит на доступ відправлено адміністратору. Очікуйте схвалення.")
        else:
            await query.answer("ℹ️ Ваш запит вже надіслано. Очікуйте схвалення.", show_alert=True)
        return
    
    # Витягуємо callback_data з CSRF токеном
    callback_data = csrf_manager.extract_callback_data(user_id, query.data, allow_refresh=True)
    
    if not callback_data:
        # Можливо це системний callback без CSRF
        if query.data == "no_access":
            await query.answer("❌ У вас немає доступу до системи.", show_alert=True)
        return
    
    # Для всіх інших callback потрібен доступ
    if not auth_manager.is_user_allowed(user_id):
        await query.answer("❌ У вас немає доступу до системи.", show_alert=True)
        return
    
    # Обробка різних callback
    if callback_data == "start_shift":
        await start_shift_callback(update, context)
    elif callback_data == "end_shift":
        await end_shift_callback(update, context)
    elif callback_data == "add_event":
        await add_event_callback(update, context)
    elif callback_data == "handover_shift":
        await handover_shift_callback(update, context)
    elif callback_data == "accept_handover":
        await accept_handover_callback(update, context)
    elif callback_data == "my_shifts":
        await my_shifts_callback(update, context)
    elif callback_data == "who_on_shift":
        await who_on_shift_callback(update, context)
    elif callback_data == "view_schedule":
        await schedule_month_callback(update, context)
    elif callback_data == "main_menu":
        await main_menu_callback(update, context)
    elif callback_data.startswith("event_type:"):
        await event_type_callback(update, context)
    elif callback_data.startswith("event_confirm:"):
        await event_confirm_callback(update, context)
    elif callback_data.startswith("select_handover_to:"):
        await select_handover_to_callback(update, context)
    elif callback_data.startswith("view_handover:"):
        await view_handover_callback(update, context)
    elif callback_data.startswith("accept_handover_ok:"):
        await accept_handover_ok_callback(update, context)
    elif callback_data.startswith("accept_handover_notes:"):
        await accept_handover_notes_callback(update, context)
    elif callback_data.startswith("my_shifts:"):
        page = int(callback_data.split(":", 1)[1])
        await my_shifts_callback(update, context, page)
    elif callback_data == "cancel_event":
        await cancel_event_callback(update, context)
    elif callback_data == "cancel_handover":
        await cancel_handover_callback(update, context)
    elif callback_data == "cancel_accept":
        await cancel_accept_callback(update, context)
    elif callback_data == "cancel_my_handover":
        await cancel_my_handover_callback(update, context)
    # elif callback_data.startswith("reject_handover"):
    #     await reject_handover_callback(update, context)  # Прибрано з інтерфейсу охоронців
    elif callback_data.startswith("cancel_handover_confirm:"):
        await cancel_handover_confirm_callback(update, context)
    # elif callback_data == "fix_my_handover":
    #     await fix_my_handover_callback(update, context)  # Прибрано з інтерфейсу охоронців


def main():
    """Головна функція запуску бота"""
    if not TELEGRAM_BOT_TOKEN:
        logger.log_error("TELEGRAM_BOT_TOKEN не встановлено в config.env")
        print("Помилка: TELEGRAM_BOT_TOKEN не встановлено в config.env")
        return
    
    # Ініціалізуємо БД
    logger.log_info("Ініціалізація бази даних...")
    init_database()
    
    # Створюємо додаток
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Реєструємо обробники
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # Обробник текстових повідомлень (для введення описів подій та зауважень)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    # Запускаємо бота
    logger.log_info("Запуск Telegram бота...")
    print("=" * 60)
    print("🤖 Telegram бот Security")
    print("=" * 60)
    print("Бот запущено. Натисніть Ctrl+C для зупинки.")
    print()
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
