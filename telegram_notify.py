"""
Відправка повідомлень у Telegram через Bot API (для веб-адмінки та інших процесів без context бота).
"""
import html
import os
from typing import Optional

import requests
from dotenv import load_dotenv

from logger import logger

_config_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_config_dir, "config.env"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else None


def send_telegram_message(chat_id: int, text: str, parse_mode: str = "HTML") -> bool:
    """
    Надіслати повідомлення користувачу в Telegram.

    Returns:
        True якщо API повернув успіх.
    """
    if not TELEGRAM_API_URL:
        return False
    try:
        response = requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        if response.status_code == 200:
            return True
        logger.log_error(f"send_telegram_message: chat_id={chat_id}, status={response.status_code}, body={response.text[:200]}")
        return False
    except Exception as e:
        logger.log_error(f"send_telegram_message: {e}")
        return False


def notify_guard_points_awarded(
    guard_id: int,
    points_delta: int,
    reason: Optional[str],
) -> None:
    """
    Сповіщення охоронцю про нарахування/зняття балів (після add_points).
    """
    if not TELEGRAM_API_URL:
        return
    from points_manager import get_points_manager

    points_mgr = get_points_manager()
    balance = points_mgr.get_balance(guard_id)
    if points_delta > 0:
        delta_str = f"+{points_delta}"
    else:
        delta_str = str(points_delta)
    reason_safe = html.escape((reason or "").strip() or "—")
    text = (
        "<b>Нарахування балів</b>\n\n"
        f"<b>Зміна:</b> {delta_str}\n"
        f"<b>Причина:</b> {reason_safe}\n"
        f"<b>Поточний баланс:</b> {balance}"
    )
    send_telegram_message(guard_id, text, parse_mode="HTML")
