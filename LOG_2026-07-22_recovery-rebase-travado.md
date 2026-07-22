# LOG 2026-07-22 — Recovery de rebase travado (app não subia)

## Sintoma
Gih pediu o localhost. `http://localhost:5000` não respondia. Server não subia.

## Causa raiz
Havia um **rebase interativo pausado no meio** (`.git/rebase-merge` presente),
parado no commit `e3cee80` ("feat: análise IA robusta, allowlist de login,
mascote Acordito e docs"), replayado em cima da `main` atual (`e77c031`).

Isso deixou **53 marcadores de conflito** (`<<<<<<<` / `=======` / `>>>>>>>`)
dentro de 8 arquivos rastreados. Em `app/config.py:29` os marcadores viravam
`SyntaxError: invalid syntax` → Flask não conseguia importar o app → boot falhava.

Arquivos em conflito: `.env.example`, `STATUS.md`, `app/api/routes.py`,
`app/auth/__init__.py`, `app/config.py`, `meeting-ddm-dashboard.html`,
`login.html` (AA), `registrar.html` (AA), `schema.sql`, e
`app/pipeline/recall_client.py` (DU — deletado pela main, modificado pelo commit antigo).

## Decisão
O lado `HEAD` (main atual) era sempre a versão **nova e superior**:
Skribby, auto-cadastro + aprovação de acesso, isolamento por setor, gestão de admin.
O lado `e3cee80` era código **antigo/superado**: Recall.ai e login por allowlist
simples (`precisa_definir_senha`/`definir_senha`/`email_permitido`).

Resolução: **manter HEAD em todos os conflitos**.

## Ações
1. `git checkout --ours` nos 8 arquivos conflitados (mantém HEAD, remove marcadores).
2. `git rm app/pipeline/recall_client.py` — órfão; o código usa `app/pipeline/skribby_client.py`
   (importado em `routes.py:479` e `workers/tasks.py:156`). `recall_client` não é importado em lugar nenhum.
3. Verificado: 0 marcadores restantes no código.
4. `git add -A && GIT_EDITOR=true git rebase --continue`:
   - `65269d0` (fix segurança) **dropado** — "patch contents already upstream" (duplicata de `e77c031`).
   - `c3757c2` (cpanel) aplicado.
   - Rebase finalizado, `main` atualizada.

## Verificação
- `python -c "from app import create_app; create_app()"` → **APP IMPORTA OK** (sem SyntaxError).
- Server: `python -m flask --app run.py run --port 5000 --no-reload`.
- `GET /` → **HTTP 200**; `GET /api/health` → **200** `{"status":"ok"}`.

## Notas / pendências
- Server sobe **sem** reloader de propósito (reloader mata requests longas — ver LOG 2026-07-13).
- APIs de dados dependem de Supabase/credenciais no `.env` (não configurado — ver STATUS.md).
- Nenhum commit foi perdido: os commits antigos seguem no reflog.
- Comando padrão pra subir local: `python -m flask --app run.py run --port 5000 --no-reload`
