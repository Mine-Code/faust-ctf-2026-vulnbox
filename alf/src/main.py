#!/usr/bin/env python3
from flask import Blueprint, render_template, request, redirect, flash, send_file, url_for, abort, current_app
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
import resource
import tarfile
import shutil

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

def set_file_limit():
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1000 * 1000, 4 * 1000 * 1000))

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

# ===== tar extraction limits =====
# RLIMIT_FSIZE only caps the size of *one* extracted file and MAX_CONTENT_LENGTH
# only caps the upload, so an archive with very many small members inflates
# without bound: a 2.9 MB upload was measured at 10.8 MB of files and 2000
# inodes per request, i.e. ~57 MB/s of quiet disk fill.
TAR_MAX_MEMBERS = 512
TAR_MAX_TOTAL_BYTES = 32 * 1000 * 1000

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


def check_tar(stream):
    """Reject an archive whose extraction would exceed our disk budget.

    Runs on the upload stream *before* anything is written, so a refused bomb
    costs no disk at all.
    """
    members = 0
    total = 0
    try:
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:*") as tf:
            for info in tf:
                members += 1
                if members > TAR_MAX_MEMBERS:
                    return "too many archive members"
                total += max(info.size, 0)
                if total > TAR_MAX_TOTAL_BYTES:
                    return "archive expands beyond the allowed size"
    except tarfile.TarError:
        return "not a readable archive"
    finally:
        try:
            stream.seek(0)
        except Exception:
            pass
    return None

# ===== GET REQUESTS =====
@main.route('/')
def index():
    return render_template('index.html')

@main.route('/download_file/<project>')
@login_required
def download_file(project):
    projects = os.listdir(f"{DATA_PATH}/{current_user.id}")
    if project not in projects:
        flash("Project does not exist")
        return redirect(url_for("main.index"))
    project_path = f"{DATA_PATH}/{current_user.id}/{project}/{project}.pdf"
    
    return send_file(project_path)

@main.route('/list_files')
@login_required
def list_files():
    projects = os.listdir(f"{DATA_PATH}/{current_user.id}")
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
    def __init__(self, project_name, project_path, upload_path, pdf_path):
        self.project_name = project_name
        self.project_path = project_path
        self.upload_path = upload_path
        self.pdf_path = pdf_path

    def set_typ_path(self, typ_path):
        self.typ_path = typ_path

def convert_typ_file(file, project, language):
    filecontent = file.stream.read().decode("utf-8")
    with open(project.upload_path, "w+") as f:
        f.write(get_translation(language))
        f.write("\n")
        f.write(filecontent)
        project.set_typ_path(project.upload_path)

def convert_tar_file(file, project, language):
    problem = check_tar(file.stream)
    if problem:
        logging.warning("rejected archive: %s", problem)
        return False
    file.save(project.upload_path)
    try:
        result = subprocess.run(["tar", "xf", project.upload_path, "-C", project.project_path],
                                preexec_fn=set_file_limit,
                                capture_output=True,
                                check=True)
    except subprocess.CalledProcessError as e:
        flash("Failed to extract archive")
        return False
    if result.returncode != 0:
        flash("Failed to extract archive")
        return False
    project.set_typ_path(f"{project.project_path}/main.typ")

    try: 
        with open(project.typ_path, "r") as f:
            filecontent = f.read()
    except:
        flash("Couldn't find main.typ")
        return
    with open(project.typ_path, "w") as f:
        f.write(get_translation(language))
        f.write("\n")
        f.write(filecontent)
    return True

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
    if not file.filename or file.filename == '' or not extension_allowed(file.filename):
        flash("Invalid filetype")
        return redirect(request.url)
    project_name = file.filename.split(".", maxsplit=1)[0]
    user_path = Path(DATA_PATH).joinpath(current_user.id).resolve()
    project_path = Path(user_path).joinpath(project_name).resolve()
    pdf_path = Path(project_path).joinpath(f"{project_name}.pdf").resolve()
    if not project_path.is_relative_to(user_path):
        flash("Invalid filename")
        return redirect(request.url)
    if project_path.exists():
        flash("Project with this name already exists")
        return redirect(request.url)
    project_path.mkdir()
    upload_path = project_path.joinpath(file.filename).resolve()
    if not upload_path.is_relative_to(project_path):
        flash("Invalid filename")
        return redirect(request.url)
    project = Project(project_name, project_path, upload_path, pdf_path)

    if get_extension(file.filename) == "typ":
        convert_typ_file(file, project, language)
    elif not convert_tar_file(file, project, language):
        # nothing was extracted: drop the project directory again so a refused
        # upload leaves no trace on disk
        shutil.rmtree(project_path, ignore_errors=True)
        return redirect(request.url)

    try:
        result = subprocess.run(["typst", "compile", "--root", project.project_path,
                     "--font-path", "/app/src/static/fonts", project.typ_path, project.pdf_path],
                                timeout=5, capture_output=True)
    except subprocess.TimeoutExpired:
        flash("Document translation failed. Try again.")
        return redirect(request.url)
    if result.returncode != 0:
        logging.error(result.stderr)
        logging.error(result.stdout)
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
