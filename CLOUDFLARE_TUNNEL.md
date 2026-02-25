# Робота через Cloudflare Tunnel

Документ описує запуск веб-додатку «Система ведення змін охоронців» через Cloudflare Tunnel поруч із проєктом «Система заявок» на одній машині.

## Порти

| Проєкт                    | Порт  | config.env        |
|---------------------------|-------|-------------------|
| Система заявок            | 5000  | HOST, PORT у своєму config.env |
| Система ведення змін охоронців | 9080  | `HOST=127.0.0.1`, `PORT=9080` |

У `config.env` цього проєкту мають бути: `HOST=127.0.0.1`, `PORT=9080`.

## Приклад конфігу cloudflared (ingress)

Один тунель з двома hostname — кожен на свій локальний порт:

```yaml
ingress:
  - hostname: tickets.example.com
    service: http://127.0.0.1:5000
  - hostname: shifts.example.com
    service: http://127.0.0.1:9080
  - service: http_status:404
```

Замініть `tickets.example.com` та `shifts.example.com` на свої домени в Cloudflare.

## Зауваження

- Для коректних URL за HTTPS встановіть у `config.env` цього проєкту **`FLASK_ENV=production`** — тоді працює ProxyFix і правильно обробляються заголовки X-Forwarded-* від Cloudflare.
- Обидва проєкти мають бути запущені одночасно; cloudflared направляє трафік на відповідний порт за hostname.
