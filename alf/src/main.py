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
    file.save(project.upload_path)
    try:
        result = subprocess.run(["tar", "xf", project.upload_path, "-C", project.project_path],
                                preexec_fn=set_file_limit,
                                capture_output=True,
                                check=True)
    except subprocess.CalledProcessError as e:
        flash("Failed to extract archive")
        return
    if result.returncode != 0:
        flash("Failed to extract archive")
        return
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
    else:
        convert_tar_file(file, project, language)

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
