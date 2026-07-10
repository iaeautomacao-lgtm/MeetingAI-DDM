import json
import os
from dotenv import load_dotenv

load_dotenv()

# ── Provedor de IA (OpenAI / Gemini / Anthropic — detecta pela chave) ─────────
# Gemini usa o endpoint compatível com OpenAI, então compartilha o mesmo cliente.
_client = None
_provider = None  # "openai_like" | "anthropic"
_model = None

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _init_client():
    """Inicializa o cliente conforme a chave disponível.
    Prioridade: OpenAI → Gemini → Anthropic."""
    global _client, _provider, _model
    if _client is not None:
        return

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    if openai_key:
        from openai import OpenAI
        _client = OpenAI(api_key=openai_key)
        _provider = "openai_like"
        _model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    elif gemini_key:
        from openai import OpenAI
        _client = OpenAI(api_key=gemini_key, base_url=GEMINI_BASE_URL)
        _provider = "openai_like"
        _model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    elif anthropic_key:
        import anthropic
        _client = anthropic.Anthropic(api_key=anthropic_key)
        _provider = "anthropic"
        _model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")


def _chat(system: str, user: str, max_tokens: int = 2048) -> str | None:
    """Chamada unificada. Retorna o texto bruto da resposta ou None se sem provedor."""
    _init_client()
    if _client is None:
        return None

    if _provider == "openai_like":
        resp = _client.chat.completions.create(
            model=_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    # anthropic
    resp = _client.messages.create(
        model=_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text.strip()


def _parse_json(raw: str) -> dict | None:
    """Extrai JSON da resposta, tolerando texto/markdown ao redor."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end])
            except json.JSONDecodeError:
                return None
    return None


SYSTEM_PROMPT = """Você é um assistente de análise corporativa.
Sempre responda SOMENTE com JSON válido, sem texto adicional, sem markdown.
Idioma: português-BR."""

EXTRACTION_PROMPT = """Analise esta transcrição de reunião e extraia:

{{
  "decisoes estrategicas": ["string"],
  "pendencias": [{{"tarefa": "string", "responsavel": "string ou null", "prazo": "string ou null"}}],
  "topicos": ["string"],
  "participantes_ativos": [{{"nome": "string", "percentual_fala": 0}}],
  "sentimento_geral": "positivo|neutro|tenso",
  "resumo_executivo": "string (max 3 frases, direto ao ponto para diretoria)"
}}

TRANSCRIÇÃO:
{transcricao}"""


def _get_client():
    global _client
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    if _client is None:
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def extrair_reuniao(transcricao: str, utterances: list) -> dict:
    if not transcricao.strip():
        return _empty_result()
        

    texto = _formatar_utterances(utterances) if utterances else transcricao

    try:
        raw = _chat(
            SYSTEM_PROMPT,
            EXTRACTION_PROMPT.format(transcricao=texto[:12000]),
            max_tokens=2048,
        )
    except Exception as e:
        return _fallback_result(f"Erro na análise: {str(e)}")

    if raw is None:
        return _fallback_result("Análise indisponível: nenhuma chave de IA configurada (OPENAI_API_KEY ou ANTHROPIC_API_KEY).")

    resultado = _parse_json(raw)
    if resultado is None:
        return _fallback_result("Não foi possível estruturar a análise.")
    return resultado


def _formatar_utterances(utterances: list) -> str:
    return "\n".join(
        f"[Speaker {u.get('speaker', '?')}]: {u.get('texto', '')}"
        for u in utterances
    )


def _empty_result() -> dict:
    return {
        "decisoes estrategicas": [],
        "pendencias": [],
        "topicos": [],
        "participantes_ativos": [],
        "sentimento_geral": "neutro",
        "resumo_executivo": "",
    }


def _fallback_result(resumo: str) -> dict:
    r = _empty_result()
    r["resumo_executivo"] = resumo
    return r


# ── Análise / Classificação de E-mail ─────────────────────────────────────────

# Categorias: corporativo | promocional | notificacao | spam | pessoal
# relevante = True apenas para "corporativo" e "pessoal" acionáveis.

# Filtro rápido (sem IA): remetentes/assuntos que são claramente ruído.
_REMETENTE_RUIDO = (
    "no-reply", "noreply", "no_reply", "do-not-reply", "donotreply",
    "notification", "notifications", "notificacao", "mailer", "mailer-daemon",
    "postmaster", "bounce", "newsletter", "news@", "marketing", "comunicacao",
    "automated", "auto-confirm", "updates@", "alerts@", "alert@", "info@",
)
_DOMINIO_RUIDO = (
    "teams.mail.microsoft", "email.teams.microsoft", "microsoft.com",
    "accounts.google.com", "github.com", "noreply.github.com",
    "sendgrid.net", "mailchimp", "rdstation", "hubspot", "notion.so",
)
_ASSUNTO_RUIDO = (
    "está tentando entrar em contato", "tentando entrar em contato",
    "alerta de segurança", "security alert", "verifique seu", "confirme seu",
    "newsletter", "unsubscribe", "cancelar inscrição", "promoção", "desconto",
    "oferta", "webinar", "convite para", "third-party oauth",
)


def pre_categoria(de_email: str, assunto: str) -> str | None:
    """Classificação heurística rápida. Retorna categoria de ruído ou None (segue p/ IA)."""
    de = (de_email or "").lower()
    ass = (assunto or "").lower()

    if any(p in de for p in _REMETENTE_RUIDO):
        return "notificacao"
    if any(d in de for d in _DOMINIO_RUIDO):
        return "notificacao"
    if any(a in ass for a in _ASSUNTO_RUIDO):
        return "promocional"
    return None


EMAIL_PROMPT = """Analise este e-mail corporativo e classifique. Retorne SOMENTE JSON válido:

{{
  "resumo": "string (1-2 frases)",
  "temas": ["string"],
  "sentimento": "positivo|neutro|negativo",
  "categoria": "corporativo|promocional|notificacao|spam|pessoal",
  "relevante": true|false
}}

Regras:
- "corporativo": assunto de trabalho, decisão, tarefa, cliente, projeto interno.
- "promocional": marketing, newsletter, oferta, convite de produto.
- "notificacao": aviso automático de sistema (Teams, GitHub, banco, etc).
- "spam": não solicitado / suspeito.
- "pessoal": assunto pessoal legítimo.
- "relevante" = true apenas se "corporativo" ou "pessoal" acionável.

ASSUNTO: {assunto}
CONTEÚDO: {corpo}"""


def extrair_email(assunto: str, corpo: str, de_email: str = "") -> dict:
    vazio = {"resumo": "", "temas": [], "sentimento": "neutro",
             "categoria": "corporativo", "relevante": True}

    # camada 1: filtro rápido sem IA (economiza tokens)
    cat = pre_categoria(de_email, assunto)
    if cat is not None:
        return {
            "resumo": "",
            "temas": [],
            "sentimento": "neutro",
            "categoria": cat,
            "relevante": False,
        }

    # camada 2: IA
    try:
        raw = _chat(
            SYSTEM_PROMPT,
            EMAIL_PROMPT.format(assunto=assunto, corpo=corpo[:4000]),
            max_tokens=512,
        )
    except Exception:
        return vazio
    if raw is None:
        return vazio
    r = _parse_json(raw) or vazio
    r.setdefault("categoria", "corporativo")
    r.setdefault("relevante", r.get("categoria") in ("corporativo", "pessoal"))
    return r


# ── Resumo Diário ─────────────────────────────────────────────────────────────

RESUMO_DIARIO_PROMPT = """Com base nas decisões e pendências abaixo, escreva um resumo executivo
do dia em no máximo 5 frases. Foco em diretoria. PT-BR.

DECISÕES:
{decisoes}

PENDÊNCIAS SEM RESPONSÁVEL:
{pendencias}"""


def extrair_resumo_diario(decisoes: list, pendencias: list) -> str:
    if not decisoes:
        return ""

    sem_dono = [p for p in pendencias if not p.get("responsavel")]

    try:
        raw = _chat(
            "Você é um assistente executivo corporativo. Seja direto e objetivo.",
            RESUMO_DIARIO_PROMPT.format(
                decisoes="\n".join(f"- {d}" for d in decisoes[:20]),
                pendencias="\n".join(
                    f"- {p.get('tarefa', '')}" for p in sem_dono[:10]
                ),
            ),
            max_tokens=512,
        )
        return raw or ""
    except Exception:
        return ""