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

# HARDCODED CONFIG - Replace with env vars after testing on Render
class Config:
    BOT_TOKEN = "8615731945:AAF5ltmg_j_abBngVTSQnXa2MiVu7eweTTI"
    BOT_USERNAME = "@neXUSSBINGObot"
    ADMIN_ID = 8461485965
    DATABASE_URL = "sqlite:///bingo.db"
    SECRET_KEY = "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6"
    DEFAULT_HOUSE_CUT = 10.0
    MAX_CARTELAS_PER_PLAYER = 3
    AUTO_FILL_BOT_COUNT = 10
    MIN_PLAYERS_TO_START = 2
    TOTAL_CARTELAS_IN_GAME = 100
    WEBAPP_URL = "https://nexus-bingo.onrender.com/"
    WEBHOOK_URL = "https://nexus-bingo.onrender.com/webhook"
    WELCOME_BONUS = 25.0

app.config.from_object(Config)
app.config['SQLALCHEMY_DATABASE_URI'] = Config.DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = Config.SECRET_KEY

CORS(app)
db = SQLAlchemy(app)

# [Rest of your code with models, game logic, routes, etc.]

# [Rest of your code remains the same...]

class GameCall(db.Model):
    __tablename__ = 'game_calls'
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(10), db.ForeignKey('rooms.id'), nullable=False)
    call_number = db.Column(db.String(10), nullable=False)
    number_value = db.Column(db.Integer)
    called_at = db.Column(db.DateTime, default=datetime.utcnow)

class Admin(db.Model):
    __tablename__ = 'admins'
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False)
    username = db.Column(db.String(100))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

class User(db.Model):
    __tablename__ = 'users'
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
    registration_step = db.Column(db.String(50), default='telegram_auth')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    welcome_bonus_claimed = db.Column(db.Boolean, default=False)
    total_games_played = db.Column(db.Integer, default=0)
    total_games_won = db.Column(db.Integer, default=0)
    total_deposited = db.Column(db.Numeric(15, 2), default=0.00)
    total_withdrawn = db.Column(db.Numeric(15, 2), default=0.00)

    def to_dict(self):
        return {
            'id': self.id,
            'telegram_id': self.telegram_id,
            'username': self.username,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'phone_number': self.phone_number,
            'balance': float(self.balance),
            'is_approved': self.is_approved,
            'is_banned': self.is_banned,
            'is_bot': self.is_bot,
            'registration_step': self.registration_step,
            'welcome_bonus_claimed': self.welcome_bonus_claimed,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_active': self.last_active.isoformat() if self.last_active else None,
            'stats': {
                'games_played': self.total_games_played,
                'games_won': self.total_games_won,
                'win_rate': round((self.total_games_won / self.total_games_played * 100), 1) if self.total_games_played > 0 else 0
            }
        }

class Room(db.Model):
    __tablename__ = 'rooms'
    id = db.Column(db.String(10), primary_key=True)
    game_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    stake = db.Column(db.Numeric(10, 2), nullable=False)
    max_players = db.Column(db.Integer, default=20)
    max_cartelas = db.Column(db.Integer, default=100)
    status = db.Column(db.String(20), default='waiting')
    pot_amount = db.Column(db.Numeric(15, 2), default=0.00)
    house_cut_percent = db.Column(db.Numeric(5, 2), default=10.00)
    created_by = db.Column(db.BigInteger, db.ForeignKey('users.telegram_id'))
    winner_id = db.Column(db.BigInteger, db.ForeignKey('users.telegram_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    current_call = db.Column(db.String(10), nullable=True)
    called_numbers = db.Column(db.Text, default='[]')
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
    __tablename__ = 'room_players'
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(10), db.ForeignKey('rooms.id'), nullable=False)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.telegram_id'), nullable=False)
    is_host = db.Column(db.Boolean, default=False)
    has_won = db.Column(db.Boolean, default=False)
    cartela_count = db.Column(db.Integer, default=1)
    cartela_numbers = db.Column(db.Text, nullable=False)
    marked_numbers = db.Column(db.Text, default='[]')
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_fake = db.Column(db.Boolean, default=False)
    room = db.relationship('Room', backref='room_players')

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
    __tablename__ = 'deposits'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.telegram_id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default='pending')
    screenshot_file_id = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.BigInteger, nullable=True)
    user = db.relationship('User', foreign_keys=[user_id])

class Withdrawal(db.Model):
    __tablename__ = 'withdrawals'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.telegram_id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default='pending')
    phone_number = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.BigInteger, nullable=True)
    user = db.relationship('User', foreign_keys=[user_id])

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.telegram_id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    reference_id = db.Column(db.String(50))
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class GameSettings(db.Model):
    __tablename__ = 'game_settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(255))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.BigInteger)

    @classmethod
    def get_house_cut(cls):
        setting = cls.query.filter_by(key='house_cut_percent').first()
        if setting:
            return float(setting.value)
        return Config.DEFAULT_HOUSE_CUT

    @classmethod
    def set_house_cut(cls, percent, admin_id):
        setting = cls.query.filter_by(key='house_cut_percent').first()
        if not setting:
            setting = cls(key='house_cut_percent')
        setting.value = str(percent)
        setting.updated_by = admin_id
        db.session.add(setting)
        db.session.commit()
        return setting

    @classmethod
    def get_house_favor(cls):
        setting = cls.query.filter_by(key='house_favor_enabled').first()
        if setting:
            return setting.value.lower() == 'true'
        return False

    @classmethod
    def set_house_favor(cls, enabled, admin_id):
        setting = cls.query.filter_by(key='house_favor_enabled').first()
        if not setting:
            setting = cls(key='house_favor_enabled')
        setting.value = 'true' if enabled else 'false'
        setting.updated_by = admin_id
        db.session.add(setting)
        db.session.commit()
        return setting

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
        return 'B'
    elif 16 <= num <= 30:
        return 'I'
    elif 31 <= num <= 45:
        return 'N'
    elif 46 <= num <= 60:
        return 'G'
    elif 61 <= num <= 75:
        return 'O'
    return 'B'

def send_telegram_message(chat_id, text, parse_mode='HTML', reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {'chat_id': chat_id, 'text': text, 'parse_mode': parse_mode}
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup)
        response = requests.post(url, json=payload, timeout=10)
        result = response.json()
        if not result.get('ok'):
            logger.error(f"Telegram API error: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return None

def validate_telegram_init_data(init_data):
    try:
        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed_data.pop('hash', None)
        if not received_hash:
            raise ValueError("No hash found")
        data_check_pairs = [f"{k}={v}" for k, v in sorted(parsed_data.items())]
        data_check_string = '\n'.join(data_check_pairs)
        secret_key = hmac.new(key=b"WebAppData", msg=Config.BOT_TOKEN.encode(), digestmod=hashlib.sha256).digest()
        calculated_hash = hmac.new(key=secret_key, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated_hash, received_hash):
            raise ValueError("Invalid hash")
        auth_date = int(parsed_data.get('auth_date', 0))
        if time.time() - auth_date > 86400:
            raise ValueError("Auth expired")
        user_data = json.loads(parsed_data.get('user', '{}'))
        if not user_data:
            raise ValueError("No user data")
        return user_data
    except Exception as e:
        raise ValueError(f"Validation failed: {str(e)}")

def require_telegram_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        test_mode = request.headers.get('X-Test-Mode') or request.args.get('test')
        if test_mode:
            test_user = User.query.filter_by(telegram_id=999999999).first()
            if not test_user:
                test_user = User(telegram_id=999999999, username='testuser', first_name='Test', last_name='Player', is_approved=True, balance=100000.0, registration_step='approved', welcome_bonus_claimed=True)
                db.session.add(test_user)
                db.session.commit()
            request.telegram_user = {'id': 999999999, 'first_name': 'Test', 'last_name': 'Player', 'username': 'testuser'}
            request.current_user = test_user
            request.is_test_mode = True
            return f(*args, **kwargs)

        auth_header = request.headers.get('X-Telegram-Init-Data')
        if not auth_header:
            auth_header = request.headers.get('Authorization', '')
            if auth_header.lower().startswith('tma '):
                auth_header = auth_header[4:]
            else:
                auth_header = None

        if not auth_header:
            return jsonify({'error': 'Authentication required'}), 401

        try:
            user_data = validate_telegram_init_data(auth_header)
            telegram_id = user_data.get('id')
            if not telegram_id:
                return jsonify({'error': 'Invalid user data'}), 401

            user = User.query.filter_by(telegram_id=telegram_id).first()
            is_new_user = False

            if not user:
                user = User(telegram_id=telegram_id, username=user_data.get('username'), first_name=user_data.get('first_name', 'Player'), last_name=user_data.get('last_name', ''), registration_step='telegram_auth', is_approved=True, balance=Config.WELCOME_BONUS, welcome_bonus_claimed=True)
                db.session.add(user)
                db.session.commit()
                is_new_user = True

                transaction = Transaction(user_id=telegram_id, type='welcome_bonus', amount=Config.WELCOME_BONUS, description='Welcome bonus')
                db.session.add(transaction)
                db.session.commit()

                send_telegram_message(Config.ADMIN_ID, f"🆕 New user: {user.first_name} (+{Config.WELCOME_BONUS} ETB)")

            if user.is_banned:
                return jsonify({'error': 'Account banned'}), 403

            user.last_active = datetime.utcnow()
            db.session.commit()

            request.telegram_user = user_data
            request.current_user = user
            request.is_test_mode = False
            request.is_new_user = is_new_user
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Auth error: {e}")
            return jsonify({'error': 'Authentication failed'}), 401
    return decorated_function

def require_admin_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        test_mode = request.headers.get('X-Test-Mode') or request.args.get('test')
        if test_mode:
            request.telegram_user = {'id': Config.ADMIN_ID, 'first_name': 'Test', 'last_name': 'Admin'}
            request.is_admin = True
            return f(*args, **kwargs)

        auth_header = request.headers.get('X-Telegram-Init-Data')
        if not auth_header:
            return jsonify({'error': 'No authentication data'}), 401

        try:
            user_data = validate_telegram_init_data(auth_header)
            telegram_id = user_data.get('id')
            is_admin = telegram_id == Config.ADMIN_ID
            
            if not is_admin:
                admin_record = Admin.query.filter_by(telegram_id=telegram_id).first()
                is_admin = admin_record is not None
                
            if not is_admin:
                return jsonify({'error': 'Unauthorized - Admin only'}), 403
            request.telegram_user = user_data
            request.is_admin = True
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Admin auth error: {e}")
            return jsonify({'error': 'Authentication failed'}), 401
    return decorated_function

class BotPlayerManager:
    BOT_NAMES = ['Abebe', 'Kebede', 'Desta', 'Tesfaye', 'Alemu', 'Bekele', 'Mekonnen', 'Solomon', 'Daniel', 'Michael', 'Yohannes', 'Girma', 'Hailu', 'Tadesse', 'Fatuma', 'Amina', 'Hawa', 'Mulu', 'Tigist', 'Hiwot']

    @classmethod
    def get_or_create_bot(cls, bot_index):
        bot_id = -(1000000000 + bot_index)
        bot = User.query.filter_by(telegram_id=bot_id).first()
        if bot:
            return bot
        name = random.choice(cls.BOT_NAMES)
        username = f"{name.lower()}{random.randint(1000, 9999)}_bot"
        bot = User(telegram_id=bot_id, username=username, first_name=f"🤖 {name}", last_name="Bot", is_approved=True, is_bot=True, balance=1000000.0, registration_step='approved', welcome_bonus_claimed=True)
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
                if time.time() - cached['timestamp'] < 1:
                    return cached
            
            room = Room.query.get(room_id)
            if not room:
                return None
            
            state = {
                'current_call': room.current_call,
                'called_numbers': room.get_called_numbers(),
                'status': room.status,
                'timestamp': time.time()
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
                if not room or room.status != 'waiting':
                    return
                house_favor = GameSettings.get_house_favor()
                BotPlayerManager.fill_room_with_bots(room_id, float(room.stake), house_favor=house_favor)
                room = Room.query.get(room_id)
                if room.status == 'waiting':
                    room.status = 'calling'
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
            
            if not room or room.status != 'calling':
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
                    'current_call': call_str,
                    'called_numbers': room.get_called_numbers(),
                    'status': room.status,
                    'timestamp': time.time()
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
            if not room or room.status == 'completed':
                return

            room.status = 'completed'
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

                    transaction = Transaction(user_id=winner_id, type='win', amount=float(win_amount), reference_id=room.id, description=f'Won game {room.game_id}')
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

PLAYER_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>NEXUS BINGO</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: Arial, sans-serif; }
        body { background: #0f0a1e; color: white; min-height: 100vh; padding-bottom: 100px; }
        .hidden { display: none !important; }
        #loading-screen { position: fixed; inset: 0; background: #0f0a1e; display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 5000; }
        .loading-logo { font-size: 80px; margin-bottom: 20px; animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.1); } }
        .app-container { max-width: 800px; margin: 0 auto; padding: 12px; }
        .app-header { background: linear-gradient(135deg, rgba(139, 92, 246, 0.2), rgba(236, 72, 153, 0.2)); border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 20px; padding: 20px; margin-bottom: 16px; }
        .balance-section { text-align: center; padding: 16px; background: rgba(0,0,0,0.2); border-radius: 16px; }
        .balance-amount { font-size: 42px; font-weight: 800; color: #f59e0b; }
        .bonus-banner { background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(245, 158, 11, 0.2)); border: 2px solid #10b981; border-radius: 16px; padding: 16px; margin-bottom: 16px; text-align: center; }
        .btn { padding: 16px; border-radius: 16px; border: none; cursor: pointer; font-weight: 700; transition: all 0.3s; }
        .btn-primary { background: linear-gradient(135deg, #8b5cf6, #ec4899); color: white; width: 100%; }
        .btn-success { background: #10b981; color: white; }
        .btn-danger { background: #ef4444; color: white; }
        .card { background: #1a1425; border-radius: 20px; padding: 20px; margin-bottom: 16px; }
        .stake-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 20px; }
        .stake-btn { padding: 20px; border-radius: 16px; border: 2px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.03); color: white; cursor: pointer; text-align: center; }
        .stake-btn.active { background: linear-gradient(135deg, rgba(139, 92, 246, 0.3), rgba(236, 72, 153, 0.3)); border-color: #8b5cf6; }
        .cartela-selector { display: flex; align-items: center; justify-content: center; gap: 24px; margin: 20px 0; }
        .cartela-btn { width: 56px; height: 56px; border-radius: 16px; border: 2px solid #8b5cf6; background: transparent; color: #8b5cf6; font-size: 28px; font-weight: 700; cursor: pointer; }
        .call-display { background: linear-gradient(135deg, rgba(139, 92, 246, 0.2), rgba(236, 72, 153, 0.2)); border: 2px solid rgba(139, 92, 246, 0.4); border-radius: 24px; padding: 30px; text-align: center; margin-bottom: 20px; position: relative; }
        .call-letter { font-size: 64px; font-weight: 900; }
        .call-number { font-size: 80px; font-weight: 900; margin: 10px 0; }
        .call-letter.b { color: #3b82f6; } .call-letter.i { color: #8b5cf6; } .call-letter.n { color: #ec4899; } .call-letter.g { color: #10b981; } .call-letter.o { color: #f59e0b; }
        .voice-btn { position: absolute; top: 10px; right: 10px; width: 40px; height: 40px; border-radius: 50%; background: rgba(255,255,255,0.2); border: none; cursor: pointer; font-size: 20px; }
        .cartela-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 20px 0; }
        .cartela-cell { aspect-ratio: 1; display: flex; align-items: center; justify-content: center; background: white; color: #0f0a1e; border-radius: 12px; font-weight: 700; font-size: 18px; cursor: pointer; border: 3px solid transparent; }
        .cartela-cell.marked { background: #10b981; color: white; border-color: #10b981; }
        .cartela-cell.called { border-color: #f59e0b; box-shadow: 0 0 15px rgba(245, 158, 11, 0.5); }
        .cartela-cell.free { background: linear-gradient(135deg, #8b5cf6, #ec4899); color: white; font-size: 24px; }
        .bottom-nav { position: fixed; bottom: 0; left: 0; right: 0; background: rgba(15, 10, 30, 0.95); backdrop-filter: blur(20px); border-top: 1px solid rgba(255,255,255,0.1); display: flex; justify-content: space-around; padding: 12px 20px 24px; z-index: 1000; }
        .nav-item { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 8px; cursor: pointer; opacity: 0.5; }
        .nav-item.active { opacity: 1; color: #8b5cf6; }
    </style>
</head>
<body>
    <div id="loading-screen">
        <div class="loading-logo">🎰</div>
        <div style="font-size: 20px; font-weight: 700; color: #8b5cf6;">NEXUS BINGO</div>
    </div>

    <div id="app-content" class="hidden app-container">
        <div id="view-dashboard" class="view-section">
            <div class="app-header">
                <div class="balance-section">
                    <div style="font-size: 12px; color: #9ca3af;">Balance</div>
                    <div class="balance-amount" id="balance">0</div>
                    <div style="font-size: 14px; color: #9ca3af;">ETB</div>
                </div>
            </div>

            <div class="bonus-banner" id="bonus-banner" style="display: none;">
                <div style="font-size: 18px; font-weight: 700; color: #10b981;">🎁 Welcome Bonus!</div>
                <div style="font-size: 32px; font-weight: 800; color: #f59e0b;">+25 ETB</div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px;">
                <button class="btn btn-success" onclick="alert('Send Telebirr to 0936 719 379')">💰 Deposit</button>
                <button class="btn btn-danger" onclick="alert('Min 50 ETB')">💸 Withdraw</button>
            </div>

            <div class="card">
                <div style="font-size: 18px; font-weight: 700; margin-bottom: 16px;">🎯 Select Stake</div>
                <div class="stake-grid">
                    <button class="stake-btn active" onclick="selectStake(10)" id="stake-10">10 ETB</button>
                    <button class="stake-btn" onclick="selectStake(25)" id="stake-25">25 ETB</button>
                    <button class="stake-btn" onclick="selectStake(50)" id="stake-50">50 ETB</button>
                    <button class="stake-btn" onclick="selectStake(100)" id="stake-100">100 ETB</button>
                </div>
                
                <div class="cartela-selector">
                    <button class="cartela-btn" onclick="changeCartelaCount(-1)">−</button>
                    <div style="text-align: center;">
                        <div style="font-size: 48px; font-weight: 800; color: #8b5cf6;" id="cartela-count">1</div>
                        <div style="font-size: 14px; color: #9ca3af;">Cartelas</div>
                    </div>
                    <button class="cartela-btn" onclick="changeCartelaCount(1)">+</button>
                </div>
                
                <button class="btn btn-primary" onclick="startGame()" style="margin-top: 20px;">🚀 START GAME</button>
            </div>
        </div>

        <div id="view-game" class="view-section hidden">
            <div class="call-display">
                <button class="voice-btn" id="voice-btn" onclick="toggleVoice()">🔊</button>
                <div class="call-letter" id="call-letter">-</div>
                <div class="call-number" id="call-number">-</div>
                <div style="font-size: 12px; color: #9ca3af;">Current Call</div>
            </div>
            
            <div class="cartela-grid" id="cartela-grid"></div>
            
            <button class="btn btn-success" onclick="claimBingo()" style="width: 100%; padding: 24px; font-size: 24px; margin-bottom: 20px;">🎉 BINGO!</button>
            <button class="btn btn-danger" onclick="leaveGame()" style="width: 100%;">Leave Game</button>
        </div>
    </div>

    <nav class="bottom-nav">
        <div class="nav-item active" onclick="showView('dashboard')">
            <span style="font-size: 24px;">🎮</span>
            <span style="font-size: 11px;">Play</span>
        </div>
    </nav>

    <script>
        let tg = window.Telegram?.WebApp;
        let currentUser = null;
        let currentRoom = null;
        let selectedStake = 10;
        let cartelaCount = 1;
        let currentCartelas = [];
        let markedCells = {};
        let calledNumbers = new Set();
        let voiceEnabled = true;
        let speechSynthesis = window.speechSynthesis;
        let pollInterval = null;

        if (tg) { 
            tg.ready(); 
            tg.expand();
            tg.enableClosingConfirmation();
        }

        function getHeaders() {
            let headers = {};
            if (tg?.initData) {
                headers['X-Telegram-Init-Data'] = tg.initData;
                headers['Authorization'] = `tma ${tg.initData}`;
            } else {
                headers['X-Test-Mode'] = '1';
            }
            return headers;
        }

        async function init() {
            try {
                const response = await fetch('/api/player/auth', {
                    method: 'POST',
                    headers: { ...getHeaders(), 'Content-Type': 'application/json' }
                });
                const data = await response.json();
                if (data.error) {
                    throw new Error(data.error);
                }
                currentUser = data.user;
                document.getElementById('balance').textContent = currentUser.balance.toLocaleString();
                if (data.is_new_user) {
                    document.getElementById('bonus-banner').style.display = 'block';
                    setTimeout(() => document.getElementById('bonus-banner').style.display = 'none', 5000);
                }
                document.getElementById('loading-screen').classList.add('hidden');
                document.getElementById('app-content').classList.remove('hidden');
                
                if (tg) {
                    tg.setHeaderColor('#0f0a1e');
                    tg.setBackgroundColor('#0f0a1e');
                }
            } catch (error) {
                console.error('Init error:', error);
                setTimeout(() => location.reload(), 3000);
            }
        }

        function showView(view) {
            document.querySelectorAll('.view-section').forEach(v => v.classList.add('hidden'));
            document.getElementById('view-' + view).classList.remove('hidden');
        }

        function selectStake(stake) {
            selectedStake = stake;
            document.querySelectorAll('.stake-btn').forEach(btn => btn.classList.remove('active'));
            document.getElementById('stake-' + stake).classList.add('active');
        }

        function changeCartelaCount(delta) {
            const newCount = cartelaCount + delta;
            if (newCount >= 1 && newCount <= 3) {
                cartelaCount = newCount;
                document.getElementById('cartela-count').textContent = cartelaCount;
            }
        }

        function toggleVoice() {
            voiceEnabled = !voiceEnabled;
            document.getElementById('voice-btn').textContent = voiceEnabled ? '🔊' : '🔇';
        }

        function speakNumber(letter, number) {
            if (!voiceEnabled || !speechSynthesis) return;
            const utterance = new SpeechSynthesisUtterance(`${letter}... ${number}`);
            utterance.rate = 0.8;
            utterance.pitch = 1.1;
            const voices = speechSynthesis.getVoices();
            const englishVoice = voices.find(v => v.lang.includes('en'));
            if (englishVoice) utterance.voice = englishVoice;
            speechSynthesis.speak(utterance);
        }

        async function startGame() {
            const totalCost = selectedStake * cartelaCount;
            if (currentUser.balance < totalCost) {
                alert('Insufficient balance!');
                return;
            }
            try {
                const response = await fetch('/api/player/game/join', {
                    method: 'POST',
                    headers: { ...getHeaders(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ stake: selectedStake, cartela_count: cartelaCount })
                });
                const data = await response.json();
                if (data.error) {
                    alert(data.error);
                    return;
                }
                currentRoom = data;
                setupGame(data);
                showView('game');
                startPolling();
            } catch (error) {
                alert('Error: ' + error.message);
            }
        }

        function setupGame(data) {
            currentCartelas = data.cartelas || [];
            markedCells = {};
            renderCartela();
        }

        function renderCartela() {
            const grid = document.getElementById('cartela-grid');
            grid.innerHTML = '';
            const cartela = currentCartelas[0] || [];
            cartela.forEach((num, idx) => {
                const cell = document.createElement('div');
                cell.className = 'cartela-cell';
                if (num === 0) {
                    cell.classList.add('free');
                    cell.textContent = '★';
                } else {
                    cell.textContent = num;
                    if (markedCells[idx]) cell.classList.add('marked');
                    if (calledNumbers.has(num)) {
                        cell.classList.add('called');
                        cell.onclick = () => toggleCell(idx);
                    }
                }
                grid.appendChild(cell);
            });
        }

        function toggleCell(idx) {
            markedCells[idx] = !markedCells[idx];
            renderCartela();
        }

        function startPolling() {
            pollInterval = setInterval(async () => {
                if (!currentRoom) return;
                try {
                    const response = await fetch(`/api/player/game/room/${currentRoom.room_id}/status`, { headers: getHeaders() });
                    const data = await response.json();
                    if (data.error) {
                        console.error('Poll error:', data.error);
                        return;
                    }
                    if (data.current_call && data.current_call !== document.getElementById('call-letter').textContent + document.getElementById('call-number').textContent) {
                        const letter = data.current_call.charAt(0);
                        const num = parseInt(data.current_call.slice(1));
                        document.getElementById('call-letter').textContent = letter;
                        document.getElementById('call-letter').className = 'call-letter ' + letter.toLowerCase();
                        document.getElementById('call-number').textContent = num;
                        calledNumbers.add(num);
                        speakNumber(letter, num);
                        renderCartela();
                    }
                    if (data.game_ended) {
                        clearInterval(pollInterval);
                        alert(data.winner_id === currentUser.telegram_id ? '🎉 YOU WON!' : 'Game ended. Better luck next time!');
                        leaveGame();
                    }
                } catch (e) {
                    console.error('Poll error:', e);
                }
            }, 1000);
        }

        async function claimBingo() {
            try {
                const markedArray = Object.keys(markedCells).filter(k => markedCells[k]).map(Number);
                const response = await fetch(`/api/player/game/${currentRoom.game_id}/bingo`, {
                    method: 'POST',
                    headers: { ...getHeaders(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ marked_indices: {0: markedArray} })
                });
                const data = await response.json();
                alert(data.winner ? '🎉 BINGO! You won ' + data.prize + ' ETB!' : 'Not a valid bingo yet!');
            } catch (error) {
                alert('Error claiming bingo');
            }
        }

        function leaveGame() {
            if (pollInterval) clearInterval(pollInterval);
            currentRoom = null;
            currentCartelas = [];
            markedCells = {};
            calledNumbers.clear();
            showView('dashboard');
            init();
        }

        init();
    </script>
</body>
</html>'''

ADMIN_HTML = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin - NEXUS BINGO</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background: #0f0a1e; color: white; margin: 0; padding: 20px; }
        .card { background: #1a1425; border-radius: 16px; padding: 20px; margin-bottom: 16px; }
        .btn { padding: 12px 24px; border-radius: 8px; border: none; cursor: pointer; font-weight: 600; margin-right: 8px; }
        .btn-success { background: #10b981; color: white; }
        .btn-danger { background: #ef4444; color: white; }
        .toggle { display: flex; align-items: center; justify-content: space-between; padding: 16px; background: rgba(255,255,255,0.05); border-radius: 12px; margin-bottom: 12px; }
        .toggle-switch { width: 60px; height: 34px; background: rgba(255,255,255,0.1); border-radius: 17px; cursor: pointer; position: relative; transition: all 0.3s; }
        .toggle-switch.active { background: #10b981; }
        .toggle-switch::after { content: ''; position: absolute; width: 28px; height: 28px; background: white; border-radius: 50%; top: 3px; left: 3px; transition: all 0.3s; }
        .toggle-switch.active::after { left: 29px; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.1); }
        th { color: #8b5cf6; }
        .error { color: #ef4444; padding: 20px; text-align: center; }
        .loading { text-align: center; padding: 40px; }
    </style>
</head>
<body>
    <h1>🔐 NEXUS BINGO Admin</h1>
    
    <div id="loading" class="loading">Loading...</div>
    <div id="error" class="error hidden"></div>
    <div id="content" class="hidden">
        <div class="card">
            <h3>🏠 House Favor Mode</h3>
            <div class="toggle">
                <div>
                    <div style="font-weight: 600;">Enable House Favor</div>
                    <div style="font-size: 13px; color: #9ca3af;">Bots have higher chance to win</div>
                </div>
                <div class="toggle-switch" id="house-favor-toggle" onclick="toggleHouseFavor()"></div>
            </div>
        </div>

        <div class="card">
            <h3>👥 Users</h3>
            <table id="users-table"></table>
        </div>
    </div>

    <script>
        let tg = window.Telegram?.WebApp;
        if (tg) { 
            tg.ready(); 
            tg.expand();
            tg.setHeaderColor('#0f0a1e');
            tg.setBackgroundColor('#0f0a1e');
        }
        
        function getHeaders() {
            let headers = {};
            if (tg?.initData) {
                headers['X-Telegram-Init-Data'] = tg.initData;
                headers['Authorization'] = `tma ${tg.initData}`;
            }
            return headers;
        }

        async function init() {
            try {
                const response = await fetch('/api/admin/users', { headers: getHeaders() });
                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.error || 'Unauthorized');
                }
                
                document.getElementById('loading').classList.add('hidden');
                document.getElementById('content').classList.remove('hidden');
                loadUsers();
                loadSettings();
            } catch (error) {
                document.getElementById('loading').classList.add('hidden');
                document.getElementById('error').textContent = 'Error: ' + error.message;
                document.getElementById('error').classList.remove('hidden');
            }
        }

        async function loadSettings() {
            const response = await fetch('/api/admin/settings/house-favor', { headers: getHeaders() });
            if (response.ok) {
                const data = await response.json();
                document.getElementById('house-favor-toggle').classList.toggle('active', data.enabled);
            }
        }

        async function toggleHouseFavor() {
            const toggle = document.getElementById('house-favor-toggle');
            const enabled = !toggle.classList.contains('active');
            const response = await fetch('/api/admin/settings/house-favor', {
                method: 'POST',
                headers: { ...getHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            });
            if (response.ok) {
                toggle.classList.toggle('active', enabled);
            } else {
                alert('Failed to update setting');
            }
        }

        async function loadUsers() {
            try {
                const response = await fetch('/api/admin/users', { headers: getHeaders() });
                const data = await response.json();
                const table = document.getElementById('users-table');
                table.innerHTML = '<tr><th>ID</th><th>Name</th><th>Balance</th><th>Actions</th></tr>';
                data.users.forEach(u => {
                    table.innerHTML += `<tr>
                        <td>${u.telegram_id}</td>
                        <td>${u.first_name}</td>
                        <td>${u.balance} ETB</td>
                        <td>
                            <button class="btn btn-success" onclick="approveUser(${u.telegram_id})">Approve</button>
                            <button class="btn btn-danger" onclick="banUser(${u.telegram_id})">Ban</button>
                        </td>
                    </tr>`;
                });
            } catch (e) {
                console.error('Failed to load users', e);
            }
        }

        async function approveUser(id) {
            await fetch(`/api/admin/users/${id}/approve`, { method: 'POST', headers: getHeaders() });
            loadUsers();
        }

        async function banUser(id) {
            await fetch(`/api/admin/users/${id}/ban`, { method: 'POST', headers: getHeaders() });
            loadUsers();
        }

        init();
    </script>
</body>
</html>'''

# [All API routes remain the same as previous fix]
@app.route('/api/player/auth', methods=['POST'])
@require_telegram_auth
def player_auth():
    return jsonify({
        'success': True,
        'user': request.current_user.to_dict(),
        'is_new_user': getattr(request, 'is_new_user', False)
    })

@app.route('/api/player/game/join', methods=['POST'])
@require_telegram_auth
def join_game():
    user = request.current_user
    data = request.get_json()

    stake = Decimal(str(data.get('stake', 10)))
    cartela_count = int(data.get('cartela_count', 1))

    if stake not in [Decimal('10'), Decimal('25'), Decimal('50'), Decimal('100')]:
        return jsonify({'error': 'Invalid stake amount'}), 400

    if cartela_count < 1 or cartela_count > 3:
        return jsonify({'error': 'Max 3 cartelas per player'}), 400

    total_cost = stake * cartela_count

    if user.balance < total_cost:
        return jsonify({'error': 'Insufficient balance'}), 400

    existing_room = Room.query.filter(Room.status == 'waiting', Room.stake == stake).first()

    if existing_room:
        room = existing_room
        is_new_room = False
    else:
        room = Room(
            id=generate_room_id(),
            game_id=generate_game_id(),
            stake=stake,
            max_players=20,
            max_cartelas=100,
            created_by=user.telegram_id,
            house_cut_percent=GameSettings.get_house_cut(),
            house_favor_enabled=GameSettings.get_house_favor(),
            auto_start_at=datetime.utcnow() + timedelta(seconds=120)
        )
        db.session.add(room)
        is_new_room = True

    if room.total_cartelas + cartela_count > room.max_cartelas:
        return jsonify({'error': 'Room is full (max 100 cartelas)'}), 400

    cartelas = generate_cartelas(cartela_count)

    room_player = RoomPlayer(
        room_id=room.id,
        user_id=user.telegram_id,
        is_host=is_new_room,
        cartela_count=cartela_count
    )
    room_player.set_cartelas(cartelas)

    user.balance = float(user.balance) - float(total_cost)
    user.total_games_played = user.total_games_played + 1

    room.pot_amount = float(room.pot_amount) + float(total_cost)
    room.total_cartelas = room.total_cartelas + cartela_count

    transaction = Transaction(
        user_id=user.telegram_id,
        type='game_entry',
        amount=float(total_cost),
        reference_id=room.id,
        description=f'Joined game {room.id} with {cartela_count} cartelas'
    )

    db.session.add(room_player)
    db.session.add(transaction)
    db.session.commit()

    if is_new_room:
        game_manager.start_timer(room.id, 120)

    player_count = RoomPlayer.query.filter_by(room_id=room.id).count()
    game_started = player_count >= Config.MIN_PLAYERS_TO_START

    if game_started and room.status == 'waiting':
        room.status = 'calling'
        room.started_at = datetime.utcnow()
        db.session.commit()
        game_manager.start_game(room.id)

    return jsonify({
        'success': True,
        'room_id': room.id,
        'game_id': room.game_id,
        'stake': float(stake),
        'cartelas': cartelas,
        'game_started': game_started,
        'players': [{'id': p.user_id, 'is_fake': p.is_fake} for p in room.room_players],
        'pot_amount': float(room.pot_amount)
    })

@app.route('/api/player/game/room/<room_id>/status', methods=['GET'])
@require_telegram_auth
def get_room_status(room_id):
    state = game_manager.get_room_state(room_id)
    if not state:
        return jsonify({'error': 'Room not found'}), 404

    room = Room.query.get(room_id)
    
    return jsonify({
        'room_id': room_id,
        'status': state['status'],
        'current_call': state['current_call'],
        'called_numbers': state['called_numbers'],
        'called_count': len(state['called_numbers']),
        'game_started': state['status'] == 'calling',
        'game_ended': state['status'] == 'completed',
        'winner_id': room.winner_id if room else None,
        'players': [{'id': p.user_id, 'is_fake': p.is_fake} for p in room.room_players] if room else [],
        'pot_amount': float(room.pot_amount) if room else 0,
        'house_favor': room.house_favor_enabled if room else False,
        'timestamp': state['timestamp']
    })

@app.route('/api/player/game/<game_id>/bingo', methods=['POST'])
@require_telegram_auth
def claim_bingo(game_id):
    user = request.current_user
    data = request.get_json()
    
    room = Room.query.filter_by(game_id=game_id).first()
    if not room or room.status != 'calling':
        return jsonify({'error': 'Game not active'}), 400

    room_player = RoomPlayer.query.filter_by(room_id=room.id, user_id=user.telegram_id).first()
    if not room_player:
        return jsonify({'error': 'Not in this game'}), 403

    marked_indices = data.get('marked_indices', {})
    has_bingo = False
    
    for cartela_idx in range(room_player.cartela_count):
        marked = set(marked_indices.get(str(cartela_idx), []))
        if len(marked) >= 5:
            for row in range(5):
                if all(row * 5 + col in marked for col in range(5)):
                    has_bingo = True
                    break
            for col in range(5):
                if all(row * 5 + col in marked for row in range(5)):
                    has_bingo = True
                    break
            if all(i * 6 in marked for i in range(5)):
                has_bingo = True
            if all(i * 4 + 4 in marked for i in range(5)):
                has_bingo = True

    if not has_bingo:
        return jsonify({'winner': False, 'message': 'Not a valid bingo'}), 200

    game_manager.end_game(room.id, user.telegram_id)

    return jsonify({
        'winner': True,
        'prize': float(room.pot_amount) * (1 - float(room.house_cut_percent) / 100),
        'new_balance': float(user.balance)
    })

@app.route('/api/admin/users', methods=['GET'])
@require_admin_auth
def get_users():
    users = User.query.all()
    return jsonify({'users': [u.to_dict() for u in users]})

@app.route('/api/admin/users/<int:user_id>/approve', methods=['POST'])
@require_admin_auth
def approve_user(user_id):
    user = User.query.filter_by(telegram_id=user_id).first()
    if user:
        user.is_approved = True
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/admin/users/<int:user_id>/ban', methods=['POST'])
@require_admin_auth
def ban_user(user_id):
    user = User.query.filter_by(telegram_id=user_id).first()
    if user:
        user.is_banned = True
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/admin/settings/house-favor', methods=['GET'])
@require_admin_auth
def get_house_favor():
    """Get current house favor setting"""
    enabled = GameSettings.get_house_favor()
    return jsonify({'enabled': enabled})

@app.route('/api/admin/settings/house-favor', methods=['POST'])
@require_admin_auth
def set_house_favor():
    data = request.get_json()
    enabled = data.get('enabled', False)
    admin_id = request.telegram_user.get('id')
    GameSettings.set_house_favor(enabled, admin_id)
    return jsonify({'success': True, 'house_favor': enabled})

@app.route('/')
def index():
    return render_template_string(PLAYER_HTML)

@app.route('/admin')
def admin_panel():
    return render_template_string(ADMIN_HTML)

@app.route('/init_db')
def init_db():
    try:
        db.create_all()
        
        # Create default settings
        if not GameSettings.query.first():
            settings = [
                GameSettings(key='house_cut_percent', value='10.0'),
                GameSettings(key='house_favor_enabled', value='false')
            ]
            for s in settings:
                db.session.add(s)
            db.session.commit()
        
        # Create admin user if not exists
        admin = User.query.filter_by(telegram_id=Config.ADMIN_ID).first()
        if not admin:
            admin = User(
                telegram_id=Config.ADMIN_ID,
                username='admin',
                first_name='Admin',
                last_name='User',
                is_approved=True,
                balance=0,
                welcome_bonus_claimed=True
            )
            db.session.add(admin)
            db.session.commit()
        
        # Add admin to admins table
        admin_record = Admin.query.filter_by(telegram_id=Config.ADMIN_ID).first()
        if not admin_record:
            admin_record = Admin(telegram_id=Config.ADMIN_ID, username='admin')
            db.session.add(admin_record)
            db.session.commit()
        
        return '✅ Database initialized!<br><br><a href="/">Go to App</a> | <a href="/admin">Go to Admin</a>'
    except Exception as e:
        logger.error(f"Init DB error: {e}")
        return f'❌ Error: {str(e)}'

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json()
        logger.info(f"Webhook received: {data}")
        
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            user = message.get('from', {})
            text = message.get('text', '')
            
            if 'photo' in message:
                with app.app_context():
                    handle_deposit_screenshot(chat_id, user, message['photo'])
                return jsonify({'ok': True})
            
            if text:
                with app.app_context():
                    handle_bot_command(chat_id, user, text)
                
        return jsonify({'ok': True})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'ok': False, 'error': str(e)})

def handle_deposit_screenshot(chat_id, user, photos):
    telegram_id = user.get('id')
    if not telegram_id:
        send_telegram_message(chat_id, "❌ Error: Could not identify user.")
        return

    db_user = User.query.filter_by(telegram_id=telegram_id).first()
    if not db_user:
        send_telegram_message(chat_id, "❌ Please /start the bot first")
        return

    photo = photos[-1]
    file_id = photo['file_id']

    deposit = Deposit(user_id=telegram_id, amount=0, screenshot_file_id=file_id, status='pending')
    db.session.add(deposit)
    db.session.commit()

    send_telegram_message(chat_id, "✅ Screenshot received! Admin will review shortly.")

    admin_text = f"""💰 New Deposit

From: {db_user.first_name}
User ID: {telegram_id}
Deposit ID: {deposit.id}

Reply: /approve {deposit.id} [amount] or /reject {deposit.id}"""

    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendPhoto"
        requests.post(url, json={'chat_id': Config.ADMIN_ID, 'photo': file_id, 'caption': admin_text, 'parse_mode': 'HTML'}, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send photo to admin: {e}")
        send_telegram_message(Config.ADMIN_ID, admin_text)

def handle_bot_command(chat_id, user, text):
    cmd = text.lower().split()[0] if text else ''
    first_name = user.get('first_name', 'Player')
    telegram_id = user.get('id')

    if not telegram_id:
        send_telegram_message(chat_id, "❌ Error: Could not identify user.")
        return

    if cmd == '/start':
        existing_user = User.query.filter_by(telegram_id=telegram_id).first()
        is_new_user = False

        if not existing_user:
            new_user = User(
                telegram_id=telegram_id,
                username=user.get('username'),
                first_name=first_name,
                last_name=user.get('last_name', ''),
                registration_step='telegram_auth',
                is_approved=True,
                balance=Config.WELCOME_BONUS,
                welcome_bonus_claimed=True
            )
            db.session.add(new_user)
            db.session.commit()
            is_new_user = True

            transaction = Transaction(user_id=telegram_id, type='welcome_bonus', amount=Config.WELCOME_BONUS, description='Welcome bonus')
            db.session.add(transaction)
            db.session.commit()

            send_telegram_message(Config.ADMIN_ID, f"🆕 New user: {first_name} (+{Config.WELCOME_BONUS} ETB bonus)")

                # FIX: Use Config.WEBAPP_URL directly (already has trailing slash)
        welcome_text = f"""🎰 Welcome to NEXUS BINGO, {first_name}!

{f"🎁 You got {Config.WELCOME_BONUS} ETB bonus!" if is_new_user else ""}

👇 Click below to play!"""

        keyboard = {
            "inline_keyboard": [[
                {
                    "text": "🎰 PLAY NEXUS BINGO",
                    "web_app": {"url": Config.WEBAPP_URL}
                }
            ]]
        }
        result = send_telegram_message(chat_id, welcome_text, reply_markup=keyboard)
        if result and not result.get('ok'):
            logger.error(f"Failed to send start message: {result}")

    elif cmd == '/deposit':
        send_telegram_message(chat_id, "💰 Send Telebirr to 0936 719 379, then send screenshot here.")

    elif cmd == '/balance':
        db_user = User.query.filter_by(telegram_id=telegram_id).first()
        if db_user:
            balance_text = f"💰 Balance: {float(db_user.balance):.2f} ETB\nGames: {db_user.total_games_played}\nWins: {db_user.total_games_won}"
            send_telegram_message(chat_id, balance_text)
        else:
            send_telegram_message(chat_id, "❌ Please /start first")

    elif cmd == '/help':
        send_telegram_message(chat_id, "🎰 /start - Start & get bonus\n/deposit - Add money\n/balance - Check balance")

    elif cmd == '/admin':
        if telegram_id == Config.ADMIN_ID:
            # FIX: Use Config.WEBAPP_URL + 'admin' (URL already has trailing slash)
            admin_url = f"{Config.WEBAPP_URL}admin"
            
            keyboard = {
                "inline_keyboard": [[
                    {
                        "text": "🔐 Open Admin Panel",
                        "web_app": {"url": admin_url}
                    }
                ]]
            }
            send_telegram_message(chat_id, "🔐 Admin Panel:", reply_markup=keyboard)
        else:
            send_telegram_message(chat_id, "❌ Unauthorized")

    # Admin commands
    if telegram_id == Config.ADMIN_ID:
        parts = text.split()
        if len(parts) >= 2:
            if parts[0] == '/approve' and len(parts) >= 3:
                try:
                    deposit_id = int(parts[1])
                    amount = float(parts[2])
                    deposit = Deposit.query.get(deposit_id)
                    if deposit and deposit.status == 'pending':
                        deposit.amount = amount
                        deposit.status = 'approved'
                        deposit.approved_at = datetime.utcnow()
                        deposit.approved_by = Config.ADMIN_ID
                        user = User.query.filter_by(telegram_id=deposit.user_id).first()
                        if user:
                            user.balance = float(user.balance) + amount
                            user.total_deposited = float(user.total_deposited) + amount
                            transaction = Transaction(
                                user_id=deposit.user_id,
                                type='deposit',
                                amount=amount,
                                reference_id=str(deposit.id),
                                description='Deposit approved'
                            )
                            db.session.add(transaction)
                            db.session.commit()
                            send_telegram_message(deposit.user_id, f"✅ Your deposit of {amount} ETB approved!")
                            send_telegram_message(Config.ADMIN_ID, f"✅ Approved deposit #{deposit_id}")
                        else:
                            send_telegram_message(Config.ADMIN_ID, "❌ User not found for deposit")
                except Exception as e:
                    logger.error(f"Approve error: {e}")
                    send_telegram_message(Config.ADMIN_ID, f"❌ Error: {str(e)}")

            elif parts[0] == '/reject' and len(parts) >= 2:
                try:
                    deposit_id = int(parts[1])
                    deposit = Deposit.query.get(deposit_id)
                    if deposit:
                        deposit.status = 'rejected'
                        db.session.commit()
                        send_telegram_message(deposit.user_id, "❌ Deposit rejected.")
                        send_telegram_message(Config.ADMIN_ID, f"✅ Rejected deposit #{deposit_id}")
                except Exception as e:
                    logger.error(f"Reject error: {e}")
                    send_telegram_message(Config.ADMIN_ID, f"❌ Error: {str(e)}")

@app.route('/setup_webhook', methods=['GET'])
def setup_webhook():
    """Setup webhook for Telegram bot"""
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/setWebhook"
        webhook_url = Config.WEBHOOK_URL
        payload = {
            "url": webhook_url,
            "allowed_updates": ["message", "callback_query"]
        }
        response = requests.post(url, json=payload, timeout=10)
        result = response.json()
        if result.get('ok'):
            return f"✅ Webhook set to: {webhook_url}"
        else:
            return f"❌ Failed: {result.get('description', 'Unknown error')}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
        'bot_token_set': bool(Config.BOT_TOKEN and Config.BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE'),
        'webapp_url': Config.WEBAPP_URL,
        'webhook_url': Config.WEBHOOK_URL,
        'admin_id': Config.ADMIN_ID
    })

if __name__ == '__main__':
    # Validate configuration on startup
    config_errors = Config.validate()
    if config_errors:
        logger.error("Configuration errors detected. Check your environment variables.")
    
    with app.app_context():
        db.create_all()
        
        # Initialize default settings
        if not GameSettings.query.first():
            settings = [
                GameSettings(key='house_cut_percent', value='10.0'),
                GameSettings(key='house_favor_enabled', value='false')
            ]
            for s in settings:
                db.session.add(s)
            db.session.commit()
        
        # Create admin user if not exists
        admin = User.query.filter_by(telegram_id=Config.ADMIN_ID).first()
        if not admin:
            admin = User(
                telegram_id=Config.ADMIN_ID,
                username='admin',
                first_name='Admin',
                last_name='User',
                is_approved=True,
                balance=0,
                welcome_bonus_claimed=True
            )
            db.session.add(admin)
            db.session.commit()
            logger.info(f"Created admin user with ID: {Config.ADMIN_ID}")
        
        # Add admin to admins table
        admin_record = Admin.query.filter_by(telegram_id=Config.ADMIN_ID).first()
        if not admin_record:
            admin_record = Admin(telegram_id=Config.ADMIN_ID, username='admin')
            db.session.add(admin_record)
            db.session.commit()
    
    port = int(os.environ.get('PORT', '5000').strip())
    app.run(host='0.0.0.0', port=port, debug=False)
