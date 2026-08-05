import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Provedor de IA (OpenAI / Gemini / Anthropic — detecta pela chave) ─────────
# Gemini usa o endpoint compatível com OpenAI, então compartilha o mesmo cliente.
_client = None
_provider = None  # "openai_like" | "gemini" | "anthropic"
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
        _client = gemini_key
        _provider = "gemini"
        _model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    elif anthropic_key:
        import anthropic
        _client = anthropic.Anthropic(api_key=anthropic_key)
        _provider = "anthropic"
        _model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")


def _chat(system: str, user: str, max_tokens: int = 2048, json_mode: bool = False) -> str | None:
    """Chamada unificada. Retorna o texto bruto da resposta ou None se sem provedor.
    json_mode=True força resposta JSON pura (OpenAI/Gemini) — evita texto/markdown ao redor."""
    _init_client()
    if _client is None:
        return None

    if _provider == "openai_like":
        kwargs = {
            "model": _model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = _client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()

    if _provider == "gemini":
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{_model}:generateContent"
        )
        payload = {
            "systemInstruction": {
                "parts": [{"text": system}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user}],
                }
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
            },
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        # Nos modelos 2.5 o "thinking" consome maxOutputTokens e a resposta sai
        # cortada no meio do JSON. Extração não precisa raciocínio longo.
        if "2.5" in (_model or ""):
            payload["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": 0
            }

        resp = requests.post(
            url,
            params={"key": _client},
            json=payload,
            timeout=60,
        )
        if not resp.ok:
            try:
                error = resp.json().get("error", {})
                detail = (
                    error.get("message")
                    or error.get("status")
                    or resp.reason
                )
            except Exception:
                detail = resp.reason
            raise RuntimeError(f"Gemini API {resp.status_code}: {detail}")

        data = resp.json()
        candidato = (data.get("candidates") or [{}])[0]

        # Sem isso a resposta cortada volta como JSON inválido e o erro real
        # ("estourou o limite de tokens") fica invisível.
        if candidato.get("finishReason") == "MAX_TOKENS":
            raise RuntimeError(
                "Gemini cortou a resposta no limite de tokens "
                f"(maxOutputTokens={max_tokens})."
            )

        parts = candidato.get("content", {}).get("parts", [])
        return "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict)
        ).strip()

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
  "decisoes": ["string"],
  "pendencias": [{{"tarefa": "string", "responsavel": "string ou null", "prazo": "string ou null"}}],
  "topicos": ["string"],
  "sentimento_geral": "positivo|neutro|tenso",
  "resumo_executivo": "string (max 3 frases, direto ao ponto para diretoria)"
}}

Regras:
- "decisoes": decisões concretas tomadas na reunião. [] se nenhuma.
- "pendencias": tarefas/ações a fazer. responsavel/prazo = null se não citado.
- "topicos": principais assuntos discutidos.
- Responda SOMENTE o JSON, sem markdown.

TRANSCRIÇÃO:
{transcricao}"""


def extrair_reuniao(transcricao: str, utterances: list) -> dict:
    if not transcricao.strip():
        return _empty_result()

    texto = _formatar_utterances(utterances) if utterances else transcricao
    prompt = EXTRACTION_PROMPT.format(transcricao=texto[:12000])
    participantes = _participantes_de_utterances(utterances)

    # Gemini/OpenAI ocasionalmente devolvem JSON malformado — tenta até 3x.
    ultimo_erro = "Não foi possível estruturar a análise."
    for _ in range(3):
        try:
            raw = _chat(SYSTEM_PROMPT, prompt, max_tokens=4096, json_mode=True)
        except Exception as e:
            ultimo_erro = f"Erro na análise: {str(e)}"
            continue

        if raw is None:
            r = _fallback_result("Análise indisponível: nenhuma chave de IA configurada (OPENAI_API_KEY ou ANTHROPIC_API_KEY).")
            r["participantes_ativos"] = participantes
            return r

        resultado = _parse_json(raw)
        if resultado is not None:
            resultado["participantes_ativos"] = participantes
            return resultado

    r = _fallback_result(ultimo_erro)
    r["participantes_ativos"] = participantes
    return r


def _participantes_de_utterances(utterances: list) -> list:
    """Deriva participantes + % de fala das utterances diarizadas."""
    if not utterances:
        return []
    fala_por_nome: dict[str, float] = {}

    for u in utterances:
        nome = (u.get("speaker") or "?").strip()
        if not nome or nome == "?":
            continue

        inicio = u.get("start_ms")
        fim = u.get("end_ms")
        duracao = 0

        if inicio is not None and fim is not None:
            try:
                duracao = max(0, float(fim) - float(inicio))
            except (TypeError, ValueError):
                duracao = 0

        fala_por_nome[nome] = fala_por_nome.get(nome, 0) + (duracao or 1)

    total = sum(fala_por_nome.values())
    if total == 0:
        return []

    return [
        {"nome": nome, "percentual_fala": round(valor * 100 / total)}
        for nome, valor in sorted(
            fala_por_nome.items(),
            key=lambda kv: kv[1],
            reverse=True,
        )
    ]


def _formatar_utterances(utterances: list) -> str:
    return "\n".join(
        f"[Speaker {u.get('speaker', '?')}]: {u.get('texto', '')}"
        for u in utterances
    )


def _empty_result() -> dict:
    return {
        "decisoes": [],
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
