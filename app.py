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
from flask import Flask, jsonify, request, render_template, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from functools import wraps
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
    BOT_USERNAME = os.environ.get("BOT_USERNAME", "@BingoBot")
    _admin_raw = os.environ.get("ADMIN_ID") or os.environ.get("ADMIN_IDS", "")
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
    except:
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
app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')
app.config["SQLALCHEMY_DATABASE_URI"] = Config.DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = Config.SECRET_KEY

if Config.DATABASE_URL.startswith("sqlite"):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {"check_same_thread": False},
        "pool_pre_ping": True,
        "pool_recycle": 300
    }

CORS(app, origins=[Config.WEBAPP_URL, "https://*.telegram.org", "https://telegram.org"])
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["200 per day", "50 per hour"])
db = SQLAlchemy(app)

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
    stake = db.Column(db.Numeric(10, 2), nullable=False)
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

    def get_called_numbers(self):
        try:
            return json.loads(self.called_numbers)
        except:
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
    room = db.relationship("Room", backref="room_players")

    def get_cartelas(self):
        try:
            return json.loads(self.cartela_numbers)
        except:
            return [[]]

    def get_marked(self, cartela_index=0):
        try:
            all_marked = json.loads(self.marked_numbers)
            if isinstance(all_marked, list) and cartela_index < len(all_marked):
                return all_marked[cartela_index]
            return []
        except:
            return []

    def set_cartelas(self, cartelas):
        self.cartela_numbers = json.dumps(cartelas)
        self.marked_numbers = json.dumps([[] for _ in cartelas])

    def mark_number(self, cartela_index, number_index):
        marked = self.get_marked(cartela_index)
        if number_index not in marked:
            marked.append(number_index)
            all_marked = json.loads(self.marked_numbers)
            all_marked[cartela_index] = marked
            self.marked_numbers = json.dumps(all_marked)

    def check_bingo_on_cartela(self, cartela_index):
        marked = set(self.get_marked(cartela_index))
        if len(marked) < 5:
            return False
        for row in range(5):
            if all(row * 5 + col in marked for col in range(5)):
                return True
        for col in range(5):
            if all(row * 5 + col in marked for row in range(5)):
                return True
        if all(i * 6 in marked for i in range(5)):
            return True
        if all(i * 4 + 4 in marked for i in range(5)):
            return True
        return False

class Deposit(db.Model):
    __tablename__ = "deposits"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default="pending")
    screenshot_file_id = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.BigInteger, nullable=True)
    user = db.relationship("User", foreign_keys=[user_id])

class Withdrawal(db.Model):
    __tablename__ = "withdrawals"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default="pending")
    phone_number = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.BigInteger, nullable=True)
    user = db.relationship("User", foreign_keys=[user_id])

class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=False, index=True)
    type = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    reference_id = db.Column(db.String(50))
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class GameSettings(db.Model):
    __tablename__ = "game_settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.BigInteger)

    @classmethod
    def get_house_cut(cls):
        setting = cls.query.filter_by(key="house_cut_percent").first()
        return float(setting.value) if setting else Config.DEFAULT_HOUSE_CUT

    @classmethod
    def set_house_cut(cls, percent, admin_id):
        setting = cls.query.filter_by(key="house_cut_percent").first()
        if not setting:
            setting = cls(key="house_cut_percent")
        setting.value = str(percent)
        setting.updated_by = admin_id
        db.session.add(setting)
        db.session.commit()
        return setting

# ==================== UTILITIES ====================
def generate_cartela():
    ranges = [range(1, 16), range(16, 31), range(31, 46), range(46, 61), range(61, 76)]
    cartela = []
    for r in ranges:
        cols = random.sample(list(r), 5)
        cartela.extend(cols)
    cartela[12] = 0
    return cartela

def generate_cartelas(count):
    return [generate_cartela() for _ in range(count)]

def generate_room_id():
    while True:
        rid = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Room.query.get(rid):
            return rid

def generate_game_id():
    while True:
        gid = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
        if not Room.query.filter_by(game_id=gid).first():
            return gid

def get_letter_for_number(num):
    if 1 <= num <= 15: return "B"
    elif 16 <= num <= 30: return "I"
    elif 31 <= num <= 45: return "N"
    elif 46 <= num <= 60: return "G"
    elif 61 <= num <= 75: return "O"
    return "B"

def send_telegram_message(chat_id, text, parse_mode="HTML", reply_markup=None):
    if not Config.BOT_TOKEN:
        return None
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        response = requests.post(url, json=payload, timeout=10)
        result = response.json()
        if not result.get("ok"):
            logger.error(f"Telegram API error: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return None

def validate_telegram_init_data(init_data):
    try:
        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed_data.pop("hash", None)
        if not received_hash:
            raise ValueError("No hash found")
        data_check_pairs = [f"{k}={v}" for k, v in sorted(parsed_data.items())]
        data_check_string = "\\n".join(data_check_pairs)
        secret_key = hmac.new(key=b"WebAppData", msg=Config.BOT_TOKEN.encode(), digestmod=hashlib.sha256).digest()
        calculated_hash = hmac.new(key=secret_key, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated_hash, received_hash):
            raise ValueError("Invalid hash")
        auth_date = int(parsed_data.get("auth_date", 0))
        current_time = int(time.time())
        if auth_date == 0 or current_time - auth_date > 86400 or auth_date > current_time + 60:
            raise ValueError("Auth expired or invalid")
        user_data = json.loads(parsed_data.get("user", "{}"))
        if not user_data:
            raise ValueError("No user data")
        return user_data
    except Exception as e:
        raise ValueError(f"Validation failed: {str(e)}")

def get_user_with_lock(telegram_id):
    return db.session.query(User).filter_by(telegram_id=telegram_id).with_for_update().first()

# ==================== DECORATORS ====================
def require_telegram_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        test_mode = request.headers.get("X-Test-Mode") or request.args.get("test")
        if test_mode and Config.TEST_MODE_ENABLED:
            test_secret = request.headers.get("X-Test-Secret", "")
            if test_secret != Config.TEST_MODE_SECRET:
                return jsonify({"error": "Invalid test secret"}), 401
            test_user = User.query.filter_by(telegram_id=999999999).first()
            if not test_user:
                test_user = User(telegram_id=999999999, username="testuser", first_name="Test", last_name="Player",
                    is_approved=True, balance=Decimal("100000.00"), registration_step="approved", welcome_bonus_claimed=True)
                db.session.add(test_user)
                db.session.commit()
            request.telegram_user = {"id": 999999999, "first_name": "Test", "last_name": "Player", "username": "testuser"}
            request.current_user = test_user
            request.is_test_mode = True
            return f(*args, **kwargs)
        
        auth_header = request.headers.get("X-Telegram-Init-Data")
        if not auth_header:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.lower().startswith("tma "):
                auth_header = auth_header[4:]
            else:
                auth_header = None
        if not auth_header:
            return jsonify({"error": "Authentication required"}), 401
        
        try:
            user_data = validate_telegram_init_data(auth_header)
            telegram_id = user_data.get("id")
            if not telegram_id:
                return jsonify({"error": "Invalid user data"}), 401
            user = User.query.filter_by(telegram_id=telegram_id).first()
            is_new_user = False
            if not user:
                user = User(telegram_id=telegram_id, username=user_data.get("username"),
                    first_name=user_data.get("first_name", "Player"), last_name=user_data.get("last_name", ""),
                    registration_step="telegram_auth", is_approved=True, balance=Config.WELCOME_BONUS, welcome_bonus_claimed=True)
                db.session.add(user)
                db.session.commit()
                is_new_user = True
                transaction = Transaction(user_id=telegram_id, type="welcome_bonus", amount=Config.WELCOME_BONUS, description="Welcome bonus")
                db.session.add(transaction)
                db.session.commit()
                if Config.ADMIN_ID:
                    send_telegram_message(Config.ADMIN_ID, f"🆕 New user: {user.first_name} (+{Config.WELCOME_BONUS} ETB)")
            if user.is_banned:
                return jsonify({"error": "Account banned"}), 403
            user.last_active = datetime.utcnow()
            db.session.commit()
            request.telegram_user = user_data
            request.current_user = user
            request.is_test_mode = False
            request.is_new_user = is_new_user
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Auth error: {e}")
            return jsonify({"error": "Authentication failed"}), 401
    return decorated_function

def require_admin_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        test_mode = request.headers.get("X-Test-Mode") or request.args.get("test")
        if test_mode and Config.TEST_MODE_ENABLED:
            test_secret = request.headers.get("X-Test-Secret", "")
            if test_secret != Config.TEST_MODE_SECRET:
                return jsonify({"error": "Invalid test secret"}), 401
            request.telegram_user = {"id": Config.ADMIN_ID, "first_name": "Test", "last_name": "Admin"}
            request.is_admin = True
            return f(*args, **kwargs)
        
        auth_header = request.headers.get("X-Telegram-Init-Data")
        if not auth_header:
            return jsonify({"error": "No authentication data"}), 401
        try:
            user_data = validate_telegram_init_data(auth_header)
            telegram_id = user_data.get("id")
            is_admin = telegram_id in Config.ADMIN_IDS
            if not is_admin:
                admin_record = Admin.query.filter_by(telegram_id=telegram_id).first()
                is_admin = admin_record is not None
            if not is_admin:
                return jsonify({"error": "Unauthorized - Admin only"}), 403
            request.telegram_user = user_data
            request.is_admin = True
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Admin auth error: {e}")
            return jsonify({"error": "Authentication failed"}), 401
    return decorated_function

# ==================== BOT MANAGER ====================
class BotPlayerManager:
    BOT_NAMES = ["Abebe", "Kebede", "Desta", "Tesfaye", "Alemu", "Bekele", "Mekonnen", "Solomon",
        "Daniel", "Michael", "Yohannes", "Girma", "Hailu", "Tadesse", "Fatuma", "Amina", "Hawa",
        "Mulu", "Tigist", "Hiwot"]

    @classmethod
    def get_or_create_bot(cls, bot_index):
        bot_id = -(1000000000 + bot_index)
        bot = User.query.filter_by(telegram_id=bot_id).first()
        if bot:
            return bot
        name = random.choice(cls.BOT_NAMES)
        username = f"{name.lower()}{random.randint(1000, 9999)}_bot"
        bot = User(telegram_id=bot_id, username=username, first_name=f"🤖 {name}", last_name="Bot",
            is_approved=True, is_bot=True, balance=Decimal("1000000.00"), registration_step="approved", welcome_bonus_claimed=True)
        db.session.add(bot)
        db.session.commit()
        return bot

    @classmethod
    def fill_room_with_bots(cls, room_id, stake, num_bots=None):
        if num_bots is None:
            num_bots = Config.AUTO_FILL_BOT_COUNT
        room = Room.query.get(room_id)
        if not room:
            return 0
        current_players = RoomPlayer.query.filter_by(room_id=room_id).count()
        max_players = room.max_players
        bots_to_add = min(num_bots, max_players - current_players)
        for i in range(bots_to_add):
            bot = cls.get_or_create_bot(i)
            cartela_count = random.randint(1, min(3, Config.MAX_CARTELAS_PER_PLAYER))
            total_cost = stake * cartela_count
            if float(bot.balance) < float(total_cost):
                bot.balance = Decimal("1000000.00")
            cartelas = generate_cartelas(cartela_count)
            player = RoomPlayer(room_id=room_id, user_id=bot.telegram_id, is_host=False, is_fake=True, cartela_count=cartela_count)
            player.set_cartelas(cartelas)
            bot.balance = Decimal(float(bot.balance)) - Decimal(float(total_cost))
            room.pot_amount = Decimal(float(room.pot_amount)) + Decimal(float(total_cost))
            room.total_cartelas = room.total_cartelas + cartela_count
            db.session.add(player)
        room.is_automated = True
        db.session.commit()
        return bots_to_add

# ==================== GAME MANAGER ====================
class GameManager:
    _instance = None
    _lock = threading.Lock()
    _room_locks = {}
    _room_states = {}
    _global_lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance.active_games = {}
                    cls._instance.call_threads = {}
                    cls._instance.timer_threads = {}
        return cls._instance

    def _get_room_lock(self, room_id):
        with self._global_lock:
            if room_id not in self._room_locks:
                self._room_locks[room_id] = threading.RLock()
            return self._room_locks[room_id]

    def _cleanup_room(self, room_id):
        with self._global_lock:
            for d in [self.call_threads, self.timer_threads, self.active_games, self._room_states]:
                d.pop(room_id, None)
            self._room_locks.pop(room_id, None)

    def get_room_state(self, room_id):
        with self._get_room_lock(room_id):
            if room_id in self._room_states:
                cached = self._room_states[room_id]
                if time.time() - cached["timestamp"] < 1:
                    return cached
            room = Room.query.get(room_id)
            if not room:
                return None
            state = {
                "current_call": room.current_call,
                "called_numbers": room.get_called_numbers(),
                "status": room.status,
                "timestamp": time.time()
            }
            self._room_states[room_id] = state
            return state

    def start_timer(self, room_id, delay_seconds=120):
        if room_id in self.timer_threads and self.timer_threads[room_id].is_alive():
            return
        def timer_callback():
            time.sleep(delay_seconds)
            with app.app_context():
                try:
                    room = Room.query.get(room_id)
                    if not room or room.status != "waiting":
                        return
                    BotPlayerManager.fill_room_with_bots(room_id, float(room.stake))
                    room = Room.query.get(room_id)
                    if room and room.status == "waiting":
                        room.status = "calling"
                        room.started_at = datetime.utcnow()
                        db.session.commit()
                        self.start_game(room_id)
                except Exception as e:
                    logger.error(f"Timer callback error: {e}")
                    db.session.rollback()
        thread = threading.Thread(target=timer_callback, daemon=True)
        self.timer_threads[room_id] = thread
        thread.start()

    def start_game(self, room_id):
        if room_id in self.call_threads and self.call_threads[room_id].is_alive():
            return
        def call_numbers():
            with app.app_context():
                self._run_game_loop(room_id)
        thread = threading.Thread(target=call_numbers, daemon=True)
        self.call_threads[room_id] = thread
        thread.start()

    def _run_game_loop(self, room_id):
        room = Room.query.get(room_id)
        if not room:
            return
        available_numbers = list(range(1, 76))
        random.shuffle(available_numbers)
        called = room.get_called_numbers()
        available_numbers = [n for n in available_numbers if n not in called]
        
        while available_numbers:
            time.sleep(random.uniform(5, 8))
            db.session.remove()
            with app.app_context():
                room = Room.query.get(room_id)
                if not room or room.status != "calling":
                    break
                with self._get_room_lock(room_id):
                    if not available_numbers:
                        break
                    number = available_numbers.pop(random.randint(0, len(available_numbers) - 1))
                    letter = get_letter_for_number(number)
                    call_str = f"{letter}{number}"
                    room.add_called_number(number)
                    db.session.commit()
                    self._room_states[room_id] = {
                        "current_call": call_str,
                        "called_numbers": room.get_called_numbers(),
                        "status": room.status,
                        "timestamp": time.time()
                    }
                    game_call = GameCall(room_id=room_id, call_number=call_str, number_value=number)
                    db.session.add(game_call)
                    db.session.commit()
                    self._auto_mark_for_bots(room_id, number)
                    winner = self._check_for_winner(room_id)
                    if winner:
                        self.end_game(room_id, winner)
                        return
            if len(available_numbers) >= 75:
                break
        with app.app_context():
            winner = self._pick_random_winner(room_id)
            self.end_game(room_id, winner)

    def _auto_mark_for_bots(self, room_id, number):
        try:
            players = RoomPlayer.query.filter_by(room_id=room_id, is_fake=True).all()
            for player in players:
                cartelas = player.get_cartelas()
                for cartela_idx, cartela in enumerate(cartelas):
                    if number in cartela:
                        number_idx = cartela.index(number)
                        player.mark_number(cartela_idx, number_idx)
            db.session.commit()
        except Exception as e:
            logger.error(f"Auto-mark error: {e}")
            db.session.rollback()

    def _check_for_winner(self, room_id):
        try:
            players = RoomPlayer.query.filter_by(room_id=room_id).all()
            for player in players:
                for cartela_idx in range(player.cartela_count):
                    if player.check_bingo_on_cartela(cartela_idx):
                        return player.user_id
            return None
        except Exception as e:
            logger.error(f"Winner check error: {e}")
            return None

    def _pick_random_winner(self, room_id):
        try:
            players = RoomPlayer.query.filter_by(room_id=room_id).all()
            if players:
                weighted_players = []
                for p in players:
                    weighted_players.extend([p] * p.cartela_count)
                winner = random.choice(weighted_players)
                return winner.user_id
            return None
        except Exception as e:
            logger.error(f"Random winner error: {e}")
            return None

    def end_game(self, room_id, winner_id):
        with self._get_room_lock(room_id):
            try:
                room = Room.query.get(room_id)
                if not room or room.status == "completed":
                    self._cleanup_room(room_id)
                    return
                room.status = "completed"
                room.completed_at = datetime.utcnow()
                room.winner_id = winner_id
                if winner_id:
                    winner = User.query.filter_by(telegram_id=winner_id).first()
                    if winner:
                        house_cut_percent = float(room.house_cut_percent if room.house_cut_percent else GameSettings.get_house_cut())
                        total_pot = float(room.pot_amount)
                        house_fee = total_pot * (house_cut_percent / 100)
                        win_amount = total_pot - house_fee
                        winner.balance = Decimal(float(winner.balance)) + Decimal(win_amount)
                        winner.total_games_won = winner.total_games_won + 1
                        winner_player = RoomPlayer.query.filter_by(room_id=room_id, user_id=winner_id).first()
                        if winner_player:
                            winner_player.has_won = True
                        transaction = Transaction(user_id=winner_id, type="win", amount=Decimal(str(win_amount)),
                            reference_id=room.id, description=f"Won game {room.game_id}")
                        db.session.add(transaction)
                        if not winner.is_bot:
                            send_telegram_message(winner_id, f"🎉 You won {win_amount:.0f} ETB! New balance: {float(winner.balance):.0f} ETB")
                        if Config.ADMIN_ID:
                            send_telegram_message(Config.ADMIN_ID, f"🏆 Winner: {winner.first_name}, Prize: {win_amount:.0f} ETB, Room: {room.id}")
                db.session.commit()
            except Exception as e:
                logger.error(f"End game error: {e}")
                db.session.rollback()
            finally:
                self._cleanup_room(room_id)

game_manager = GameManager()

# ==================== FRONTEND ROUTES 
@app.route('/')
def index():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'index.html')
@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/health')
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    return jsonify({"status": "healthy", "database": db_status, "timestamp": datetime.utcnow().isoformat()}), 200

# ==================== API ROUTES ====================
@app.route('/webapp')
@require_telegram_auth
def webapp():
    user = request.current_user
    return jsonify({"user": user.to_dict(), "config": {
        "welcome_bonus": float(Config.WELCOME_BONUS), "max_cartelas": Config.MAX_CARTELAS_PER_PLAYER,
        "telebirr": Config.TELEBIRR_NUMBER, "cbe": Config.CBE_ACCOUNT, "webapp_url": Config.WEBAPP_URL,
        "min_deposit": 10, "min_withdrawal": 50}})

@app.route('/webhook', methods=['POST'])
@limiter.limit("100 per minute")
def webhook():
    try:
        data = request.get_json(silent=True) or {}
        logger.info(f"Webhook: {json.dumps(data)[:500]}")
        if 'message' in data:
            message = data['message']
            chat_id = message.get('chat', {}).get('id')
            text = message.get('text', '') or ''
            if text == '/start':
                send_telegram_message(chat_id,
                    f"🎮 <b>Welcome to Nexus Bingo!</b>\\n\\nPlay Bingo and win real money! 💰\\n"
                    f"🎁 Welcome bonus: <b>{float(Config.WELCOME_BONUS):.0f} ETB</b>\\n\\n📱 Click below:",
                    reply_markup={"inline_keyboard": [[{"text": "🎮 Open Bingo Game", "web_app": {"url": Config.WEBAPP_URL}}]]})
            elif text == '/help':
                send_telegram_message(chat_id,
                    "📖 <b>Nexus Bingo Help</b>\\n/start - Open game\\n/balance - Check balance\\n"
                    "/deposit - Add funds\\n/withdraw - Cash out\\n/history - Game history")
            elif text == '/balance':
                user_db = User.query.filter_by(telegram_id=chat_id).first()
                if user_db:
                    send_telegram_message(chat_id,
                        f"💰 <b>Balance</b>: {float(user_db.balance):.2f} ETB\\n🎮 Played: {user_db.total_games_played}\\n🏆 Won: {user_db.total_games_won}")
                else:
                    send_telegram_message(chat_id, "❌ No account yet. Register below:",
                        reply_markup={"inline_keyboard": [[{"text": "🎮 Register & Play", "web_app": {"url": Config.WEBAPP_URL}}]]})
            elif text.startswith('/admin') and chat_id in Config.ADMIN_IDS:
                send_telegram_message(chat_id, "🔧 <b>Admin Panel</b>\\nUse web interface for full controls.")
            elif text.startswith('/'):
                send_telegram_message(chat_id, f"❓ Unknown: {text}\\nUse /help")
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": "Internal error"}), 500

@app.route('/api/rooms', methods=['GET'])
@require_telegram_auth
@limiter.limit("30 per minute")
def list_rooms():
    rooms = Room.query.filter(Room.status.in_(['waiting', 'calling'])).all()
    return jsonify([{"id": r.id, "game_id": r.game_id, "stake": float(r.stake), "status": r.status,
        "players": RoomPlayer.query.filter_by(room_id=r.id).count(), "max_players": r.max_players,
        "pot": float(r.pot_amount), "is_automated": r.is_automated} for r in rooms])

@app.route('/api/rooms', methods=['POST'])
@require_telegram_auth
@limiter.limit("10 per minute")
def create_room():
    user = request.current_user
    data = request.get_json(silent=True) or {}
    try:
        stake = Decimal(str(data.get('stake', 10)))
        if stake <= 0 or stake > 10000:
            return jsonify({"error": "Stake 0.01-10000 ETB"}), 400
    except:
        return jsonify({"error": "Invalid stake"}), 400
    cartela_count = min(int(data.get('cartelas', 1)), Config.MAX_CARTELAS_PER_PLAYER)
    if cartela_count < 1:
        return jsonify({"error": "Min 1 cartela"}), 400
    total_cost = stake * cartela_count
    try:
        user_locked = get_user_with_lock(user.telegram_id)
        if not user_locked:
            return jsonify({"error": "User not found"}), 404
        if float(user_locked.balance) < float(total_cost):
            return jsonify({"error": "Insufficient balance"}), 400
        room_id = generate_room_id()
        game_id = generate_game_id()
        cartelas = generate_cartelas(cartela_count)
        room = Room(id=room_id, game_id=game_id, stake=stake, created_by=user.telegram_id,
            pot_amount=total_cost, total_cartelas=cartela_count)
        player = RoomPlayer(room_id=room_id, user_id=user.telegram_id, is_host=True, cartela_count=cartela_count)
        player.set_cartelas(cartelas)
        user_locked.balance = Decimal(float(user_locked.balance)) - Decimal(float(total_cost))
        user_locked.total_games_played = user_locked.total_games_played + 1
        db.session.add(room)
        db.session.add(player)
        db.session.commit()
        game_manager.start_timer(room_id)
        logger.info(f"Room {room_id} created by {user.telegram_id}")
        return jsonify({"room": {"id": room_id, "game_id": game_id, "stake": float(stake), "status": "waiting"}, "cartelas": cartelas})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Create room error: {e}")
        return jsonify({"error": "Failed to create room"}), 500

@app.route('/api/rooms/<room_id>/join', methods=['POST'])
@require_telegram_auth
@limiter.limit("10 per minute")
def join_room(room_id):
    user = request.current_user
    room = Room.query.get_or_404(room_id)
    if room.status != 'waiting':
        return jsonify({"error": "Game already started"}), 400
    existing = RoomPlayer.query.filter_by(room_id=room_id, user_id=user.telegram_id).first()
    if existing:
        return jsonify({"error": "Already joined"}), 400
    current_players = RoomPlayer.query.filter_by(room_id=room_id).count()
    if current_players >= room.max_players:
        return jsonify({"error": "Room full"}), 400
    data = request.get_json(silent=True) or {}
    cartela_count = min(int(data.get('cartelas', 1)), Config.MAX_CARTELAS_PER_PLAYER)
    if cartela_count < 1:
        return jsonify({"error": "Min 1 cartela"}), 400
    total_cost = float(room.stake) * cartela_count
    try:
        user_locked = get_user_with_lock(user.telegram_id)
        if not user_locked:
            return jsonify({"error": "User not found"}), 404
        if float(user_locked.balance) < total_cost:
            return jsonify({"error": "Insufficient balance"}), 400
        cartelas = generate_cartelas(cartela_count)
        player = RoomPlayer(room_id=room_id, user_id=user.telegram_id, cartela_count=cartela_count)
        player.set_cartelas(cartelas)
        user_locked.balance = Decimal(float(user_locked.balance)) - Decimal(total_cost)
        user_locked.total_games_played = user_locked.total_games_played + 1
        room.pot_amount = Decimal(float(room.pot_amount)) + Decimal(total_cost)
        room.total_cartelas = room.total_cartelas + cartela_count
        db.session.add(player)
        db.session.commit()
        logger.info(f"User {user.telegram_id} joined {room_id}")
        return jsonify({"cartelas": cartelas, "pot": float(room.pot_amount), "players": current_players + 1})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Join room error: {e}")
        return jsonify({"error": "Failed to join"}), 500

@app.route('/api/rooms/<room_id>/state')
@require_telegram_auth
@limiter.limit("60 per minute")
def get_room_state(room_id):
    state = game_manager.get_room_state(room_id)
    if not state:
        return jsonify({"error": "Room not found"}), 404
    player = RoomPlayer.query.filter_by(room_id=room_id, user_id=request.current_user.telegram_id).first()
    return jsonify({**state, "my_cartelas": player.get_cartelas() if player else [],
        "my_marked": json.loads(player.marked_numbers) if player else [],
        "player_count": RoomPlayer.query.filter_by(room_id=room_id).count()})

@app.route('/api/rooms/<room_id>/mark', methods=['POST'])
@require_telegram_auth
@limiter.limit("120 per minute")
def mark_number(room_id):
    user = request.current_user
    data = request.get_json(silent=True) or {}
    cartela_idx = data.get('cartela_index', 0)
    number_idx = data.get('number_index')
    if number_idx is None:
        return jsonify({"error": "number_index required"}), 400
    try:
        player = RoomPlayer.query.filter_by(room_id=room_id, user_id=user.telegram_id).first()
        if not player:
            return jsonify({"error": "Not in room"}), 404
        room = Room.query.get(room_id)
        if not room or room.status != 'calling':
            return jsonify({"error": "Game not active"}), 400
        cartelas = player.get_cartelas()
        if cartela_idx >= len(cartelas):
            return jsonify({"error": "Invalid cartela"}), 400
        called = room.get_called_numbers()
        number = cartelas[cartela_idx][number_idx]
        if number not in called and number != 0:
            return jsonify({"error": "Number not called"}), 400
        player.mark_number(cartela_idx, number_idx)
        db.session.commit()
        if player.check_bingo_on_cartela(cartela_idx):
            game_manager.end_game(room_id, user.telegram_id)
            return jsonify({"marked": True, "bingo": True, "winner": True, "message": "🎉 BINGO! You won!"})
        return jsonify({"marked": True, "number": number, "cartela_index": cartela_idx})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Mark error: {e}")
        return jsonify({"error": "Failed to mark"}), 500

@app.route('/api/user/profile')
@require_telegram_auth
def get_profile():
    return jsonify(request.current_user.to_dict())

@app.route('/api/user/deposit', methods=['POST'])
@require_telegram_auth
@limiter.limit("5 per minute")
def request_deposit():
    user = request.current_user
    data = request.get_json(silent=True) or {}
    try:
        amount = Decimal(str(data.get('amount', 0)))
        if amount < 10 or amount > 100000:
            return jsonify({"error": "Deposit 10-100000 ETB"}), 400
    except:
        return jsonify({"error": "Invalid amount"}), 400
    try:
        deposit = Deposit(user_id=user.telegram_id, amount=amount, status='pending')
        db.session.add(deposit)
        db.session.commit()
        return jsonify({"deposit_id": deposit.id, "amount": float(amount),
            "telebirr": Config.TELEBIRR_NUMBER, "cbe": Config.CBE_ACCOUNT,
            "instructions": f"Send {amount} ETB to account above, reply with tx ID"})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Deposit error: {e}")
        return jsonify({"error": "Failed"}), 500

@app.route('/api/user/withdraw', methods=['POST'])
@require_telegram_auth
@limiter.limit("5 per minute")
def request_withdrawal():
    user = request.current_user
    data = request.get_json(silent=True) or {}
    try:
        amount = Decimal(str(data.get('amount', 0)))
        if amount < 50 or amount > 100000:
            return jsonify({"error": "Withdrawal 50-100000 ETB"}), 400
    except:
        return jsonify({"error": "Invalid amount"}), 400
    try:
        user_locked = get_user_with_lock(user.telegram_id)
        if not user_locked:
            return jsonify({"error": "User not found"}), 404
        if float(user_locked.balance) < float(amount):
            return jsonify({"error": "Insufficient balance"}), 400
        withdrawal = Withdrawal(user_id=user.telegram_id, amount=amount,
            phone_number=data.get('phone_number', user.phone_number), status='pending')
        db.session.add(withdrawal)
        db.session.commit()
        user_locked.balance = Decimal(float(user_locked.balance)) - Decimal(float(amount))
        db.session.commit()
        if Config.ADMIN_ID:
            send_telegram_message(Config.ADMIN_ID,
                f"💸 Withdrawal\\nUser: {user.first_name} (@{user.username})\\nAmount: {float(amount):.2f} ETB")
        return jsonify({"withdrawal_id": withdrawal.id, "amount": float(amount), "status": "pending"})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Withdraw error: {e}")
        return jsonify({"error": "Failed"}), 500

@app.route('/api/user/transactions')
@require_telegram_auth
@limiter.limit("30 per minute")
def get_transactions():
    user = request.current_user
    transactions = Transaction.query.filter_by(user_id=user.telegram_id).order_by(Transaction.created_at.desc()).limit(50).all()
    return jsonify([{"id": t.id, "type": t.type, "amount": float(t.amount), "description": t.description,
        "reference_id": t.reference_id, "created_at": t.created_at.isoformat() if t.created_at else None} for t in transactions])

# ==================== ADMIN ROUTES ====================
@app.route('/api/admin/stats')
@require_admin_auth
@limiter.limit("30 per minute")
def admin_stats():
    try:
        total_users = User.query.count()
        total_games = Room.query.count()
        active_games = Room.query.filter(Room.status.in_(['waiting', 'calling'])).count()
        completed_games = Room.query.filter_by(status='completed').count()
        pending_deposits = Deposit.query.filter_by(status='pending').count()
        pending_withdrawals = Withdrawal.query.filter_by(status='pending').count()
        total_deposits = db.session.query(db.func.sum(Deposit.amount)).filter_by(status='approved').scalar() or 0
        total_withdrawals = db.session.query(db.func.sum(Withdrawal.amount)).filter_by(status='approved').scalar() or 0
        return jsonify({"users": {"total": total_users, "bots": User.query.filter_by(is_bot=True).count(),
            "active_today": User.query.filter(User.last_active >= datetime.utcnow() - timedelta(days=1)).count()},
            "games": {"total": total_games, "active": active_games, "completed": completed_games},
            "financial": {"pending_deposits": pending_deposits, "pending_withdrawals": pending_withdrawals,
            "total_deposits": float(total_deposits), "total_withdrawals": float(total_withdrawals),
            "house_cut_percent": GameSettings.get_house_cut()}})
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({"error": "Failed"}), 500

@app.route('/api/admin/deposits')
@require_admin_auth
@limiter.limit("30 per minute")
def list_pending_deposits():
    try:
        deposits = Deposit.query.filter_by(status='pending').order_by(Deposit.created_at.desc()).all()
        return jsonify([{"id": d.id, "user_id": d.user_id, "username": d.user.username if d.user else None,
            "first_name": d.user.first_name if d.user else None, "amount": float(d.amount),
            "created_at": d.created_at.isoformat() if d.created_at else None, "screenshot": d.screenshot_file_id} for d in deposits])
    except Exception as e:
        logger.error(f"Deposits error: {e}")
        return jsonify({"error": "Failed"}), 500

@app.route('/api/admin/deposits/<int:deposit_id>/approve', methods=['POST'])
@require_admin_auth
@limiter.limit("20 per minute")
def approve_deposit(deposit_id):
    try:
        deposit = Deposit.query.get_or_404(deposit_id)
        if deposit.status != 'pending':
            return jsonify({"error": "Already processed"}), 400
        data = request.get_json(silent=True) or {}
        approved = data.get('approved', True)
        if approved:
            deposit.status = 'approved'
            deposit.approved_at = datetime.utcnow()
            deposit.approved_by = request.telegram_user['id']
            user = User.query.filter_by(telegram_id=deposit.user_id).first()
            if user:
                user.balance = Decimal(float(user.balance)) + Decimal(float(deposit.amount))
                user.total_deposited = Decimal(float(user.total_deposited)) + Decimal(float(deposit.amount))
                transaction = Transaction(user_id=deposit.user_id, type='deposit', amount=deposit.amount, description=f'Deposit #{deposit.id} approved')
                db.session.add(transaction)
                send_telegram_message(deposit.user_id, f"✅ Deposit {float(deposit.amount):.0f} ETB approved!\\nBalance: {float(user.balance):.0f} ETB")
        else:
            deposit.status = 'rejected'
            deposit.approved_at = datetime.utcnow()
            deposit.approved_by = request.telegram_user['id']
            send_telegram_message(deposit.user_id, f"❌ Deposit {float(deposit.amount):.0f} ETB rejected.")
        db.session.commit()
        return jsonify({"success": True, "status": deposit.status})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Approve deposit error: {e}")
        return jsonify({"error": "Failed"}), 500

@app.route('/api/admin/withdrawals')
@require_admin_auth
@limiter.limit("30 per minute")
def list_pending_withdrawals():
    try:
        withdrawals = Withdrawal.query.filter_by(status='pending').order_by(Withdrawal.created_at.desc()).all()
        return jsonify([{"id": w.id, "user_id": w.user_id, "username": w.user.username if w.user else None,
            "first_name": w.user.first_name if w.user else None, "amount": float(w.amount),
            "phone_number": w.phone_number, "created_at": w.created_at.isoformat() if w.created_at else None} for w in withdrawals])
    except Exception as e:
        logger.error(f"Withdrawals error: {e}")
        return jsonify({"error": "Failed"}), 500

@app.route('/api/admin/withdrawals/<int:withdrawal_id>/approve', methods=['POST'])
@require_admin_auth
@limiter.limit("20 per minute")
def approve_withdrawal(withdrawal_id):
    try:
        withdrawal = Withdrawal.query.get_or_404(withdrawal_id)
        if withdrawal.status != 'pending':
            return jsonify({"error": "Already processed"}), 400
        data = request.get_json(silent=True) or {}
        approved = data.get('approved', True)
        if approved:
            withdrawal.status = 'approved'
            withdrawal.approved_at = datetime.utcnow()
            withdrawal.approved_by = request.telegram_user['id']
            user = User.query.filter_by(telegram_id=withdrawal.user_id).first()
            if user:
                user.total_withdrawn = Decimal(float(user.total_withdrawn)) + Decimal(float(withdrawal.amount))
                transaction = Transaction(user_id=withdrawal.user_id, type='withdrawal', amount=withdrawal.amount, description=f'Withdrawal #{withdrawal.id} approved')
                db.session.add(transaction)
                send_telegram_message(withdrawal.user_id, f"✅ Withdrawal {float(withdrawal.amount):.0f} ETB processed!\\nSent to: {withdrawal.phone_number}")
        else:
            withdrawal.status = 'rejected'
            withdrawal.approved_at = datetime.utcnow()
            withdrawal.approved_by = request.telegram_user['id']
            user = User.query.filter_by(telegram_id=withdrawal.user_id).first()
            if user:
                user.balance = Decimal(float(user.balance)) + Decimal(float(withdrawal.amount))
            send_telegram_message(withdrawal.user_id, f"❌ Withdrawal {float(withdrawal.amount):.0f} ETB rejected. Refunded.")
        db.session.commit()
        return jsonify({"success": True, "status": withdrawal.status})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Approve withdrawal error: {e}")
        return jsonify({"error": "Failed"}), 500

@app.route('/api/admin/settings', methods=['GET', 'POST'])
@require_admin_auth
@limiter.limit("30 per minute")
def admin_settings():
    if request.method == 'GET':
        return jsonify({"house_cut_percent": GameSettings.get_house_cut(),
            "welcome_bonus": float(Config.WELCOME_BONUS), "max_cartelas": Config.MAX_CARTELAS_PER_PLAYER,
            "auto_fill_bots": Config.AUTO_FILL_BOT_COUNT})
    try:
        data = request.get_json(silent=True) or {}
        admin_id = request.telegram_user['id']
        if 'house_cut' in data:
            house_cut = float(data['house_cut'])
            if 0 <= house_cut <= 50:
                GameSettings.set_house_cut(house_cut, admin_id)
                logger.info(f"Admin {admin_id} set house cut to {house_cut}%")
            else:
                return jsonify({"error": "House cut 0-50%"}), 400
        return jsonify({"success": True, "house_cut": GameSettings.get_house_cut()})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Settings error: {e}")
        return jsonify({"error": "Failed"}), 500

# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return jsonify({"error": "Internal error"}), 500

@app.errorhandler(429)
def rate_limit(e):
    return jsonify({"error": "Rate limit exceeded"}), 429

# ==================== INIT & MAIN ====================
def init_db():
    with app.app_context():
        try:
            db.create_all()
            logger.info("✅ Database created")
            if Config.ADMIN_ID and Config.ADMIN_IDS:
                for admin_id in Config.ADMIN_IDS:
                    if not Admin.query.filter_by(telegram_id=admin_id).first():
                        db.session.add(Admin(telegram_id=admin_id, username="admin"))
                        db.session.commit()
                        logger.info(f"✅ Admin {admin_id} created")
        except Exception as e:
            logger.error(f"DB init error: {e}")
            raise

def set_webhook():
    if not Config.BOT_TOKEN:
        return False
    try:
        requests.get(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook", timeout=10)
        response = requests.post(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/setWebhook",
            json={"url": Config.WEBHOOK_URL, "max_connections": 40, "allowed_updates": ["message", "callback_query"]}, timeout=10)
        result = response.json()
        if result.get("ok"):
            logger.info(f"✅ Webhook set: {Config.WEBHOOK_URL}")
        return result.get("ok", False)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return False

def setup_webhook_async():
    def task():
        time.sleep(5)
        with app.app_context():
            set_webhook()
    threading.Thread(target=task, daemon=True).start()

if __name__ == '__main__':
    init_db()
    setup_webhook_async()
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 Starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
else:
    init_db()
    setup_webhook_async()
    logger.info("🚀 Loaded via WSGI")
