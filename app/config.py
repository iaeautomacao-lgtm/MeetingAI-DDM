import os
import secrets
import logging
from dotenv import load_dotenv

load_dotenv()

_IS_DEV = os.getenv("FLASK_ENV", "production").strip().lower() == "development"


def _resolve_secret_key() -> str:
    """SECRET_KEY do ambiente. Sem default fraco: se não houver, gera uma chave
    aleatória forte por processo (sessões não persistem entre restarts, mas NÃO
    são forjáveis). Defina SECRET_KEY fixa no .env/painel p/ persistência."""
    key = os.getenv("SECRET_KEY", "").strip()
    if key and key != "dev-inseguro":
        return key
    logging.getLogger(__name__).warning(
        "SECRET_KEY ausente/insegura — gerando chave aleatória por processo. "
        "Defina SECRET_KEY no ambiente para manter as sessões entre reinícios."
    )
    return secrets.token_hex(32)


class Config:
    SECRET_KEY = _resolve_secret_key()
    FLASK_ENV = os.getenv("FLASK_ENV", "production")

    # Limite de upload (áudio avulso). Evita DoS por corpo gigante.
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "200")) * 1024 * 1024

    # Login de diretores (dashboard). Senha em DIRECTOR_PASSWORD.
    DIRECTOR_PASSWORD = os.getenv("DIRECTOR_PASSWORD", "")
    # E-mails admin (aprovam novos acessos). Separados por vírgula.
    ADMIN_EMAILS = os.getenv("ADMIN_EMAILS", "gisele.oliveira@ddm.adv.br,dimaio@ddm.adv.br,joao.dimaio@ddm.adv.br")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Seguro por padrão em produção (HTTPS). Em dev (HTTP) desliga automático.
    # Override explícito via env SESSION_COOKIE_SECURE=0/1.
    SESSION_COOKIE_SECURE = os.getenv(
        "SESSION_COOKIE_SECURE", "0" if _IS_DEV else "1"
    ) == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8h

    # MariaDB / MySQL do cPanel
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "")
    MYSQL_USER = os.getenv("MYSQL_USER", "")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

    AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
    AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
    AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
    AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", "")
    AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "")
    AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "brazilsouth")

    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

    # Skribby (bot "Acordito" entra na reunião, grava e transcreve)
    SKRIBBY_API_KEY = os.getenv("SKRIBBY_API_KEY", "")
    SKRIBBY_HOST = os.getenv("SKRIBBY_HOST", "platform.skribby.io")
    SKRIBBY_MODEL = os.getenv("SKRIBBY_MODEL", "groq/whisper-large-v3-turbo")
    SKRIBBY_LANG = os.getenv("SKRIBBY_LANG", "pt")
    SKRIBBY_BOT_NAME = os.getenv("SKRIBBY_BOT_NAME", "Acordito")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")  # URL pública p/ webhook + avatar

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # IMAP (e-mail cPanel — contas fora do Microsoft 365)
    IMAP_HOST = os.getenv("IMAP_HOST", "")
    IMAP_PORT = int(os.getenv("IMAP_PORT", 993))
    IMAP_USER = os.getenv("IMAP_USER", "")
    IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")

    TEAMS_DOMAIN = os.getenv("TEAMS_DOMAIN", "ddm.adv.br")
    # domínios corporativos aceitos (e-mail interno) — separados por vírgula
    CORP_DOMAINS = os.getenv("CORP_DOMAINS", "ddm.adv.br,grupoddm.com.br")
    SYNC_INTERVAL_MINUTES = int(os.getenv("SYNC_INTERVAL_MINUTES", 5))
