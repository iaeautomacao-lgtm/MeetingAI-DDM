import os
from celery import Celery
from celery.schedules import crontab
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions

celery = Celery(__name__)

_supabase: Client | None = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        schema = os.getenv("SUPABASE_SCHEMA", "public")
        _supabase = create_client(
            os.getenv("SUPABASE_URL", ""),
            os.getenv("SUPABASE_SERVICE_KEY", ""),
            options=ClientOptions(schema=schema),
        )
    return _supabase


def init_celery(app):
    celery.conf.update(
        broker_url=app.config["REDIS_URL"],
        result_backend=app.config["REDIS_URL"],
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="America/Sao_Paulo",
        enable_utc=True,
        beat_schedule={
            "sync-reunioes": {
                "task": "app.workers.tasks.sync_reunioes_teams",
                "schedule": app.config["SYNC_INTERVAL_MINUTES"] * 60,
            },
            "sync-emails-imap": {
                "task": "app.workers.tasks.sync_emails_imap",
                "schedule": app.config["SYNC_INTERVAL_MINUTES"] * 60,
            },
            "sync-usuarios": {
                "task": "app.workers.tasks.sync_usuarios_ad",
                "schedule": 3600,
            },
            "resumo-diario": {
                "task": "app.workers.tasks.gerar_resumo_diario",
                "schedule": crontab(hour=18, minute=0),
            },
        },
    )

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery
