import os
from flask import Flask, send_file, send_from_directory, redirect
from app.config import Config
from app.extensions import init_celery
from app.auth import is_authed


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    init_celery(app)

    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    root = os.path.abspath(os.path.join(app.root_path, ".."))

    def _page(nome):
        return send_file(os.path.join(root, nome))

    @app.get("/")
    def index():
        # Tela pública: qualquer funcionário registra reunião (sem dados).
        return _page("registrar.html")

    @app.get("/login")
    def login_page():
        if is_authed():
            return redirect("/painel")
        return _page("login.html")

    @app.get("/painel")
    def painel():
        # Dashboard completo — só diretores autenticados.
        if not is_authed():
            return redirect("/login")
        return _page("meeting-ddm-dashboard.html")

    @app.get("/assets/<path:filename>")
    def assets(filename):
        pasta = os.path.join(root, "assets")
        return send_from_directory(pasta, filename)

    _CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        resp.headers.setdefault("Content-Security-Policy", _CSP)
        return resp

    return app
