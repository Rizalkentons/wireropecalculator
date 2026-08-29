"""Automatic removal of old processed/incoming quotation PDFs.

Every quotation anyone uploads or generates gets saved permanently
(uploads/quotations/incoming + processed) — real customer names, prices,
and sometimes bank details. Left alone forever, that both grows storage
without bound and keeps sensitive customer data around far longer than
needed. This module deletes files older than RETENTION_DAYS.

The picture LIBRARY (uploads/library/*) is never touched here — those are
deliberately curated reference diagrams, not per-quotation data.

Runs opportunistically on incoming requests (like the login check), at
most once a day (tracked via a marker file's mtime) — no extra process,
scheduler, or dependency needed. A failure here is caught and logged, and
can NEVER surface as an error to the user or block their actual request.
"""
import os
import time

import click

CHECK_INTERVAL_SECONDS = 24 * 60 * 60  # run the actual scan at most this often


def _marker_path(app):
    return os.path.join(app.instance_path, ".last_cleanup")


def _should_run(app):
    marker = _marker_path(app)
    if not os.path.exists(marker):
        return True
    return (time.time() - os.path.getmtime(marker)) >= CHECK_INTERVAL_SECONDS


def _touch_marker(app):
    # Written BEFORE the scan runs, so two requests arriving back-to-back
    # can't both decide a scan is due and run it twice.
    with open(_marker_path(app), "w") as f:
        f.write(str(time.time()))


def _delete_old_pdfs(folder, cutoff_time):
    deleted = 0
    if not os.path.isdir(folder):
        return deleted
    for name in os.listdir(folder):
        if not name.endswith(".pdf"):
            continue
        path = os.path.join(folder, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff_time:
                os.remove(path)
                deleted += 1
        except OSError:
            continue
    return deleted


def run_cleanup(app):
    """Delete incoming/processed quotation PDFs older than RETENTION_DAYS.
    Returns the number of files deleted. Safe to call any time.
    """
    retention_days = app.config["QUOTATION_RETENTION_DAYS"]
    cutoff = time.time() - retention_days * 24 * 60 * 60
    deleted = 0
    deleted += _delete_old_pdfs(app.config["QUOTATION_INCOMING_FOLDER"], cutoff)
    deleted += _delete_old_pdfs(app.config["QUOTATION_PROCESSED_FOLDER"], cutoff)
    return deleted


@click.command("cleanup-quotations")
def cleanup_command():
    """Manually delete quotation PDFs older than QUOTATION_RETENTION_DAYS."""
    from flask import current_app
    deleted = run_cleanup(current_app)
    click.echo(f"Deleted {deleted} old quotation PDF(s).")


def init_app(app):
    app.cli.add_command(cleanup_command)

    @app.before_request
    def _maybe_run_cleanup():
        try:
            if _should_run(app):
                _touch_marker(app)
                deleted = run_cleanup(app)
                if deleted:
                    app.logger.info("Cleanup: removed %d old quotation PDF(s)", deleted)
        except Exception:
            # Cleanup must never break the actual request being served.
            app.logger.exception("Quotation cleanup failed")
