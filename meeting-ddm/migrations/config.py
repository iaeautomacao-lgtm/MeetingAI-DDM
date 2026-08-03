import os
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
ENV_FILE = BASE_DIR / ".env"
if not ENV_FILE.exists():
    ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"A variavel de ambiente obrigatoria '{name}' nao foi definida."
        )

    return value


@dataclass(frozen=True)
class PostgresConfig:
    url: str | None
    host: str | None
    port: int
    database: str
    user: str | None
    password: str | None
    sslmode: str


@dataclass(frozen=True)
class MySQLConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    charset: str = "utf8mb4"


POSTGRES_URL = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")

POSTGRES_CONFIG = None
if not POSTGRES_URL:
    POSTGRES_CONFIG = {
        "host": require_env("PG_HOST"),
        "port": int(os.getenv("PG_PORT", "5432")),
        "dbname": os.getenv("PG_DATABASE", "postgres"),
        "user": require_env("PG_USER"),
        "password": require_env("PG_PASSWORD"),
        "sslmode": os.getenv("PG_SSLMODE", "require"),
    }

MYSQL_CONFIG = {
    "host": require_env("MYSQL_HOST"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "database": require_env("MYSQL_DATABASE"),
    "user": require_env("MYSQL_USER"),
    "password": require_env("MYSQL_PASSWORD"),
    "charset": "utf8mb4",
}

POSTGRES_SCHEMA = os.getenv("PG_SCHEMA", "meeting_ai")


def postgres_config() -> PostgresConfig:
    return PostgresConfig(
        url=POSTGRES_URL,
        host=os.getenv("PG_HOST"),
        port=int(os.getenv("PG_PORT", "5432")),
        database=os.getenv("PG_DATABASE", "postgres"),
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
        sslmode=os.getenv("PG_SSLMODE", "require"),
    )


def mysql_config() -> MySQLConfig:
    return MySQLConfig(
        host=require_env("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=require_env("MYSQL_DATABASE"),
        user=require_env("MYSQL_USER"),
        password=require_env("MYSQL_PASSWORD"),
        charset="utf8mb4",
    )
