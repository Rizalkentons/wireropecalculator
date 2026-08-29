import os

from flask import Flask, render_template


def create_app(test_config=None):
    # DATA_DIR points at a persistent volume when deployed (e.g. Railway) —
    # without it, the SQLite database and uploaded pictures/PDFs would be
    # wiped on every redeploy/restart, since a container's own filesystem
    # isn't kept between deploys. Locally (DATA_DIR unset) everything stays
    # right next to the project, exactly as before. Falls back to
    # RAILWAY_VOLUME_MOUNT_PATH, which Railway sets automatically once a
    # volume is attached — so DATA_DIR usually doesn't need to be set by
    # hand at all on Railway specifically.
    data_dir = os.environ.get("DATA_DIR") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if data_dir:
        app = Flask(__name__, instance_path=os.path.join(data_dir, "instance"))
        uploads_root = os.path.join(data_dir, "uploads")
    else:
        app = Flask(__name__, instance_relative_config=True)
        uploads_root = os.path.join(app.root_path, "..", "uploads")

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev"),
        SITE_PASSWORD=os.environ.get("SITE_PASSWORD", "changeme"),
        # Deployments run behind HTTPS, so the session cookie is marked
        # Secure there; locally the dev server is plain http and a Secure
        # cookie would simply never be stored, breaking login. SameSite=Lax
        # is what makes cross-site POSTs (CSRF) from another origin unable
        # to carry the session, instead of relying on browser defaults.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(data_dir),
        DATABASE=os.path.join(app.instance_path, "library.db"),
        LIBRARY_UPLOAD_FOLDER=os.path.join(uploads_root, "library"),
        QUOTATION_INCOMING_FOLDER=os.path.join(uploads_root, "quotations", "incoming"),
        QUOTATION_PROCESSED_FOLDER=os.path.join(uploads_root, "quotations", "processed"),
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,  # 25 MB
        QUOTATION_RETENTION_DAYS=int(os.environ.get("QUOTATION_RETENTION_DAYS", 30)),
    )

    if test_config is not None:
        app.config.from_mapping(test_config)

    # A deployment (i.e. one with a persistent volume) must set its own
    # secrets. Falling back to the well-known dev defaults there would mean
    # a single missing/typo'd variable silently leaves the site guessable,
    # with nothing in the UI to reveal it — so fail loudly at startup
    # instead, while it's still obvious why.
    if data_dir and test_config is None:
        missing = [
            name
            for name, value in (
                ("SECRET_KEY", app.config["SECRET_KEY"]),
                ("SITE_PASSWORD", app.config["SITE_PASSWORD"]),
            )
            if value in ("dev", "changeme")
        ]
        if missing:
            raise RuntimeError(
                "Refusing to start: "
                + " and ".join(missing)
                + " still set to the insecure development default. Set "
                "them as environment variables on the host."
            )

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["LIBRARY_UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["QUOTATION_INCOMING_FOLDER"], exist_ok=True)
    os.makedirs(app.config["QUOTATION_PROCESSED_FOLDER"], exist_ok=True)

    from . import db
    db.init_app(app)

    from . import auth
    auth.init_app(app)

    from . import cleanup
    cleanup.init_app(app)

    from .importers import kata_baku
    kata_baku.init_app(app)

    from .library.routes import bp as library_bp
    from .quotation.routes import bp as quotation_bp
    app.register_blueprint(library_bp)
    app.register_blueprint(quotation_bp)

    @app.route("/")
    def index():
        return render_template("home.html")

    @app.errorhandler(404)
    def _not_found(e):
        return render_template(
            "error.html",
            code=404,
            heading="Page not found",
            message="That link doesn't exist. It may have been mistyped.",
        ), 404

    @app.errorhandler(413)
    def _too_large(e):
        limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return render_template(
            "error.html",
            code=413,
            heading="File too large",
            message=f"Please upload a file smaller than {limit_mb} MB.",
        ), 413

    @app.errorhandler(500)
    def _server_error(e):
        app.logger.exception("Unhandled server error")
        return render_template(
            "error.html",
            code=500,
            heading="Something went wrong",
            message="An unexpected error occurred. Please try again — if it "
                    "keeps happening, let Muhammad Rizal Baihaqi know.",
        ), 500

    return app
