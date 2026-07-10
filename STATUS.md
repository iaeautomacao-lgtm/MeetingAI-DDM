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
- **Chave com espaço**: a análise retorna `"decisoes estrategicas"` (com espaço) — consistente no código, mas frágil/typo. Padronizar para `decisoes_estrategicas`.
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
