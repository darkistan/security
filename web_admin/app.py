"""
Flask веб-інтерфейс для системи ведення змін охоронців
"""
import os
import sys
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session as flask_session
from flask_wtf import CSRFProtect
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv

# Додаємо батьківську директорію в Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import init_database, get_session
from models import User, SecurityObject, Shift, Event, ShiftHandover, Report, Log, ActiveSession, Announcement
from shift_manager import get_shift_manager
from event_manager import get_event_manager
from handover_manager import get_handover_manager
from guard_manager import get_guard_manager
from object_manager import get_object_manager
from report_manager import get_report_manager
from points_manager import get_points_manager
from announcement_manager import get_announcement_manager
from schedule_manager import get_schedule_manager
from vacation_manager import get_vacation_manager
from auth import auth_manager
from logger import logger

# Завантажуємо змінні середовища
load_dotenv("config.env")

# Перевірка режиму роботи
FLASK_ENV = os.getenv('FLASK_ENV', 'development')
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true' if FLASK_ENV == 'development' else False

# Ініціалізація Flask
app = Flask(__name__)
app.config['ENV'] = FLASK_ENV
app.config['DEBUG'] = FLASK_DEBUG and FLASK_ENV == 'development'
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

# CSRF захист
csrf = CSRFProtect(app)

# Налаштування для Cloudflare (ProxyFix для правильної обробки X-Forwarded-For)
if FLASK_ENV == 'production':
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_port=1
    )

# Ініціалізація Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Будь ласка, увійдіть для доступу до цієї сторінки.'

# Ініціалізація Flask-Limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["500 per day", "200 per hour"],
    storage_uri="memory://"
)

# Ініціалізація БД
init_database()


# Фільтри Jinja2
@app.template_filter('event_type_ua')
def event_type_ua_filter(event_type):
    """Переклад типу події на українську мову"""
    type_translations = {
        'INCIDENT': 'Інцидент',
        'POWER_OFF': 'Вимкнення світла',
        'POWER_ON': 'Відновлення світла',
    }
    return type_translations.get(event_type, event_type)


@app.template_filter('shift_status_ua')
def shift_status_ua_filter(status):
    """Переклад статусу зміни на українську мову"""
    status_translations = {
        'ACTIVE': 'Активна',
        'COMPLETED': 'Завершена',
        'HANDED_OVER': 'Передана'
    }
    return status_translations.get(status, status)


@app.template_filter('handover_status_ua')
def handover_status_ua_filter(status):
    """Переклад статусу передачі на українську мову"""
    status_translations = {
        'PENDING': 'Очікує підтвердження',
        'ACCEPTED': 'Прийнято',
        'ACCEPTED_WITH_NOTES': 'Прийнято з зауваженнями'
    }
    return status_translations.get(status, status)


@app.template_filter('nl2br')
def nl2br_filter(text):
    """Заміна переносів рядків на <br>"""
    if not text:
        return ""
    return text.replace('\n', '<br>')


# Клас для Flask-Login
class WebUser(UserMixin):
    """Обгортка для User моделі"""
    def __init__(self, user: User):
        self.id = user.user_id
        self._user_id = user.user_id
        self._role = user.role
        self._full_name = user.full_name
        self._username = user.username
        self._object_id = user.object_id
    
    def get_id(self):
        return str(self._user_id)
    
    @property
    def is_admin(self):
        return self._role == 'admin'
    
    @property
    def is_senior(self):
        return self._role in ['senior', 'admin']
    
    @property
    def object_id(self):
        return self._object_id
    
    @property
    def user_id(self):
        return self._user_id
    
    @property
    def username(self):
        return self._username
    
    @property
    def full_name(self):
        return self._full_name


@login_manager.user_loader
def load_user(user_id_str):
    """Завантаження користувача для Flask-Login"""
    try:
        user_id = int(user_id_str)
        with get_session() as session:
            user = session.query(User).filter(User.user_id == user_id).first()
            if user and user.is_active:
                return WebUser(user)
        return None
    except Exception as e:
        logger.log_error(f"Помилка завантаження користувача: {e}")
        return None


def admin_required(f):
    """Декоратор для перевірки прав адміністратора"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash('Доступ заборонено. Потрібні права адміністратора.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def senior_required(f):
    """Декоратор для перевірки прав старшого або адміністратора"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_senior:
            flash('Доступ заборонено. Потрібні права старшого або адміністратора.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
@login_required
def dashboard():
    """Дашборд"""
    try:
        shift_manager = get_shift_manager()
        handover_manager = get_handover_manager()
        report_manager = get_report_manager()
        
        # Статистика для адміністраторів та старших
        guard_manager = get_guard_manager()
        if current_user.is_senior:
            all_shifts = shift_manager.get_shifts(limit=100)
            active_shifts = [s for s in all_shifts if s['status'] == 'ACTIVE']
            pending_handovers = handover_manager.get_handovers(status='PENDING', limit=10)
            recent_reports = report_manager.get_reports(limit=5)
        else:
            # Для звичайних охоронців - тільки свої дані
            all_shifts = shift_manager.get_shifts(guard_id=current_user.user_id, limit=100)
            active_shifts = [s for s in all_shifts if s['status'] == 'ACTIVE']
            pending_handovers = handover_manager.get_pending_handovers(current_user.user_id)
            recent_reports = []
        
        # Додаємо ПІБ, телефон охоронця та назву об'єкта до кожної активної зміни
        object_manager = get_object_manager()
        for shift in active_shifts:
            guard = guard_manager.get_guard(shift['guard_id'])
            shift['guard_full_name'] = guard['full_name'] if guard else ('ID: ' + str(shift['guard_id']))
            shift['guard_phone'] = guard.get('phone', '') if guard else ''
            obj = object_manager.get_object(shift['object_id'])
            shift['object_name'] = obj['name'] if obj else ("Об'єкт #" + str(shift['object_id']))
        
        return render_template('dashboard.html',
                             active_shifts=active_shifts,
                             pending_handovers=pending_handovers,
                             recent_reports=recent_reports)
    except Exception as e:
        logger.log_error(f"Помилка дашборду: {e}")
        flash('Помилка завантаження дашборду.', 'danger')
        return render_template('dashboard.html',
                             active_shifts=[],
                             pending_handovers=[],
                             recent_reports=[])


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Вхід у систему"""
    # Отримуємо список користувачів з ПІБ та паролем для відображення в переліку
    with get_session() as session:
        users_with_passwords = session.query(User).filter(
            User.password_hash.isnot(None),
            User.full_name.isnot(None),
            User.full_name != ''
        ).order_by(User.full_name, User.username).all()
        
        users_list = []
        for user in users_with_passwords:
            display_name = user.full_name
            if user.role == 'admin':
                display_name += " (Адмін)"
            elif user.role == 'senior':
                display_name += " (Старший)"
            users_list.append({
                'user_id': user.user_id,
                'display_name': display_name
            })
    
    if request.method == 'POST':
        user_id_str = request.form.get('user_id', '').strip()
        password = request.form.get('password', '')
        
        if not user_id_str or not password:
            flash('Заповніть всі поля.', 'danger')
            return render_template('login.html', users=users_list)
        
        try:
            user_id = int(user_id_str)
        except ValueError:
            flash('Невірний формат User ID.', 'danger')
            return render_template('login.html', users=users_list)
        
        with get_session() as session:
            user = session.query(User).filter(User.user_id == user_id).first()
            
            if user and user.is_active and user.password_hash:
                if check_password_hash(user.password_hash, password):
                    # Створюємо сесію
                    session_id = str(uuid.uuid4())
                    active_session = ActiveSession(
                        user_id=user.user_id,
                        session_id=session_id,
                        ip_address=request.remote_addr,
                        user_agent=request.headers.get('User-Agent', ''),
                        login_time=datetime.now(),
                        last_activity=datetime.now(),
                        is_active=True
                    )
                    session.add(active_session)
                    session.commit()
                    
                    flask_session['session_id'] = session_id
                    login_user(WebUser(user), remember=True)
                    
                    logger.log_info(f"Користувач {user_id} ({user.full_name}) увійшов у веб-інтерфейс")
                    next_page = request.args.get('next')
                    return redirect(next_page) if next_page else redirect(url_for('dashboard'))
                else:
                    flash('Невірний пароль.', 'danger')
            else:
                flash('Користувач не знайдено або неактивний.', 'danger')
        
        return render_template('login.html', users=users_list)
    
    return render_template('login.html', users=users_list)


@app.route('/logout')
@login_required
def logout():
    """Вихід з системи"""
    user_id = current_user.user_id
    
    # Деактивуємо сесію
    if 'session_id' in flask_session:
        session_id = flask_session['session_id']
        with get_session() as session:
            active_session = session.query(ActiveSession).filter(
                ActiveSession.session_id == session_id
            ).first()
            if active_session:
                active_session.is_active = False
                session.commit()
    
    logout_user()
    flash('Ви вийшли з системи.', 'info')
    return redirect(url_for('login'))


@app.errorhandler(404)
def not_found(error):
    """Обробка помилки 404"""
    url = request.url.lower()
    if '/favicon.ico' not in url and 'apple-touch-icon' not in url and '/sw.js' not in url:
        logger.log_warning(f"404: {request.url}")
    return render_template('error.html', error_code=404, error_message='Сторінку не знайдено'), 404


@app.errorhandler(500)
def internal_error(error):
    """Обробка помилки 500"""
    logger.log_error(f"Внутрішня помилка сервера: {error}")
    return render_template('error.html', error_code=500, error_message='Внутрішня помилка сервера'), 500


@app.errorhandler(429)
def ratelimit_handler(e):
    """Обробка помилки rate limit"""
    flash('Занадто багато запитів. Спробуйте пізніше.', 'warning')
    return redirect(url_for('dashboard'))


@app.route('/guards')
@admin_required
def guards():
    """Сторінка управління охоронцями"""
    sort_by = request.args.get('sort_by', 'user_id')
    sort_order = request.args.get('sort_order', 'asc')
    
    # Пагінація
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Кількість охоронців на сторінку
    
    guard_manager = get_guard_manager()
    object_manager = get_object_manager()
    
    with get_session() as session:
        # Застосовуємо сортування
        if sort_by == 'object_id':
            # Для об'єкта сортуємо по назві через join
            from models import SecurityObject
            query = session.query(User).outerjoin(SecurityObject, User.object_id == SecurityObject.id)
            if sort_order == 'desc':
                query = query.order_by(SecurityObject.name.desc().nulls_last(), User.user_id.asc())
            else:
                query = query.order_by(SecurityObject.name.asc().nulls_first(), User.user_id.asc())
        else:
            query = session.query(User)
            
            # Визначаємо поле для сортування
            if sort_by == 'user_id':
                order_field = User.user_id
            elif sort_by == 'username':
                order_field = User.username
            elif sort_by == 'full_name':
                order_field = User.full_name
            elif sort_by == 'role':
                order_field = User.role
            elif sort_by == 'phone':
                order_field = User.phone
            else:
                order_field = User.user_id
            
            # Застосовуємо порядок сортування
            if sort_order == 'desc':
                query = query.order_by(order_field.desc().nulls_last())
            else:
                query = query.order_by(order_field.asc().nulls_first())
        
        all_guards = query.all()
        
        # Обчислюємо пагінацію
        total_guards = len(all_guards)
        total_pages = (total_guards + per_page - 1) // per_page if total_guards > 0 else 0
        
        # Обмежуємо page в межах допустимих значень
        if page < 1:
            page = 1
        elif page > total_pages and total_pages > 0:
            page = total_pages
        
        # Обчислюємо індекси для поточної сторінки
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_guards)
        guards_page = all_guards[start_idx:end_idx]
        
        # Отримуємо запити на доступ
        from auth import auth_manager
        pending_requests = auth_manager.get_pending_requests()
        
        # Отримуємо список об'єктів
        objects_list = object_manager.get_all_objects(active_only=True)
        
        # Отримуємо активні зміни для кожного охоронця
        shift_manager = get_shift_manager()
        active_shifts = {}
        for guard in guards_page:
            active_shift = shift_manager.get_active_shift(guard.user_id)
            if active_shift:
                active_shifts[guard.user_id] = active_shift
        
        return render_template('guards.html',
                             guards=guards_page,
                             pending_requests=pending_requests,
                             objects=objects_list,
                             active_shifts=active_shifts,
                             sort_by=sort_by,
                             sort_order=sort_order,
                             page=page,
                             total_pages=total_pages,
                             total_guards=total_guards,
                             per_page=per_page,
                             end_index=min(page * per_page, total_guards))


@app.route('/guards/add', methods=['POST'])
@admin_required
def add_guard():
    """Додавання нового охоронця"""
    user_id_str = request.form.get('user_id', '').strip()
    username = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip()
    object_id_str = request.form.get('object_id', '').strip()
    
    if not all([user_id_str, full_name, phone, object_id_str]):
        flash('Заповніть всі обов\'язкові поля.', 'danger')
        return redirect(url_for('guards'))
    
    try:
        user_id = int(user_id_str)
        object_id = int(object_id_str)
    except ValueError:
        flash('Невірний формат даних.', 'danger')
        return redirect(url_for('guards'))
    
    guard_manager = get_guard_manager()
    success = guard_manager.create_guard(user_id, username, full_name, phone, object_id)
    
    if success:
        flash('Охоронця додано успішно.', 'success')
    else:
        flash('Помилка додавання охоронця. Можливо користувач вже існує.', 'danger')
    
    return redirect(url_for('guards'))


@app.route('/guards/<int:user_id>/edit', methods=['POST'])
@admin_required
def edit_guard(user_id):
    """Редагування охоронця"""
    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip()
    object_id_str = request.form.get('object_id', '').strip()
    role = request.form.get('role', '').strip()
    
    guard_manager = get_guard_manager()
    
    update_data = {}
    if full_name:
        update_data['full_name'] = full_name
    if phone:
        update_data['phone'] = phone
    if object_id_str:
        try:
            update_data['object_id'] = int(object_id_str)
        except ValueError:
            flash('Невірний формат об\'єкта.', 'danger')
            return redirect(url_for('guards'))
    if role:
        update_data['role'] = role
    
    success = guard_manager.update_guard(user_id, **update_data)
    
    if success:
        flash('Дані охоронця оновлено.', 'success')
    else:
        flash('Помилка оновлення даних.', 'danger')
    
    return redirect(url_for('guards'))


@app.route('/guards/<int:user_id>/activate', methods=['POST'])
@admin_required
def activate_guard(user_id):
    """Активація охоронця"""
    guard_manager = get_guard_manager()
    success = guard_manager.activate_guard(user_id)
    
    if success:
        flash('Охоронця активовано.', 'success')
    else:
        flash('Помилка активації.', 'danger')
    
    return redirect(url_for('guards'))


@app.route('/guards/<int:user_id>/deactivate', methods=['POST'])
@admin_required
def deactivate_guard(user_id):
    """Деактивація охоронця"""
    # Перевірка чи не намагаються деактивувати адміністратора
    with get_session() as session:
        guard = session.query(User).filter(User.user_id == user_id).first()
        if guard and guard.role == 'admin':
            flash('Адміністратора не можна деактивувати.', 'warning')
            return redirect(url_for('guards'))
    
    guard_manager = get_guard_manager()
    success = guard_manager.deactivate_guard(user_id)
    
    if success:
        flash('Охоронця деактивовано.', 'success')
    else:
        flash('Помилка деактивації.', 'danger')
    
    return redirect(url_for('guards'))


@app.route('/guards/<int:user_id>/set_password', methods=['POST'])
@admin_required
def set_guard_password(user_id):
    """Встановлення пароля для охоронця"""
    password = request.form.get('password', '').strip()
    
    if not password or len(password) < 6:
        flash('Пароль повинен містити мінімум 6 символів.', 'danger')
        return redirect(url_for('guards'))
    
    with get_session() as session:
        user = session.query(User).filter(User.user_id == user_id).first()
        if user:
            user.password_hash = generate_password_hash(password)
            session.commit()
            flash('Пароль встановлено.', 'success')
        else:
            flash('Користувач не знайдено.', 'danger')
    
    return redirect(url_for('guards'))


@app.route('/guards/approve/<int:user_id>', methods=['POST'])
@admin_required
def approve_user(user_id):
    """Схвалення користувача"""
    object_id = request.form.get('object_id', type=int)
    full_name = request.form.get('full_name', '').strip()
    phone = request.form.get('phone', '').strip()
    role = request.form.get('role', 'guard').strip()
    
    with get_session() as session:
        from models import PendingRequest
        pending = session.query(PendingRequest).filter(PendingRequest.user_id == user_id).first()
        if pending:
            success = auth_manager.approve_user(
                user_id=user_id,
                username=pending.username,
                object_id=object_id,
                role=role,
                full_name=full_name if full_name else None,
                phone=phone if phone else None
            )
            if success:
                flash('Користувача схвалено.', 'success')
            else:
                flash('Помилка схвалення користувача.', 'danger')
        else:
            flash('Запит не знайдено.', 'warning')
    
    return redirect(url_for('guards'))


@app.route('/guards/deny/<int:user_id>', methods=['POST'])
@admin_required
def deny_user(user_id):
    """Відхилення користувача"""
    with get_session() as session:
        from models import PendingRequest
        pending = session.query(PendingRequest).filter(PendingRequest.user_id == user_id).first()
        if pending:
            success = auth_manager.deny_user(user_id, pending.username)
            if success:
                flash('Запит відхилено.', 'info')
        else:
            flash('Запит не знайдено.', 'warning')
    
    return redirect(url_for('guards'))


@app.route('/guards/<int:user_id>/update_full_name', methods=['POST'])
@admin_required
def update_guard_full_name(user_id):
    """Оновлення ПІБ охоронця"""
    full_name = request.form.get('full_name', '').strip()
    
    with get_session() as session:
        user = session.query(User).filter(User.user_id == user_id).first()
        if user:
            user.full_name = full_name if full_name else None
            session.commit()
            flash('ПІБ охоронця оновлено.', 'success')
        else:
            flash('Охоронця не знайдено.', 'danger')
    
    return redirect(url_for('guards'))


@app.route('/guards/add_web', methods=['POST'])
@admin_required
def add_web_guard():
    """Додавання веб-користувача (без Telegram)"""
    full_name = request.form.get('full_name', '').strip()
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    object_id = request.form.get('object_id', type=int)
    role = request.form.get('role', 'guard')
    phone = request.form.get('phone', '').strip()
    
    if not full_name:
        flash('ПІБ користувача не може бути порожнім.', 'danger')
        return redirect(url_for('guards'))
    
    if not password or len(password) < 6:
        flash('Пароль повинен містити мінімум 6 символів.', 'danger')
        return redirect(url_for('guards'))
    
    if not phone:
        flash('Телефон не може бути порожнім.', 'danger')
        return redirect(url_for('guards'))
    
    if not object_id:
        flash('Об\'єкт не може бути порожнім.', 'danger')
        return redirect(url_for('guards'))
    
    try:
        with get_session() as session:
            # Генеруємо унікальний негативний user_id для веб-користувачів
            min_web_user_id = session.query(User.user_id).filter(User.user_id < 0).order_by(User.user_id.asc()).first()
            if min_web_user_id:
                new_user_id = min_web_user_id[0] - 1
            else:
                new_user_id = -1
            
            # Перевіряємо, чи не існує вже такий user_id
            existing = session.query(User).filter(User.user_id == new_user_id).first()
            if existing:
                all_web_ids = {u[0] for u in session.query(User.user_id).filter(User.user_id < 0).all()}
                new_user_id = -1
                while new_user_id in all_web_ids:
                    new_user_id -= 1
            
            # Створюємо користувача
            user = User(
                user_id=new_user_id,
                username=username if username else None,
                full_name=full_name,
                password_hash=generate_password_hash(password),
                phone=phone,
                object_id=object_id,
                role=role,
                approved_at=datetime.now(),
                is_active=True
            )
            session.add(user)
            session.commit()
            flash(f'Веб-користувача "{full_name}" додано. User ID: {new_user_id}', 'success')
    except Exception as e:
        logger.log_error(f"Помилка додавання веб-користувача: {e}")
        flash('Помилка додавання веб-користувача.', 'danger')
    
    return redirect(url_for('guards'))


@app.route('/guards/delete', methods=['POST'])
@admin_required
def delete_guard():
    """Безпечне видалення охоронця"""
    try:
        user_id_str = request.form.get('user_id', '').strip()
        if not user_id_str:
            flash('Не вказано ID охоронця.', 'danger')
            return redirect(url_for('guards'))
        
        try:
            user_id = int(user_id_str)
        except ValueError:
            flash('Невірний формат ID охоронця.', 'danger')
            return redirect(url_for('guards'))
        
        with get_session() as session:
            user = session.query(User).filter(User.user_id == user_id).first()
            if not user:
                flash('Охоронця не знайдено.', 'danger')
                return redirect(url_for('guards'))
            
            # Заборона видалення системного адміністратора
            if user_id == 1:
                flash('Неможливо видалити системного адміністратора (User ID: 1).', 'danger')
                return redirect(url_for('guards'))
            
            # Перевіряємо, чи не є останнім адміном
            if user.role == 'admin':
                admin_count = session.query(User).filter(User.role == 'admin').count()
                if admin_count <= 1:
                    flash('Неможливо видалити останнього адміністратора.', 'danger')
                    return redirect(url_for('guards'))
            
            # Перевіряємо чи є активні зміни
            active_shifts = session.query(Shift).filter(
                Shift.guard_id == user_id,
                Shift.status == 'ACTIVE'
            ).count()
            
            if active_shifts > 0:
                flash('Неможливо видалити охоронця з активними змінами.', 'danger')
                return redirect(url_for('guards'))
            
            # Видаляємо користувача
            session.delete(user)
            session.commit()
            flash('Охоронця видалено.', 'success')
    except Exception as e:
        logger.log_error(f"Помилка видалення охоронця: {e}")
        flash('Помилка видалення охоронця.', 'danger')
    
    return redirect(url_for('guards'))


@app.route('/objects')
@admin_required
def objects():
    """Сторінка управління об'єктами"""
    object_manager = get_object_manager()
    objects_list = object_manager.get_all_objects()
    
    return render_template('objects.html', objects=objects_list)


@app.route('/objects/<int:object_id>/edit', methods=['POST'])
@admin_required
def edit_object(object_id):
    """Редагування об'єкта (назва та тип охорони)."""
    name = request.form.get('name', '').strip()
    protection_type = request.form.get('protection_type', 'SHIFT')
    if protection_type not in ('SHIFT', 'TEMPORARY_SINGLE'):
        protection_type = 'SHIFT'
    if not name:
        flash('Назва об\'єкта не може бути порожньою.', 'danger')
        return redirect(url_for('objects'))
    object_manager = get_object_manager()
    success = object_manager.update_object(object_id, name=name, protection_type=protection_type)
    if success:
        flash('Об\'єкт оновлено.', 'success')
    else:
        flash('Помилка оновлення.', 'danger')
    return redirect(url_for('objects'))


@app.route('/journal')
@login_required
def journal():
    """Об'єднана сторінка: Зміни, Події, Передачі, Звіти (вкладки)"""
    tab = request.args.get('tab', 'shifts')
    shift_manager = get_shift_manager()
    event_manager = get_event_manager()
    handover_manager = get_handover_manager()
    report_manager = get_report_manager()
    guard_manager = get_guard_manager()
    object_manager = get_object_manager()
    objects_list = object_manager.get_all_objects(active_only=True)
    guards_list = guard_manager.get_all_guards() if current_user.is_senior else []

    # Зміни
    guard_id = request.args.get('guard_id', type=int)
    shift_object_id = request.args.get('shift_object_id', type=int)
    shift_status = request.args.get('shift_status', '')
    if not current_user.is_senior:
        guard_id = current_user.user_id
    shifts_list = shift_manager.get_shifts(guard_id=guard_id, object_id=shift_object_id, limit=100)
    if shift_status:
        shifts_list = [s for s in shifts_list if s['status'] == shift_status]
    for s in shifts_list:
        guard = guard_manager.get_guard(s['guard_id'])
        s['guard_full_name'] = guard['full_name'] if guard else ('ID: ' + str(s['guard_id']))
        s['guard_phone'] = guard.get('phone', '') if guard else ''

    # Події
    ev_object_id = request.args.get('ev_object_id', type=int)
    event_type = request.args.get('event_type', '')
    if not current_user.is_senior:
        ev_object_id = current_user.object_id
    events_list = event_manager.get_events(object_id=ev_object_id, event_type=event_type if event_type else None, limit=100)
    for ev in events_list:
        shift = shift_manager.get_shift(ev['shift_id'])
        if shift:
            guard = guard_manager.get_guard(shift['guard_id'])
            ev['guard_full_name'] = guard['full_name'] if guard else ('ID: ' + str(shift['guard_id']))
            ev['guard_phone'] = guard.get('phone', '') if guard else ''
        else:
            ev['guard_full_name'] = '—'
            ev['guard_phone'] = ''
    # Передачі
    handover_status = request.args.get('handover_status', '')
    if current_user.is_senior:
        handovers_list = handover_manager.get_handovers(status=handover_status if handover_status else None, limit=100)
    else:
        sent = handover_manager.get_handovers(handover_by_id=current_user.user_id, limit=50)
        received = handover_manager.get_handovers(handover_to_id=current_user.user_id, limit=50)
        handovers_list = sent + received
    for h in handovers_list:
        by_guard = guard_manager.get_guard(h['handover_by_id'])
        to_guard = guard_manager.get_guard(h['handover_to_id'])
        h['handover_by_full_name'] = by_guard['full_name'] if by_guard else ('ID: ' + str(h['handover_by_id']))
        h['handover_by_phone'] = by_guard.get('phone', '') if by_guard else ''
        h['handover_to_full_name'] = to_guard['full_name'] if to_guard else ('ID: ' + str(h['handover_to_id']))
        h['handover_to_phone'] = to_guard.get('phone', '') if to_guard else ''
    # Звіти (тільки для старших/адмінів)
    report_object_id = request.args.get('report_object_id', type=int)
    if current_user.is_senior:
        reports_list = report_manager.get_reports(object_id=report_object_id, limit=100)
        for r in reports_list:
            by_guard = guard_manager.get_guard(r['handover_by_id'])
            to_guard = guard_manager.get_guard(r['handover_to_id'])
            r['handover_by_full_name'] = by_guard['full_name'] if by_guard else ('ID: ' + str(r['handover_by_id']))
            r['handover_by_phone'] = by_guard.get('phone', '') if by_guard else ''
            r['handover_to_full_name'] = to_guard['full_name'] if to_guard else ('ID: ' + str(r['handover_to_id']))
            r['handover_to_phone'] = to_guard.get('phone', '') if to_guard else ''
    else:
        reports_list = []

    return render_template('journal.html',
                         tab=tab,
                         shifts=shifts_list,
                         events=events_list,
                         handovers=handovers_list,
                         reports=reports_list,
                         guards=guards_list,
                         objects=objects_list,
                         selected_guard_id=guard_id,
                         selected_shift_object_id=shift_object_id,
                         selected_shift_status=shift_status,
                         selected_ev_object_id=ev_object_id,
                         selected_event_type=event_type,
                         selected_handover_status=handover_status,
                         selected_report_object_id=report_object_id)


@app.route('/shifts')
@login_required
def shifts():
    """Сторінка перегляду змін"""
    shift_manager = get_shift_manager()
    
    # Фільтри
    guard_id = request.args.get('guard_id', type=int)
    object_id = request.args.get('object_id', type=int)
    status = request.args.get('status', '')
    
    # Для звичайних охоронців - тільки свої зміни
    if not current_user.is_senior:
        guard_id = current_user.user_id
    
    shifts_list = shift_manager.get_shifts(
        guard_id=guard_id,
        object_id=object_id,
        limit=100
    )
    
    # Фільтрація за статусом
    if status:
        shifts_list = [s for s in shifts_list if s['status'] == status]
    
    guard_manager = get_guard_manager()
    object_manager = get_object_manager()
    
    for s in shifts_list:
        guard = guard_manager.get_guard(s['guard_id'])
        s['guard_full_name'] = guard['full_name'] if guard else ('ID: ' + str(s['guard_id']))
        s['guard_phone'] = guard.get('phone', '') if guard else ''
    
    guards_list = guard_manager.get_all_guards() if current_user.is_senior else []
    objects_list = object_manager.get_all_objects(active_only=True)
    
    return render_template('shifts.html',
                         shifts=shifts_list,
                         guards=guards_list,
                         objects=objects_list,
                         selected_guard_id=guard_id,
                         selected_object_id=object_id,
                         selected_status=status)


@app.route('/points')
@admin_required
def points():
    """Сторінка балів охоронців: таблиця з балансом та історія операцій"""
    points_mgr = get_points_manager()
    guard_mgr = get_guard_manager()
    object_mgr = get_object_manager()
    guards_list = guard_mgr.get_all_guards()
    balances = {g['user_id']: points_mgr.get_balance(g['user_id']) for g in guards_list}
    history = points_mgr.get_history(guard_id=None, limit=50)
    objects_list = object_mgr.get_all_objects(active_only=True)
    objects_by_id = {obj['id']: obj['name'] for obj in objects_list}
    return render_template('points.html',
                          guards=guards_list,
                          balances=balances,
                          history=history,
                          objects_by_id=objects_by_id)


@app.route('/points/add', methods=['POST'])
@admin_required
def points_add():
    """Нарахування або зняття балів охоронцю"""
    guard_id = request.form.get('guard_id', type=int)
    points_delta_raw = request.form.get('points_delta', type=str)
    reason = request.form.get('reason', '').strip()[:500] or None
    if guard_id is None:
        flash('Оберіть охоронця.', 'danger')
        return redirect(url_for('points'))
    try:
        points_delta = int(points_delta_raw)
    except (TypeError, ValueError):
        flash('Введіть коректне число балів (додатнє або від\'ємне).', 'danger')
        return redirect(url_for('points'))
    if points_delta == 0:
        flash('Введіть ненульове значення балів.', 'warning')
        return redirect(url_for('points'))
    points_mgr = get_points_manager()
    if points_mgr.add_points(guard_id, points_delta, reason, created_by_id=current_user.user_id):
        flash(f'Бали успішно нараховано: {points_delta:+d}.', 'success')
    else:
        flash('Не вдалося нарахувати бали. Перевірте охоронця.', 'danger')
    return redirect(url_for('points'))


@app.route('/points/edit/<int:point_id>', methods=['POST'])
@admin_required
def points_edit(point_id):
    """Редагування запису балів."""
    points_delta_raw = request.form.get('points_delta', type=str)
    reason = request.form.get('reason', '').strip()[:500] or None
    try:
        points_delta = int(points_delta_raw)
    except (TypeError, ValueError):
        flash('Введіть коректне число балів.', 'danger')
        return redirect(url_for('points'))
    if points_delta == 0:
        flash('Бали не можуть бути нулем.', 'warning')
        return redirect(url_for('points'))
    points_mgr = get_points_manager()
    if points_mgr.update_point(point_id, points_delta, reason):
        flash('Запис балів оновлено.', 'success')
    else:
        flash('Не вдалося оновити запис.', 'danger')
    return redirect(url_for('points'))


@app.route('/points/delete/<int:point_id>', methods=['POST'])
@admin_required
def points_delete(point_id):
    """Видалення запису балів."""
    points_mgr = get_points_manager()
    if points_mgr.delete_point(point_id):
        flash('Запис балів видалено.', 'success')
    else:
        flash('Не вдалося видалити запис.', 'danger')
    return redirect(url_for('points'))


@app.route('/announcements')
@admin_required
def announcements():
    """Сторінка оголошень: історія та створення."""
    try:
        announcement_mgr = get_announcement_manager()
        announcements_list = announcement_mgr.get_announcement_history(limit=50)
        users_list = announcement_mgr.get_all_users_for_select()
        object_mgr = get_object_manager()
        objects_list = object_mgr.get_all_objects(active_only=True)
        return render_template(
            'announcements.html',
            announcements=announcements_list,
            users=users_list,
            objects=objects_list,
        )
    except Exception as e:
        logger.log_error(f"Помилка завантаження оголошень: {e}")
        flash(f'Помилка завантаження оголошень: {e}', 'danger')
        return render_template('announcements.html', announcements=[], users=[], objects=[])


@app.route('/announcements/create', methods=['POST'])
@admin_required
def create_announcement():
    """Створення та відправка оголошення охоронцям."""
    try:
        content = request.form.get('content', '').strip()
        priority = request.form.get('priority', 'normal')
        recipient_type = request.form.get('recipient_type', 'users')
        recipient_ids = []

        if recipient_type == 'objects':
            object_ids = [int(oid) for oid in request.form.getlist('object_ids')]
            if not object_ids:
                flash('Виберіть хоча б один об\'єкт.', 'warning')
                return redirect(url_for('announcements'))
            with get_session() as session:
                users = session.query(User).filter(
                    User.object_id.in_(object_ids),
                    User.is_active == True,
                ).all()
                recipient_ids = [u.user_id for u in users]
        else:
            recipient_ids = [int(rid) for rid in request.form.getlist('recipient_ids')]

        if not recipient_ids:
            flash('Виберіть хоча б одного отримувача.', 'warning')
            return redirect(url_for('announcements'))
        if not content:
            flash('Введіть текст оголошення.', 'warning')
            return redirect(url_for('announcements'))

        announcement_mgr = get_announcement_manager()
        result = announcement_mgr.send_announcement_to_users(
            recipient_user_ids=recipient_ids,
            content=content,
            priority=priority,
            author_id=current_user.user_id,
            author_username=current_user.username or f"user_{current_user.user_id}",
        )
        if result['sent'] > 0:
            flash(f'Оголошення відправлено {result["sent"]} охоронцям.', 'success')
        if result['failed'] > 0:
            flash(f'Помилка відправки: {result["failed"]} оголошень.', 'warning')
    except Exception as e:
        logger.log_error(f"Помилка створення оголошення: {e}")
        flash(f'Помилка створення оголошення: {e}', 'danger')
    return redirect(url_for('announcements'))


@app.route('/announcements/<int:ann_id>/recipients')
@admin_required
def announcement_recipients(ann_id):
    """Перегляд отримувачів оголошення."""
    try:
        announcement_mgr = get_announcement_manager()
        recipients = announcement_mgr.get_announcement_recipients(ann_id)
        with get_session() as session:
            ann = session.query(Announcement).filter(Announcement.id == ann_id).first()
            if not ann:
                flash('Оголошення не знайдено.', 'warning')
                return redirect(url_for('announcements'))
            announcement_data = {
                'id': ann.id,
                'content': ann.content,
                'author_username': ann.author_username,
                'priority': ann.priority,
                'sent_at': ann.sent_at,
            }
        return render_template(
            'announcement_recipients.html',
            announcement=announcement_data,
            recipients=recipients,
        )
    except Exception as e:
        logger.log_error(f"Помилка отримання отримувачів оголошення: {e}")
        flash(f'Помилка отримання отримувачів: {e}', 'danger')
        return redirect(url_for('announcements'))


@app.route('/announcements/<int:ann_id>/delete', methods=['POST'])
@admin_required
def delete_announcement(ann_id):
    """Видалення оголошення."""
    try:
        announcement_mgr = get_announcement_manager()
        if announcement_mgr.delete_announcement(ann_id):
            flash('Оголошення видалено.', 'success')
        else:
            flash('Оголошення не знайдено.', 'warning')
    except Exception as e:
        logger.log_error(f"Помилка видалення оголошення: {e}")
        flash(f'Помилка видалення оголошення: {e}', 'danger')
    return redirect(url_for('announcements'))


# Назви місяців українською для графіка змін
MONTH_NAMES_UA = (
    '', 'СІЧЕНЬ', 'ЛЮТИЙ', 'БЕРЕЗЕНЬ', 'КВІТЕНЬ', 'ТРАВЕНЬ', 'ЧЕРВЕНЬ',
    'ЛИПЕНЬ', 'СЕРПЕНЬ', 'ВЕРЕСЕНЬ', 'ЖОВТЕНЬ', 'ЛИСТОПАД', 'ГРУДЕНЬ'
)


@app.route('/schedule')
@login_required
def schedule_page():
    """Сторінка графіка змін: сітка місяця (охоронці × дні)."""
    from datetime import date
    import calendar as cal_mod
    today = date.today()
    year = request.args.get('year', type=int) or today.year
    month = request.args.get('month', type=int) or today.month
    object_id = request.args.get('object_id', type=int)

    # Корекція меж
    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1

    schedule_mgr = get_schedule_manager()
    guards = schedule_mgr.get_guards_for_schedule(object_id=object_id)
    slots_set = schedule_mgr.get_slots_for_month(year, month, object_id=object_id)
    _, days_in_month = cal_mod.monthrange(year, month)
    month_name = MONTH_NAMES_UA[month] if 1 <= month <= 12 else ''
    object_mgr = get_object_manager()
    objects_list = object_mgr.get_all_objects(active_only=True)
    return render_template(
        'schedule.html',
        year=year,
        month=month,
        month_name=month_name,
        days_in_month=days_in_month,
        guards=guards,
        slots_set=slots_set,
        objects_list=objects_list,
        selected_object_id=object_id,
    )


@app.route('/schedule/toggle', methods=['POST'])
@login_required
def schedule_toggle():
    """Перемикання слота (додати/прибрати зміну в день). Редирект назад на графік."""
    from datetime import date, datetime as dt
    guard_id = request.form.get('guard_id', type=int)
    date_str = request.form.get('date', '').strip()
    year = request.form.get('year', type=int)
    month = request.form.get('month', type=int)
    object_id = request.form.get('object_id', type=int) or None
    if not guard_id or not date_str:
        flash('Невірні параметри.', 'danger')
        return redirect(url_for('schedule_page'))
    try:
        slot_date = dt.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Невірна дата.', 'danger')
        return redirect(url_for('schedule_page'))
    schedule_mgr = get_schedule_manager()
    new_state = schedule_mgr.toggle_slot(guard_id, slot_date)
    if new_state is None:
        flash('Помилка збереження.', 'danger')
    return redirect(url_for('schedule_page', year=year, month=month, object_id=object_id))


def _get_cyrillic_font_name():
    """Реєструє шрифт з підтримкою кирилиці (Arial/DejaVu). Повертає ім'я шрифту для ReportLab."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    windir = os.environ.get('WINDIR', 'C:\\Windows')
    candidates = [
        os.path.join(windir, 'Fonts', 'arial.ttf'),
        os.path.join(windir, 'Fonts', 'arialuni.ttf'),
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    for path in candidates:
        try:
            if os.path.isfile(path):
                pdfmetrics.registerFont(TTFont('CyrillicFont', path))
                return 'CyrillicFont'
        except Exception:
            continue
    return 'Helvetica'


def _build_schedule_pdf(year: int, month: int, object_id, guards, slots_set, days_in_month, month_name: str):
    """Збирає PDF графіка змін: заголовок — місяць, таблиця охоронці × дні, сірі клітинки — зміни."""
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

    font_name = _get_cyrillic_font_name()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12*mm, rightMargin=12*mm,
                            topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    base_title = styles['Title']
    title_style = ParagraphStyle(name='TitleCyrillic', parent=base_title, fontName=font_name)
    story = []

    # Заголовок — назва місяця
    title = Paragraph(f'<b>{month_name} {year}</b>', title_style)
    story.append(title)
    story.append(Spacer(1, 6*mm))

    # Таблиця: рядок заголовків + рядки охоронців
    header_row = ['№ з/п', "Прізвище, ім'я по батькові"] + [str(d) for d in range(1, days_in_month + 1)]
    data = [header_row]
    for idx, guard in enumerate(guards):
        row = [str(idx + 1), guard['full_name']]
        for day in range(1, days_in_month + 1):
            row.append('' if (guard['user_id'], day) in slots_set else '')
        data.append(row)

    col_widths = [18*mm, 45*mm] + [6*mm] * days_in_month
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]
    for row_idx, guard in enumerate(guards):
        for day in range(1, days_in_month + 1):
            if (guard['user_id'], day) in slots_set:
                col = 1 + day  # колонка дня: день 1 -> 2, день 31 -> 32
                style.append(('BACKGROUND', (col, 1 + row_idx), (col, 1 + row_idx), colors.lightgrey))
    t.setStyle(TableStyle(style))
    story.append(t)
    doc.build(story)
    buf.seek(0)
    return buf


@app.route('/schedule/pdf')
@login_required
def schedule_pdf():
    """Експорт графіка змін за місяць у PDF (таблиця охоронці × дні, сірі клітинки — зміни)."""
    from datetime import date
    import calendar as cal_mod
    today = date.today()
    year = request.args.get('year', type=int) or today.year
    month = request.args.get('month', type=int) or today.month
    object_id = request.args.get('object_id', type=int) or None
    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1
    _, days_in_month = cal_mod.monthrange(year, month)
    month_name = MONTH_NAMES_UA[month] if 1 <= month <= 12 else ''
    schedule_mgr = get_schedule_manager()
    guards = schedule_mgr.get_guards_for_schedule(object_id=object_id, exclude_admin=True)
    slots_set = schedule_mgr.get_slots_for_month(year, month, object_id=object_id)
    if not guards:
        flash('Немає даних для експорту.', 'warning')
        return redirect(url_for('schedule_page', year=year, month=month, object_id=object_id))
    try:
        pdf_buf = _build_schedule_pdf(year, month, object_id, guards, slots_set, days_in_month, month_name)
        filename = f'grafik_zmin_{year}_{month:02d}.pdf'
        return send_file(pdf_buf, mimetype='application/pdf', as_attachment=True, download_name=filename)
    except Exception as e:
        logger.log_error(f"Помилка експорту графіка в PDF: {e}")
        flash('Помилка формування PDF.', 'danger')
        return redirect(url_for('schedule_page', year=year, month=month, object_id=object_id))


@app.route('/vacation_schedule')
@login_required
def vacation_schedule_page():
    """Сторінка графіка відпусток: сітка місяця (охоронці × дні)."""
    from datetime import date
    import calendar as cal_mod
    today = date.today()
    year = request.args.get('year', type=int) or today.year
    month = request.args.get('month', type=int) or today.month
    object_id = request.args.get('object_id', type=int)

    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1

    vacation_mgr = get_vacation_manager()
    guards = vacation_mgr.get_guards_for_schedule(object_id=object_id)
    slots_set = vacation_mgr.get_slots_for_month(year, month, object_id=object_id)
    _, days_in_month = cal_mod.monthrange(year, month)
    month_name = MONTH_NAMES_UA[month] if 1 <= month <= 12 else ''
    object_mgr = get_object_manager()
    objects_list = object_mgr.get_all_objects(active_only=True)
    return render_template(
        'vacation_schedule.html',
        year=year,
        month=month,
        month_name=month_name,
        days_in_month=days_in_month,
        guards=guards,
        slots_set=slots_set,
        objects_list=objects_list,
        selected_object_id=object_id,
    )


@app.route('/vacation_schedule/toggle', methods=['POST'])
@login_required
def vacation_schedule_toggle():
    """Перемикання дня відпустки. Редирект назад на графік відпусток."""
    from datetime import datetime as dt
    guard_id = request.form.get('guard_id', type=int)
    date_str = request.form.get('date', '').strip()
    year = request.form.get('year', type=int)
    month = request.form.get('month', type=int)
    object_id = request.form.get('object_id', type=int) or None
    if not guard_id or not date_str:
        flash('Невірні параметри.', 'danger')
        return redirect(url_for('vacation_schedule_page'))
    try:
        vacation_date = dt.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Невірна дата.', 'danger')
        return redirect(url_for('vacation_schedule_page'))
    vacation_mgr = get_vacation_manager()
    new_state = vacation_mgr.toggle_slot(guard_id, vacation_date)
    if new_state is None:
        flash('Помилка збереження.', 'danger')
    return redirect(url_for('vacation_schedule_page', year=year, month=month, object_id=object_id))


@app.route('/shifts/<int:shift_id>')
@login_required
def shift_detail(shift_id):
    """Детальна інформація про зміну"""
    shift_manager = get_shift_manager()
    event_manager = get_event_manager()
    
    shift = shift_manager.get_shift(shift_id)
    if not shift:
        flash('Зміну не знайдено.', 'danger')
        return redirect(url_for('shifts'))
    
    # Перевірка прав доступу
    if not current_user.is_senior and shift['guard_id'] != current_user.user_id:
        flash('Доступ заборонено.', 'danger')
        return redirect(url_for('shifts'))
    
    events = event_manager.get_shift_events(shift_id)
    
    guard_manager = get_guard_manager()
    guard = guard_manager.get_guard(shift['guard_id'])
    
    object_manager = get_object_manager()
    objects_list = object_manager.get_all_objects(active_only=True)
    
    return render_template('shift_detail.html', shift=shift, events=events, guard=guard, objects=objects_list)


@app.route('/shifts/<int:shift_id>/edit', methods=['POST'])
@admin_required
def edit_shift(shift_id):
    """Редагування зміни"""
    shift_manager = get_shift_manager()
    
    guard_id = request.form.get('guard_id', type=int)
    object_id = request.form.get('object_id', type=int)
    start_time_str = request.form.get('start_time', '').strip()
    end_time_str = request.form.get('end_time', '').strip()
    status = request.form.get('status', '').strip()
    
    update_data = {}
    if guard_id:
        update_data['guard_id'] = guard_id
    if object_id:
        update_data['object_id'] = object_id
    if start_time_str:
        try:
            from datetime import datetime
            update_data['start_time'] = datetime.fromisoformat(start_time_str.replace(' ', 'T'))
        except:
            flash('Невірний формат часу початку.', 'danger')
            return redirect(url_for('shift_detail', shift_id=shift_id))
    if end_time_str:
        try:
            from datetime import datetime
            update_data['end_time'] = datetime.fromisoformat(end_time_str.replace(' ', 'T'))
        except:
            flash('Невірний формат часу завершення.', 'danger')
            return redirect(url_for('shift_detail', shift_id=shift_id))
    if status:
        if status not in ('ACTIVE', 'COMPLETED', 'HANDED_OVER'):
            flash('Невірний статус зміни.', 'danger')
            return redirect(url_for('shift_detail', shift_id=shift_id))
        update_data['status'] = status
    
    if not update_data:
        flash('Немає даних для оновлення.', 'warning')
        return redirect(url_for('shift_detail', shift_id=shift_id))
    
    success = shift_manager.update_shift(shift_id, **update_data)
    
    if success:
        flash('Зміну оновлено.', 'success')
    else:
        flash('Помилка оновлення зміни.', 'danger')
    
    return redirect(url_for('shift_detail', shift_id=shift_id))


@app.route('/shifts/<int:shift_id>/delete', methods=['POST'])
@admin_required
def delete_shift(shift_id):
    """Видалення зміни"""
    shift_manager = get_shift_manager()
    success = shift_manager.delete_shift(shift_id)
    
    if success:
        flash('Зміну видалено.', 'success')
    else:
        flash('Помилка видалення зміни.', 'danger')
    
    return redirect(url_for('shifts'))


@app.route('/events')
@login_required
def events():
    """Сторінка перегляду подій"""
    event_manager = get_event_manager()
    
    # Фільтри
    object_id = request.args.get('object_id', type=int)
    event_type = request.args.get('event_type', '')
    
    # Для звичайних охоронців - тільки події зі свого об'єкта
    if not current_user.is_senior:
        object_id = current_user.object_id
    
    events_list = event_manager.get_events(
        object_id=object_id,
        event_type=event_type if event_type else None,
        limit=100
    )
    
    shift_manager = get_shift_manager()
    guard_manager = get_guard_manager()
    for ev in events_list:
        shift = shift_manager.get_shift(ev['shift_id'])
        if shift:
            guard = guard_manager.get_guard(shift['guard_id'])
            ev['guard_full_name'] = guard['full_name'] if guard else ('ID: ' + str(shift['guard_id']))
            ev['guard_phone'] = guard.get('phone', '') if guard else ''
        else:
            ev['guard_full_name'] = '—'
            ev['guard_phone'] = ''
    
    object_manager = get_object_manager()
    objects_list = object_manager.get_all_objects(active_only=True)
    
    return render_template('events.html',
                         events=events_list,
                         objects=objects_list,
                         selected_object_id=object_id,
                         selected_event_type=event_type)


@app.route('/handovers')
@login_required
def handovers():
    """Сторінка перегляду передач"""
    handover_manager = get_handover_manager()
    
    # Фільтри
    status = request.args.get('status', '')
    
    # Для звичайних охоронців - тільки свої передачі
    if current_user.is_senior:
        handovers_list = handover_manager.get_handovers(status=status if status else None, limit=100)
    else:
        sent = handover_manager.get_handovers(handover_by_id=current_user.user_id, limit=50)
        received = handover_manager.get_handovers(handover_to_id=current_user.user_id, limit=50)
        handovers_list = sent + received
    
    guard_manager = get_guard_manager()
    for h in handovers_list:
        by_guard = guard_manager.get_guard(h['handover_by_id'])
        to_guard = guard_manager.get_guard(h['handover_to_id'])
        h['handover_by_full_name'] = by_guard['full_name'] if by_guard else ('ID: ' + str(h['handover_by_id']))
        h['handover_by_phone'] = by_guard.get('phone', '') if by_guard else ''
        h['handover_to_full_name'] = to_guard['full_name'] if to_guard else ('ID: ' + str(h['handover_to_id']))
        h['handover_to_phone'] = to_guard.get('phone', '') if to_guard else ''
    
    return render_template('handovers.html',
                         handovers=handovers_list,
                         selected_status=status)


@app.route('/handovers/<int:handover_id>')
@login_required
def handover_detail(handover_id):
    """Детальна інформація про передачу"""
    handover_manager = get_handover_manager()
    handover = handover_manager.get_handover(handover_id)
    
    if not handover:
        flash('Передачу не знайдено.', 'danger')
        return redirect(url_for('handovers'))
    
    # Перевірка прав доступу
    if not current_user.is_senior:
        if handover['handover_by_id'] != current_user.user_id and handover['handover_to_id'] != current_user.user_id:
            flash('Доступ заборонено.', 'danger')
            return redirect(url_for('handovers'))
    
    guard_manager = get_guard_manager()
    handover_by = guard_manager.get_guard(handover['handover_by_id'])
    handover_to = guard_manager.get_guard(handover['handover_to_id'])
    
    return render_template('handover_detail.html',
                         handover=handover,
                         handover_by=handover_by,
                         handover_to=handover_to)


@app.route('/handovers/<int:handover_id>/edit', methods=['POST'])
@admin_required
def edit_handover(handover_id):
    """Редагування передачі"""
    handover_manager = get_handover_manager()
    
    summary = request.form.get('summary', '').strip()
    notes = request.form.get('notes', '').strip()
    status = request.form.get('status', '').strip()
    
    update_data = {}
    if summary:
        update_data['summary'] = summary
    if notes is not None:
        update_data['notes'] = notes
    if status:
        if status not in ('PENDING', 'ACCEPTED', 'ACCEPTED_WITH_NOTES'):
            flash('Невірний статус передачі.', 'danger')
            return redirect(url_for('handover_detail', handover_id=handover_id))
        update_data['status'] = status
    
    if not update_data:
        flash('Немає даних для оновлення.', 'warning')
        return redirect(url_for('handover_detail', handover_id=handover_id))
    
    success = handover_manager.update_handover(handover_id, **update_data)
    
    if success:
        flash('Передачу оновлено.', 'success')
    else:
        flash('Помилка оновлення передачі.', 'danger')
    
    return redirect(url_for('handover_detail', handover_id=handover_id))


@app.route('/handovers/<int:handover_id>/delete', methods=['POST'])
@admin_required
def delete_handover(handover_id):
    """Видалення передачі"""
    handover_manager = get_handover_manager()
    success = handover_manager.delete_handover(handover_id)
    
    if success:
        flash('Передачу видалено.', 'success')
    else:
        flash('Помилка видалення передачі.', 'danger')
    
    return redirect(url_for('handovers'))


@app.route('/reports')
@senior_required
def reports():
    """Сторінка перегляду звітів"""
    report_manager = get_report_manager()
    
    object_id = request.args.get('object_id', type=int)
    
    reports_list = report_manager.get_reports(object_id=object_id, limit=100)
    
    guard_manager = get_guard_manager()
    for r in reports_list:
        by_guard = guard_manager.get_guard(r['handover_by_id'])
        to_guard = guard_manager.get_guard(r['handover_to_id'])
        r['handover_by_full_name'] = by_guard['full_name'] if by_guard else ('ID: ' + str(r['handover_by_id']))
        r['handover_by_phone'] = by_guard.get('phone', '') if by_guard else ''
        r['handover_to_full_name'] = to_guard['full_name'] if to_guard else ('ID: ' + str(r['handover_to_id']))
        r['handover_to_phone'] = to_guard.get('phone', '') if to_guard else ''
    
    object_manager = get_object_manager()
    objects_list = object_manager.get_all_objects(active_only=True)
    
    return render_template('reports.html',
                         reports=reports_list,
                         objects=objects_list,
                         selected_object_id=object_id)


@app.route('/reports/<int:report_id>')
@senior_required
def report_detail(report_id):
    """Детальна інформація про звіт"""
    try:
        report_manager = get_report_manager()
        report = report_manager.get_report(report_id)
        
        if not report:
            flash('Звіт не знайдено.', 'danger')
            return redirect(url_for('reports'))
        
        guard_manager = get_guard_manager()
        object_manager = get_object_manager()
        
        handover_by = guard_manager.get_guard(report['handover_by_id'])
        handover_to = guard_manager.get_guard(report['handover_to_id'])
        obj = object_manager.get_object(report['object_id'])
        
        return render_template('report_detail.html',
                             report=report,
                             handover_by=handover_by,
                             handover_to=handover_to,
                             obj=obj)
    except Exception as e:
        logger.log_error(f"Помилка отримання звіту: {e}")
        flash('Помилка завантаження звіту.', 'danger')
        return redirect(url_for('reports'))


@app.route('/reports/<int:report_id>/edit', methods=['POST'])
@admin_required
def edit_report(report_id):
    """Редагування звіту"""
    report_manager = get_report_manager()
    
    notes = request.form.get('notes', '').strip()
    
    if not notes:
        flash('Текст зауважень не може бути порожнім.', 'danger')
        return redirect(url_for('report_detail', report_id=report_id))
    
    success = report_manager.update_report(report_id, notes=notes)
    
    if success:
        flash('Звіт оновлено.', 'success')
    else:
        flash('Помилка оновлення звіту.', 'danger')
    
    return redirect(url_for('report_detail', report_id=report_id))


@app.route('/reports/<int:report_id>/delete', methods=['POST'])
@admin_required
def delete_report(report_id):
    """Видалення звіту"""
    report_manager = get_report_manager()
    success = report_manager.delete_report(report_id)
    
    if success:
        flash('Звіт видалено.', 'success')
    else:
        flash('Помилка видалення звіту.', 'danger')
    
    return redirect(url_for('reports'))


@app.route('/events/<int:event_id>/edit', methods=['POST'])
@admin_required
def edit_event(event_id):
    """Редагування події"""
    event_manager = get_event_manager()
    
    event_type = request.form.get('event_type', '').strip()
    description = request.form.get('description', '').strip()
    
    update_data = {}
    if event_type:
        update_data['event_type'] = event_type
    if description:
        update_data['description'] = description
    
    if not update_data:
        flash('Немає даних для оновлення.', 'warning')
        return redirect(url_for('events'))
    
    success = event_manager.update_event(event_id, **update_data)
    
    if success:
        flash('Подію оновлено.', 'success')
    else:
        flash('Помилка оновлення події.', 'danger')
    
    return redirect(url_for('events'))


@app.route('/events/<int:event_id>/delete', methods=['POST'])
@admin_required
def delete_event(event_id):
    """Видалення події"""
    event_manager = get_event_manager()
    success = event_manager.delete_event(event_id)
    
    if success:
        flash('Подію видалено.', 'success')
    else:
        flash('Помилка видалення події.', 'danger')
    
    return redirect(url_for('events'))


@app.route('/objects/<int:object_id>/delete', methods=['POST'])
@admin_required
def delete_object(object_id):
    """Видалення об'єкта"""
    object_manager = get_object_manager()
    success = object_manager.delete_object(object_id)
    
    if success:
        flash('Об\'єкт видалено.', 'success')
    else:
        flash('Помилка видалення об\'єкта. Можливо, на об\'єкті є користувачі або активні зміни.', 'danger')
    
    return redirect(url_for('objects'))


@app.route('/logs')
@admin_required
def logs():
    """Сторінка перегляду логів"""
    level = request.args.get('level', '')
    user_id = request.args.get('user_id', type=int)
    
    with get_session() as session:
        query = session.query(Log)
        
        if level:
            query = query.filter(Log.level == level.upper())
        
        if user_id:
            query = query.filter(Log.user_id == user_id)
        
        logs_list = query.order_by(Log.timestamp.desc()).limit(500).all()
        
        logs_data = [
            {
                'id': log.id,
                'timestamp': log.timestamp,
                'level': log.level,
                'message': log.message,
                'user_id': log.user_id,
                'command': log.command
            }
            for log in logs_list
        ]
    
    return render_template('logs.html', logs=logs_data, selected_level=level, selected_user_id=user_id)


@app.route('/logs/delete', methods=['POST'])
@admin_required
def logs_delete():
    """Видалення логів: всі або вибрані за id."""
    with get_session() as session:
        delete_all = request.form.get('delete_all') == '1'
        ids = request.form.getlist('ids', type=int)
        if delete_all:
            deleted = session.query(Log).delete()
            session.commit()
            flash(f'Видалено логів: {deleted}.', 'success')
        elif ids:
            deleted = session.query(Log).filter(Log.id.in_(ids)).delete(synchronize_session=False)
            session.commit()
            flash(f'Видалено логів: {deleted}.', 'success')
        else:
            flash('Нічого не вибрано для видалення.', 'warning')
    return redirect(url_for('logs'))


# PWA маршрути
@app.route('/manifest.json')
def manifest():
    """PWA Web App Manifest"""
    return send_file(os.path.join(app.root_path, 'static', 'manifest.json'), mimetype='application/manifest+json')


@app.route('/sw.js')
@csrf.exempt
def service_worker():
    """Service Worker для PWA"""
    response = send_file(os.path.join(app.root_path, 'static', 'js', 'sw.js'), mimetype='application/javascript')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/apple-touch-icon.png')
@app.route('/apple-touch-icon-precomposed.png')
@app.route('/apple-touch-icon-120x120.png')
@app.route('/apple-touch-icon-120x120-precomposed.png')
def apple_touch_icon():
    """Обробка запитів на apple-touch-icon для iOS"""
    try:
        return send_file(os.path.join(app.root_path, 'static', 'icons', 'apple-touch-icon.png'), mimetype='image/png')
    except FileNotFoundError:
        return '', 204


@app.template_filter('datetime_format')
def datetime_format_filter(value):
    """Форматування дати та часу"""
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            return dt.strftime('%d.%m.%Y %H:%M')
        except:
            return value
    elif isinstance(value, datetime):
        return value.strftime('%d.%m.%Y %H:%M')
    return value


if __name__ == '__main__':
    app.run(host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', 9080)), debug=FLASK_DEBUG)
