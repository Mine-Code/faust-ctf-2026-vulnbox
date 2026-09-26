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

    data_path = Path(os.environ["DATA_PATH"])
    data_path.mkdir(parents=True, exist_ok=True)
    if data_path.is_symlink():
        raise RuntimeError("DATA_PATH must not be a symlink")
    data_path.chmod(0o700)

    SECRET_FILE_PATH.mkdir(mode=0o700, parents=True, exist_ok=True)
    if SECRET_FILE_PATH.is_symlink():
        raise RuntimeError("Flask secret directory must not be a symlink")
    SECRET_FILE_PATH.chmod(0o700)
    secret_files = [
        entry.name for entry in os.scandir(SECRET_FILE_PATH)
        if entry.is_file(follow_symlinks=False)
        and len(entry.name) == 64
        and all(char in "0123456789abcdef" for char in entry.name)
    ]
    if secret_files:
        app.config['SECRET_KEY'] = sorted(secret_files)[0]
    else:
        while True:
            secret = secrets.token_hex(32)
            secret_file = SECRET_FILE_PATH / secret
            try:
                fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            except FileExistsError:
                continue
            os.close(fd)
            app.config['SECRET_KEY'] = secret
            break
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
