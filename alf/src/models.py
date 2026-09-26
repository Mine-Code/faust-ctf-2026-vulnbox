#!/usr/bin/env python3
from . import db
from flask_login import UserMixin
import datetime


class User(UserMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(103))
    creation_date = db.Column(db.TIMESTAMP, default=datetime.datetime.now)
    translations = db.relationship("Translation", backref="user", cascade="all, delete-orphan")


class Translation(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36),
                        db.ForeignKey("user.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    source_text = db.Column(db.Text, nullable=False)
    translated_text = db.Column(db.Text, nullable=False)
