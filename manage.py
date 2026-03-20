# manage.py
from flask_migrate import Migrate
from app import app, db
import os

migrate = Migrate(app, db)

if name == 'main':
    with app.app_context():
        if not os.path.exists('migrations'):
            os.system('flask db init')
        os.system('flask db migrate -m "initial"')
        os.system('flask db upgrade')
