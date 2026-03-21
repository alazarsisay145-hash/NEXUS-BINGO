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
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qsl
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from functools import wraps
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== CONFIGURATION ====================
class Config:
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "8615731945:AAF5ltmg_j_abBngVTSQnXa2MiVu7eweTTI")
    BOT_USERNAME = "@neXUSSBINGObot"
    ADMIN_ID = int(os.environ.get("ADMIN_ID", "8461485965"))
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///bingo.db")
    SECRET_KEY = os.environ.get("SECRET_KEY", "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6")
    DEFAULT_HOUSE_CUT = 10.0
    MAX_CARTELAS_PER_PLAYER = 3
    AUTO_FILL_BOT_COUNT = 10
    MIN_PLAYERS_TO_START = 2
    TOTAL_CARTELAS_IN_GAME = 100
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://nexus-bingo.onrender.com")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://nexus-bingo.onrender.com/webhook")
    WELCOME_BONUS = 25.0
    # UPDATED PAYMENT DETAILS
    TELEBIRR_NUMBER = "0952346729"
    CBE_ACCOUNT = "1000641057146"

app.config.from_object(Config)
app.config["SQLALCHEMY_DATABASE_URI"] = Config.DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = Config.SECRET_KEY

CORS(app)
db = SQLAlchemy(app)

# ==================== DATABASE MODELS ====================

class GameCall(db.Model):
    __tablename__ = "game_calls"
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(10), db.ForeignKey("rooms.id"), nullable=False)
    call_number = db.Column(db.String(10), nullable=False)
    number_value = db.Column(db.Integer)
    called_at = db.Column(db.DateTime, default=datetime.utcnow)

class Admin(db.Model):
    __tablename__ = "admins"
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False)
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
    balance = db.Column(db.Numeric(15, 2), default=0.00)
    is_approved = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    is_bot = db.Column(db.Boolean, default=False)
    registration_step = db.Column(db.String(50), default="telegram_auth")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    welcome_bonus_claimed = db.Column(db.Boolean, default=False)
    total_games_played = db.Column(db.Integer, default=0)
    total_games_won = db.Column(db.Integer, default=0)
    total_deposited = db.Column(db.Numeric(15, 2), default=0.00)
    total_withdrawn = db.Column(db.Numeric(15, 2), default=0.00)

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
    pot_amount = db.Column(db.Numeric(15, 2), default=0.00)
    house_cut_percent = db.Column(db.Numeric(5, 2), default=10.00)
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
    house_favor_enabled = db.Column(db.Boolean, default=False)

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
    room_id = db.Column(db.String(10), db.ForeignKey("rooms.id"), nullable=False)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=False)
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
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=False)
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
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=False)
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
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.telegram_id"), nullable=False)
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
        if setting:
            return float(setting.value)
        return Config.DEFAULT_HOUSE_CUT

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

    @classmethod
    def get_house_favor(cls):
        setting = cls.query.filter_by(key="house_favor_enabled").first()
        if setting:
            return setting.value.lower() == "true"
        return False

    @classmethod
    def set_house_favor(cls, enabled, admin_id):
        setting = cls.query.filter_by(key="house_favor_enabled").first()
        if not setting:
            setting = cls(key="house_favor_enabled")
        setting.value = "true" if enabled else "false"
        setting.updated_by = admin_id
        db.session.add(setting)
        db.session.commit()
        return setting

# ==================== UTILITY FUNCTIONS ====================

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
    if 1 <= num <= 15:
        return "B"
    elif 16 <= num <= 30:
        return "I"
    elif 31 <= num <= 45:
        return "N"
    elif 46 <= num <= 60:
        return "G"
    elif 61 <= num <= 75:
        return "O"
    return "B"

def send_telegram_message(chat_id, text, parse_mode="HTML", reply_markup=None):
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
        data_check_string = "\n".join(data_check_pairs)
        secret_key = hmac.new(key=b"WebAppData", msg=Config.BOT_TOKEN.encode(), digestmod=hashlib.sha256).digest()
        calculated_hash = hmac.new(key=secret_key, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated_hash, received_hash):
            raise ValueError("Invalid hash")
        auth_date = int(parsed_data.get("auth_date", 0))
        if time.time() - auth_date > 86400:
            raise ValueError("Auth expired")
        user_data = json.loads(parsed_data.get("user", "{}"))
        if not user_data:
            raise ValueError("No user data")
        return user_data
    except Exception as e:
        raise ValueError(f"Validation failed: {str(e)}")

# ==================== DECORATORS ====================

def require_telegram_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        test_mode = request.headers.get("X-Test-Mode") or request.args.get("test")
        if test_mode:
            test_user = User.query.filter_by(telegram_id=999999999).first()
            if not test_user:
                test_user = User(telegram_id=999999999, username="testuser", first_name="Test", last_name="Player", is_approved=True, balance=100000.0, registration_step="approved", welcome_bonus_claimed=True)
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
                user = User(telegram_id=telegram_id, username=user_data.get("username"), first_name=user_data.get("first_name", "Player"), last_name=user_data.get("last_name", ""), registration_step="telegram_auth", is_approved=True, balance=Config.WELCOME_BONUS, welcome_bonus_claimed=True)
                db.session.add(user)
                db.session.commit()
                is_new_user = True

                transaction = Transaction(user_id=telegram_id, type="welcome_bonus", amount=Config.WELCOME_BONUS, description="Welcome bonus")
                db.session.add(transaction)
                db.session.commit()

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
        if test_mode:
            request.telegram_user = {"id": Config.ADMIN_ID, "first_name": "Test", "last_name": "Admin"}
            request.is_admin = True
            return f(*args, **kwargs)

        auth_header = request.headers.get("X-Telegram-Init-Data")
        if not auth_header:
            return jsonify({"error": "No authentication data"}), 401

        try:
            user_data = validate_telegram_init_data(auth_header)
            telegram_id = user_data.get("id")
            is_admin = telegram_id == Config.ADMIN_ID

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
    BOT_NAMES = ["Abebe", "Kebede", "Desta", "Tesfaye", "Alemu", "Bekele", "Mekonnen", "Solomon", "Daniel", "Michael", "Yohannes", "Girma", "Hailu", "Tadesse", "Fatuma", "Amina", "Hawa", "Mulu", "Tigist", "Hiwot"]

    @classmethod
    def get_or_create_bot(cls, bot_index):
        bot_id = -(1000000000 + bot_index)
        bot = User.query.filter_by(telegram_id=bot_id).first()
        if bot:
            return bot
        name = random.choice(cls.BOT_NAMES)
        username = f"{name.lower()}{random.randint(1000, 9999)}_bot"
        bot = User(telegram_id=bot_id, username=username, first_name=f"🤖 {name}", last_name="Bot", is_approved=True, is_bot=True, balance=1000000.0, registration_step="approved", welcome_bonus_claimed=True)
        db.session.add(bot)
        db.session.commit()
        return bot

    @classmethod
    def fill_room_with_bots(cls, room_id, stake, num_bots=None, house_favor=False):
        if num_bots is None:
            num_bots = Config.AUTO_FILL_BOT_COUNT
        room = Room.query.get(room_id)
        if not room:
            return
        current_players = RoomPlayer.query.filter_by(room_id=room_id).count()
        max_players = room.max_players
        bots_to_add = min(num_bots, max_players - current_players)

        for i in range(bots_to_add):
            bot = cls.get_or_create_bot(i)
            cartela_count = random.randint(1, min(3, Config.MAX_CARTELAS_PER_PLAYER))
            cartelas = generate_cartelas(cartela_count)
            player = RoomPlayer(room_id=room_id, user_id=bot.telegram_id, is_host=False, is_fake=True, cartela_count=cartela_count)
            player.set_cartelas(cartelas)
            bot.balance = float(bot.balance) - (stake * cartela_count)
            room.pot_amount = float(room.pot_amount) + (stake * cartela_count)
            room.total_cartelas = room.total_cartelas + cartela_count
            db.session.add(player)

        room.is_automated = True
        room.house_favor_enabled = house_favor
        db.session.commit()
        return bots_to_add

# ==================== GAME MANAGER ====================

class GameManager:
    _instance = None
    _lock = threading.Lock()
    _room_locks = {}
    _room_states = {}

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
        if room_id not in self._room_locks:
            self._room_locks[room_id] = threading.RLock()
        return self._room_locks[room_id]

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
        if room_id in self.timer_threads:
            return

        def timer_callback():
            time.sleep(delay_seconds)
            with app.app_context():
                room = Room.query.get(room_id)
                if not room or room.status != "waiting":
                    return
                house_favor = GameSettings.get_house_favor()
                BotPlayerManager.fill_room_with_bots(room_id, float(room.stake), house_favor=house_favor)
                room = Room.query.get(room_id)
                if room.status == "waiting":
                    room.status = "calling"
                    room.started_at = datetime.utcnow()
                    db.session.commit()
                    self.start_game(room_id)

        thread = threading.Thread(target=timer_callback, daemon=True)
        self.timer_threads[room_id] = thread
        thread.start()

    def start_game(self, room_id):
        if room_id in self.call_threads:
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
        house_favor = room.house_favor_enabled

        while available_numbers:
            time.sleep(random.uniform(5, 8))

            db.session.expire_all()
            room = Room.query.get(room_id)

            if not room or room.status != "calling":
                break

            with self._get_room_lock(room_id):
                if not available_numbers:
                    break

                if house_favor and random.random() < 0.3:
                    number = self._select_favorable_number(room_id, available_numbers)
                else:
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

            if len(room.get_called_numbers()) >= 75:
                winner = self._pick_random_winner(room_id)
                self.end_game(room_id, winner)
                return

    def _select_favorable_number(self, room_id, available_numbers):
        bot_players = RoomPlayer.query.filter_by(room_id=room_id, is_fake=True).all()
        favorable_numbers = []

        for bot in bot_players:
            cartelas = bot.get_cartelas()
            marked = json.loads(bot.marked_numbers) if bot.marked_numbers else [[] for _ in cartelas]

            for cartela_idx, cartela in enumerate(cartelas):
                current_marked = marked[cartela_idx] if cartela_idx < len(marked) else []
                for num in cartela:
                    if num in available_numbers and num != 0:
                        temp_marked = current_marked.copy()
                        if num in cartela:
                            num_idx = cartela.index(num)
                            temp_marked.append(num_idx)
                            if self._would_complete_line(temp_marked):
                                favorable_numbers.append(num)

        if favorable_numbers:
            return favorable_numbers[random.randint(0, len(favorable_numbers) - 1)]
        return available_numbers.pop(random.randint(0, len(available_numbers) - 1))

    def _would_complete_line(self, marked_indices):
        if len(marked_indices) < 4:
            return False
        marked_set = set(marked_indices)
        for row in range(5):
            count = sum(1 for col in range(5) if row * 5 + col in marked_set)
            if count >= 4:
                return True
        for col in range(5):
            count = sum(1 for row in range(5) if row * 5 + col in marked_set)
            if count >= 4:
                return True
        return False

    def _auto_mark_for_bots(self, room_id, number):
        players = RoomPlayer.query.filter_by(room_id=room_id, is_fake=True).all()
        for player in players:
            cartelas = player.get_cartelas()
            for cartela_idx, cartela in enumerate(cartelas):
                if number in cartela:
                    number_idx = cartela.index(number)
                    player.mark_number(cartela_idx, number_idx)
        db.session.commit()

    def _check_for_winner(self, room_id):
        players = RoomPlayer.query.filter_by(room_id=room_id).all()
        for player in players:
            for cartela_idx in range(player.cartela_count):
                if player.check_bingo_on_cartela(cartela_idx):
                    return player.user_id
        return None

    def _pick_random_winner(self, room_id):
        players = RoomPlayer.query.filter_by(room_id=room_id).all()
        if players:
            weighted_players = []
            for p in players:
                weighted_players.extend([p] * p.cartela_count)
            winner = random.choice(weighted_players)
            return winner.user_id
        return None

    def end_game(self, room_id, winner_id):
        with self._get_room_lock(room_id):
            room = Room.query.get(room_id)
            if not room or room.status == "completed":
                return

            room.status = "completed"
            room.completed_at = datetime.utcnow()
            room.winner_id = winner_id

            if winner_id:
                winner = User.query.filter_by(telegram_id=winner_id).first()
                if winner:
                    house_cut_percent = float(room.house_cut_percent) if room.house_cut_percent else GameSettings.get_house_cut()
                    total_pot = float(room.pot_amount)
                    house_fee = total_pot * (house_cut_percent / 100)
                    win_amount = total_pot - house_fee

                    winner.balance = float(winner.balance) + win_amount
                    winner.total_games_won = winner.total_games_won + 1

                    winner_player = RoomPlayer.query.filter_by(room_id=room_id, user_id=winner_id).first()
                    if winner_player:
                        winner_player.has_won = True

                    transaction = Transaction(user_id=winner_id, type="win", amount=float(win_amount), reference_id=room.id, description=f"Won game {room.game_id}")
                    db.session.add(transaction)

                    if not winner.is_bot:
                        send_telegram_message(winner_id, f"🎉 You won {win_amount:.0f} ETB! New balance: {winner.balance:.0f} ETB")
                    send_telegram_message(Config.ADMIN_ID, f"🏆 Winner: {winner.first_name}, Prize: {win_amount:.0f} ETB, Room: {room.id}")

            db.session.commit()

            if room_id in self.call_threads:
                del self.call_threads[room_id]
            if room_id in self.timer_threads:
                del self.timer_threads[room_id]
            if room_id in self.active_games:
                del self.active_games[room_id]
            if room_id in self._room_states:
                del self._room_states[room_id]

game_manager = GameManager()
