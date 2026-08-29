import hmac

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

bp = Blueprint("auth", __name__)

# Endpoints reachable without being logged in — just the login page itself
# and static assets (CSS). Everything else is gated by _require_login below.
_PUBLIC_ENDPOINTS = {"auth.login", "static"}


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        entered = request.form.get("password", "")
        real = current_app.config["SITE_PASSWORD"]
        if hmac.compare_digest(entered, real):
            session["authenticated"] = True
            next_url = request.args.get("next") or url_for("index")
            return redirect(next_url)
        flash("Wrong password.")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


def init_app(app):
    app.register_blueprint(bp)

    @app.before_request
    def _require_login():
        if request.endpoint in _PUBLIC_ENDPOINTS:
            return None
        if not session.get("authenticated"):
            return redirect(url_for("auth.login", next=request.path))
        return None
