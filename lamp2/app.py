import os
import re
import secrets
from pathlib import Path

import pymysql
import redis
from flask import Flask, g, redirect, render_template, request


ROOT = Path(__file__).resolve().parent
STORAGE_PATH = Path(os.environ.get("STORAGE_PATH", "/storage"))
SESSION_TIMEOUT = 1200
USER_TIMEOUT = 2700

app = Flask(__name__, static_folder=str(ROOT / "srv" / "www"), static_url_path="")
redis_client = redis.Redis(
    host=os.environ.get("REDIS_HOST", "redis"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    decode_responses=True,
)


def connect_db(user="nonprivileged", password="nonprivileged"):
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "mariadb"),
        user=user,
        password=password,
        database=os.environ.get("DB_NAME", "lamp"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def execute(sql, parameters=()):
    connection = connect_db()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            return cursor.rowcount
    finally:
        connection.close()


def fetch_one(sql, parameters=()):
    connection = connect_db()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            return cursor.fetchone()
    finally:
        connection.close()


def fetch_all(sql, parameters=()):
    connection = connect_db()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, parameters)
            return cursor.fetchall()
    finally:
        connection.close()


def create_session():
    session_id = secrets.token_hex(16)
    redis_client.setex(f"session_active_{session_id}", SESSION_TIMEOUT, "1")
    g.session_id = session_id
    g.username = None
    g.issue_session_cookie = True


@app.before_request
def load_session():
    if request.endpoint == "static":
        return

    session_id = request.cookies.get("Session")
    if session_id and redis_client.get(f"session_active_{session_id}"):
        g.session_id = session_id
        g.username = redis_client.get(f"session_user_{session_id}")
        g.issue_session_cookie = False
        return

    create_session()


@app.after_request
def set_session_cookie(response):
    if getattr(g, "issue_session_cookie", False):
        response.set_cookie("Session", g.session_id, path="/")
    return response


def tick_ship(ship_id):
    execute(
        """UPDATE components AS c
           LEFT JOIN (
               SELECT wire.dst AS id, MAX(source.state) AS any_on
               FROM connections AS wire
               JOIN components AS source ON source.id = wire.src
               WHERE source.ship = %s
               GROUP BY wire.dst
           ) AS aggregate_state ON aggregate_state.id = c.id
           SET c.state = CASE c.type
               WHEN 'light' THEN COALESCE(aggregate_state.any_on, 0)
               WHEN 'button' THEN IF(
                   c.properties = 'on' AND COALESCE(aggregate_state.any_on, 0) = 1,
                   1, 0
               )
               ELSE c.state
           END
           WHERE c.ship = %s AND c.type <> 'source'""",
        (ship_id, ship_id),
    )


def perform_action(username):
    action = request.form.get("action")
    ship = fetch_one("SELECT id FROM ships WHERE username = %s", (username,))
    if ship is None:
        return
    ship_id = ship["id"]

    if action == "add":
        execute("UPDATE ships SET numComponents = numComponents + 1 WHERE id = %s", (ship_id,))
        count = fetch_one("SELECT numComponents FROM ships WHERE id = %s", (ship_id,))["numComponents"]
        if count < 50:
            component_type = request.form.get("typ")
            execute(
                """INSERT INTO components (x, y, type, state, ship)
                   VALUES (%s, %s, %s, IF(%s = 'source', 1, 0), %s)""",
                (
                    request.form.get("x"),
                    request.form.get("y"),
                    component_type,
                    component_type,
                    ship_id,
                ),
            )
    elif action == "connect":
        execute(
            """INSERT INTO connections (src, dst)
               SELECT %s, %s
               FROM components AS source
               JOIN components AS destination
                 ON destination.id = %s AND destination.ship = %s
               WHERE source.id = %s AND source.ship = %s""",
            (
                request.form.get("left"),
                request.form.get("right"),
                request.form.get("right"),
                ship_id,
                request.form.get("left"),
                ship_id,
            ),
        )
    elif action == "toggle":
        execute(
            """UPDATE components
               SET properties = IF(properties = 'on', 'off', 'on')
               WHERE id = %s AND type = 'button' AND ship = %s""",
            (request.form.get("id"), ship_id),
        )
        tick_ship(ship_id)
        tick_ship(ship_id)
    elif action == "tick":
        tick_ship(ship_id)


@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        if g.username:
            perform_action(g.username)
        return redirect("/", code=302)

    ship = None
    components = []
    connections = []
    if g.username:
        ship = fetch_one(
            "SELECT id, numComponents FROM ships WHERE username = %s", (g.username,)
        )
        if ship:
            components = fetch_all(
                """SELECT id, x, y, type, state, properties
                   FROM components WHERE ship = %s""",
                (ship["id"],),
            )
            connections = fetch_all(
                """SELECT source.x AS x1, source.y AS y1,
                          destination.x AS x2, destination.y AS y2,
                          source.state
                   FROM connections
                   JOIN components AS source ON source.id = connections.src
                   JOIN components AS destination ON destination.id = connections.dst
                   WHERE source.ship = %s AND destination.ship = %s""",
                (ship["id"], ship["id"]),
            )
    ship_name = None
    if g.username:
        ship_file = STORAGE_PATH / f"{g.username}.tex"
        if ship_file.is_file():
            ship_name = ship_file.read_text(encoding="utf-8")
    return render_template(
        "home.html",
        username=g.username,
        ship=ship,
        ship_name=ship_name,
        components=components,
        connections=connections,
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    errors = []
    success = False
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if not username:
            errors.append("No username given")
        if not password:
            errors.append("No password given")
        if username and password and redis_client.get(f"user_{username}") == password:
            redis_client.setex(
                f"session_user_{g.session_id}", SESSION_TIMEOUT, username
            )
            g.username = username
            success = True
        elif username and password:
            errors.append("Failed to log in")
    return render_template("login.html", errors=errors, success=success, username=g.username)


@app.route("/register", methods=["GET", "POST"])
def register():
    errors = []
    success = False
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        ship_name = request.form.get("shipname", "")
        if not username:
            errors.append("No username given")
        elif not re.fullmatch(r"[A-Za-z0-9]+", username):
            errors.append("Username must be alphanumeric")
        if not password:
            errors.append("No password given")
        if not ship_name:
            errors.append("No ship name given")
        elif not re.fullmatch(r"[A-Za-z0-9]+", ship_name):
            errors.append("Ship name must be alphanumeric")
        elif len(ship_name) > 64:
            errors.append("Ship name must not exceed 64 characters")
        if not errors and redis_client.get(f"user_{username}") is not None:
            errors.append("Account already exists")
        if not errors:
            redis_client.setex(f"user_{username}", USER_TIMEOUT, password)
            redis_client.setex(f"session_user_{g.session_id}", SESSION_TIMEOUT, username)
            g.username = username
            execute("INSERT INTO ships (username) VALUES (%s)", (username,))
            STORAGE_PATH.mkdir(parents=True, exist_ok=True)
            (STORAGE_PATH / f"{username}.tex").write_text(ship_name, encoding="utf-8")
            success = True
    return render_template("register.html", errors=errors, success=success, username=g.username)


@app.route("/logout")
def logout():
    create_session()
    return redirect("/", code=302)


if __name__ == "__main__":
    app.run(host="::", port=1337)