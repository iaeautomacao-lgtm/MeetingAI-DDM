import os
from flask import Flask, send_file, send_from_directory
from app.config import Config
from app.extensions import init_celery


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    init_celery(app)

    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.get("/")
    def index():
        html = os.path.join(app.root_path, "..", "meeting-ddm-dashboard.html")
        return send_file(os.path.abspath(html))

    @app.get("/assets/<path:filename>")
    def assets(filename):
        pasta = os.path.abspath(os.path.join(app.root_path, "..", "assets"))
        return send_from_directory(pasta, filename)

    return app
