"""
Identificação de locutores.

O Skribby entrega duas informações que ele mesmo não cruza:

- `participants[]` com os nomes reais de quem esteve na reunião;
- `transcript[].speaker` com rótulos de diarização ("1", "2", ...).

Não existe campo ligando um ao outro, nem evento de locutor ativo. Testado:
cruzar as falas com as janelas de microfone aberto (`muted`/`unmuted`) não
separa — quem nunca se muta tem janela cobrindo a reunião inteira.

Então o vínculo é inferido pela IA a partir do próprio diálogo (vocativos,
auto-apresentação, quem responde a quem) e, quando isso falha, corrigido à mão
no painel. Este módulo concentra as duas vias.
"""

import json
import re
import unicodedata

# Rótulos que significam "não sei quem é": aplicar o mapa só sobre eles.
SPEAKER_RE = re.compile(r"^\s*(speaker|locutor)\s*\d+\s*$", re.IGNORECASE)

NAO_IDENTIFICADO = ("?", "Locutor nao identificado", "Locutor não identificado")

# Abaixo disso o palpite da IA é descartado — melhor "Speaker 1" que nome errado.
CONFIANCA_MINIMA = 0.6


def rotulo_generico(speaker: str) -> bool:
    """True quando o rótulo é 'Speaker N' ou equivalente a desconhecido."""
    s = (speaker or "").strip()
    if not s or s in NAO_IDENTIFICADO:
        return True
    return bool(SPEAKER_RE.match(s))


def speakers_genericos(utterances: list) -> list:
    """Rótulos genéricos presentes nas utterances, na ordem de aparição."""
    vistos = []
    for u in utterances or []:
        s = (u.get("speaker") or "").strip()
        if s and rotulo_generico(s) and s not in vistos:
            vistos.append(s)
    return vistos


# Outros assistentes de reunião entram como participantes. Não são pessoas e
# não falam — atribuir fala a eles seria erro.
_ROBOS_RE = re.compile(
    r"notetaker|meeting notes|read\.ai|fathom|otter|fireflies|"
    r"transcri(be|ption)|\bbot\b|\bai\b",
    re.IGNORECASE,
)


def nomes_de_pessoas(nomes: list) -> list:
    """Descarta bots de anotação da lista de participantes."""
    return [n for n in (nomes or []) if n and not _ROBOS_RE.search(n)]


def rotulos_mapeaveis(rotulos: list, nomes: list) -> list:
    """
    Quais rótulos a IA pode nomear.

    "?" não é um locutor: é ausência de diarização — a transcrição inteira veio
    sem separação de vozes. Atribuir isso a alguém colocaria a fala de todos na
    boca de uma pessoa. Só vale quando existe exatamente um participante real.
    """
    numerados = [r for r in rotulos if not r.strip() in NAO_IDENTIFICADO]

    if numerados:
        return numerados

    if len(nomes) == 1:
        return list(rotulos)

    return []


def aplicar_mapa(utterances: list, mapa: dict) -> list:
    """Troca os rótulos pelos nomes do mapa. Não mexe em quem já tem nome."""
    if not mapa:
        return utterances

    saida = []
    for u in utterances or []:
        atual = (u.get("speaker") or "").strip()
        novo = mapa.get(atual)
        if novo and rotulo_generico(atual):
            u = dict(u)
            u["speaker"] = novo
        saida.append(u)
    return saida


def _normalizar(texto: str) -> str:
    """minúsculas sem acento, para comparar nomes."""
    t = unicodedata.normalize("NFKD", (texto or "").strip().lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def resolver_nome(resposta: str, nomes: list) -> str | None:
    """
    Casa o que a IA devolveu com um nome real da reunião.

    Aceita nome completo, primeiro nome ou apelido contido no nome
    ("Gabi" -> "Gabriella Cruz"), desde que a correspondência seja única.
    """
    alvo = _normalizar(resposta)
    if not alvo or not nomes:
        return None

    for nome in nomes:
        if _normalizar(nome) == alvo:
            return nome

    # Primeiro nome ou prefixo: só vale se apontar para um único participante.
    candidatos = [
        nome for nome in nomes
        if any(
            parte.startswith(alvo) or alvo.startswith(parte)
            for parte in _normalizar(nome).split()
            if len(parte) >= 3
        )
    ]
    if len(candidatos) == 1:
        return candidatos[0]

    return None


def _amostra_dialogo(utterances: list, limite: int = 9000) -> str:
    """
    Recorte do diálogo para o prompt: começo (onde estão cumprimentos,
    apresentações e vocativos) mais o final, se sobrar orçamento.
    """
    linhas = [
        "%s: %s" % (
            (u.get("speaker") or "?").strip(),
            (u.get("texto") or "").strip(),
        )
        for u in utterances or []
        if (u.get("texto") or "").strip()
    ]
    if not linhas:
        return ""

    inicio, usado = [], 0
    for linha in linhas:
        if usado + len(linha) > limite * 0.75:
            break
        inicio.append(linha)
        usado += len(linha) + 1

    fim, restante = [], limite - usado
    for linha in reversed(linhas[len(inicio):]):
        if len(linha) > restante:
            break
        fim.insert(0, linha)
        restante -= len(linha) + 1

    if fim:
        return "\n".join(inicio) + "\n[...]\n" + "\n".join(fim)
    return "\n".join(inicio)


# ── Via determinística: eventos de fala do Skribby ────────────────────────────
#
# Quando o bot roda com modelo realtime (ou `realtime_audio: true`), cada
# participante recebe eventos `started-speaking` / `stopped-speaking` com
# timestamp. Cruzando isso com o tempo de cada fala dá o vínculo exato, sem
# palpite. Com o modelo async esses eventos não vêm e cai-se na inferência.

# Fração mínima da fala do rótulo que precisa cair na janela do vencedor.
COBERTURA_MINIMA = 0.55
# Quanto o vencedor precisa superar o segundo colocado.
VANTAGEM_MINIMA = 1.5


def _inicio_gravacao(bot: dict) -> int | None:
    """Instante (epoch ms) a que os tempos da transcrição são relativos."""
    inicios = []

    for p in (bot or {}).get("participants") or []:
        for intervalo in p.get("presence_intervals") or []:
            valor = intervalo.get("joined_at")
            if isinstance(valor, (int, float)):
                inicios.append(int(valor))

    return min(inicios) if inicios else None


def _janelas_de_fala(participante: dict, fim_padrao: int) -> list:
    """Pares (início, fim) em que o participante estava falando."""
    eventos = sorted(
        (
            e for e in (participante.get("events") or [])
            if isinstance(e, dict)
            and isinstance(e.get("timestamp"), (int, float))
        ),
        key=lambda e: e["timestamp"],
    )

    janelas, aberta = [], None
    for e in eventos:
        tipo = (e.get("type") or "").lower()

        if tipo == "started-speaking":
            aberta = int(e["timestamp"])
        elif tipo == "stopped-speaking" and aberta is not None:
            janelas.append((aberta, int(e["timestamp"])))
            aberta = None

    if aberta is not None:
        janelas.append((
            aberta,
            int(participante.get("left_at") or fim_padrao),
        ))

    return janelas


def _sobreposicao(intervalos: list, janelas: list) -> float:
    total = 0.0
    for ini, fim in intervalos:
        for j0, j1 in janelas:
            total += max(0.0, min(fim, j1) - max(ini, j0))
    return total


def mapear_por_eventos_de_fala(bot: dict, utterances: list) -> dict:
    """
    Vincula rótulo -> nome cruzando o tempo das falas com os eventos
    started-speaking de cada participante. {} quando o Skribby não mandou
    esses eventos ou quando a sobreposição não é conclusiva.
    """
    t0 = _inicio_gravacao(bot)

    if t0 is None:
        return {}

    fim_padrao = t0
    for u in utterances or []:
        if isinstance(u.get("end_ms"), (int, float)):
            fim_padrao = max(fim_padrao, t0 + int(u["end_ms"]))

    janelas_por_nome = {}
    for p in (bot or {}).get("participants") or []:
        nome = _clean_nome(p.get("name") or "")
        if not nome or _ROBOS_RE.search(nome):
            continue

        janelas = _janelas_de_fala(p, fim_padrao)
        if janelas:
            janelas_por_nome[nome] = janelas

    if not janelas_por_nome:
        return {}  # sem eventos de fala: nada a cruzar

    intervalos_por_rotulo = {}
    for u in utterances or []:
        rotulo = (u.get("speaker") or "").strip()
        if not rotulo or not rotulo_generico(rotulo):
            continue

        ini, fim = u.get("start_ms"), u.get("end_ms")
        if not isinstance(ini, (int, float)) or not isinstance(fim, (int, float)):
            continue

        intervalos_por_rotulo.setdefault(rotulo, []).append(
            (t0 + int(ini), t0 + int(fim))
        )

    candidatos = []
    for rotulo, intervalos in intervalos_por_rotulo.items():
        duracao = sum(fim - ini for ini, fim in intervalos)
        if duracao <= 0:
            continue

        placar = sorted(
            (
                (_sobreposicao(intervalos, janelas), nome)
                for nome, janelas in janelas_por_nome.items()
            ),
            reverse=True,
        )

        melhor, nome = placar[0]
        segundo = placar[1][0] if len(placar) > 1 else 0.0

        if melhor / duracao < COBERTURA_MINIMA:
            continue
        if segundo > 0 and melhor < segundo * VANTAGEM_MINIMA:
            continue

        candidatos.append((melhor / duracao, rotulo, nome))

    candidatos.sort(reverse=True)

    mapa, usados = {}, set()
    for _, rotulo, nome in candidatos:
        if rotulo in mapa or nome in usados:
            continue
        mapa[rotulo] = nome
        usados.add(nome)

    return mapa


def _clean_nome(nome: str) -> str:
    from app.pipeline.skribby_client import _clean_participant_name

    return _clean_participant_name(nome)


PROMPT_LOCUTORES = """Você recebe a transcrição de uma reunião com os locutores \
rotulados por número (diarização automática) e a lista de quem realmente esteve \
na reunião. Descubra qual rótulo corresponde a qual pessoa.

Pistas confiáveis, em ordem de força:
1. Vocativo: alguém chama a pessoa pelo nome e OUTRO rótulo responde na sequência.
2. Auto-apresentação: o locutor diz o próprio nome.
3. Alguém é apresentado/agradecido e responde.
4. Papel na conversa: quem conduz, quem apresenta a tela, quem só responde.

Não invente. Só afirme o que o diálogo sustentar. Um rótulo por pessoa, sem repetir \
nome. Se não houver pista para um rótulo, devolva nome null.

PARTICIPANTES REAIS: {participantes}
RÓTULOS A IDENTIFICAR: {rotulos}

Responda SOMENTE este JSON, sem markdown:
{{
  "mapa": [
    {{"rotulo": "Speaker 1", "nome": "nome exato da lista ou null", \
"confianca": 0.0, "evidencia": "a frase curta que prova"}}
  ]
}}

TRANSCRIÇÃO:
{dialogo}"""


def identificar_locutores(bot: dict, utterances: list) -> tuple[list, dict, str]:
    """
    Põe nome real nos rótulos de diarização.

    Tenta primeiro os eventos de fala do Skribby (exato); se não vierem, infere
    pelo diálogo. Devolve (utterances, mapa, origem) — origem é "eventos", "ia"
    ou "" quando não deu para identificar.
    """
    from app.pipeline.skribby_client import extract_skribby_participants

    nomes = nomes_de_pessoas([
        p.get("nome")
        for p in extract_skribby_participants(bot)
        if p.get("nome")
    ])

    if not nomes:
        return utterances, {}, ""

    mapa = mapear_por_eventos_de_fala(bot, utterances)
    origem = "eventos" if mapa else ""

    if not mapa:
        mapa = mapear_com_ia(utterances, nomes)
        origem = "ia" if mapa else ""

    return aplicar_mapa(utterances, mapa), mapa, origem


def mapear_com_ia(utterances: list, nomes: list) -> dict:
    """
    Devolve {"Speaker 1": "Nome Real", ...} para os rótulos que a IA
    conseguiu identificar com confiança. {} quando não dá para decidir.
    """
    from app.pipeline.analysis import _chat, _parse_json

    nomes = nomes_de_pessoas([n for n in (nomes or []) if (n or "").strip()])
    rotulos = rotulos_mapeaveis(speakers_genericos(utterances), nomes)

    if not rotulos or not nomes:
        return {}

    dialogo = _amostra_dialogo(utterances)
    if not dialogo:
        return {}

    prompt = PROMPT_LOCUTORES.format(
        participantes=json.dumps(nomes, ensure_ascii=False),
        rotulos=json.dumps(rotulos, ensure_ascii=False),
        dialogo=dialogo,
    )

    try:
        raw = _chat(
            "Você identifica locutores em transcrições. Responde só JSON.",
            prompt,
            max_tokens=1024,
            json_mode=True,
        )
    except Exception:
        return {}

    if not raw:
        return {}

    dados = _parse_json(raw)
    if not isinstance(dados, dict):
        return {}

    itens = dados.get("mapa")
    if isinstance(itens, dict):  # modelo às vezes devolve objeto em vez de lista
        itens = [
            {"rotulo": k, **(v if isinstance(v, dict) else {"nome": v})}
            for k, v in itens.items()
        ]
    if not isinstance(itens, list):
        return {}

    # (rotulo, nome, confianca) válidos, melhor confiança primeiro.
    candidatos = []
    for item in itens:
        if not isinstance(item, dict):
            continue

        rotulo = str(item.get("rotulo") or "").strip()
        if rotulo not in rotulos:
            continue

        nome = resolver_nome(str(item.get("nome") or ""), nomes)
        if not nome:
            continue

        try:
            confianca = float(item.get("confianca"))
        except (TypeError, ValueError):
            confianca = 0.0

        if confianca < CONFIANCA_MINIMA:
            continue

        candidatos.append((confianca, rotulo, nome))

    candidatos.sort(reverse=True)

    mapa, usados = {}, set()
    for _, rotulo, nome in candidatos:
        if rotulo in mapa or nome in usados:
            continue  # 1 pessoa por rótulo, 1 rótulo por pessoa
        mapa[rotulo] = nome
        usados.add(nome)

    # Sobrou exatamente 1 rótulo e 1 nome: por eliminação, é ele.
    faltam_rotulos = [r for r in rotulos if r not in mapa]
    faltam_nomes = [n for n in nomes if n not in usados]
    if len(faltam_rotulos) == 1 and len(faltam_nomes) == 1:
        mapa[faltam_rotulos[0]] = faltam_nomes[0]

    return mapa
