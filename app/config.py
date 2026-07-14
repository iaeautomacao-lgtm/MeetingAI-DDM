import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-inseguro")
    FLASK_ENV = os.getenv("FLASK_ENV", "production")

    # Login de diretores (dashboard). Senha em DIRECTOR_PASSWORD.
    DIRECTOR_PASSWORD = os.getenv("DIRECTOR_PASSWORD", "")
    # E-mails admin (aprovam novos acessos). Separados por vírgula.
    ADMIN_EMAILS = os.getenv("ADMIN_EMAILS", "gisele.oliveira@ddm.adv.br")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Em produção (HTTPS) definir SESSION_COOKIE_SECURE=1 no .env
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8h

    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
    SUPABASE_SCHEMA = os.getenv("SUPABASE_SCHEMA", "public")

    AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
    AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
    AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
    AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", "")
    AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "")
    AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "brazilsouth")

    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

    # Recall.ai (bot "DDM" entra na reunião, grava e transcreve)
    RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
    RECALL_REGION = os.getenv("RECALL_REGION", "us-west-2")
    RECALL_BOT_NAME = os.getenv("RECALL_BOT_NAME", "Acordito")
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")  # URL pública p/ webhook Recall

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
