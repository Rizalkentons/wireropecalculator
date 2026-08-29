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
from PIL import Image
from werkzeug.utils import secure_filename

from . import models

bp = Blueprint("library", __name__, url_prefix="/library")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def _parse_tags(raw):
    return [t.strip() for t in raw.split(",") if t.strip()]


def _allowed_extension(filename):
    """Lowercased extension of the ORIGINAL upload name, or None if it
    isn't an accepted image type.

    Deliberately read before secure_filename(): that strips non-ASCII
    characters, so a perfectly ordinary name like "にほん.jpg" collapses to
    just "jpg" — leaving no dot to split on and crashing anything that
    assumed there would be one.
    """
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[1].lower()
    return ext if ext in ALLOWED_EXTENSIONS else None


def _save_uploaded_image(file):
    """Save an uploaded image under a unique name.

    Returns (stored_filename, display_name), or None when the upload
    isn't a usable image. The bytes are verified with Pillow rather than
    trusted by extension alone: a mislabelled file would otherwise be
    accepted here and only fail much later, in the middle of somebody
    else's PDF generation, far from the upload that caused it.
    """
    if not file or not file.filename:
        return None

    ext = _allowed_extension(file.filename)
    if ext is None:
        return None

    try:
        Image.open(file.stream).verify()
    except Exception:
        return None
    file.stream.seek(0)  # verify() consumes the stream; rewind before saving

    display_name = secure_filename(file.filename)
    if not display_name or "." not in display_name:
        display_name = f"picture.{ext}"

    stored_filename = f"{uuid.uuid4().hex}.{ext}"
    dest_path = os.path.join(current_app.config["LIBRARY_UPLOAD_FOLDER"], stored_filename)
    file.save(dest_path)
    return stored_filename, display_name


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
        flash("Please choose a valid, readable picture file (PNG, JPG, GIF, or WEBP).")
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
        flash("Please choose a valid, readable picture file (PNG, JPG, GIF, or WEBP).")
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
