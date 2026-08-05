# MEETING AI — Status do Projeto

> Documento de acompanhamento. Última atualização: **2026-07-06** (leitura inicial do código por Claude, a pedido da Gih).

---

## 1. O que é a ferramenta

Plataforma corporativa do Grupo DDM que **captura reuniões do Teams e e-mails do Outlook automaticamente**, transcreve, analisa com IA (Claude) e apresenta tudo em um dashboard executivo: decisões, pendências, sentimento, tópicos, grafo de interações entre pessoas e resumo diário para a diretoria.

### Arquitetura (stack)

| Camada | Tecnologia |
|--------|-----------|
| Web/API | Flask 3.1 (app factory) + Gunicorn |
| Fila/Agendador | Celery 5.4 + Celery Beat + Redis |
| Banco de dados | Supabase (Postgres) |
| Integração Microsoft | Microsoft Graph API (fluxo *app-only* / client credentials via MSAL) |
| Transcrição (fallback) | Azure Speech (upload manual de áudio) |
| IA / Análise | Anthropic Claude Haiku 4.5 |
| Frontend | HTML único (`meeting-ddm-dashboard.html`) servido pelo Flask |

### Fluxo de dados

```
Celery Beat (a cada 5 min)
   ├── sync_usuarios_ad        → Graph /users        → tabela usuarios (1x/h)
   ├── sync_reunioes_teams     → Graph onlineMeetings → tabela reunioes (pending)
   │        └── processar_reuniao_teams → busca VTT → parse → Claude → completed
   ├── sync_emails_outlook     → Graph /messages     → tabela emails (pending)
   │        └── processar_email → Claude → completed + grafo interacoes
   └── gerar_resumo_diario (18h) → agrega dia → tabela resumos_diarios

Upload manual de áudio → Azure Speech → Claude → reunioes
```

---

## 2. Estágio atual

**Resumo: MVP com código de backend + frontend ~escrito (~70%), mas 0% configurado/implantado/testado.** Ainda não roda ponta-a-ponta.

### ✅ Pronto (código existe)
- Estrutura Flask (factory, config, blueprint API, serve do dashboard)
- Todos os endpoints da API (`/api/health`, `/live/*`, `/dashboard*`, `/reunioes*`, `/emails`, `/setores`, `/usuarios`, `/interacoes`, `/sync/trigger`, upload de áudio)
- Todas as tasks Celery (sync usuários, reuniões, e-mails, resumo diário, áudio avulso)
- Cliente Microsoft Graph (token MSAL, paginação, usuários, reuniões, transcript VTT, e-mails, call records)
- Parser de VTT do Teams
- Transcrição Azure Speech (fallback)
- Análise com Claude (reunião, e-mail, resumo diário) com fallbacks quando sem API key
- Agendamento Celery Beat configurado
- Frontend dashboard consumindo a API (mesma origem, `BASE=''`)
- `Procfile` para deploy (web + worker)

### ❌ Pendente / faltando (bloqueia funcionamento)
1. **Schema do Supabase não existe** — nenhum arquivo SQL. Tabelas usadas pelo código precisam ser criadas: `reunioes`, `emails`, `usuarios`, `setores`, `interacoes`, `resumos_diarios`. **Bloqueador nº 1.**
2. **`.env` não configurado** — só existe `.env.example`. Faltam credenciais reais: Supabase, Azure (client id/secret/tenant), Azure Speech, Anthropic, Redis.
3. **Autenticação vazia** — `app/auth/__init__.py` está vazio. `.env` cita `AZURE_REDIRECT_URI=/auth/callback` mas **não existe rota de callback nem login**. O dashboard é aberto sem proteção.
4. **App Registration no Azure/Entra** não confirmado — precisa das permissões *Application* com consentimento de admin: `OnlineMeetings.Read.All`, `OnlineMeetingTranscript.Read.All`, `CallRecords.Read.All`, `Mail.Read`, `User.Read.All`.
5. **Auto-transcrição do Teams** precisa estar habilitada pelo admin (senão VTT vem vazio → status `sem_transcricao`).
6. **Redis** não provisionado (broker/backend Celery).
7. **Sem testes** automatizados.
8. **Sem README / instruções de deploy.**

### ⚠️ Riscos / bugs a revisar
- **Listagem de reuniões via Graph**: `get_meetings` usa `/users/{id}/onlineMeetings?$filter=startDateTime ge ...`. A API `onlineMeetings` do Graph **tem limitações** para listar por data — pode não retornar nada. Provável necessidade de usar `callRecords` ou outra estratégia. **Validar cedo.**
- ✅ **Chave com espaço** (resolvido 13/07/2026): análise agora usa `"decisoes"`, `_chat` força `response_format=json_object` (Gemini/OpenAI), `max_tokens` 4096, participantes derivados das utterances. Era a causa de "Não foi possível estruturar a análise".
- **`live_teams`**: dashboard mostra `m.participantes` como número, mas o campo é preenchido como lista (`participantes_ativos`). Inconsistência de contagem.
- **`gerar_resumo_diario`**: compara coluna `data` (timestamp) com string de data (`hoje`) no `.gte` — revisar se filtra corretamente.
- **Azure Speech**: `audio_duration_ms` sempre `None` → `duracao_minutos` fica nulo no upload manual.
- **Custo IA**: nenhuma limitação de volume/custo nas chamadas Claude.

---

## 3. Plano de execução (próximos passos)

### Fase 0 — Fundações (desbloquear execução local)
- [ ] Criar schema SQL do Supabase (6 tabelas + índices + constraints `on_conflict`). Salvar em `schema.sql`.
- [ ] Criar `.env` real a partir do `.env.example` com todas as credenciais.
- [ ] Subir Redis local (ou usar serviço gerenciado).
- [ ] Rodar `pip install -r requirements.txt` em venv.
- [ ] `flask run` + `celery worker -B` — confirmar que `/api/health` responde e beat agenda.

### Fase 1 — Integração Microsoft
- [ ] Confirmar App Registration com as 5 permissões *Application* + consentimento admin.
- [ ] Testar token MSAL (`_get_token`) isolado.
- [ ] Validar `get_users` (mais simples) → popular tabela `usuarios`.
- [ ] **Validar de fato** se `get_meetings` retorna reuniões; se não, corrigir estratégia (callRecords / subscription / delta).
- [ ] Confirmar auto-transcrição Teams habilitada → testar `get_transcript_vtt` numa reunião real.

### Fase 2 — Pipeline de análise
- [ ] Testar `extrair_reuniao` / `extrair_email` com transcrição/e-mail real.
- [ ] Padronizar chave `decisoes_estrategicas` (remover espaço) em analysis + tasks.
- [ ] Testar upload manual de áudio (Azure Speech) ponta-a-ponta.
- [ ] Corrigir `duracao_minutos` no fluxo de áudio.

### Fase 3 — Segurança / Auth
- [ ] Implementar login (proteger dashboard e API). Decisão: SSO Microsoft (rota `/auth/callback`) OU senha simples/token interno.
- [ ] Proteger endpoints `/api/*`.

### Fase 4 — Qualidade & Deploy
- [ ] Revisar/corrigir os bugs listados na seção ⚠️.
- [ ] Escrever README com passo-a-passo de setup.
- [ ] Testes básicos dos endpoints e do parser VTT.
- [ ] Deploy (Procfile já pronto — definir host: Railway/Render/Heroku-like) + Redis gerenciado + variáveis de ambiente.
- [ ] Monitorar custo Claude e definir limites.

---

## 3.1 PONTO ATUAL (2026-07-09) — DESATUALIZADO, VER 3.2/3.3

> ⚠️ Superado em 2026-07-10: abandonamos a via Microsoft Graph. Reuniões agora via **Recall.ai** (bot "DDM"), já testado e funcionando. Ver seções **3.2** (pivô) e **3.3** (teste e2e OK). O texto abaixo é histórico.

**Foco do projeto = REUNIÕES (Teams).** E-mail foi despriorizado pela Gih (funciona, mas não é o foco).

**Estado:** aguardando **Jair (TI)** criar a App Registration no Microsoft Entra. Mensagem enviada. Reuniões dependem 100% disso — sem as credenciais Microsoft, nada do Teams roda.

**Quando o Jair devolver os 3 valores** (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`):
1. Preencher no `.env`.
2. Rodar `python scripts/test_graph.py` → valida token + get_users + get_meetings.
3. **Atenção ao risco:** `get_meetings` (Graph `onlineMeetings` filtrado por data) pode não listar — validar cedo; se falhar, mudar estratégia.
4. Testar `get_transcript_vtt` numa reunião real (exige transcrição Teams ligada).
5. Rodar pipeline de reunião → dashboard.

**Alternativa oferecida e NÃO escolhida (por ora):** upload manual de gravação/transcript do Teams + transcrição via Gemini (funciona sem Microsoft). Gih preferiu esperar o Jair. Se mudar de ideia, é só construir o endpoint de upload trocando Azure Speech→Gemini.

**Config já pronta esperando:** Supabase (schema `meeting_ai`, funcionando), IA Gemini (`gemini-2.5-flash`, funcionando), IMAP e-mail (funcionando). Só falta a parte Microsoft.

## 3.2 PIVÔ (2026-07-10) — RECALL.AI substitui Microsoft Graph p/ reuniões

**Decisão da Gih:** abandonar dependência da API Microsoft (bloqueada no TI/Jair). Captura de reunião passa a ser **externa e acionada pelo funcionário** via **Recall.ai — Modo A (Meeting Bot API)**: funcionário cola o link da reunião no painel → bot **"DDM"** entra como participante → grava + transcreve → webhook → análise IA (**Gemini** por enquanto) → dashboard CEO.

**Custo Recall.ai (verificado 2026-07-10):** US$0,50/h gravação + US$0,15/h transcrição = ~**US$0,65/h**. Por segundo, sem mensalidade/mínimo, 5h grátis no signup. Storage 7 dias grátis (baixamos na hora → ignora). Ex.: 100 reuniões/mês (~1h) ≈ US$65/mês.

**Fluxo:** `POST /api/gravacoes {meeting_url,titulo}` → cria bot → insere reunião pending → (bot grava) → Recall chama `POST /api/recall/webhook` no evento `bot.done` → baixa transcript JSON → `extrair_reuniao` (Gemini) → Supabase completed → dashboard.

**IMPLEMENTADO (código, testado via smoke test — imports/rotas/parser OK):**
- `app/pipeline/recall_client.py` (novo) — `create_bot` (bot "DDM", `recallai_streaming`), `get_bot`, `bot_status`, `fetch_transcript` + `parse_recall_transcript` (converte segmentos Recall → utterances {speaker,texto,start_ms,end_ms}).
- `app/workers/tasks.py` — `_processar_recall` (sync, roda sem Redis) + task Celery `processar_gravacao_recall`.
- `app/api/routes.py` — `POST /api/gravacoes` (funcionário aciona), `POST /api/recall/webhook` (dispara processamento em thread, responde 200 <15s), `POST /api/gravacoes/<id>/processar` (puxa manual, p/ testar SEM webhook público).
- `app/config.py` + `.env` + `.env.example` — `RECALL_API_KEY`, `RECALL_REGION` (default `us-west-2` = pay-as-you-go), `RECALL_BOT_NAME=DDM`, `PUBLIC_BASE_URL`.
- `schema.sql` — coluna `reunioes.recall_bot_id` + índice + **ALTER** p/ tabela já criada no Supabase.
- `meeting-ddm-dashboard.html` — botão "+ Nova gravação" na página Reuniões + JS `novaGravacao()` (pede link + título, POST `/api/gravacoes`).

**Microsoft Graph (`graph.py`) e Azure Speech (`audio.py`):** ficam no repo mas **fora do fluxo de reunião** (não são mais dependência). E-mail IMAP intacto.

**PENDENTE p/ 1º teste e2e (do lado da Gih):**
1. Criar conta Recall.ai → colar `RECALL_API_KEY` no `.env`. (em andamento)
2. Rodar o ALTER no Supabase: `alter table reunioes add column if not exists recall_bot_id text;` (schema `meeting_ai`).
3. Subir Flask, abrir dashboard → "+ Nova gravação" → colar link de uma reunião real de teste. Bot "DDM" entra.
4. Ao fim da reunião: como não há webhook público ainda, chamar `POST /api/gravacoes/<reuniao_id>/processar` p/ puxar transcript → análise → dashboard. (Depois, no deploy, configurar webhook em recall.ai/dashboard/webhooks → `<PUBLIC_BASE_URL>/api/recall/webhook`.)

**Notas:** IA segue Gemini (`gemini-2.5-flash`) — OpenAI só quando houver chave válida (a testada deu 401). ⚠️ Segurança: Supabase service key, senha IMAP e chave Gemini reapareceram no chat — rotacionar.

## 3.3 TESTE E2E RECALL.AI — SUCESSO (2026-07-10)

**Fluxo Recall validado ponta-a-ponta.** Gih criou conta Recall (key região **us-east-1** — não us-west-2; corrigido `RECALL_REGION` no `.env`). ALTER `recall_bot_id` rodado no Supabase. Flask no ar (localhost:5000).

Teste real: Gih abriu reunião Teams, clicou "+ Nova gravação", colou link → bot **"DDM"** entrou, gravou, transcreveu. Reunião "Gelo" (bot done) processada via `POST /api/gravacoes/<id>/processar` → **status `completed`** com resumo executivo, tópicos, participantes+%fala (Gisele 85% / Oieee 15%), sentimento — tudo via **Gemini**. Apareceu no dashboard. ✅

**Lições:** (1) key Recall é atrelada a 1 região — testar auth em cada uma se der 401. (2) processar só após bot chegar em `done` (reunião encerrada); bot em `in_waiting_room`/`in_call_recording` ainda não tem transcript. (3) sem webhook público (localhost) o `bot.done` não chega → puxa manual pelo endpoint `/processar`.

**2º teste (mesma sessão) — OK.** Reunião "TESTE" (bot done) processada → `completed`: resumo, tópico "Finalização", **pendência detectada** ("Finalizar item não especificado", sem responsável), participante Gisele 100%. Dois testes seguidos sem falha. Pipeline sólido.

**Pendente p/ automático:** webhook público no deploy (ou ngrok) → configurar em recall.ai/dashboard/webhooks apontando `<PUBLIC_BASE_URL>/api/recall/webhook`. Aí funcionário aciona e aparece sozinho (hoje puxa manual via `/processar`).

**PRÓXIMO PASSO (quando a Gih quiser):** deploy (Procfile pronto) + Redis gerenciado + webhook Recall → fluxo 100% automático. Opcional: auth no dashboard (ainda aberto), trocar Gemini→OpenAI se houver chave válida.

## 3.4 DASHBOARD REMODELADO + RECUPERAÇÃO DE DADOS (2026-07-10)

**Novo design (Gih substituiu todo o HTML por layout estilo task-manager, Poppins/Inter, cartão flutuante creme, 3 colunas).** Era mockup 100% estático (avatars pravatar, tarefas/calendário/"Plano Pro" falsos, nav só trocava classe active). Claude reescreveu `meeting-ddm-dashboard.html` mantendo o visual mas tornando funcional:
- **Abas reais** (SPA): Dashboard · Reuniões · Transcrições · E-mails · Config + página Detalhe. `goto(page)` troca `.page.active` e chama o loader.
- Ligado à API: `/api/dashboard/summary`, `/api/reunioes`, `/api/reunioes/<id>`, `/api/emails`, `/api/health`.
- 3 KPI cards reais (reuniões/decisões/pendências), Reuniões Recentes, Estatísticas, Agenda (timeline por data), busca, filtro por setor, abas de categoria de e-mail.
- "+ Nova Reunião" → `novaReuniao()` (Recall). Botão "Puxar" → `/api/gravacoes/<id>/processar` em reuniões pending. Detalhe mostra transcrição/decisões/pendências/tópicos/participantes.
- Removido: avatars fake, banner "Plano Pro", dados mock. Mantido Google Fonts (CDN) — ok pois é servido pelo Flask (não é Artifact com CSP).

**PERDA DE DADOS detectada:** `reunioes`, `emails`, `usuarios` estavam ZERADOS no Supabase (só `interacoes`=34 sobreviveu). Causa provável: tabelas dropadas/recriadas ao aplicar a coluna `recall_bot_id` (o ALTER fornecido NÃO apaga; re-rodar schema com drop, sim). **Lição: usar só `ALTER TABLE ADD COLUMN`, nunca drop/re-rodar schema.**

**RECUPERAÇÃO:** gravações ainda existiam no Recall (storage 7 dias). Recriadas 2 reuniões `done` (bots b2903f21, a90c26c8) via insert + `_processar_recall` → `completed`. Dashboard repovoado (2 reuniões, 1 pendência). Bot 126cc969 seguia `in_call_recording` (travado, não recuperado).

## 3.5 AUTENTICAÇÃO + TELA PÚBLICA (2026-07-10)

**Separação de acesso:** funcionários comuns só registram reunião (sem ver dados); diretores logam e veem o dashboard completo.

- **`/` (público)** → `registrar.html`: formulário link + nome + **dropdown de setor** (via `/api/setores`) → `POST /api/gravacoes`. Zero dados expostos. Link discreto "Acessar painel executivo".
- **`/login`** → `login.html`: senha do diretor → `POST /api/auth/login` → sessão → redirect `/painel`.
- **`/painel` (protegido)** → dashboard; redireciona p/ `/login` se não autenticado.
- **`app/auth/__init__.py`**: `check_password` (hmac.compare_digest vs `DIRECTOR_PASSWORD`), `is_authed`, `login_session`, `logout_session`, `require_auth` (decorator).
- **`app/config.py`**: `DIRECTOR_PASSWORD`, cookies `HttpOnly`+`SameSite=Lax`+`Secure` (via `SESSION_COOKIE_SECURE`), sessão 8h.
- **`app/api/routes.py`**: `/auth/login|logout|status`. `@require_auth` em live/dashboard/reunioes/emails/usuarios/interacoes/upload/processar/sync. **Públicos:** `/health`, `/setores`, `/gravacoes` (funcionário registra), `/recall/webhook` (Recall chama).
- **Dashboard**: modal "Nova Reunião" com dropdown de setor (substitui prompts), botão **Sair**, redirect a `/login` em 401.
- **`.env`**: `DIRECTOR_PASSWORD` (valor redigido — TROCAR, esteve exposto no histórico) + `SESSION_COOKIE_SECURE=1`.

**Testado (curl, 8 casos):** público 200, /painel sem login → 302 /login, /api/reunioes sem login → 401, senha errada → 401, senha certa → 200 + cookie → /painel 200 + dados. Tudo OK.

**Nota segurança:** senha simples compartilhada (1 senha p/ toda diretoria). Suficiente p/ MVP interno. Evoluções possíveis: contas individuais, SSO Microsoft, rate-limit no login. Em produção: `SESSION_COOKIE_SECURE=1` (HTTPS) + trocar `SECRET_KEY` e `DIRECTOR_PASSWORD`.

## 3.6 EXTENSÃO CHROME (2026-08-05)

**Objetivo:** registrar reunião sem copiar/colar link. Funcionário está na aba da reunião → clica no ícone → popup já vem com link + título da aba → *Enviar Acordito*. Mesma chamada da tela `/` (`POST /api/gravacoes`).

**Criado `chrome-extension/`** (MV3, escopo só-popup, sem content script):
- `manifest.json` — permissões `activeTab` + `storage` + `clipboardRead`; `host_permissions` p/ `meeting.grupoddm.ia.br` + localhost; `optional_host_permissions` p/ outro host via runtime.
- `popup.html/.css/.js` — form com os mesmos campos de `registrar.html`; pré-preenche URL/título da aba, valida host contra a mesma lista do backend (`_MEETING_HOSTS`), botões *Usar aba atual* / *Colar link* (cobre reunião no app desktop do Teams, sem aba). Nome/setor/formato/local salvos em `chrome.storage.local`.
- `options.html/.js` — URL da API (default produção), nome padrão, *Testar conexão* (`/api/health`); pede permissão em runtime se o host não for um dos fixos.
- `shared.js`, `icons/icon.png` (cópia de `assets/logo-mark.png`), `README.md` (instalar, usar, limitações, opções de distribuição).

**Servidor — 1 mudança:** origem `chrome-extension://` é cross-origin, preflight batia sem handler. Adicionado CORS em `app/__init__.py` (`_cors_extensao`) **só** em `/api/health`, `/api/setores`, `/api/gravacoes` (já públicos), **sem** `Allow-Credentials` → cookie de diretor não trafega. Allowlist opcional `EXTENSION_ORIGINS` no `app/config.py` (vazio = qualquer extensão).

**Testado (curl, servidor local 5000):** preflight OPTIONS `/api/gravacoes` → 200 + headers CORS; `/api/health` e `/api/setores` com origem extensão → 200 + CORS; origem `https://evil.example` → 0 headers CORS; `/api/reunioes` com origem extensão → 401 **sem** CORS; POST com URL fora dos hosts → 400 `meeting_url inválido`. `node --check` OK nos 3 JS, manifest JSON válido.

**Instalada e funcionando** no Chrome da Gih (ID `lhamfoaglhifldglijnkcldohbnceomm` — instável, muda por máquina/pasta em extensão descompactada). Commit `eec5679` na `main`.

**Descoberta de deploy (2026-08-05):** produção **não** sai da branch `dist`. `GET /api/health` devolve `cwd=/home/grpia/repositories/MeetingAI-DDM1` e o HTML servido é o da `main` (a `dist` ainda está em Supabase; prod já em MySQL). Branch `dist` parada desde 17/07/2026 — **abandonada**. Deploy = `main` → cPanel *Update from Remote* no repo `MeetingAI-DDM1` → *Restart* do Python App.

**Pendente:** (1) *Update from Remote* + *Restart* no cPanel p/ o CORS valer em produção (até isso, o dropdown de setor da extensão vem vazio e o envio falha contra `meeting.grupoddm.ia.br`); (2) teste e2e real com bot entrando; (3) rate-limit em `/api/gravacoes` — endpoint público sem limite, vale p/ a tela `/` também; (4) decidir distribuição (zip manual / Web Store unlisted / política de grupo do TI).

## 3.7 NOMES REAIS NA TRANSCRIÇÃO (2026-08-05)

**Problema:** transcrições saíam com `Speaker 1` / `Speaker 2` em vez dos nomes. Investigado com o JSON real do bot `019fd2a8` (reunião "Curadoria do Sistema de Processos"):

- `participants[]` traz os nomes reais (`Christiano Di Maio`, `Gabriella Cruz`) com entrada/saída, mute/unmute e screenshare;
- `transcript[].speaker` traz só `"1"`, `"2"`;
- **não existe** campo ligando os dois, nem evento de locutor ativo. O código já tentava `speaker_name`, `potential_speaker_names` e mapa por ID — todos vazios. Limitação do Skribby, não bug nosso.

**Heurística de microfone testada e descartada:** cruzar falas com janelas `unmuted` não separa — quem nunca se muta tem janela cobrindo a reunião toda (Speaker 1: 100% dentro da janela do Christiano *e* 96,7% dentro da da Gabriella).

**Solução implementada — `app/pipeline/locutores.py` (novo):**
- `mapear_com_ia(utterances, nomes)` — manda o diálogo + a lista de participantes reais pro Gemini e pede o mapa `rótulo → nome`, usando vocativo ("Bora, **Gabi**" e outro rótulo responde), auto-apresentação e quem-responde-a-quem. Valida: nome tem de existir na lista (aceita primeiro nome/apelido se único), confiança ≥ 0.6, 1 rótulo por pessoa. Fecha por eliminação quando sobra 1 rótulo e 1 nome.
- `rotulos_mapeaveis()` — **`?` não é locutor, é ausência de diarização.** Mapear `?` colocaria a fala de todos na boca de um. Só permite quando há exatamente 1 participante real. (Pego na simulação: ia atribuir uma reunião de 3 pessoas inteira ao Marcelo.)
- `nomes_de_pessoas()` — descarta bots de anotação (read.ai, Fathom, Otter, "notetaker") da lista de candidatos.
- `aplicar_mapa()` — troca só rótulos genéricos, nunca nome já definido.

**`app/workers/tasks.py`:** `_processar_recall` chama o mapeamento antes de `extrair_reuniao`, então análise e % de fala já saem com nome real.

**Bug de raiz corrigido em `analysis.py`:** `gemini-2.5-flash` gasta `maxOutputTokens` com *thinking* e devolvia o JSON **cortado no meio** — era isso que zerava o mapeamento. Agora `thinkingConfig.thinkingBudget = 0` nos modelos 2.5, e `finishReason == MAX_TOKENS` virou exceção explícita em vez de JSON inválido silencioso. Provável causa também dos "Não foi possível estruturar a análise" antigos.

**Renomear à mão (painel):** `GET /api/reunioes/<id>/locutores` devolve os locutores atuais (com contagem de falas e flag `generico`) + candidatos buscados ao vivo no Skribby; `POST` recebe `{"mapa":{"Speaker 1":"Nome"}}` e reescreve `utterances` + `participantes`. Serve também para corrigir nome que a IA errou. Ambos `@require_auth` + filtro de setor. Card "Quem é quem na transcrição" abre sozinho quando há rótulo genérico; senão fica atrás do botão "Corrigir nomes".

**`scripts/mapear_locutores_existentes.py` (novo):** remapeia reuniões já no banco sem refazer resumo/decisões. Simula por padrão, grava com `--aplicar`.

**Testado:** mapa da IA na reunião real → `{'Speaker 1': 'Gabriella Cruz', 'Speaker 2': 'Christiano Di Maio'}` (bate com o vocativo). Pipeline completo reprocessado → `completed` com nomes. Endpoint: 401 sem login, 400 em nome repetido / locutor inexistente, 126 falas renomeadas no caso válido. `py_compile` nos 5 arquivos e `node --check` no JS do painel.

**Reuniões antigas:** das 12 concluídas, 8 já estão com nome. As 4 restantes vieram **sem diarização** (anteriores ao commit `7034358`, 2026-08-03) — rótulo único `?` com 2 a 8 participantes. Não há o que mapear; só re-transcrever resolveria, e as gravações provavelmente expiraram no Skribby.

### Documentação do Skribby lida (2026-08-05) — a causa é o modelo

`skribby.io/docs/guides/speaker-timelines` + `/realtime-transcription` + `/rest-api/bot-operations/createbot`:

- O Skribby **cruza o áudio com a lista de participantes da plataforma e troca "Speaker 1" pelo nome real** — mas isso é do fluxo **realtime**: modelo realtime (ex. `soniox/stt-rt-v5`) ou add-on `realtime_audio: true`.
- Participantes podem ter eventos **`started-speaking` / `stopped-speaking`** com timestamp.
- **Não existe** campo de "identificar locutor" no corpo de criação do bot. A alavanca é `transcription_model` ou `realtime_audio`.
- Nosso `soniox/stt-async-v5` é async → sem correlação, sem eventos de fala, `speaker_name` e `potential_speaker_names` vazios. Confirmado no payload real.

**Implementado para o teste:**
- `SKRIBBY_REALTIME_AUDIO=1` → manda `realtime_audio: true` na criação do bot. **Desligado por padrão** (é add-on cobrado à parte e a doc não garante que o nome persista no transcript guardado depois da reunião).
- `mapear_por_eventos_de_fala(bot, utterances)` — **via determinística**: cruza o tempo de cada fala com as janelas `started-speaking` de cada participante. Exige cobertura ≥ 55% e vantagem ≥ 1,5× sobre o segundo colocado; recusa em vez de chutar. `identificar_locutores()` tenta essa via primeiro e só cai na IA se ela não resolver.
- `scripts/inspecionar_bot_skribby.py <bot_id>` — radiografia: modelo, `realtime_audio`, tipos de evento por participante, quantos `speaker_name`/`potential_speaker_names` vieram, e o mapa que cada via produz.

**Testado:** bot async atual → "eventos started-speaking: NÃO", 0 `speaker_name`, mapa por IA correto. Via determinística validada em 4 casos sintéticos: mapeia certo com eventos; devolve `{}` para fala fora de janela, para payload sem eventos e para duas pessoas com janelas idênticas (ambíguo); bot de anotação (Otter) descartado.

**Teste pendente na Gih (localhost):** `SKRIBBY_REALTIME_AUDIO=1` no `.env`, reunião de teste, depois `python scripts/inspecionar_bot_skribby.py --ultima`. Se aparecer `started-speaking` ou `speaker_name`, o vínculo passa a ser exato e a IA fica só de reserva. Avaliar o custo do add-on antes de ligar em produção.

## 3.8 LIXEIRA DE REUNIÕES (2026-08-05)

**Excluir não apaga.** Marca `excluida_em` e a reunião sai na hora do painel, dos KPIs, da busca, do resumo diário e do detalhe — mas fica recuperável por 30 dias (`LIXEIRA_DIAS` no ambiente muda o prazo).

**Banco (migração aplicada em produção):** `migrations/2026-08-05_add_lixeira_reunioes.sql` — `excluida_em DATETIME NULL`, `excluida_por VARCHAR(190) NULL`, índice em `excluida_em`. Só `ADD COLUMN IF NOT EXISTS` (MariaDB 10.11). Conferido antes e depois: 15 reuniões intactas.

**Filtro `excluida_em IS NULL` aplicado em 10 consultas** — live Teams, em processamento, summary do dashboard, recentes, pendências, listagem, detalhe, locutores, processar manual (`routes.py`) e resumo diário (`tasks.py`). **Deixados de fora de propósito:** busca por `recall_bot_id` no webhook e dedup por `ms_meeting_id` — precisam ver o que está na lixeira para não reprocessar nem duplicar.

**Endpoints (todos `@require_admin`):**
- `POST /api/reunioes/<id>/excluir` → manda pra lixeira, grava quem excluiu
- `POST /api/reunioes/<id>/restaurar` → tira da lixeira
- `GET /api/lixeira` → lista com `dias_restantes` + `retencao_dias`
- `POST /api/lixeira/limpar` → esvazia **definitivamente**; com `{"somente_expiradas": true}` apaga só o que venceu

**Purga automática por duas vias:** task Celery `limpar_lixeira_expirada` (beat 03:30) **e** `purgar_lixeira_expirada()` chamada ao abrir a lixeira e ao excluir. A segunda existe porque o cPanel não mantém worker Celery vivo — sem ela o prazo de 30 dias nunca seria cumprido em produção.

**Painel:** item **Lixeira** na navegação (só admin, com contador), botão **Excluir** no detalhe da reunião, **Restaurar** por item e **Esvaziar agora** com dupla confirmação. Excluir também confirma antes.

**Decisão de permissão:** excluir/restaurar/esvaziar são **admin-only** (`require_admin`), não por setor. Apagar é destrutivo e usuário de setor escondendo reunião da diretoria seria pior que o incômodo de pedir a um admin. Para liberar por setor, trocar `@require_admin` por `@require_auth` + checagem de setor nos três endpoints.

**Testado (12 casos, servidor local contra o banco de produção):** excluir → sai da listagem (17→16), detalhe 404, locutores 404, KPIs recalculados, aparece na lixeira com `dias_restantes: 30` e autor; restaurar → volta (16→17); sem login → 401 em excluir e em lixeira. Esvaziar e purga por vencimento testados com **2 reuniões sintéticas** (`zz-teste-a` recente, `zz-teste-b` com `excluida_em` de 31 dias atrás), nunca com dado real: o `GET /api/lixeira` purgou sozinho a vencida, o esvaziar levou a outra, total voltou a 17 e nada real foi tocado.

## 4. Log de alterações
- **2026-07-06** — Leitura completa do código. Criação deste STATUS.md. Nenhuma alteração de código feita ainda.
- **2026-07-06** — Gih recebeu credencial **Global Admin** da organização. Criados: `schema.sql` (6 tabelas do Supabase inferidas do código) e `scripts/test_graph.py` (valida token MSAL + `get_users` + `get_meetings`). Fornecido passo-a-passo Azure (App Registration, secret, 5 permissões + consentimento admin, transcrição Teams, Application Access Policy via PowerShell). Aguardando `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` / `AZURE_TENANT_ID` p/ montar `.env` e testar.
- **2026-07-06** — **CORREÇÃO DE DOMÍNIO:** admin e usuários reais são `@ddm.adv.br` (não `grupoddm.com.br`). `.env` deve usar `TEAMS_DOMAIN=ddm.adv.br`. Confirmado via print do Teams Admin Center.
- **2026-07-06** — Conta admin correta: `gisele.oliveira@ddm.adv.br`, função **Administrador do Teams** (escopo Organização). Essa função basta p/ políticas Teams + Application Access Policy, mas **pode não bastar** p/ criar App Registration nem dar consentimento admin (precisa Application Admin / Global). Pendente: destravar senha da conta `@ddm.adv.br` (login em uso hoje é conta pessoal `@outlook.com` — não serve).
- **2026-07-06** — **Ambiente local rodando.** Python 3.14 detectado. Deps instaladas (exceto `azure-cognitiveservices-speech==1.41.0` — indisponível p/ 3.14; só afeta transcrição de áudio avulso). Flask sobe OK: `http://localhost:5000` → dashboard 200, `/api/health` OK. APIs de dados vazias (sem Supabase/credenciais ainda). Comando: `python -m flask --app run.py run --port 5000 --no-reload`.
- **2026-07-06** — **DESCOBERTA CRÍTICA: e-mail NÃO é Microsoft.** Print do webmail mostrou **cPanel/Roundcube** — e-mail `@ddm.adv.br` vive em hospedagem cPanel, não em Exchange/Microsoft 365. Confirmado com Gih: reuniões = Teams (Microsoft) ✅; e-mail = cPanel. **Impacto:** `sync_emails_outlook` (Microsoft Graph `/messages`) NÃO vai encontrar e-mails. A trilha de e-mail precisa ser **reescrita para IMAP** (cPanel). Reuniões Teams seguem via Graph.
- **2026-07-06** — **Plano dividido em 2 trilhas.** Trilha A (E-mail/cPanel via IMAP) — NÃO bloqueada, só precisa e-mail+senha+servidor IMAP (Gih já tem webmail funcionando). Trilha B (Teams/Microsoft) — bloqueada no acesso admin Microsoft (login `gisele.oliveira@ddm.adv.br` abre webmail cPanel mas não confirmado na Microsoft; senha do cPanel provavelmente ≠ senha Microsoft). Pendente: testar login Microsoft + dados do servidor IMAP cPanel (host/porta).
- **2026-07-08** — **Login Microsoft CONFIRMADO como bloqueado** (senha cPanel não abre `entra.microsoft.com`). Trilha B (Teams) depende 100% do TI criar a App Registration e devolver os 3 valores (mensagem pronta entregue à Gih).
- **2026-07-08** — **Trilha A (E-mail IMAP) IMPLEMENTADA e TESTADA.** Servidor: `mail.ddm.adv.br:993` SSL. Login OK, 1065 e-mails na INBOX. Criados/alterados:
  - `app/pipeline/imap_client.py` (novo) — conecta, busca desde data, parseia remetente/destinatários/assunto/corpo (com fallback HTML→texto), decode MIME.
  - `app/workers/tasks.py` — nova task `sync_emails_imap` (substitui Graph p/ e-mail; insere pending + chama `processar_email`). `sync_emails_outlook` mantida como fallback (não agendada).
  - `app/config.py` — vars IMAP + `CORP_DOMAINS` + `TEAMS_DOMAIN` default corrigido p/ `ddm.adv.br`.
  - `app/extensions.py` — beat agora agenda `sync-emails-imap` no lugar de outlook.
  - `.env.example` — vars IMAP.
  - `.gitignore` (novo) — protege `.env`, prints, uploads.
  - Descoberta: caixa recebe e-mails de `ddm.adv.br` E `grupoddm.com.br` (2 domínios corporativos → `CORP_DOMAINS`).
  - Teste `get_emails_imap` retornou 4 e-mails (3 dias) com campos corretos. `�` no terminal = só encoding do console Windows, dado salvo é UTF-8 OK.
  - **Limitação:** IMAP exige senha por caixa → cobre só contas configuradas (hoje: a da Gih). Multi-caixa exigiria mais credenciais ou admin cPanel.
  - **Falta p/ rodar e2e:** projeto Supabase + `schema.sql` aplicado + `ANTHROPIC_API_KEY` + `.env` preenchido.
- **2026-07-08** — **Supabase criado** (projeto `ddm lab`, schema `meeting_ai`, ref `uesongunmuiylltdvqjb`). 6 tabelas criadas via SQL limpo (versão ASCII — a decorada com box-chars dava erro 42601). Suporte a schema customizado no código: `SUPABASE_SCHEMA` em config + `ClientOptions(schema=...)` em extensions. **Pendente:** rodar `grant` de privilégios no schema (erro `42501 permission denied` até rodar) + expor `meeting_ai` em Settings→API.
- **2026-07-08** — **IA multi-provedor.** `analysis.py` reescrito p/ suportar OpenAI / Gemini / Anthropic (prioridade nessa ordem, detecta pela chave). Gemini usa endpoint OpenAI-compat. Chave OpenAI fornecida = **inválida (401)**. Chave Gemini fornecida = **funciona** com modelo `gemini-2.5-flash` (o `gemini-2.0-flash` foi descontinuado). Instalado `openai` 2.44.0. `.env` criado (local, gitignored) com Supabase + IMAP + Gemini. **Segurança:** chaves apareceram no chat — rotacionar depois.
- **2026-07-08** — **Pipeline de e-mail e2e RODANDO.** Grant aplicado, Supabase read/write OK. `scripts/run_email_sync.py` (novo) roda o fluxo sem Celery: IMAP→Supabase→Gemini→grafo. Testado: **10 e-mails reais analisados** (resumo+temas+sentimento) gravados no schema `meeting_ai`. Nota: prints no terminal quebram com emoji (cp1252) — usar `PYTHONUTF8=1`; dado gravado é UTF-8 OK.
- **2026-07-08** — **Filtro de ruído (promo/spam/notificação).** 2 camadas em `analysis.py`: (1) heurística grátis `pre_categoria` (remetente/domínio/assunto — no-reply, teams.mail, github, marketing, etc → pula IA); (2) IA classifica `categoria` (corporativo|promocional|notificacao|spam|pessoal) + `relevante` bool. Colunas `categoria`+`relevante` no schema (ALTER pendente na Gih). `/api/emails` filtra `relevante=true` por default (`?relevante=todos` traz tudo, `?categoria=`). Dashboard: abas por categoria (Relevantes/Notificações/Promoções/Spam/Todos), badge de categoria, ruído com opacidade. Testado nos 5 casos reais — classificou certo.
- **2026-07-08** — **Dashboard: logo + seção de e-mails.** Descoberto que o HTML não tinha seção de e-mail (backend servia, frontend não consumia). Feito: (1) rota Flask `/assets/<path>` serve logos; (2) logos DDM copiados do Design System p/ `assets/` (logo.png, logo-mark.png, logo-glyph-white.png); (3) `.logo-box` texto "DDM" → `<img>` logo-mark real; (4) nav item "E-mails" + `page-emails` + `loadEmails`/`filterSentimento`/`renderEmails` (cards com resumo, remetente, data, temas, badge de sentimento). Cor de marca já era `#FF5706` (correta). Gotcha: matar servidores antigos na porta 5000 antes de reiniciar (rota Python só recarrega em processo novo). Servidor limpo: assets/home/api todos HTTP 200.
