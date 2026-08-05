import os

import mysql.connector
from mysql.connector import pooling
from flask import current_app
from celery import Celery
from celery.schedules import crontab


celery = Celery(__name__)

_mysql_pool: pooling.MySQLConnectionPool | None = None


def get_mysql_pool() -> pooling.MySQLConnectionPool:
    """
    Cria um pool de conexões MySQL por processo.
    """
    global _mysql_pool

    if _mysql_pool is None:
        required = {
            "MYSQL_HOST": current_app.config.get("MYSQL_HOST"),
            "MYSQL_DATABASE": current_app.config.get("MYSQL_DATABASE"),
            "MYSQL_USER": current_app.config.get("MYSQL_USER"),
            "MYSQL_PASSWORD": current_app.config.get("MYSQL_PASSWORD"),
        }

        missing = [
            name
            for name, value in required.items()
            if value is None or str(value).strip() == ""
        ]

        if missing:
            raise RuntimeError(
        "Configurações MySQL ausentes: " + ", ".join(missing)
    )

    _mysql_pool = pooling.MySQLConnectionPool(
        pool_name="meeting_ai_pool",
        pool_size=5,
        pool_reset_session=True,
        host=current_app.config["MYSQL_HOST"],
        port=current_app.config["MYSQL_PORT"],
        database=current_app.config["MYSQL_DATABASE"],
        user=current_app.config["MYSQL_USER"],
        password=current_app.config["MYSQL_PASSWORD"],
        charset="utf8mb4",
        autocommit=False,
        connection_timeout=15,
    )

    return _mysql_pool


def get_mysql_connection():
    """
    Retorna uma conexão do pool.

    Ao executar connection.close(), a conexão retorna ao pool.
    """
    return get_mysql_pool().get_connection()


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
            # Rede de segurança: sem Celery no ar, a purga acontece quando
            # alguém abre a lixeira (ver purgar_lixeira_expirada em routes.py).
            "limpar-lixeira": {
                "task": "app.workers.tasks.limpar_lixeira_expirada",
                "schedule": crontab(hour=3, minute=30),
            },
        },
    )

class ContextTask(celery.Task):
    def __call__(self, *args, **kwargs):
        with app.app_context():
            return self.run(*args, **kwargs)

        celery.Task = ContextTask

        return celery
