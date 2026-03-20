# init_db.py
import os
import sys

# Add your project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(file)))

# Import your app and db
from app import app, db

with app.app_context():
    db.create_all()
    print("✅ Database tables created successfully!")
