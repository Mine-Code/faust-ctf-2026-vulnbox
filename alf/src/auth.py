#!/usr/bin/env python3
from flask import Blueprint, redirect, url_for, render_template, request, flash
from flask_login import login_user, login_required, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from . import db
from .models import User
from pathlib import Path
import uuid
import os

auth = Blueprint('auth', __name__)
DATA_PATH = os.getenv("DATA_PATH")

@auth.get('/login')
def login():
    return render_template('login.html')

@auth.post('/login')
def login_post():
    username = request.form.get('username')
    password = request.form.get('password')
    if not username or not password:
        flash('Try again.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(username=username).first()

    if not user or not check_password_hash(user.password, password):
        flash('Try again.', 'danger')
        return redirect(url_for('auth.login'))

    login_user(user)
    flash("Login successful")
    return redirect(url_for('main.index'))

@auth.get('/register')
def register():
    return render_template('register.html')

@auth.post('/register')
def register_post():
    username = request.form.get('username')
    password = request.form.get('password')
    if not username or not password:
        flash('Try again.', 'danger')
        return redirect(url_for('auth.register'))

    user = User.query.filter_by(username=username).first()

    if user:
        return redirect(url_for('auth.register'))

    uid = str(uuid.uuid4())
    new_user = User(id=uid, username=username, password=generate_password_hash(password, method='pbkdf2:sha256:1'))
    Path(DATA_PATH).joinpath(uid).mkdir()

    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)

    flash('Registration successful', 'info')
    return redirect(url_for('main.index'))

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.index'))
