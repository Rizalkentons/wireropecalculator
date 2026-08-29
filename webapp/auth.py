import hmac
import time

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

bp = Blueprint("auth", __name__)

# Endpoints reachable without being logged in — just the login page itself
# and static assets (CSS). Everything else is gated by _require_login below.
_PUBLIC_ENDPOINTS = {"auth.login", "static"}

# Brute-force throttling. In-memory and therefore per-worker-process: with
# several gunicorn workers an attacker effectively gets this many tries per
# worker, which still slows a guessing attack by orders of magnitude without
# adding a database or cache dependency for a small internal tool.
#
# The limit is deliberately generous because a whole office usually shares
# one public IP: a stricter cap would let a few colleagues fumbling their
# password lock out everyone else. Even at this rate an online guessing
# attack manages only a few hundred tries an hour, which is nowhere near
# enough against a non-trivial password.
_MAX_ATTEMPTS = 20
_LOCKOUT_SECONDS = 300
_failed_attempts = {}  # client ip -> [attempt_count, window_started_at]


def _client_ip():
    # Railway (like most platforms) terminates TLS at a proxy, so the direct
    # peer address is the proxy's. The left-most X-Forwarded-For entry is the
    # original client. Spoofable in general, but good enough for throttling —
    # a spoofed value only ever costs the attacker their own bucket.
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _is_locked_out(ip):
    record = _failed_attempts.get(ip)
    if not record:
        return False
    count, started_at = record
    if time.time() - started_at > _LOCKOUT_SECONDS:
        _failed_attempts.pop(ip, None)
        return False
    return count >= _MAX_ATTEMPTS


def _record_failure(ip):
    count, started_at = _failed_attempts.get(ip, [0, time.time()])
    if time.time() - started_at > _LOCKOUT_SECONDS:
        count, started_at = 0, time.time()
    _failed_attempts[ip] = [count + 1, started_at]


def _passwords_match(entered, real):
    # compare_digest rejects str inputs that aren't ASCII-only, so compare
    # the encoded bytes — otherwise a password containing any non-ASCII
    # character would raise TypeError and 500 instead of just being wrong.
    return hmac.compare_digest(entered.encode("utf-8"), real.encode("utf-8"))


def _safe_next_url(candidate):
    """Return `candidate` only if it's a same-site relative path.

    Without this check, /login?next=https://evil.example/phish would send
    the user to an attacker's page the instant they typed the real
    password — a convincing phishing flow, because the link they clicked
    genuinely was our own domain. Anything absolute, protocol-relative
    ("//host"), or backslash-prefixed (which some browsers normalise to
    "//") is rejected in favour of the home page.
    """
    if not candidate:
        return None
    if not candidate.startswith("/"):
        return None
    if candidate.startswith("//") or candidate.startswith("/\\"):
        return None
    return candidate


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = _client_ip()
        if _is_locked_out(ip):
            flash("Too many failed attempts. Please wait a few minutes and try again.")
            return render_template("login.html"), 429

        entered = request.form.get("password", "")
        if _passwords_match(entered, current_app.config["SITE_PASSWORD"]):
            _failed_attempts.pop(ip, None)
            session["authenticated"] = True
            return redirect(_safe_next_url(request.args.get("next")) or url_for("index"))

        _record_failure(ip)
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
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return None
