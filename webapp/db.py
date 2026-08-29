import sqlite3

import click
from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf8"))


@click.command("init-db")
def init_db_command():
    """Drop and recreate the picture library tables."""
    init_db()
    click.echo("Initialized the database.")


def ensure_db_initialized(app):
    """Create the tables on first run only — e.g. a fresh deploy pointed
    at an empty volume. Never touches an already-initialized database, so
    a redeploy/restart can't silently wipe the picture library.
    """
    with app.app_context():
        db = get_db()
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pictures'"
        ).fetchone()
        if row is None:
            init_db()
        close_db()


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    ensure_db_initialized(app)
