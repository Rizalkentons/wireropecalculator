import os
import uuid

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.utils import secure_filename

from . import models

bp = Blueprint("library", __name__, url_prefix="/library")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _parse_tags(raw):
    return [t.strip() for t in raw.split(",") if t.strip()]


def _save_uploaded_image(file):
    """Save an uploaded FileStorage under a unique name. Returns (stored, original) or None."""
    if not file or file.filename == "":
        return None
    if not _allowed_file(file.filename):
        return None

    original_filename = secure_filename(file.filename)
    ext = original_filename.rsplit(".", 1)[1].lower()
    stored_filename = f"{uuid.uuid4().hex}.{ext}"
    dest_path = os.path.join(current_app.config["LIBRARY_UPLOAD_FOLDER"], stored_filename)
    file.save(dest_path)
    return stored_filename, original_filename


@bp.route("/image/<filename>")
def image(filename):
    return send_from_directory(current_app.config["LIBRARY_UPLOAD_FOLDER"], filename)


@bp.route("/")
def index():
    pictures = models.get_pictures_with_tags()
    return render_template("library/index.html", pictures=pictures)


@bp.route("/upload", methods=["POST"])
def upload():
    tags_raw = request.form.get("tags", "")
    tags = _parse_tags(tags_raw)
    if not tags:
        flash("Please enter at least one keyword/description tag.")
        return redirect(url_for("library.index"))

    saved = _save_uploaded_image(request.files.get("picture"))
    if saved is None:
        flash("Please choose a valid picture file (PNG, JPG, GIF, or WEBP).")
        return redirect(url_for("library.index"))

    stored_filename, original_filename = saved
    models.add_picture(stored_filename, original_filename, tags)
    flash(f"Uploaded {original_filename} with tags: {', '.join(tags)}")
    return redirect(url_for("library.index"))


@bp.route("/<int:picture_id>/upload-image", methods=["POST"])
def upload_image(picture_id):
    picture = models.get_picture(picture_id)
    if picture is None:
        flash("Item not found.")
        return redirect(url_for("library.index"))

    saved = _save_uploaded_image(request.files.get("picture"))
    if saved is None:
        flash("Please choose a valid picture file (PNG, JPG, GIF, or WEBP).")
        return redirect(url_for("library.index"))

    old_filename = picture["filename"]
    stored_filename, original_filename = saved
    models.set_picture_file(picture_id, stored_filename, original_filename)

    if old_filename:
        old_path = os.path.join(current_app.config["LIBRARY_UPLOAD_FOLDER"], old_filename)
        if os.path.exists(old_path):
            os.remove(old_path)

    flash(f"Picture attached to: {', '.join(picture['tags'])}")
    return redirect(url_for("library.index"))


@bp.route("/<int:picture_id>/edit", methods=["GET", "POST"])
def edit(picture_id):
    picture = models.get_picture(picture_id)
    if picture is None:
        flash("Picture not found.")
        return redirect(url_for("library.index"))

    if request.method == "POST":
        tags = _parse_tags(request.form.get("tags", ""))
        if not tags:
            flash("Please enter at least one keyword tag.")
            return redirect(url_for("library.edit", picture_id=picture_id))
        models.update_tags(picture_id, tags)
        flash("Tags updated.")
        return redirect(url_for("library.index"))

    return render_template("library/edit.html", picture=picture)


@bp.route("/<int:picture_id>/delete", methods=["POST"])
def delete(picture_id):
    filename = models.delete_picture(picture_id)
    if filename:
        file_path = os.path.join(current_app.config["LIBRARY_UPLOAD_FOLDER"], filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        flash("Picture deleted.")
    return redirect(url_for("library.index"))
