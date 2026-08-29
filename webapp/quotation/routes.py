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

from webapp.library import models as library_models

from . import pdf_draw
from .matcher import match_items_to_pictures
from .pdf_extract import extract_lines_with_bbox

bp = Blueprint("quotation", __name__, url_prefix="/quotation")


class QuotationError(Exception):
    """A problem worth showing the user in plain language, rather than
    letting a PyMuPDF/Pillow traceback surface as a raw 500 page."""


def _extract_and_match(incoming_path):
    """Re-derive lines/matches/picture_paths for a saved incoming PDF.

    Deterministic given the same PDF + current library state, so this is
    safe to call again in the /generate step instead of persisting the
    match list between requests.

    Also returns library_entries so callers don't have to re-query.
    """
    try:
        lines = extract_lines_with_bbox(incoming_path)
    except Exception as exc:
        raise QuotationError(
            "That file could not be read as a PDF. Please make sure it's a "
            "real PDF (not renamed from another format) and try again."
        ) from exc

    library_entries = library_models.get_pictures_with_tags()
    matches = match_items_to_pictures(lines, library_entries)

    picture_paths = {
        entry["id"]: os.path.join(
            current_app.config["LIBRARY_UPLOAD_FOLDER"], entry["filename"]
        )
        for entry in library_entries
        if entry["filename"]
    }

    matched_with_picture = [m for m in matches if m["picture_id"] in picture_paths]
    matched_without_picture = [m for m in matches if m["picture_id"] not in picture_paths]
    return lines, matched_with_picture, matched_without_picture, picture_paths, library_entries


def _render_pdf(incoming_path, matches, picture_paths, processed_path):
    try:
        pdf_draw.insert_images(incoming_path, matches, picture_paths, processed_path)
    except Exception as exc:
        raise QuotationError(
            "Something went wrong while building the PDF. One of the "
            "matched library pictures may be damaged — try re-uploading it "
            "from the Picture Library page."
        ) from exc


@bp.route("/")
def index():
    return render_template("quotation/upload.html")


@bp.route("/process", methods=["POST"])
def process():
    file = request.files.get("quotation_pdf")
    if not file or file.filename == "":
        flash("Please choose a PDF file.")
        return redirect(url_for("quotation.index"))

    if not file.filename.lower().endswith(".pdf"):
        flash("Please upload a PDF file.")
        return redirect(url_for("quotation.index"))

    job_id = uuid.uuid4().hex
    original_filename = secure_filename(file.filename) or "quotation.pdf"
    incoming_path = os.path.join(
        current_app.config["QUOTATION_INCOMING_FOLDER"], f"{job_id}.pdf"
    )
    file.save(incoming_path)

    try:
        (
            lines,
            matched_with_picture,
            matched_without_picture,
            picture_paths,
            library_entries,
        ) = _extract_and_match(incoming_path)

        if not matched_with_picture:
            # Nothing to size — skip straight to generating (empty) output.
            processed_path = os.path.join(
                current_app.config["QUOTATION_PROCESSED_FOLDER"], f"{job_id}.pdf"
            )
            _render_pdf(incoming_path, [], {}, processed_path)
            return render_template(
                "quotation/result.html",
                job_id=job_id,
                original_filename=original_filename,
                matched_with_picture=matched_with_picture,
                matched_without_picture=matched_without_picture,
                total_lines=len(lines),
            )
    except QuotationError as exc:
        current_app.logger.exception("Quotation processing failed")
        flash(str(exc))
        return redirect(url_for("quotation.index"))

    picture_filenames = {
        entry["id"]: entry["filename"] for entry in library_entries if entry["filename"]
    }

    return render_template(
        "quotation/dimensions.html",
        job_id=job_id,
        original_filename=original_filename,
        matches=matched_with_picture,
        picture_filenames=picture_filenames,
    )


@bp.route("/generate/<job_id>", methods=["POST"])
def generate(job_id):
    incoming_path = os.path.join(current_app.config["QUOTATION_INCOMING_FOLDER"], f"{job_id}.pdf")
    if not os.path.exists(incoming_path):
        flash("This job has expired, please upload the PDF again.")
        return redirect(url_for("quotation.index"))

    try:
        (
            lines,
            matched_with_picture,
            matched_without_picture,
            picture_paths,
            _library_entries,
        ) = _extract_and_match(incoming_path)

        for i, m in enumerate(matched_with_picture):
            m["dim_a"] = request.form.get(f"a_{i}", "").strip()
            m["dim_b"] = request.form.get(f"b_{i}", "").strip()
            m["dim_c"] = request.form.get(f"c_{i}", "").strip()

        processed_path = os.path.join(
            current_app.config["QUOTATION_PROCESSED_FOLDER"], f"{job_id}.pdf"
        )
        _render_pdf(incoming_path, matched_with_picture, picture_paths, processed_path)
    except QuotationError as exc:
        current_app.logger.exception("Quotation generation failed")
        flash(str(exc))
        return redirect(url_for("quotation.index"))

    return render_template(
        "quotation/result.html",
        job_id=job_id,
        original_filename=request.form.get("original_filename", "quotation.pdf"),
        matched_with_picture=matched_with_picture,
        matched_without_picture=matched_without_picture,
        total_lines=len(lines),
    )


@bp.route("/preview/<job_id>")
def preview(job_id):
    return send_from_directory(
        current_app.config["QUOTATION_PROCESSED_FOLDER"],
        f"{job_id}.pdf",
        mimetype="application/pdf",
    )


@bp.route("/download/<job_id>")
def download(job_id):
    return send_from_directory(
        current_app.config["QUOTATION_PROCESSED_FOLDER"],
        f"{job_id}.pdf",
        as_attachment=True,
        download_name="quotation_with_pictures.pdf",
    )
