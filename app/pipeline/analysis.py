# Anotacoes adiadas: "X | None" (PEP 604) so avalia em runtime a partir
# do Python 3.10, e o interpretador do cPanel e mais antigo. Sem isso o
# app quebra no import em producao.
from __future__ import annotations

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
  "resumo_executivo": "string (max 3 frases, direto ao ponto para diretoria)",
  "key_takeaways": ["string"],
  "decisoes": [{{"decisao": "string", "tipo": "aprovada|recusada|alterada", "responsavel": "string ou null"}}],
  "pendencias": [{{"tarefa": "string", "responsavel": "string ou null", "prazo": "string ou null", "urgencia": "alta|media|baixa", "status": "pendente|em_andamento|concluida"}}],
  "riscos": [{{"titulo": "string", "detalhe": "string", "gravidade": "alta|media|baixa"}}],
  "perguntas_abertas": [{{"pergunta": "string", "quem_perguntou": "string ou null"}}],
  "clima": {{"tipo": "consensual|conflituosa|informativa|negociacao", "justificativa": "string (1 frase)"}},
  "topicos": ["string"],
  "sentimento_geral": "positivo|neutro|tenso"
}}

Regras:
- "key_takeaways": 3 a 5 bullets no estilo TL;DR — o que alguém precisa saber
  em 30 segundos sem ler o resto. Cada bullet uma frase, com o desfecho, não o
  assunto ("Fechado aumento de 8% na tabela" e não "Falou-se de preços").
- "decisoes": só o que foi de fato decidido. "tipo" = aprovada (seguir adiante),
  recusada (descartado) ou alterada (mudou algo que já existia). [] se nenhuma.
- "pendencias": tarefas a fazer, no formato [Quem] faz [O quê] até [Quando].
  responsavel/prazo = null se não citado — NÃO invente nome nem data.
  "urgencia": alta se tem prazo curto/bloqueia alguém; baixa se é desejável.
  "status": pelo que foi dito na reunião (em_andamento se já começou).
- "riscos": gargalos, prazos apertados, dependência de terceiro, divergência
  entre participantes, decisão adiada que trava trabalho. [] se nada relevante.
  Não repita pendência comum aqui — risco é o que pode dar errado.
- "perguntas_abertas": dúvidas levantadas que ninguém respondeu até o fim.
  Só o que ficou mesmo sem resposta. [] se todas foram respondidas.
- "clima": como a conversa transcorreu. consensual (todos alinhados),
  conflituosa (divergência explícita), informativa (um apresenta, outros ouvem),
  negociacao (partes buscando acordo com interesses distintos).
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
            resultado = normalizar_analise(resultado)
            resultado["participantes_ativos"] = participantes
            return resultado

    r = _fallback_result(ultimo_erro)
    r["participantes_ativos"] = participantes
    return r


PERGUNTA_PROMPT = """Responda à pergunta usando SOMENTE a transcrição abaixo.

Cada fala está numerada. Responda em português-BR, direto, em no máximo 4 frases,
e aponte os números das falas que sustentam a resposta.

Se a transcrição não responder à pergunta, diga isso claramente em "resposta" e
devolva "trechos": []. Não deduza o que não foi dito, não invente prazo, valor
nem nome.

Responda SOMENTE este JSON, sem markdown:
{{"resposta": "string", "trechos": [0]}}

PERGUNTA: {pergunta}

TRANSCRIÇÃO:
{transcricao}"""


def perguntar_sobre_reuniao(pergunta: str, utterances: list) -> dict:
    """
    Busca semântica na transcrição: responde e devolve os índices das falas
    que sustentam a resposta, para o painel poder destacá-las.
    """
    pergunta = (pergunta or "").strip()

    if not pergunta:
        return {"resposta": "", "trechos": []}

    if not utterances:
        return {
            "resposta": "Esta reunião não tem transcrição para consultar.",
            "trechos": [],
        }

    linhas = []
    total = 0

    for i, u in enumerate(utterances):
        texto = (u.get("texto") or "").strip()
        if not texto:
            continue

        linha = "[%d] %s: %s" % (i, (u.get("speaker") or "?").strip(), texto)

        # Orçamento de contexto: transcrição longa é cortada pelo fim.
        if total + len(linha) > 28000:
            break

        linhas.append(linha)
        total += len(linha) + 1

    prompt = PERGUNTA_PROMPT.format(
        pergunta=pergunta[:500],
        transcricao="\n".join(linhas),
    )

    try:
        raw = _chat(
            "Você responde perguntas sobre reuniões citando a transcrição. Só JSON.",
            prompt,
            max_tokens=1024,
            json_mode=True,
        )
    except Exception as e:
        return {"resposta": f"Erro ao consultar o Acordito: {e}", "trechos": []}

    if not raw:
        return {
            "resposta": "Acordito indisponível: nenhum provedor de IA configurado.",
            "trechos": [],
        }

    dados = _parse_json(raw) or {}

    trechos = []
    for t in (dados.get("trechos") or []):
        try:
            indice = int(t)
        except (TypeError, ValueError):
            continue
        if 0 <= indice < len(utterances) and indice not in trechos:
            trechos.append(indice)

    return {
        "resposta": (dados.get("resposta") or "").strip()
                    or "Não consegui responder com base nesta transcrição.",
        "trechos": trechos[:8],
    }


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
        "key_takeaways": [],
        "riscos": [],
        "perguntas_abertas": [],
        "clima": {},
        "sentimento_geral": "neutro",
        "resumo_executivo": "",
    }


def normalizar_analise(resultado: dict) -> dict:
    """
    Garante o formato esperado pelo painel, venha o que vier do modelo.

    A IA às vezes devolve string onde se pediu objeto (e vice-versa), e as
    reuniões analisadas antes desta versão têm `decisoes` como lista de texto.
    Sem isso o front quebraria em campo faltando ou tipo trocado.
    """
    base = _empty_result()
    base.update(resultado or {})

    def lista(chave):
        valor = base.get(chave)
        return valor if isinstance(valor, list) else []

    base["key_takeaways"] = [
        t.strip() for t in lista("key_takeaways")
        if isinstance(t, str) and t.strip()
    ][:5]

    decisoes = []
    for d in lista("decisoes"):
        if isinstance(d, str) and d.strip():
            decisoes.append({"decisao": d.strip(), "tipo": "aprovada"})
        elif isinstance(d, dict) and (d.get("decisao") or d.get("texto")):
            tipo = str(d.get("tipo") or "aprovada").lower()
            decisoes.append({
                "decisao": (d.get("decisao") or d.get("texto")).strip(),
                "tipo": tipo if tipo in ("aprovada", "recusada", "alterada") else "aprovada",
                "responsavel": d.get("responsavel") or None,
            })
    base["decisoes"] = decisoes

    pendencias = []
    for p in lista("pendencias"):
        if isinstance(p, str) and p.strip():
            p = {"tarefa": p.strip()}
        if not isinstance(p, dict) or not (p.get("tarefa") or "").strip():
            continue

        urgencia = str(p.get("urgencia") or "media").lower()
        status = str(p.get("status") or "pendente").lower()

        pendencias.append({
            "tarefa": p["tarefa"].strip(),
            "responsavel": p.get("responsavel") or None,
            "prazo": p.get("prazo") or None,
            "urgencia": urgencia if urgencia in ("alta", "media", "baixa") else "media",
            "status": status if status in ("pendente", "em_andamento", "concluida") else "pendente",
            "concluida_por": p.get("concluida_por") or None,
            "concluida_em": p.get("concluida_em") or None,
        })
    base["pendencias"] = pendencias

    riscos = []
    for r in lista("riscos"):
        if isinstance(r, str) and r.strip():
            r = {"titulo": r.strip()}
        if not isinstance(r, dict) or not (r.get("titulo") or "").strip():
            continue

        gravidade = str(r.get("gravidade") or "media").lower()
        riscos.append({
            "titulo": r["titulo"].strip(),
            "detalhe": (r.get("detalhe") or "").strip(),
            "gravidade": gravidade if gravidade in ("alta", "media", "baixa") else "media",
        })
    base["riscos"] = riscos

    perguntas = []
    for q in lista("perguntas_abertas"):
        if isinstance(q, str) and q.strip():
            q = {"pergunta": q.strip()}
        if not isinstance(q, dict) or not (q.get("pergunta") or "").strip():
            continue

        perguntas.append({
            "pergunta": q["pergunta"].strip(),
            "quem_perguntou": q.get("quem_perguntou") or None,
        })
    base["perguntas_abertas"] = perguntas

    clima = base.get("clima")
    if isinstance(clima, str):
        clima = {"tipo": clima}
    if not isinstance(clima, dict):
        clima = {}

    tipo = str(clima.get("tipo") or "").lower()
    base["clima"] = {
        "tipo": tipo if tipo in ("consensual", "conflituosa", "informativa", "negociacao") else "",
        "justificativa": (clima.get("justificativa") or "").strip(),
    }

    base["topicos"] = [
        t.strip() for t in lista("topicos")
        if isinstance(t, str) and t.strip()
    ]

    return base


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
