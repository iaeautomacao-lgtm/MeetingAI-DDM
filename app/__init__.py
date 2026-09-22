import os
from flask import Flask, send_file, send_from_directory, redirect, request
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

    # A extensão Chrome roda em origem chrome-extension:// — precisa de CORS.
    # Liberado apenas nos endpoints públicos da extensão e SEM Allow-Credentials, ou seja,
    # o cookie de sessão do diretor nunca é enviado nem aceito por essa via.
    _EXT_PATHS = ("/api/health", "/api/setores", "/api/gravacoes", "/api/extensao/usuario")

    def _origem_extensao(origin):
        if not origin.startswith("chrome-extension://"):
            return False
        permitidas = app.config.get("EXTENSION_ORIGINS") or []
        return not permitidas or origin in permitidas

    @app.after_request
    def _cors_extensao(resp):
        origin = request.headers.get("Origin", "")
        if request.path in _EXT_PATHS and _origem_extensao(origin):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resp.headers["Access-Control-Max-Age"] = "600"
            resp.headers.add("Vary", "Origin")
        return resp

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
