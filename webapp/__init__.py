import os

from flask import Flask, render_template


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        SECRET_KEY="dev",
        DATABASE=os.path.join(app.instance_path, "library.db"),
        LIBRARY_UPLOAD_FOLDER=os.path.join(app.root_path, "..", "uploads", "library"),
        QUOTATION_INCOMING_FOLDER=os.path.join(
            app.root_path, "..", "uploads", "quotations", "incoming"
        ),
        QUOTATION_PROCESSED_FOLDER=os.path.join(
            app.root_path, "..", "uploads", "quotations", "processed"
        ),
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,  # 25 MB
    )

    if test_config is not None:
        app.config.from_mapping(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["LIBRARY_UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["QUOTATION_INCOMING_FOLDER"], exist_ok=True)
    os.makedirs(app.config["QUOTATION_PROCESSED_FOLDER"], exist_ok=True)

    from . import db
    db.init_app(app)

    from .importers import kata_baku
    kata_baku.init_app(app)

    from .library.routes import bp as library_bp
    from .quotation.routes import bp as quotation_bp
    app.register_blueprint(library_bp)
    app.register_blueprint(quotation_bp)

    @app.route("/")
    def index():
        return render_template("home.html")

    return app
