# Log — 13/07/2026 — Correção análise IA + setor Diretores + copiar/exportar

## Contexto
Dashboard trazia só transcrição; decisões/pendências/tópicos/participantes/resumo vinham vazios
("Não foi possível estruturar a análise"). Pedido: (1) setor Diretores, (2) corrigir análise,
(3) botão copiar tudo / exportar transcrição.

## O que foi feito

### 1. Setor "Diretores"
- `schema.sql`: add seed `('Diretores', '#8b5cf6')`.
- **Pendente rodar no Supabase (SQL Editor):**
  ```sql
  set search_path to meeting_ai;
  insert into setores (nome, cor) values ('Diretores', '#8b5cf6') on conflict do nothing;
  ```
- Form registrar + chips dashboard leem `/api/setores` → aparecem sozinhos após o insert.

### 2. Análise vazia (causa raiz)
`app/pipeline/analysis.py`:
- `_chat()`: novo param `json_mode` → força `response_format={"type":"json_object"}` (Gemini/OpenAI).
  Era a causa do parse falhar (modelo embrulhava em markdown).
- Prompt: chave `"decisoes estrategicas"` (com espaço) → `"decisoes"` + regras explícitas.
- `extrair_reuniao`: `json_mode=True`, `max_tokens` 2048→4096.
- Participantes agora derivados das `utterances` (speakers + % por contagem), não do modelo.
- Removido `_get_client()` morto (NameError potencial — `anthropic` sem import).
- `_empty_result`: chave `decisoes`.

`app/workers/tasks.py`: 3 leitores `analise.get("decisoes estrategicas")` → `"decisoes"`
(processar_reuniao_teams, _processar_recall, processar_audio_avulso).

### 3. Copiar / Exportar transcrição
`meeting-ddm-dashboard.html` (tela detalhe):
- Global `_reuniaoAtual`.
- Botões "Copiar tudo" + "Exportar" ao lado do título Transcrição.
- Copiar: `navigator.clipboard` (fallback textarea) → "Copiado ✓".
- Exportar: relatório .txt completo (título, setor, data, resumo, decisões, pendências,
  tópicos, participantes, transcrição). Nome `{titulo}.txt`.

## Validação (feita, e2e real)
- Setor Diretores inserido no Supabase live (`/api/setores` retorna Diretores).
- **Time IA** reprocessada: 2 decisões, 7 pendências, 6 tópicos, 3 participantes, resumo ✅.
- **Reunião Executiva** reprocessada: 2 decisões, 2 pendências, 4 tópicos, 3 participantes, resumo ✅.
- `_parse_json` tolera markdown ```json.

## GOTCHA importante (custou tempo)
Reunião Executiva falhava no reprocess pela API, mas o pipeline funcionava em teste direto.
Causa: **Flask debug reloader** (`app.run(debug=True)` em run.py) reiniciava o servidor NO MEIO
da requisição — watchdog do Windows detecta "mudança" em stdlib (`xml/etree`) e faz reload,
matando `_processar_recall` no meio → gravava resultado parcial/fallback.
**Fix operacional**: rodar sem reloader:
`python -c "from app import create_app; create_app().run(port=5000, debug=False, use_reloader=False)"`
Além disso, add **retry 3x** em `extrair_reuniao` contra JSON malformado ocasional do Gemini.

## Falta / próximo
- Deploy + webhook público (100% automático) — ainda pendente.
- Considerar rodar dev server sempre sem reloader (ou trocar por waitress) p/ evitar o gotcha.

## Arquivos tocados
- schema.sql, STATUS.md
- app/pipeline/analysis.py
- app/workers/tasks.py
- meeting-ddm-dashboard.html

---

# Parte 2 — Acordito (mascote) — 14/07/2026

Fonte: `assets/Acordito.jpeg` (coruja laranja de terno, crachá DDM; 682x1024).

## A. Bot renomeado DDM → Acordito
- `app/config.py`: `RECALL_BOT_NAME` default → "Acordito".
- `app/pipeline/recall_client.py`: `_bot_name()` default → "Acordito" + docstring.
- `.env` e `.env.example`: `RECALL_BOT_NAME=Acordito`.

## B. Blob azul da sidebar → imagem Acordito
- `meeting-ddm-dashboard.html`: `<svg class="sidebar-deco">` (blob #5EC4CD) → `<img class="sidebar-deco" src="/assets/Acordito.jpeg">`.
- CSS: width 140px, `mix-blend-mode:multiply` (funde o fundo cinza da imagem no branco da sidebar).
- Servido pela rota `/assets/<file>` que já existia. Verificado live (HTTP 200, HTML atualizado).

## C. Avatar do bot na câmera ao entrar na reunião
- Recall.ai suporta via `automatic_video_output` no create bot (base64 — **funciona no localhost**, não precisa URL pública).
- Requisito: JPEG **16:9 / 1280x720 / <=1.3MB**. Acordito é retrato → gerado avatar landscape.
- `scripts/make_bot_avatar.py`: centraliza Acordito em canvas 1280x720 com fundo amostrado do canto (blend). Saída `assets/acordito_bot.jpg` (45KB). Rodar de novo se trocar a fonte.
- `recall_client.create_bot`: carrega o avatar, base64, injeta `automatic_video_output.{in_call_recording,in_call_not_recording}`. Gracioso — só adiciona se o arquivo existe.
- Validado: bot_name=Acordito, avatar carrega, payload monta com `kind:jpeg`. **Ainda NÃO testado com bot real** (precisa reunião ao vivo + créditos Recall) — próxima reunião que o bot entrar mostra o avatar.

## Docs Recall consultadas
- https://docs.recall.ai/docs/output-video-in-meetings
- https://docs.recall.ai/reference/bot_output_media_create
