# Deploy no cPanel — Meeting DDM (branch `dist`)

Esta branch contém **só** o necessário para rodar em produção, dentro da pasta
`dist/`. O restante do projeto (docs, mobile, design system, scripts, Vercel)
fica na branch `main`.

## Conteúdo
```
dist/
├─ passenger_wsgi.py      # entry point do Passenger (cPanel)
├─ run.py                 # cria o app Flask
├─ celery_worker.py       # worker Celery (opcional, se usar Redis)
├─ requirements.txt       # dependências
├─ requirements-optional.txt
├─ app/                   # código da aplicação
├─ registrar.html login.html meeting-ddm-dashboard.html
├─ assets/                # só as imagens servidas em produção
├─ .env.example           # referência das variáveis (NÃO comitar .env real)
└─ .cpanel.yml            # template opcional de auto-deploy
```

## Passo a passo (cPanel)

### 1. Trazer o código via Git
cPanel → **Git™ Version Control** → *Create*:
- Clone URL: `https://github.com/iaeautomacaoddm-lgtm/MeetingAI-DDM.git`
- Branch: **`dist`**
- Vai clonar em algo como `/home/USUARIO/repositories/MeetingAI-DDM`.

Para atualizar depois: **Manage → Update from Remote** (puxa novos commits da `dist`).

### 2. Criar o Python App
cPanel → **Setup Python App** → *Create Application*:
- Python version: 3.11+ (bate com `.python-version`)
- **Application root:** `repositories/MeetingAI-DDM/dist`  ← aponta para a pasta `dist/`
- Application URL: o domínio (ex.: `meeting.grupoddm.ia.br`)
- Application startup file: `passenger_wsgi.py`
- Application Entry point: `application`

### 3. Instalar dependências
No painel do Python App, campo **"Run Pip Install"** com `requirements.txt`,
ou pelo terminal (entrar no virtualenv que o cPanel mostra):
```
pip install -r requirements.txt
```

### 4. Variáveis de ambiente
No Python App → seção **Environment variables**, definir as chaves do
`.env.example`. **Obrigatórias / de segurança:**
- `SECRET_KEY` — chave forte e fixa: `python -c "import secrets; print(secrets.token_hex(32))"`
- `DIRECTOR_PASSWORD` — senha forte (a antiga vazou no histórico do git — TROCAR)
- `FLASK_ENV=production`
- `SESSION_COOKIE_SECURE=1` (domínio é HTTPS)
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_SCHEMA`
- IA: uma de `OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`
- Skribby: `SKRIBBY_API_KEY`, `PUBLIC_BASE_URL`, `SKRIBBY_WEBHOOK_SECRET`
- (Opcional) Azure / IMAP conforme uso.

> Não subir `.env` para o Git. No cPanel as variáveis ficam na UI do Python App.

### 5. Restart
Python App → **Restart**. Testar `https://SEU_DOMINIO/api/health` → `{"status":"ok"}`.

## Auto-deploy (opcional)
Para o cPanel reimplantar sozinho a cada `Update from Remote`, mova o
`.cpanel.yml` para a **raiz da branch** e ajuste o `DEPLOYPATH`. Sem isso, o
app roda direto da pasta clonada `dist/` (recomendado — mais simples).

## Celery / sync automático (opcional)
`celery_worker.py` + `REDIS_URL` rodam os syncs (Teams/IMAP) e o resumo diário.
Precisa de Redis e de um processo persistente (cPanel geralmente não mantém
worker vivo). Sem Celery, o webhook do Skribby ainda processa via thread.
