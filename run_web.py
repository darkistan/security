"""
Скрипт запуску веб-інтерфейсу системи ведення змін охоронців
"""
import os
from web_admin.app import app

if __name__ == '__main__':
    flask_env = os.getenv('FLASK_ENV', 'development')
    if flask_env == 'production':
        flask_debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    else:
        flask_debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', 5000))

    if flask_env == 'production':
        from waitress import serve
        print("=" * 60)
        print("🌐 Запуск веб-інтерфейсу Security (Production)")
        print("=" * 60)
        print(f"\n📍 Адреса: http://{host}:{port}")
        print("💡 Натисніть Ctrl+C для зупинки\n")
        serve(
            app,
            host=host,
            port=port,
            threads=4,
            channel_timeout=120,
            cleanup_interval=30,
            asyncore_use_poll=True
        )
    else:
        print("=" * 60)
        print("🌐 Запуск веб-інтерфейсу Security (Development)")
        print("=" * 60)
        print(f"\n📍 Адреса: http://{host}:{port}")
        print("💡 Натисніть Ctrl+C для зупинки\n")
        app.run(host=host, port=port, debug=flask_debug)
