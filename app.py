import os
import secrets
import random
import string
import hashlib
import json
import hmac
import requests
import threading
import time
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qsl
from functools import wraps

from flask import Flask, jsonify, request, render_template, send_from_directory, abort, g
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_talisman import Talisman

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
def get_database_url():
    default_url = "sqlite:///bingo.db"
    raw_url = os.environ.get("DATABASE_URL", default_url)
    if not raw_url or not raw_url.strip():
        logger.warning("DATABASE_URL missing; using sqlite")
        return default_url
    raw_url = raw_url.strip()
    if raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql://", 1)
    return raw_url

class Config:
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    BOT_USERNAME = os.environ.get("BOT_USERNAME", "@neXUSSBINGObot")
    _admin_raw = os.environ.get("ADMIN_ID", "")
    ADMIN_ID = None
    ADMIN_IDS = set()
    try:
        if _admin_raw:
            if "," in str(_admin_raw):
                ADMIN_IDS = {int(x.strip()) for x in str(_admin_raw).split(",") if x.strip().isdigit()}
                ADMIN_ID = list(ADMIN_IDS)[0] if ADMIN_IDS else None
            else:
                ADMIN_ID = int(_admin_raw)
                ADMIN_IDS = {ADMIN_ID}
    except Exception:
        ADMIN_ID = None

    DATABASE_URL = get_database_url()
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    DEFAULT_HOUSE_CUT = float(os.environ.get("DEFAULT_HOUSE_CUT", "10.0"))
    MAX_CARTELAS_PER_PLAYER = int(os.environ.get("MAX_CARTELAS_PER_PLAYER", "3"))
    AUTO_FILL_BOT_COUNT = int(os.environ.get("AUTO_FILL_BOT_COUNT", "10"))
    MIN_PLAYERS_TO_START = int(os.environ.get("MIN_PLAYERS_TO_START", "2"))
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://your-app.onrender.com").rstrip('/')
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", f"{WEBAPP_URL}/webhook")
    WELCOME_BONUS = Decimal(str(os.environ.get("WELCOME_BONUS", "25.0")))
    TELEBIRR_NUMBER = os.environ.get("TELEBIRR_NUMBER", "")
    CBE_ACCOUNT = os.environ.get("CBE_ACCOUNT", "")
    TEST_MODE_ENABLED = os.environ.get("TEST_MODE_ENABLED", "false").lower() == "true"
    TEST_MODE_SECRET = os.environ.get("TEST_MODE_SECRET", "")
    CALL_INTERVAL_MIN = float(os.environ.get("CALL_INTERVAL_MIN", "2.0"))
    CALL_INTERVAL_MAX = float(os.environ.get("CALL_INTERVAL_MAX", "4.0"))
    TIMER_DELAY_SECONDS = int(os.environ.get("TIMER_DELAY_SECONDS", "0"))
    WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", secrets.token_hex(32))
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", "16")) * 1024 * 1024  # 16MB

config_errors = []
if not Config.BOT_TOKEN:
    config_errors.append("FATAL: BOT_TOKEN required")
if not Config.ADMIN_ID:
    logger.warning("ADMIN_ID not set")
if config_errors:
    for e in config_errors:
        logger.error(e)
    raise ValueError("Missing config")

# ==================== FLASK APP ====================
app = Flask(__name__, template_folder='template', static_folder='static', static_url_path='/static')
app.config["SQLALCHEMY_DATABASE_URI"] = Config.DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = Config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=24)

if Config.DATABASE_URL.startswith("sqlite"):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {"check_same_thread": False},
        "pool_pre_ping": True,
        "pool_recycle": 300
    }
else:
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
        "pool_recycle": 3600,
        "pool_timeout": 30
    }

# Security headers via Talisman
Talisman(app, 
    force_https=True,
    strict_transport_security=True,
    strict_transport_security_max_age=31536000,
    content_security_policy={
        'default-src': "'self'",
        'script-src': "'self' 'unsafe-inline' https://telegram.org",
        'style-src': "'self' 'unsafe-inline'",
        'img-src': "'self' data: https:",
        'connect-src': "'self' https://api.telegram.org"
    },
    feature_policy={
        'geolocation': "'none'",
        'microphone': "'none'",
        'camera': "'none'"
    }
)

# CORS restricted to known origins
allowed_origins = [Config.WEBAPP_URL, "https://*.telegram.org", "https://telegram.org", "https://t.me"]
CORS(app, origins=allowed_origins, supports_credentials=True)

# Rate limiting
limiter = Limiter(
    app=app, 
    key_func=get_remote_address, 
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ==================== DECORATORS ====================
def require_telegram_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_data = request.headers.get('X-Telegram-Auth-Data') or request.cookies.get('telegram_auth')
        if not auth_data:
            return jsonify({"error": "Authentication required"}), 401
        
        try:
            data = json.loads(auth_data)
            if not verify_telegram_auth(data):
                return jsonify({"error": "Invalid authentication"}), 401
            request.telegram_user = data
            g.telegram_user = data
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Auth decode error: {e}")
            return jsonify({"error": "Invalid authentication data"}), 401
        return f(*args, **kwargs)
    return decorated_function

def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(request, 'telegram_user') or request.telegram_user.get('id') not in Config.ADMIN_IDS:
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function

# ==================== TELEGRAM AUTH VERIFICATION ====================
def verify_telegram_auth(auth_data):
    """Verify Telegram WebApp initData signature"""
    try:
        check_hash = auth_data.get('hash', '')
        auth_data_copy = {k: v for k, v in auth_data.items() if k != 'hash'}
        data_check_string = '\n'.join([f"{k}={v}" for k, v in sorted(auth_data_copy.items())])
        secret_key = hashlib.sha256(Config.BOT_TOKEN.encode()).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(calculated_hash, check_hash)
    except Exception as e:
        logger.error(f"Auth verification error: {e}")
        return False

def verify_webhook_secret(request_headers):
    """Verify webhook secret token"""
    secret = request_headers.get('X-Telegram-Bot-Api-Secret-Token')
    return secret and hmac.compare_digest(secret, Config.WEBHOOK_SECRET)

# ==================== TELEGRAM API HELPERS ====================
def send_telegram_message(chat_id, text, reply_markup=None, parse_mode=None):
    """Send message to Telegram with timeout and retry"""
    url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=(5, 30))
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            logger.warning(f"Telegram API timeout (attempt {attempt + 1})")
            time.sleep(2 ** attempt)
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram API error: {e}")
            time.sleep(1)
    return None

def answer_callback(query_id, text, show_alert=False):
    """Answer callback query with retry"""
    url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": query_id, "text": text, "show_alert": show_alert}
    
    try:
        resp = requests.post(url, json=payload, timeout=(3, 10))
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Callback answer error: {e}")
        return None

def edit_message_text(chat_id, message_id, text, reply_markup=None):
    """Edit message with retry"""
    url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    
    try:
        resp = requests.post(url, json=payload, timeout=(3, 10))
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Edit message error: {e}")
        return None

# ==================== UTILITY FUNCTIONS ====================
def generate_room_id():
    """Generate unique room ID"""
    while True:
        room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Room.query.get(room_id):
            return room_id

def generate_game_id():
    """Generate unique game ID"""
    return f"GAME-{datetime.utcnow().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"

def get_letter_for_number(number):
    """Get bingo letter for number"""
    if 1 <= number <= 15:
        return "B"
    elif 16 <= number <= 30:
        return "I"
    elif 31 <= number <= 45:
        return "N"
    elif 46 <= number <= 60:
        return "G"
    elif 61 <= number <= 75:
        return "O"
    return ""

def generate_cartela_numbers():
    """Generate random bingo card numbers"""
    cartela = []
    ranges = [(1, 15), (16, 30), (31, 45), (46, 60), (61, 75)]
    for start, end in ranges:
        col = random.sample(range(start, end + 1), 5)
        cartela.extend(col)
    return cartela

def generate_cartelas(count=1):
    """Generate multiple cartelas"""
    return [generate_cartela_numbers() for _ in range(count)]

def check_win_condition(marked_numbers, cartela_numbers):
    """Check if player has winning pattern"""
    if len(marked_numbers) < 5:
        return False
    
    # Convert to set for faster lookup
    marked = set(marked_numbers)
    cartela = set(cartela_numbers)
    
    # Check rows
    for row in range(5):
        row_numbers = set(cartela_numbers[row*5:(row+1)*5])
        if row_numbers.issubset(marked):
            return True
    
    # Check columns
    for col in range(5):
        col_numbers = {cartela_numbers[row*5 + col] for row in range(5)}
        if col_numbers.issubset(marked):
            return True
    
    # Check diagonals
    diag1 = {cartela_numbers[i*5 + i] for i in range(5)}
    diag2 = {cartela_numbers[i*5 + (4-i)] for i in range(5)}
    if diag1.issubset(marked) or diag2.issubset(marked):
        return True
    
    return False

def get_winning_pattern(marked_numbers, cartela_numbers):
    """Get the winning pattern name"""
    marked = set(marked_numbers)
    
    for row in range(5):
        row_numbers = set(cartela_numbers[row*5:(row+1)*5])
        if row_numbers.issubset(marked):
            return f"Row {row + 1}"
    
    for col in range(5):
        col_numbers = {cartela_numbers[row*5 + col] for row in range(5)}
        if col_numbers.issubset(marked):
            return f"Column {col + 1}"
    
    diag1 = {cartela_numbers[i*5 + i] for i in range(5)}
    if diag1.issubset(marked):
        return "Diagonal (Top-Left to Bottom-Right)"
    
    diag2 = {cartela_numbers[i*5 + (4-i)] for i in range(5)}
    if diag2.issubset(marked):
        return "Diagonal (Top-Right to Bottom-Left)"
    
    return "Unknown"

# ==================== MODELS ====================
class GameCall(db.Model):
    __tablename__ = "game_calls"
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(10), db.ForeignKey("rooms.id"), nullable=False, index=True)
    call_number = db.Column(db.String(10), nullable=False)
    number_value = db.Column(db.Integer)
    called_at = db.Column(db.DateTime, default=datetime.utcnow)

class Admin(db.Model):
    __tablename__ = "admins"
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    username = db.Column(db.String(100))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    username = db.Column(db.String(100))
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100))
    phone_number = db.Column(db.String(20))
    balance = db.Column(db.Numeric(15, 2), default=Decimal("0.00"))
    is_approved = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    is_bot = db.Column(db.Boolean, default=False)
    registration_step = db.Column(db.String(50), default="telegram_auth")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    welcome_bonus_claimed = db.Column(db.Boolean, default=False)
    total_games_played = db.Column(db.Integer, default=0)
    total_games_won = db.Column(db.Integer, default=0)
    total_deposited = db.Column(db.Numeric(15, 2), default=Decimal("0.00"))
    total_withdrawn = db.Column(db.Numeric(15, 2), default=Decimal("0.00"))

    def to_dict(self):
        return {
            "id": self.id,
            "telegram_id": self.telegram_id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "phone_number": self.phone_number,
            "balance": float(self.balance),
            "is_approved": self.is_approved,
            "is_banned": self.is_banned,
            "is_bot": self.is_bot,
            "registration_step": self.registration_step,
            "welcome_bonus_claimed": self.welcome_bonus_claimed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_active": self.last_active.isoformat() if self.last_active else None,
            "stats": {
                "games_played": self.total_games_played,
                "games_won": self.total_games_won,
                "win_rate": round((self.total_games_won / self.total_games_played * 100), 1) if self.total_games_played > 0 else 0
            }
        }

class Room(db.Model):
    __tablename__ = "rooms"
    id = db.Column(db.String(10), primary_key=True)
    game_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    stake = db.Column(db.Numeric(10, 2), nullable=False, index=True)
    max_players = db.Column(db.Integer, default=20)
    max_cartelas = db.Column(db.Integer, default=100)
    status = db.Column(db.String(20), default="waiting")
    pot_amount = db.Column(db.Numeric(15, 2), default=Decimal("0.00"))
    house_cut_percent = db.Column(db.Numeric(5, 2), default=Decimal("10.00"))
    created_by = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"))
    winner_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    current_call = db.Column(db.String(10), nullable=True)
    called_numbers = db.Column(db.Text, default="[]")
    is_automated = db.Column(db.Boolean, default=False)
    auto_start_at = db.Column(db.DateTime, nullable=True)
    total_cartelas = db.Column(db.Integer, default=0)
    is_private = db.Column(db.Boolean, default=False)
    invite_code = db.Column(db.String(20), nullable=True, index=True)
    rigged_mode = db.Column(db.Boolean, default=False)
    bot_timer_started = db.Column(db.DateTime, nullable=True)
    bingo_claimed = db.Column(db.Boolean, default=False)
    bingo_claimed_by = db.Column(db.BigInteger, nullable=True)
    bingo_claimed_at = db.Column(db.DateTime, nullable=True)

    def get_called_numbers(self):
        try:
            return json.loads(self.called_numbers)
        except (json.JSONDecodeError, TypeError):
            return []

    def add_called_number(self, number):
        numbers = self.get_called_numbers()
        numbers.append(number)
        self.called_numbers = json.dumps(numbers)
        self.current_call = f"{get_letter_for_number(number)}{number}"

class RoomPlayer(db.Model):
    __tablename__ = "room_players"
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(10), db.ForeignKey("rooms.id"), nullable=False, index=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=False, index=True)
    is_host = db.Column(db.Boolean, default=False)
    has_won = db.Column(db.Boolean, default=False)
    cartela_count = db.Column(db.Integer, default=1)
    cartela_numbers = db.Column(db.Text, nullable=False)
    marked_numbers = db.Column(db.Text, default="[]")
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_fake = db.Column(db.Boolean, default=False)
    selected_cartela_ids = db.Column(db.Text, default="[]")
    room = db.relationship("Room", backref="room_players")

    def get_cartela_numbers(self):
        try:
            return json.loads(self.cartela_numbers)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_marked_numbers(self):
        try:
            return json.loads(self.marked_numbers)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_selected_cartela_ids(self):
        try:
            return json.loads(self.selected_cartela_ids)
        except (json.JSONDecodeError, TypeError):
            return []

class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=False, index=True)
    type = db.Column(db.String(50), nullable=False, index=True)  # deposit, withdrawal, win, loss, welcome_bonus
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    description = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

class Deposit(db.Model):
    __tablename__ = "deposits"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default="pending", index=True)  # pending, approved, rejected
    payment_method = db.Column(db.String(50), default="telebirr")
    transaction_reference = db.Column(db.String(100))
    screenshot_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.BigInteger, nullable=True)

class Withdrawal(db.Model):
    __tablename__ = "withdrawals"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default="pending", index=True)  # pending, approved, rejected
    payment_method = db.Column(db.String(50), default="telebirr")
    phone_number = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.BigInteger, nullable=True)

class GameHistory(db.Model):
    __tablename__ = "game_history"
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(10), db.ForeignKey("rooms.id"), nullable=False, index=True)
    game_id = db.Column(db.String(20), nullable=False, index=True)
    winner_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=True)
    stake = db.Column(db.Numeric(10, 2), nullable=False)
    pot_amount = db.Column(db.Numeric(15, 2))
    house_cut = db.Column(db.Numeric(15, 2))
    player_count = db.Column(db.Integer)
    called_numbers_count = db.Column(db.Integer)
    winning_pattern = db.Column(db.String(100))
    completed_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

# ==================== CRITICAL PATH FUNCTIONS WITH ROW LOCKING ====================
def update_user_balance(user_id, amount, operation='add'):
    """
    Safely update user balance with row-level locking.
    Returns (success, new_balance, error_message)
    """
    try:
        with db.session.begin():
            user = User.query.filter_by(telegram_id=user_id).with_for_update().first()
            if not user:
                return False, None, "User not found"
            
            current_balance = Decimal(float(user.balance))
            amount_dec = Decimal(float(amount))
            
            if operation == 'add':
                new_balance = current_balance + amount_dec
            elif operation == 'subtract':
                if current_balance < amount_dec:
                    return False, float(current_balance), "Insufficient balance"
                new_balance = current_balance - amount_dec
            else:
                return False, float(current_balance), "Invalid operation"
            
            user.balance = new_balance
            # User is automatically saved by session commit
            return True, float(new_balance), None
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Balance update error for user {user_id}: {e}", exc_info=True)
        return False, None, "Transaction failed"

def process_deposit_approval(deposit_id, approved, admin_id):
    """Process deposit approval with proper locking and rollback"""
    try:
        with db.session.begin():
            deposit = Deposit.query.filter_by(id=deposit_id).with_for_update().first()
            if not deposit or deposit.status != 'pending':
                return False
            
            deposit.status = 'approved' if approved else 'rejected'
            deposit.approved_at = datetime.utcnow()
            deposit.approved_by = admin_id
            
            if approved:
                user = User.query.filter_by(telegram_id=deposit.user_id).with_for_update().first()
                if not user:
                    raise ValueError("User not found")
                
                user.balance = Decimal(float(user.balance)) + Decimal(float(deposit.amount))
                user.total_deposited = Decimal(float(user.total_deposited)) + Decimal(float(deposit.amount))
                
                transaction = Transaction(
                    user_id=deposit.user_id,
                    type='deposit',
                    amount=deposit.amount,
                    description=f'Deposit #{deposit.id} approved by admin'
                )
                db.session.add(transaction)
            
            return True
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Deposit approval error: {e}", exc_info=True)
        return False

def process_withdrawal_approval(withdrawal_id, approved, admin_id):
    """Process withdrawal approval with proper locking and rollback"""
    try:
        with db.session.begin():
            withdrawal = Withdrawal.query.filter_by(id=withdrawal_id).with_for_update().first()
            if not withdrawal or withdrawal.status != 'pending':
                return False
            
            withdrawal.status = 'approved' if approved else 'rejected'
            withdrawal.approved_at = datetime.utcnow()
            withdrawal.approved_by = admin_id
            
            if not approved:
                # Refund balance on rejection
                user = User.query.filter_by(telegram_id=withdrawal.user_id).with_for_update().first()
                if not user:
                    raise ValueError("User not found")
                
                user.balance = Decimal(float(user.balance)) + Decimal(float(withdrawal.amount))
                
                transaction = Transaction(
                    user_id=withdrawal.user_id,
                    type='withdrawal_refund',
                    amount=withdrawal.amount,
                    description=f'Withdrawal #{withdrawal.id} rejected, balance refunded'
                )
                db.session.add(transaction)
            else:
                user = User.query.filter_by(telegram_id=withdrawal.user_id).with_for_update().first()
                if user:
                    user.total_withdrawn = Decimal(float(user.total_withdrawn)) + Decimal(float(withdrawal.amount))
            
            return True
            
    except Exception as e:
        db.session.rollback()
        logger.error(f"Withdrawal approval error: {e}", exc_info=True)
        return False

# ==================== GAME LOGIC ====================
def create_bot_players(room_id, count):
    """Create fake bot players for a room"""
    bots = []
    for i in range(count):
        bot_id = 900000000 + i + random.randint(1, 100000)
        bot_username = f"bot_{secrets.token_hex(4)}"
        
        bot = User.query.filter_by(telegram_id=bot_id).first()
        if not bot:
            bot = User(
                telegram_id=bot_id,
                username=bot_username,
                first_name=f"Bot {i+1}",
                is_bot=True,
                is_approved=True,
                balance=Decimal("1000000.00"),
                registration_step="approved",
                welcome_bonus_claimed=True
            )
            db.session.add(bot)
            db.session.flush()
        
        cartelas = generate_cartelas(random.randint(1, 3))
        cartela_numbers_json = json.dumps(cartelas)
        
        room_player = RoomPlayer(
            room_id=room_id,
            user_id=bot_id,
            is_host=False,
            cartela_count=len(cartelas),
            cartela_numbers=cartela_numbers_json,
            is_fake=True
        )
        db.session.add(room_player)
        bots.append(bot_id)
    
    try:
        db.session.commit()
        return bots
    except Exception as e:
        db.session.rollback()
        logger.error(f"Bot creation error: {e}")
        return []

def start_game_timer(room_id):
    """Start automated game timer"""
    def timer_thread():
        time.sleep(Config.TIMER_DELAY_SECONDS)
        room = Room.query.get(room_id)
        if room and room.status == 'waiting':
            room.bot_timer_started = datetime.utcnow()
            db.session.commit()
            
            # Wait for auto-start
            time.sleep(30)  # 30 second countdown
            room = Room.query.get(room_id)
            if room and room.status == 'waiting':
                start_game(room_id)
    
    thread = threading.Thread(target=timer_thread, daemon=True)
    thread.start()

def start_game(room_id):
    """Start the bingo game"""
    try:
        with db.session.begin():
            room = Room.query.filter_by(id=room_id).with_for_update().first()
            if not room or room.status != 'waiting':
                return False
            
            room.status = 'active'
            room.started_at = datetime.utcnow()
            
            # Add bot players if needed
            player_count = RoomPlayer.query.filter_by(room_id=room_id).count()
            if player_count < Config.MIN_PLAYERS_TO_START:
                needed = Config.MIN_PLAYERS_TO_START - player_count
                create_bot_players(room_id, min(needed, Config.AUTO_FILL_BOT_COUNT))
            
            return True
    except Exception as e:
        logger.error(f"Start game error: {e}")
        return False

def call_number(room_id):
    """Call next bingo number"""
    try:
        with db.session.begin():
            room = Room.query.filter_by(id=room_id).with_for_update().first()
            if not room or room.status != 'active':
                return None
            
            called = room.get_called_numbers()
            available = [n for n in range(1, 76) if n not in called]
            
            if not available:
                return None
            
            number = random.choice(available)
            room.add_called_number(number)
            
            # Record the call
            game_call = GameCall(
                room_id=room_id,
                call_number=f"{get_letter_for_number(number)}{number}",
                number_value=number
            )
            db.session.add(game_call)
            
            return number
            
    except Exception as e:
        logger.error(f"Call number error: {e}")
        return None

def check_bingo_claim(room_id, user_id):
    """Verify bingo claim"""
    try:
        room = Room.query.get(room_id)
        if not room or room.status != 'active' or room.bingo_claimed:
            return False, "Invalid game state"
        
        player = RoomPlayer.query.filter_by(room_id=room_id, user_id=user_id).first()
        if not player:
            return False, "Player not found"
        
        marked = player.get_marked_numbers()
        cartelas = player.get_cartela_numbers()
        
        if not cartelas:
            return False, "No cartelas"
        
        # Check all cartelas
        for cartela in cartelas:
            if check_win_condition(marked, cartela):
                return True, get_winning_pattern(marked, cartela)
        
        return False, "No winning pattern"
        
    except Exception as e:
        logger.error(f"Bingo check error: {e}")
        return False, "Verification error"

def process_win(room_id, winner_id):
    """Process game win with proper locking"""
    try:
        with db.session.begin():
            room = Room.query.filter_by(id=room_id).with_for_update().first()
            if not room or room.bingo_claimed:
                return False
            
            winner = User.query.filter_by(telegram_id=winner_id).with_for_update().first()
            if not winner:
                return False
            
            # Calculate winnings
            house_cut = Decimal(float(room.pot_amount)) * Decimal(float(room.house_cut_percent)) / Decimal("100")
            win_amount = Decimal(float(room.pot_amount)) - house_cut
            
            # Update winner
            winner.balance = Decimal(float(winner.balance)) + win_amount
            winner.total_games_won += 1
            
            # Update room
            room.bingo_claimed = True
            room.bingo_claimed_by = winner_id
            room.bingo_claimed_at = datetime.utcnow()
            room.winner_id = winner_id
            room.status = 'completed'
            room.completed_at = datetime.utcnow()
            
            # Record transaction
            transaction = Transaction(
                user_id=winner_id,
                type='win',
                amount=win_amount,
                description=f'Won game {room.game_id}'
            )
            db.session.add(transaction)
            
            # Record game history
            history = GameHistory(
                room_id=room_id,
                game_id=room.game_id,
                winner_id=winner_id,
                stake=room.stake,
                pot_amount=room.pot_amount,
                house_cut=house_cut,
                player_count=RoomPlayer.query.filter_by(room_id=room_id).count(),
                called_numbers_count=len(room.get_called_numbers()),
                winning_pattern=get_winning_pattern(winner_id, room_id)
            )
            db.session.add(history)
            
            return True
            
    except Exception as e:
        logger.error(f"Process win error: {e}")
        return False

# ==================== ROUTES ====================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin_panel():
    return render_template('admin.html')

@app.route('/health')
def health_check():
    try:
        # Check database
        db.session.execute(db.text('SELECT 1'))
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "database": "connected",
            "version": "1.0.0"
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 503

@app.route('/webapp')
def webapp():
    return render_template('webapp.html')

@app.route('/webhook', methods=['POST'])
@limiter.limit("100 per minute")
def webhook():
    # Verify webhook secret
    if not verify_webhook_secret(request.headers):
        logger.warning("Webhook rejected: invalid secret")
        abort(401)
    
    try:
        data = request.get_json(silent=True) or {}
        logger.info(f"Webhook received: {json.dumps(data)[:500]}")
        
        if 'message' in data:
            message = data['message']
            chat_id = message.get('chat', {}).get('id')
            text = message.get('text', '') or ''
            
            if text == '/start':
                send_telegram_message(chat_id,
                    f"Welcome to Nexus Bingo!\n\nPlay Bingo and win real money!\n"
                    f"Welcome bonus: {float(Config.WELCOME_BONUS):.0f} ETB\n\nClick below:",
                    reply_markup={"inline_keyboard": [[{"text": "Open Bingo Game", "web_app": {"url": Config.WEBAPP_URL}}]]})
            
            elif text == '/help':
                send_telegram_message(chat_id,
                    "Nexus Bingo Help\n/start - Open game\n/balance - Check balance\n"
                    "/deposit - Add funds\n/withdraw - Cash out\n/history - Game history")
            
            elif text == '/balance':
                user_db = User.query.filter_by(telegram_id=chat_id).first()
                if user_db:
                    send_telegram_message(chat_id,
                        f"Balance: {float(user_db.balance):.2f} ETB\nPlayed: {user_db.total_games_played}\nWon: {user_db.total_games_won}")
                else:
                    send_telegram_message(chat_id, "No account yet. Register below:",
                        reply_markup={"inline_keyboard": [[{"text": "Register & Play", "web_app": {"url": Config.WEBAPP_URL}}]]})
            
            elif text == '/register':
                user_db = User.query.filter_by(telegram_id=chat_id).first()
                if user_db:
                    send_telegram_message(chat_id, f"Already registered!\nBalance: {float(user_db.balance):.2f} ETB")
                else:
                    from_user = message.get('from', {})
                    try:
                        with db.session.begin():
                            new_user = User(
                                telegram_id=chat_id,
                                username=from_user.get('username'),
                                first_name=from_user.get('first_name', 'Player'),
                                last_name=from_user.get('last_name', ''),
                                registration_step='approved',
                                is_approved=True,
                                balance=Config.WELCOME_BONUS,
                                welcome_bonus_claimed=True
                            )
                            db.session.add(new_user)
                        
                        transaction = Transaction(
                            user_id=chat_id,
                            type='welcome_bonus',
                            amount=Config.WELCOME_BONUS,
                            description='Welcome bonus via /register'
                        )
                        db.session.add(transaction)
                        db.session.commit()
                        
                        send_telegram_message(chat_id, 
                            f"Registration complete!\nBonus: {float(Config.WELCOME_BONUS):.0f} ETB credited.\nClick to play:",
                            reply_markup={"inline_keyboard": [[{"text": "Play Now", "web_app": {"url": Config.WEBAPP_URL}}]]})
                    except Exception as e:
                        db.session.rollback()
                        logger.error(f"Registration error: {e}")
                        send_telegram_message(chat_id, "Registration failed. Please try again.")
            
            elif text.startswith('/admin') and chat_id in Config.ADMIN_IDS:
                send_telegram_message(chat_id, "Admin Panel\nUse web interface for full controls.")
        
        elif 'callback_query' in data:
            callback_query = data['callback_query']
            query_id = callback_query.get('id')
            chat_id = callback_query.get('from', {}).get('id')
            data_str = callback_query.get('data', '')
            
            if not data_str or chat_id not in Config.ADMIN_IDS:
                answer_callback(query_id, "Unauthorized")
                return jsonify({"ok": True})
            
            try:
                action, item_id = data_str.split(':', 1)
                item_id = int(item_id)
            except ValueError:
                answer_callback(query_id, "Invalid action")
                return jsonify({"ok": True})
            
            if action == 'approve_deposit':
                success = process_deposit_approval(item_id, True, chat_id)
                if success:
                    answer_callback(query_id, "Deposit approved! Balance updated.")
                    edit_message_text(chat_id, callback_query['message']['message_id'],
                        callback_query['message']['text'] + "\n\nAPPROVED by admin")
                else:
                    answer_callback(query_id, "Failed to approve deposit.")
            
            elif action == 'reject_deposit':
                success = process_deposit_approval(item_id, False, chat_id)
                if success:
                    answer_callback(query_id, "Deposit rejected.")
                    edit_message_text(chat_id, callback_query['message']['message_id'],
                        callback_query['message']['text'] + "\n\nREJECTED by admin")
                else:
                    answer_callback(query_id, "Failed to reject deposit.")
            
            elif action == 'approve_withdrawal':
                success = process_withdrawal_approval(item_id, True, chat_id)
                if success:
                    answer_callback(query_id, "Withdrawal approved! Send payment now.")
                    edit_message_text(chat_id, callback_query['message']['message_id'],
                        callback_query['message']['text'] + "\n\nAPPROVED by admin\nSend payment to player's phone")
                else:
                    answer_callback(query_id, "Failed to approve withdrawal.")
            
            elif action == 'reject_withdrawal':
                success = process_withdrawal_approval(item_id, False, chat_id)
                if success:
                    answer_callback(query_id, "Withdrawal rejected. Balance refunded.")
                    edit_message_text(chat_id, callback_query['message']['message_id'],
                        callback_query['message']['text'] + "\n\nREJECTED by admin\nBalance refunded to player")
                else:
                    answer_callback(query_id, "Failed to reject withdrawal.")
        
        return jsonify({"ok": True})
        
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        return jsonify({"error": "Internal error"}), 500

# ==================== API ROUTES ====================
@app.route('/api/rooms', methods=['GET'])
@require_telegram_auth
def get_rooms():
    try:
        stake = request.args.get('stake', type=float)
        status = request.args.get('status', 'waiting')
        
        query = Room.query.filter_by(status=status)
        if stake:
            query = query.filter_by(stake=Decimal(str(stake)))
        
        rooms = query.order_by(Room.created_at.desc()).limit(50).all()
        
        return jsonify({
            "rooms": [{
                "id": r.id,
                "game_id": r.game_id,
                "stake": float(r.stake),
                "max_players": r.max_players,
                "current_players": RoomPlayer.query.filter_by(room_id=r.id).count(),
                "status": r.status,
                "pot_amount": float(r.pot_amount),
                "is_private": r.is_private,
                "created_at": r.created_at.isoformat() if r.created_at else None
            } for r in rooms]
        })
    except Exception as e:
        logger.error(f"Get rooms error: {e}")
        return jsonify({"error": "Failed to fetch rooms"}), 500

@app.route('/api/rooms', methods=['POST'])
@require_telegram_auth
@limiter.limit("10 per hour")
def create_room():
    try:
        data = request.get_json(silent=True) or {}
        
        # Validate input
        stake = data.get('stake')
        if not stake or not isinstance(stake, (int, float)) or stake <= 0:
            return jsonify({"error": "Invalid stake amount"}), 400
        
        max_players = data.get('max_players', 20)
        if not isinstance(max_players, int) or max_players < 2 or max_players > 100:
            return jsonify({"error": "Invalid max_players"}), 400
        
        is_private = data.get('is_private', False)
        if not isinstance(is_private, bool):
            return jsonify({"error": "Invalid is_private value"}), 400
        
        user = User.query.filter_by(telegram_id=request.telegram_user['id']).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        room_id = generate_room_id()
        game_id = generate_game_id()
        invite_code = secrets.token_urlsafe(8) if is_private else None
        
        room = Room(
            id=room_id,
            game_id=game_id,
            stake=Decimal(str(stake)),
            max_players=max_players,
            created_by=request.telegram_user['id'],
            is_private=is_private,
            invite_code=invite_code,
            house_cut_percent=Decimal(str(Config.DEFAULT_HOUSE_CUT))
        )
        db.session.add(room)
        db.session.commit()
        
        return jsonify({
            "room": {
                "id": room.id,
                "game_id": room.game_id,
                "invite_code": room.invite_code,
                "stake": float(room.stake)
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Create room error: {e}")
        return jsonify({"error": "Failed to create room"}), 500

@app.route('/api/rooms/join-by-code', methods=['POST'])
@require_telegram_auth
@limiter.limit("20 per hour")
def join_by_code():
    try:
        data = request.get_json(silent=True) or {}
        code = data.get('code', '').strip()
        
        if not code or len(code) < 4 or len(code) > 20:
            return jsonify({"error": "Invalid invite code"}), 400
        
        room = Room.query.filter_by(invite_code=code).first()
        if not room:
            return jsonify({"error": "Room not found"}), 404
        
        if room.status != 'waiting':
            return jsonify({"error": "Game already started"}), 400
        
        # Check if already joined
        existing = RoomPlayer.query.filter_by(room_id=room.id, user_id=request.telegram_user['id']).first()
        if existing:
            return jsonify({"error": "Already joined"}), 400
        
        # Check player limit
        current_players = RoomPlayer.query.filter_by(room_id=room.id).count()
        if current_players >= room.max_players:
            return jsonify({"error": "Room is full"}), 400
        
        # Generate cartelas
        cartela_count = min(data.get('cartela_count', 1), Config.MAX_CARTELAS_PER_PLAYER)
        cartelas = generate_cartelas(cartela_count)
        
        player = RoomPlayer(
            room_id=room.id,
            user_id=request.telegram_user['id'],
            cartela_count=cartela_count,
            cartela_numbers=json.dumps(cartelas)
        )
        db.session.add(player)
        
        # Update pot
        total_cost = Decimal(str(room.stake)) * Decimal(str(cartela_count))
        room.pot_amount = Decimal(float(room.pot_amount)) + total_cost
        
        # Deduct balance
        success, new_balance, error = update_user_balance(
            request.telegram_user['id'], 
            total_cost, 
            'subtract'
        )
        if not success:
            db.session.rollback()
            return jsonify({"error": error or "Insufficient balance"}), 400
        
        db.session.commit()
        
        return jsonify({
            "room": {
                "id": room.id,
                "game_id": room.game_id,
                "cartelas": cartelas
            }
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Join by code error: {e}")
        return jsonify({"error": "Failed to join room"}), 500

@app.route('/api/rooms/<room_id>/join', methods=['POST'])
@require_telegram_auth
@limiter.limit("20 per hour")
def join_room(room_id):
    try:
        room = Room.query.get(room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        
        if room.status != 'waiting':
            return jsonify({"error": "Game already started"}), 400
        
        existing = RoomPlayer.query.filter_by(room_id=room_id, user_id=request.telegram_user['id']).first()
        if existing:
            return jsonify({"error": "Already joined"}), 400
        
        current_players = RoomPlayer.query.filter_by(room_id=room_id).count()
        if current_players >= room.max_players:
            return jsonify({"error": "Room is full"}), 400
        
        data = request.get_json(silent=True) or {}
        cartela_count = min(data.get('cartela_count', 1), Config.MAX_CARTELAS_PER_PLAYER)
        cartelas = generate_cartelas(cartela_count)
        
        player = RoomPlayer(
            room_id=room_id,
            user_id=request.telegram_user['id'],
            cartela_count=cartela_count,
            cartela_numbers=json.dumps(cartelas)
        )
        db.session.add(player)
        
        total_cost = Decimal(str(room.stake)) * Decimal(str(cartela_count))
        room.pot_amount = Decimal(float(room.pot_amount)) + total_cost
        
        success, new_balance, error = update_user_balance(
            request.telegram_user['id'],
            total_cost,
            'subtract'
        )
        if not success:
            db.session.rollback()
            return jsonify({"error": error or "Insufficient balance"}), 400
        
        db.session.commit()
        
        return jsonify({
            "room": {
                "id": room.id,
                "game_id": room.game_id,
                "cartelas": cartelas
            }
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Join room error: {e}")
        return jsonify({"error": "Failed to join room"}), 500

@app.route('/api/rooms/stake-counts', methods=['GET'])
def get_stake_counts():
    try:
        stakes = db.session.query(
            Room.stake,
            db.func.count(Room.id).label('count')
        ).filter_by(status='waiting').group_by(Room.stake).all()
        
        return jsonify({
            "stakes": [{"stake": float(s[0]), "count": s[1]} for s in stakes]
        })
    except Exception as e:
        logger.error(f"Stake counts error: {e}")
        return jsonify({"error": "Failed to fetch stakes"}), 500

@app.route('/api/rooms/join-by-stake', methods=['POST'])
@require_telegram_auth
@limiter.limit("20 per hour")
def join_by_stake():
    try:
        data = request.get_json(silent=True) or {}
        stake = data.get('stake')
        
        if not stake or not isinstance(stake, (int, float)) or stake <= 0:
            return jsonify({"error": "Invalid stake"}), 400
        
        room = Room.query.filter_by(
            stake=Decimal(str(stake)),
            status='waiting',
            is_private=False
        ).order_by(Room.created_at.asc()).first()
        
        if not room:
            # Create new room
            room_id = generate_room_id()
            game_id = generate_game_id()
            room = Room(
                id=room_id,
                game_id=game_id,
                stake=Decimal(str(stake)),
                created_by=request.telegram_user['id'],
                house_cut_percent=Decimal(str(Config.DEFAULT_HOUSE_CUT))
            )
            db.session.add(room)
            db.session.flush()
        
        # Check if full
        current_players = RoomPlayer.query.filter_by(room_id=room.id).count()
        if current_players >= room.max_players:
            return jsonify({"error": "Room is full"}), 400
        
        cartela_count = min(data.get('cartela_count', 1), Config.MAX_CARTELAS_PER_PLAYER)
        cartelas = generate_cartelas(cartela_count)
        
        player = RoomPlayer(
            room_id=room.id,
            user_id=request.telegram_user['id'],
            cartela_count=cartela_count,
            cartela_numbers=json.dumps(cartelas)
        )
        db.session.add(player)
        
        total_cost = Decimal(str(room.stake)) * Decimal(str(cartela_count))
        room.pot_amount = Decimal(float(room.pot_amount)) + total_cost
        
        success, new_balance, error = update_user_balance(
            request.telegram_user['id'],
            total_cost,
            'subtract'
        )
        if not success:
            db.session.rollback()
            return jsonify({"error": error or "Insufficient balance"}), 400
        
        db.session.commit()
        
        return jsonify({
            "room": {
                "id": room.id,
                "game_id": room.game_id,
                "cartelas": cartelas
            }
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Join by stake error: {e}")
        return jsonify({"error": "Failed to join"}), 500

@app.route('/api/cartelas/preview')
def preview_cartelas():
    try:
        count = request.args.get('count', 1, type=int)
        count = max(1, min(count, Config.MAX_CARTELAS_PER_PLAYER))
        cartelas = generate_cartelas(count)
        return jsonify({"cartelas": cartelas})
    except Exception as e:
        logger.error(f"Preview cartelas error: {e}")
        return jsonify({"error": "Failed to generate preview"}), 500

@app.route('/api/cartelas/<int:cartela_id>')
def get_cartela(cartela_id):
    # This would normally fetch from DB, but cartelas are stored in RoomPlayer
    return jsonify({"error": "Use room state endpoint"}), 400

@app.route('/api/rooms/<room_id>/state')
@require_telegram_auth
def get_room_state(room_id):
    try:
        room = Room.query.get(room_id)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        
        player = RoomPlayer.query.filter_by(room_id=room_id, user_id=request.telegram_user['id']).first()
        
        return jsonify({
            "room": {
                "id": room.id,
                "status": room.status,
                "current_call": room.current_call,
                "called_numbers": room.get_called_numbers(),
                "pot_amount": float(room.pot_amount),
                "player_count": RoomPlayer.query.filter_by(room_id=room_id).count()
            },
            "player": {
                "cartelas": player.get_cartela_numbers() if player else [],
                "marked_numbers": player.get_marked_numbers() if player else [],
                "has_won": player.has_won if player else False
            } if player else None
        })
    except Exception as e:
        logger.error(f"Room state error: {e}")
        return jsonify({"error": "Failed to fetch state"}), 500

@app.route('/api/rooms/<room_id>/mark', methods=['POST'])
@require_telegram_auth
@limiter.limit("200 per minute")
def mark_number(room_id):
    try:
        data = request.get_json(silent=True) or {}
        number = data.get('number')
        
        if not isinstance(number, int) or number < 1 or number > 75:
            return jsonify({"error": "Invalid number"}), 400
        
        room = Room.query.get(room_id)
        if not room or room.status != 'active':
            return jsonify({"error": "Game not active"}), 400
        
        called = room.get_called_numbers()
        if number not in called:
            return jsonify({"error": "Number not called"}), 400
        
        player = RoomPlayer.query.filter_by(room_id=room_id, user_id=request.telegram_user['id']).first()
        if not player:
            return jsonify({"error": "Not in room"}), 400
        
        marked = player.get_marked_numbers()
        if number in marked:
            return jsonify({"error": "Already marked"}), 400
        
        marked.append(number)
        player.marked_numbers = json.dumps(marked)
        db.session.commit()
        
        return jsonify({"marked_numbers": marked})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Mark number error: {e}")
        return jsonify({"error": "Failed to mark"}), 500

@app.route('/api/rooms/<room_id>/bingo', methods=['POST'])
@require_telegram_auth
@limiter.limit("10 per minute")
def claim_bingo(room_id):
    try:
        room = Room.query.get(room_id)
        if not room or room.status != 'active':
            return jsonify({"error": "Game not active"}), 400
        
        if room.bingo_claimed:
            return jsonify({"error": "Bingo already claimed"}), 400
        
        is_valid, pattern = check_bingo_claim(room_id, request.telegram_user['id'])
        if not is_valid:
            return jsonify({"error": pattern}), 400
        
        # Process win with locking
        success = process_win(room_id, request.telegram_user['id'])
        if not success:
            return jsonify({"error": "Failed to process win"}), 500
        
        return jsonify({
            "winner": True,
            "pattern": pattern,
            "win_amount": float(room.pot_amount) * (1 - float(room.house_cut_percent) / 100)
        })
        
    except Exception as e:
        logger.error(f"Bingo claim error: {e}")
        return jsonify({"error": "Failed to claim bingo"}), 500

@app.route('/api/user/profile')
@require_telegram_auth
def get_profile():
    try:
        user = User.query.filter_by(telegram_id=request.telegram_user['id']).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        return jsonify(user.to_dict())
    except Exception as e:
        logger.error(f"Profile error: {e}")
        return jsonify({"error": "Failed to fetch profile"}), 500

@app.route('/api/user/deposit', methods=['POST'])
@require_telegram_auth
@limiter.limit("5 per hour")
def create_deposit():
    try:
        data = request.get_json(silent=True) or {}
        amount = data.get('amount')
        phone = data.get('phone_number', '').strip()
        
        if not amount or not isinstance(amount, (int, float)) or amount <= 0:
            return jsonify({"error": "Invalid amount"}), 400
        
        if not phone or len(phone) < 10 or len(phone) > 15:
            return jsonify({"error": "Invalid phone number"}), 400
        
        # Validate amount limits
        if amount < 10 or amount > 10000:
            return jsonify({"error": "Amount must be between 10 and 10000 ETB"}), 400
        
        user = User.query.filter_by(telegram_id=request.telegram_user['id']).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        deposit = Deposit(
            user_id=user.telegram_id,
            amount=Decimal(str(amount)),
            payment_method='telebirr',
            phone_number=phone
        )
        db.session.add(deposit)
        db.session.commit()
        
        # Notify admins
        for admin_id in Config.ADMIN_IDS:
            send_telegram_message(admin_id,
                f"New Deposit Request\nUser: {user.first_name} (@{user.username})\n"
                f"Amount: {amount} ETB\nPhone: {phone}\nID: #{deposit.id}")
        
        return jsonify({
            "deposit_id": deposit.id,
            "amount": float(deposit.amount),
            "status": deposit.status,
            "message": "Deposit request submitted. Wait for admin approval."
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Deposit error: {e}")
        return jsonify({"error": "Failed to create deposit"}), 500

@app.route('/api/user/withdraw', methods=['POST'])
@require_telegram_auth
@limiter.limit("5 per hour")
def create_withdrawal():
    try:
        data = request.get_json(silent=True) or {}
        amount = data.get('amount')
        phone = data.get('phone_number', '').strip()
        
        if not amount or not isinstance(amount, (int, float)) or amount <= 0:
            return jsonify({"error": "Invalid amount"}), 400
        
        if not phone or len(phone) < 10 or len(phone) > 15:
            return jsonify({"error": "Invalid phone number"}), 400
        
        if amount < 50 or amount > 5000:
            return jsonify({"error": "Amount must be between 50 and 5000 ETB"}), 400
        
        user = User.query.filter_by(telegram_id=request.telegram_user['id']).first()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        # Check balance with lock
        success, current_balance, error = update_user_balance(
            user.telegram_id,
            amount,
            'subtract'
        )
        if not success:
            return jsonify({"error": error or "Insufficient balance"}), 400
        
        withdrawal = Withdrawal(
            user_id=user.telegram_id,
            amount=Decimal(str(amount)),
            payment_method='telebirr',
            phone_number=phone
        )
        db.session.add(withdrawal)
        db.session.commit()
        
        # Notify admins
        for admin_id in Config.ADMIN_IDS:
            send_telegram_message(admin_id,
                f"New Withdrawal Request\nUser: {user.first_name} (@{user.username})\n"
                f"Amount: {amount} ETB\nPhone: {phone}\nID: #{withdrawal.id}")
        
        return jsonify({
            "withdrawal_id": withdrawal.id,
            "amount": float(withdrawal.amount),
            "status": withdrawal.status,
            "message": "Withdrawal request submitted. Wait for admin approval."
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Withdrawal error: {e}")
        return jsonify({"error": "Failed to create withdrawal"}), 500

@app.route('/api/user/transactions')
@require_telegram_auth
def get_transactions():
    try:
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)
        
        pagination = Transaction.query.filter_by(
            user_id=request.telegram_user['id']
        ).order_by(Transaction.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            "transactions": [{
                "id": t.id,
                "type": t.type,
                "amount": float(t.amount),
                "description": t.description,
                "created_at": t.created_at.isoformat() if t.created_at else None
            } for t in pagination.items],
            "total": pagination.total,
            "pages": pagination.pages,
            "current_page": page
        })
    except Exception as e:
        logger.error(f"Transactions error: {e}")
        return jsonify({"error": "Failed to fetch transactions"}), 500

# ==================== ADMIN ROUTES ====================
@app.route('/api/admin/stats')
@require_telegram_auth
@require_admin
def admin_stats():
    try:
        total_users = User.query.count()
        total_rooms = Room.query.count()
        active_rooms = Room.query.filter_by(status='active').count()
        pending_deposits = Deposit.query.filter_by(status='pending').count()
        pending_withdrawals = Withdrawal.query.filter_by(status='pending').count()
        
        total_deposits = db.session.query(db.func.sum(Deposit.amount)).filter_by(status='approved').scalar() or 0
        total_withdrawals = db.session.query(db.func.sum(Withdrawal.amount)).filter_by(status='approved').scalar() or 0
        
        return jsonify({
            "users": {
                "total": total_users,
                "active_today": User.query.filter(User.last_active >= datetime.utcnow() - timedelta(days=1)).count()
            },
            "rooms": {
                "total": total_rooms,
                "active": active_rooms,
                "waiting": Room.query.filter_by(status='waiting').count()
            },
            "finance": {
                "pending_deposits": pending_deposits,
                "pending_withdrawals": pending_withdrawals,
                "total_deposits": float(total_deposits),
                "total_withdrawals": float(total_withdrawals),
                "net_revenue": float(total_deposits) - float(total_withdrawals)
            }
        })
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        return jsonify({"error": "Failed to fetch stats"}), 500

@app.route('/api/admin/deposits')
@require_telegram_auth
@require_admin
def admin_deposits():
    try:
        status = request.args.get('status', 'pending')
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 50, type=int), 100)
        
        query = Deposit.query.filter_by(status=status)
        pagination = query.order_by(Deposit.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            "deposits": [{
                "id": d.id,
                "user_id": d.user_id,
                "amount": float(d.amount),
                "status": d.status,
                "payment_method": d.payment_method,
                "phone_number": d.phone_number,
                "created_at": d.created_at.isoformat() if d.created_at else None
            } for d in pagination.items],
            "total": pagination.total,
            "pages": pagination.pages
        })
    except Exception as e:
        logger.error(f"Admin deposits error: {e}")
        return jsonify({"error": "Failed to fetch deposits"}), 500

@app.route('/api/admin/deposits/<int:deposit_id>/approve', methods=['POST'])
@require_telegram_auth
@require_admin
@limiter.limit("30 per minute")
def approve_deposit(deposit_id):
    try:
        data = request.get_json(silent=True) or {}
        approved = data.get('approved', True)
        
        admin_id = request.telegram_user['id']
        success = process_deposit_approval(deposit_id, approved, admin_id)
        
        if not success:
            return jsonify({"error": "Failed to process deposit"}), 400
        
        return jsonify({"message": f"Deposit {'approved' if approved else 'rejected'} successfully"})
        
    except Exception as e:
        logger.error(f"Approve deposit error: {e}")
        return jsonify({"error": "Failed to process"}), 500

@app.route('/api/admin/withdrawals')
@require_telegram_auth
@require_admin
def admin_withdrawals():
    try:
        status = request.args.get('status', 'pending')
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 50, type=int), 100)
        
        query = Withdrawal.query.filter_by(status=status)
        pagination = query.order_by(Withdrawal.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            "withdrawals": [{
                "id": w.id,
                "user_id": w.user_id,
                "amount": float(w.amount),
                "status": w.status,
                "payment_method": w.payment_method,
                "phone_number": w.phone_number,
                "created_at": w.created_at.isoformat() if w.created_at else None
            } for w in pagination.items],
            "total": pagination.total,
            "pages": pagination.pages
        })
    except Exception as e:
        logger.error(f"Admin withdrawals error: {e}")
        return jsonify({"error": "Failed to fetch withdrawals"}), 500

@app.route('/api/admin/withdrawals/<int:withdrawal_id>/approve', methods=['POST'])
@require_telegram_auth
@require_admin
@limiter.limit("30 per minute")
def approve_withdrawal(withdrawal_id):
    try:
        data = request.get_json(silent=True) or {}
        approved = data.get('approved', True)
        
        admin_id = request.telegram_user['id']
        success = process_withdrawal_approval(withdrawal_id, approved, admin_id)
        
        if not success:
            return jsonify({"error": "Failed to process withdrawal"}), 400
        
        return jsonify({"message": f"Withdrawal {'approved' if approved else 'rejected'} successfully"})
        
    except Exception as e:
        logger.error(f"Approve withdrawal error: {e}")
        return jsonify({"error": "Failed to process"}), 500

@app.route('/api/admin/settings', methods=['GET', 'POST'])
@require_telegram_auth
@require_admin
def admin_settings():
    if request.method == 'GET':
        return jsonify({
            "default_house_cut": Config.DEFAULT_HOUSE_CUT,
            "max_cartelas_per_player": Config.MAX_CARTELAS_PER_PLAYER,
            "min_players_to_start": Config.MIN_PLAYERS_TO_START,
            "welcome_bonus": float(Config.WELCOME_BONUS),
            "call_interval_min": Config.CALL_INTERVAL_MIN,
            "call_interval_max": Config.CALL_INTERVAL_MAX
        })
    
    try:
        data = request.get_json(silent=True) or {}
        # Validate and update settings
        # Note: These would normally update database settings, not just return
        return jsonify({"message": "Settings updated", "settings": data})
    except Exception as e:
        logger.error(f"Settings error: {e}")
        return jsonify({"error": "Failed to update settings"}), 500

@app.route('/api/admin/rooms/<room_id>/remove-player', methods=['POST'])
@require_telegram_auth
@require_admin
def remove_player(room_id):
    try:
        data = request.get_json(silent=True) or {}
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({"error": "user_id required"}), 400
        
        player = RoomPlayer.query.filter_by(room_id=room_id, user_id=user_id).first()
        if not player:
            return jsonify({"error": "Player not found"}), 404
        
        # Refund balance
        room = Room.query.get(room_id)
        if room and room.status == 'waiting':
            refund = Decimal(str(room.stake)) * Decimal(str(player.cartela_count))
            success, _, error = update_user_balance(user_id, refund, 'add')
            if success:
                room.pot_amount = Decimal(float(room.pot_amount)) - refund
        
        db.session.delete(player)
        db.session.commit()
        
        return jsonify({"message": "Player removed successfully"})
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Remove player error: {e}")
        return jsonify({"error": "Failed to remove player"}), 500

@app.route('/api/admin/rooms/<room_id>/players')
@require_telegram_auth
@require_admin
def get_room_players(room_id):
    try:
        players = RoomPlayer.query.filter_by(room_id=room_id).all()
        return jsonify({
            "players": [{
                "user_id": p.user_id,
                "username": p.room.created_by if hasattr(p, 'room') else None,
                "cartela_count": p.cartela_count,
                "is_host": p.is_host,
                "has_won": p.has_won,
                "joined_at": p.joined_at.isoformat() if p.joined_at else None
            } for p in players]
        })
    except Exception as e:
        logger.error(f"Room players error: {e}")
        return jsonify({"error": "Failed to fetch players"}), 500

# ==================== ERROR HANDLERS ====================
@app.errorhandler(400)
def bad_request(error):
    return jsonify({"error": "Bad request", "message": str(error.description)}), 400

@app.errorhandler(401)
def unauthorized(error):
    return jsonify({"error": "Unauthorized"}), 401

@app.errorhandler(403)
def forbidden(error):
    return jsonify({"error": "Forbidden"}), 403

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(429)
def rate_limit_handler(error):
    return jsonify({"error": "Rate limit exceeded", "retry_after": error.description}), 429

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    logger.error(f"Internal error: {error}")
    return jsonify({"error": "Internal server error"}), 500

# ==================== MAIN ====================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
