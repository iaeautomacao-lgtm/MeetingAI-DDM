# Log — 14/07/2026 — Allowlist de login (e-mail + senha própria)

## Contexto
Login era só senha-mestre única (`DIRECTOR_PASSWORD`). Pedido: só e-mails autorizados
acessam o painel, cada um com senha própria.

Decisões (Gih): allowlist em **tabela Supabase** + **e-mail + senha própria** (hash no banco).
Confirmado: manter senha-mestre como fallback; usuário define a própria senha no 1º acesso.

## O que foi feito

### 1. Tabela `painel_acessos` (Supabase, schema meeting_ai)
Adicionada em `schema.sql`. **A tabela É a allowlist** — só e-mail presente e `ativo=true` loga.
`senha_hash` null = ainda não definiu senha.
**Pendente rodar no Supabase (SQL Editor):**
```sql
set search_path to meeting_ai;
create table if not exists painel_acessos (
  id uuid primary key default gen_random_uuid(),
  email text unique not null, nome text default '',
  senha_hash text, ativo boolean default true,
  criado_em timestamptz default now()
);
create index if not exists idx_painel_acessos_email on painel_acessos (lower(email));
insert into painel_acessos (email, nome) values
  ('gisele.oliveira@ddm.adv.br', 'Gisele Oliveira') on conflict (email) do nothing;
```

### 2. Backend `app/auth/__init__.py` (reescrito)
- Hash com `werkzeug.security` (generate/check_password_hash).
- `_buscar_acesso` (case-insensitive) — **blindado** com try/except: tabela ausente/erro → não-permitido (nunca 500 no login).
- `verificar_login(email, senha)`, `precisa_definir_senha`, `definir_senha` (só 1º acesso, mín. 6 chars).
- `check_master_password` (ex-check_password; alias mantido p/ retrocompat).
- Sessão guarda `email` além de `diretor=True`. `sessao_email()`.

### 3. API `app/api/routes.py`
- `/api/auth/login` aceita `{email, senha}`. Ordem: master-só-senha → master+email permitido → email+senha própria → 403 `primeiro_acesso` se permitido sem senha → 401.
- Novo `/api/auth/registrar` (define senha 1º acesso, loga em seguida).
- `/api/auth/status` retorna `{autenticado, email}`.

### 4. Frontend `login.html`
- Campo E-mail + senha. Link "Primeiro acesso? Definir senha" alterna p/ form de criar senha (com confirmação).
- Se login devolve `primeiro_acesso`, troca automático p/ o form de definir senha.

## Validação
- Syntax OK (auth + routes). werkzeug hash OK.
- Server no ar (sem reloader). **Master login** → 200. **E-mail inexistente** → 401 (sem 500, após blindagem).
- **Falta e2e do fluxo e-mail+senha** — depende da tabela criada no Supabase. Depois: registrar senha → login → acessar /painel.

## Gestão da allowlist
Por SQL (insert/update/delete em painel_acessos). Desativar acesso: `update painel_acessos set ativo=false where email=...`.
Resetar senha de alguém: `update painel_acessos set senha_hash=null where email=...` (ela redefine no próximo acesso).
UI de gestão fica pra depois.

## Arquivos tocados
- schema.sql
- app/auth/__init__.py
- app/api/routes.py
- login.html
