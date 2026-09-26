#!/usr/bin/env python3
from flask import Blueprint, render_template, request, redirect, flash, send_file, url_for, current_app, abort
from flask_login import current_user, login_required
import logging
from .typst_util import get_translation
from pathlib import Path
import translate as translator
import os
import subprocess
from . import db
from .models import Translation
import uuid
import base64
import tarfile
import shutil
from werkzeug.utils import secure_filename
from .safe_archive import UnsafeArchiveError, extract_archive
from .typst_runner import TypstSandboxError, compile_typst
from .user_storage import ensure_user_directory

main = Blueprint('main', __name__)

ALLOWED_EXTENSIONS = {'typ', 'tar'}
DATA_PATH = os.getenv("DATA_PATH")
LANGS = [
"Dravuun",
"Irixo7",
"Mnemosh",
"Vael’kora",
"Xyrrathi",
]
# ===== UTIL =====
def get_extension(filename: str) -> str:
    return filename.rsplit('.', 1)[1].lower()

def extension_allowed(filename: str) -> bool:
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ===== libparser.so capacity =====
# libparser.so keeps every word in a fixed heap chunk
#     struct word { char text[WORD_TEXT_CAP]; struct word *next; unsigned char len; }
# and its translation pass rewrites that string *in place*, emitting one extra
# 'r' for every 'r' it contains (0x341a).  A word of n characters holding k 'r's
# therefore becomes n + k bytes, while the scanner only rejects words longer than
# MAX_WORDSIZE characters -- so n + k reaches 128 and writes 48 bytes past the
# chunk's usable area: word->next is replaced with attacker data (the next pass
# dereferences it and the gunicorn worker dies with SIGSEGV) and the following
# chunk's header is corrupted as well.  Refuse anything that does not still fit
# in text[].
WORD_TEXT_CAP = 0x48               # char text[WORD_TEXT_CAP] in struct word
MAX_WORDSIZE = 0x3f                # longest word the scanner accepts
MAX_SENTENCE_WORDS = 0xff          # sentence->count is a single byte

# The flex LETTER class of libparser.so, mirrored so the word splitting below
# matches what the parser will actually accept.
_TRANSLATE_SEPARATORS = b" \t\r\n\v\f"
_TRANSLATE_TERMINATORS = b"!?.\x00"


def check_translatable(raw: bytes):
    """Reject a /translate_text payload that would overflow libparser.so.

    Mirrors the accepted grammar (LETTER+ words separated by separator +
    whitespace, sentence closed by a terminator) and applies the bound the
    in-place 'r' expansion needs.  Returns None when the payload is safe.
    """
    if not raw or len(raw) > 64 * 1024:
        return "input too large"
    words = length = rs = 0
    in_word = False
    for byte in raw:
        if byte in _TRANSLATE_SEPARATORS or byte in _TRANSLATE_TERMINATORS:
            if in_word:
                if length + rs > WORD_TEXT_CAP - 1:
                    return "word grows past the parser buffer"
                words += 1
                if words > MAX_SENTENCE_WORDS:
                    return "too many words in one sentence"
                in_word = False
            continue
        if not in_word:
            in_word, length, rs = True, 0, 0
        length += 1
        rs += (byte == ord("r"))
        if length > MAX_WORDSIZE:
            return "word longer than the parser accepts"
    if in_word and length + rs > WORD_TEXT_CAP - 1:
        return "word grows past the parser buffer"
    return None


# ===== GET REQUESTS =====
@main.route('/')
def index():
    return render_template('index.html')

@main.route('/download_file/<project>')
@login_required
def download_file(project):
    try:
        user_path = ensure_user_directory(DATA_PATH, current_user.id)
    except (OSError, ValueError):
        abort(404)
    projects = os.listdir(user_path)
    if project not in projects:
        flash("Project does not exist")
        return redirect(url_for("main.index"))
    project_path = user_path / project
    if project_path.is_symlink() or not project_path.resolve().is_relative_to(user_path):
        abort(404)
    pdf_path = project_path / f"{project}.pdf"
    if pdf_path.is_symlink() or not pdf_path.is_file():
        abort(404)
    return send_file(pdf_path)

@main.route('/list_files')
@login_required
def list_files():
    try:
        user_path = ensure_user_directory(DATA_PATH, current_user.id)
    except (OSError, ValueError):
        abort(404)
    projects = os.listdir(user_path)
    return render_template("list_files.html", projects=projects)

@main.route('/convert_file')
@login_required
def convert_view():
    return render_template("convert_file.html", langs=LANGS)

@main.route('/translate_text')
def translate_text_view():
    return render_template("translate_text.html")

@main.route('/profile')
@login_required
def profile():
    return render_template("profile.html")

@main.route('/translation_history')
@login_required
def get_translations():
    return render_template("translation_history.html", translations=current_user.translations)

# ===== POST REQUESTS =====
class Project:
    def __init__(self, project_name, project_path, pdf_path):
        self.project_name = project_name
        self.project_path = project_path
        self.pdf_path = pdf_path

    def set_typ_path(self, typ_path):
        self.typ_path = typ_path

def convert_typ_file(file, project, language):
    filecontent = file.stream.read().decode("utf-8")
    typ_path = project.project_path / f"{project.project_name}.typ"
    with open(typ_path, "w") as f:
        f.write(get_translation(language))
        f.write("\n")
        f.write(filecontent)
    project.set_typ_path(typ_path)

def convert_tar_file(file, project, language):
    try:
        typ_path = extract_archive(file.stream, project.project_path)
        filecontent = typ_path.read_text(encoding="utf-8")
    except (tarfile.TarError, OSError, UnicodeError, UnsafeArchiveError) as error:
        raise UnsafeArchiveError("invalid or unsafe tar archive") from error

    with open(typ_path, "w") as f:
        f.write(get_translation(language))
        f.write("\n")
        f.write(filecontent)
    project.set_typ_path(typ_path)

@main.route('/convert_file', methods=['POST'])
@login_required
def convert_file():
    if 'file' not in request.files or 'lang' not in request.form:
        flash("No file or target language provided")
        return redirect(request.url)
    file = request.files['file']
    language = request.form['lang']
    if language not in LANGS:
        flash("Language not supported")
        return redirect(request.url)
    if not file.filename:
        flash("Invalid filetype")
        return redirect(request.url)
    safe_filename = secure_filename(file.filename)
    if not extension_allowed(safe_filename):
        flash("Invalid filetype")
        return redirect(request.url)
    project_name = safe_filename.split(".", maxsplit=1)[0]
    if not project_name:
        flash("Invalid filename")
        return redirect(request.url)
    try:
        user_path = ensure_user_directory(DATA_PATH, current_user.id)
    except (OSError, ValueError) as error:
        current_app.logger.warning("cannot access user project directory: %s", error)
        flash("Document translation failed. Try again.")
        return redirect(request.url)
    project_path = user_path / project_name
    if project_path.exists():
        flash("Project with this name already exists")
        return redirect(request.url)
    try:
        project_path.mkdir(mode=0o700)
    except FileExistsError:
        flash("Project with this name already exists")
        return redirect(request.url)
    pdf_path = project_path / f"{project_name}.pdf"
    project = Project(project_name, project_path, pdf_path)

    try:
        if get_extension(safe_filename) == "typ":
            convert_typ_file(file, project, language)
        else:
            convert_tar_file(file, project, language)
        result = compile_typst(
            project.project_path,
            project.typ_path,
            project.pdf_path,
            "/app/src/static/fonts",
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(project_path, ignore_errors=True)
        flash("Document translation failed. Try again.")
        return redirect(request.url)
    except (UnsafeArchiveError, TypstSandboxError, OSError, UnicodeError,
            tarfile.TarError, subprocess.SubprocessError) as error:
        current_app.logger.warning("Document processing rejected: %s", error)
        shutil.rmtree(project_path, ignore_errors=True)
        flash("Document translation failed. Try again.")
        return redirect(request.url)

    if result.returncode != 0:
        current_app.logger.error("Typst compilation failed: %s", result.stderr.decode("utf-8", "replace"))
        shutil.rmtree(project_path, ignore_errors=True)
        flash("Document translation failed. Try again.")
        return redirect(request.url)

    return send_file(pdf_path)


@main.route('/translate_text', methods=['POST'])
def translate_text():
    text = request.form.get("to_translate")
    try:
        raw = base64.b64decode(text.rstrip(), validate=False)
    except Exception:
        return base64.b64encode(b"Sorry, we were unable to translate your text!")
    problem = check_translatable(raw)
    if problem:
        logging.warning("rejected /translate_text payload: %s", problem)
        return base64.b64encode(b"Sorry, we were unable to translate your text!")
    translated = translator.translate(text.rstrip())
    if translated == "Translation failed!":
        return base64.b64encode("Sorry, we were unable to translate your text!".encode())
    if current_user.is_authenticated:
        t = Translation(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                source_text=base64.b64decode(text).decode("utf-8", "ignore"),
                translated_text=base64.b64decode(translated).decode("utf-8", "ignore"))
        db.session.add(t)
        db.session.commit()

    return translated

@main.route('/contact_form', methods=['POST'])
def contact_form():
    flash("Thank you for your feeback!")
    return redirect(url_for('main.index'))
