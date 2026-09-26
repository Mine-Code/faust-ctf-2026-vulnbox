from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import secrets
import os
from pathlib import Path

db = SQLAlchemy()
SECRET_FILE_PATH = Path("/app/.flask_secret/")


def create_app():
    app = Flask(__name__)

    if len(os.listdir(SECRET_FILE_PATH)) == 0:
        secret = secrets.token_hex(32)
        app.config['SECRET_KEY'] = secret
        secret_file = SECRET_FILE_PATH.joinpath(secret)
        secret_file.touch()
    else:
        app.config['SECRET_KEY'] = os.listdir(SECRET_FILE_PATH)[0]
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DB_URL")
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True}
    app.config['MAX_CONTENT_LENGTH'] = 4 * 1000 * 1000


    db.init_app(app)
    from . import models
    with app.app_context():
        db.create_all()
        db.engine.dispose()

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    from .models import User


    @login_manager.user_loader
    def load_user(agent_id):
        return User.query.get(agent_id)


    from .auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)
    from .main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    return app
