# LOG 2026-07-17 — Auditoria de Segurança (MEETING AI)

Varredura de todo o código (Flask/Celery/Supabase + frontend HTML). Abaixo:
vulnerabilidades encontradas, severidade, correção aplicada e verificação.

## Resumo por severidade

| # | Severidade | Local | Problema | Status |
|---|-----------|-------|----------|--------|
| 1 | **CRÍTICO** | `app/config.py:8` | `SECRET_KEY` default `"dev-inseguro"` → cookie de sessão forjável → bypass total de login (forja `admin=True`) | ✅ corrigido |
| 2 | **ALTO** | `meeting-ddm-dashboard.html:506` | `esc()` não escapa aspa simples `'` → XSS armazenado no painel admin via e-mail/setor do auto-cadastro | ✅ corrigido |
| 3 | MÉDIO | `app/config.py:18` | `SESSION_COOKIE_SECURE` default `0` → cookie de sessão trafega em HTTP | ✅ corrigido |
| 4 | MÉDIO | `app/__init__.py` | Sem cabeçalhos de segurança (clickjacking, sniffing, CSP) | ✅ corrigido |
| 5 | MÉDIO | `run.py:6` | `debug=True` fixo → Werkzeug debugger (RCE) se rodar direto em prod | ✅ corrigido |
| 6 | MÉDIO | `app/api/routes.py:361` | Upload sem limite de tamanho → DoS por upload gigante | ✅ corrigido |
| 7 | MÉDIO | `app/api/routes.py:402` | `/gravacoes` público sem validar `meeting_url` → abuso/SSRF (bot entra em URL arbitrária) | ✅ corrigido |
| 8 | BAIXO-MÉDIO | `app/api/routes.py:443` | Webhook Skribby sem autenticação | ✅ corrigido (segredo opcional) |
| 9 | BAIXO | `registrar.html:85` | `innerHTML` com trecho dinâmico (msg de erro) | ✅ corrigido |
| 10 | NOTA | `schema.sql` | Sem RLS no Postgres — service key é única defesa | ⚠ recomendação |
| 11 | NOTA | `app/api/routes.py:538` | `/usuarios` vaza nome/e-mail de todos os setores p/ qualquer autenticado | ⚠ recomendação |
| 12 | NOTA | login/registrar | Sem rate limit → brute force de senha e flood de `/gravacoes` | ⚠ recomendação |

## Detalhe das correções

### 1. SECRET_KEY (CRÍTICO)
Default `"dev-inseguro"` é público (está no repo). Flask assina o cookie de sessão
com ela; quem souber a chave forja um cookie com `diretor=True, admin=True,
acesso_total=True` e entra como diretor sem senha.
**Fix:** sem default fraco. Se `SECRET_KEY` não estiver no ambiente, gera chave
aleatória forte (`secrets.token_hex(32)`) por processo + warning. Recomendado
setar `SECRET_KEY` fixa no `.env`/painel para as sessões persistirem entre restarts.

### 2. XSS armazenado no painel admin (ALTO)
`esc()` escapava só `& < > "`, não `'`. Vários handlers no dashboard interpolam
dados dentro de string entre aspas simples:
`onclick="aprovar('${esc(a.email)}')"`, idem `setor`.
O auto-cadastro (`/api/auth/registrar`) é público e só valida o **domínio** do
e-mail (parte depois do `@`); a parte local e o `setor` são texto livre. Atacante
registra `x');fetch(...)//@ddm.adv.br` (ou setor idem) → quando o admin abre a aba
"Acessos", o JS executa no navegador do admin (roubo de sessão/ações admin).
**Fix:** `esc()` passa a escapar também `'` → `&#39;` e `` ` `` → `&#96;`.

### 3. SESSION_COOKIE_SECURE (MÉDIO)
Default agora é seguro em produção (`FLASK_ENV != development`). Override por env mantido.

### 4. Cabeçalhos de segurança (MÉDIO)
`after_request` adiciona: `X-Frame-Options: DENY` (anti-clickjacking),
`X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy` e uma
`Content-Security-Policy` que bloqueia scripts externos injetados e enquadramento
(`frame-ancestors 'none'`), permitindo o inline atual + Google Fonts.

### 5. debug=True (MÉDIO)
`run.py` agora liga debug só quando `FLASK_ENV=development`.

### 6. Limite de upload (MÉDIO)
`MAX_CONTENT_LENGTH` (default 200 MB, configurável via `MAX_UPLOAD_MB`).

### 7. Validação de meeting_url (MÉDIO)
`/gravacoes` agora exige URL http(s) de provedor conhecido
(teams.microsoft.com/live, zoom.us, meet.google.com, webex.com). Bloqueia
`javascript:`, `file:`, IP/host interno e URLs arbitrárias.

### 8. Webhook Skribby (BAIXO-MÉDIO)
Se `SKRIBBY_WEBHOOK_SECRET` estiver setado, o token é enviado no `webhook_url`
(query) ao criar o bot e verificado (tempo constante) na entrada do webhook.
Sem o segredo setado, comportamento inalterado (retrocompat).

## ⚠ AÇÃO MANUAL PENDENTE — segredos fracos no .env de produção (CRÍTICO)

Decisão da Gih: **não mexer nos segredos do .env** (troca manual). Domínio de
produção confirmado: `https://meeting.grupoddm.ia.br`. Trocar o quanto antes:

1. **`SECRET_KEY`** está como string previsível (placeholder de dev — valor
   redigido). Com ela é possível **forjar o cookie de sessão e entrar como
   admin**. Gerar chave forte e substituir:
   ```
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
   (Ao trocar, todas as sessões atuais caem — esperado.)

2. **`DIRECTOR_PASSWORD`** (valor redigido) é a senha-mestre de diretor
   (admin total, sem e-mail). Fraca/adivinhável **e já exposta no histórico do
   git** (ver item 4). Trocar por senha forte e comunicar aos diretores por
   canal seguro. (Ou esvaziar `DIRECTOR_PASSWORD=` para desabilitar o
   login-mestre, se ninguém mais usa.)

4. **VAZAMENTO EM HISTÓRICO (grave):** `STATUS.md` commitou a senha real do
   diretor no commit `e3cee80`. Mesmo redigindo o arquivo agora, o valor
   permanece acessível no histórico do GitHub. Ações: (a) trocar a
   `DIRECTOR_PASSWORD` obrigatoriamente; (b) se o repo for público ou sensível,
   limpar o histórico com `git filter-repo`/BFG e forçar push; (c) revisar se o
   repo pode ser tornado privado.

3. **`SUPABASE_SERVICE_KEY`**: está só no `.env` (não commitado — ok). É service_role
   (ignora RLS). Se vazar = banco inteiro. Não expor no frontend; considerar RLS.

## Aplicado no .env (autorizado)
- `FLASK_ENV=development` → **`production`** (desliga debug tooling).
- `SESSION_COOKIE_SECURE=0` → **`1`** (cookie de sessão só via HTTPS).
- Segredos (SECRET_KEY / DIRECTOR_PASSWORD) **não alterados** (troca manual — ver acima).

## Recomendações não aplicadas (precisam de infra/decisão)
- **RLS no Supabase**: habilitar Row Level Security nas tabelas como defesa em
  profundidade — hoje o vazamento da service key = banco inteiro.
- **Rate limiting**: `/api/auth/login` (brute force) e `/api/gravacoes` (flood /
  gasto de créditos Skribby). Requer Redis/limiter.
- **/usuarios**: filtrar por setor para usuário comum.
- **Política de senha**: mínimo 6 é fraco; considerar 10+.

## Verificação
- Import do app / compileall dos módulos Python: OK.
- Revisão manual dos diffs (abaixo).
