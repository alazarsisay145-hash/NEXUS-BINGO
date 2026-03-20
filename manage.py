# manage.py
from flask_migrate import Migrate
from app import app, db
import os
import sys

# Add project to path (for imports)
sys.path.insert(0, os.path.dirname(os.path.abspath(file)))

# ⚠️ CRITICAL: Import your models so SQLAlchemy knows about them
# Change 'models' to wherever your User model is defined
try:
    from models import User
    print("✅ User model imported")
except ImportError:
    try:
        from app import User
        print("✅ User model imported from app")
    except ImportError:
        print("❌ Could not import User model - check where it's defined")

migrate = Migrate(app, db)

if name == 'main':  # ✅ Fixed syntax here
    with app.app_context():
        # Initialize migrations if not exists
        if not os.path.exists('migrations'):
            print("📁 Initializing migrations...")
            os.system('flask db init')
        
        print("🔄 Creating migration...")
        os.system('flask db migrate -m "auto"')
        
        print("⬆️ Upgrading database...")
        os.system('flask db upgrade')
        
        # Verify tables were created
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"📋 Tables in database: {tables}")
        
        if 'users' in tables:
            print("✅ SUCCESS: users table exists!")
        else:
            print("❌ ERROR: users table not found")
            print("Make sure User model is imported in manage.py")
