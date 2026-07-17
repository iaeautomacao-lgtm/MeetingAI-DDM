from app import create_app
from app.extensions import celery

flask_app = create_app()
