"""
Генерація секретного ключа для Flask
"""
import secrets

if __name__ == '__main__':
    secret_key = secrets.token_urlsafe(32)
    print("=" * 60)
    print("🔑 Згенеровано секретний ключ для Flask")
    print("=" * 60)
    print(f"\n{secret_key}\n")
    print("Скопіюйте цей ключ та додайте його в config.env як FLASK_SECRET_KEY\n")
