# LOG 2026-07-23 — Fix HTTP 500 no botão "Enviar assistente Acordito"

## Sintoma
Painel em produção (cPanel, https://meeting.grupoddm.ia.br). Clicar em
"Enviar assistente Acordito" (Nova Reunião) → toast **"Erro: HTTP 500"**.
Resto do painel funciona (dashboard lista reuniões normalmente).

## Diagnóstico (como cheguei)
1. Botão chama `POST /api/gravacoes` (rota `criar_gravacao` em `app/api/routes.py`).
2. Front (`apiPost`) só mostra "HTTP 500" quando o corpo do erro **não é JSON** →
   exceção Python não tratada (500 HTML padrão do Flask).
3. Testes:
   - `GET /api/health` em prod → **200** (app no ar).
   - `POST /api/gravacoes` com corpo **vazio `{}`** → **500** (devia ser 400).
   - INSERT direto na tabela `reunioes` via REST → **201** (banco OK).
   - Todas as colunas existem (`recall_bot_id` inclusive, com valor).
4. Corpo vazio estoura ANTES de qualquer lógica → falha na 1ª linha:
   `from app.pipeline.skribby_client import create_bot` (import lazy).
   Esse módulo faz `import requests` no topo.

## Causa raiz
**`requests` não instalado no venv Python do cPanel.**
Import lazy → `ImportError` só quando /gravacoes roda → 500.
Resto do painel não importa `requests`, por isso só esse botão quebrava.
(Não era Skribby — falha do Skribby daria 502 com mensagem. Não era banco.)

## Correção
### Servidor (conserto real — FALTA FAZER)
No cPanel → Setup Python App → entrar no venv (comando "Enter to the virtual
environment") no Terminal e rodar:
```
pip install -r requirements.txt
```
(ou mínimo: `pip install requests`). Depois **Restart** da app.

### Código (feito, main) — blindagem
`app/api/routes.py` `criar_gravacao()`:
- import do skribby_client movido p/ dentro de try → erro de dependência vira
  JSON `{"erro":"dependencia_ausente","msg":...}` (500) em vez de HTML opaco.
- INSERT no Supabase agora em try/except → erro de banco vira 502 com msg.
- Trata `row.data` vazio.
Resultado: próximos erros aparecem legíveis no toast.
> Precisa deploy na branch `dist` + redeploy cPanel pra valer em prod.
> Mesmo assim, o `pip install` é obrigatório — a blindagem só torna o erro claro.

---

# Fix 2 — Transcrição sem nomes dos locutores (tudo "?")

## Sintoma
Aba Transcrição mostra todas as falas com prefixo "?:" (sem nome de quem falou).

## Diagnóstico
- utterances salvas em `reunioes` têm `speaker: "?"` em 100% das falas.
- Puxei o bot real na API Skribby (`GET /bot/{id}?with-speaker-events=true`):
  cada utterance vem com `speaker: null`, sem `speaker_name`, sem
  `potential_speaker_names`. As `words` também `speaker: null`.
- Causa: modelo `groq/whisper-large-v3-turbo` **não faz diarização**. Whisper
  transcreve mas não separa locutor. Sem rótulo de locutor, o Skribby não tem
  como correlacionar com a lista de `participants` (que EXISTE: Christiano Di
  Maio, Danyelle, etc. com presence_intervals e mute/unmute).
- O parser (`_speaker_label`) já sabe ler `speaker_name`/`potential_speaker_names`/
  índice — só nunca recebia. Nenhuma mudança de parser necessária.

## Correção (feito)
Trocado modelo default p/ `openai/gpt-4o-transcribe-diarize` (doc Skribby: é o
modelo de diarização; batch → casa com webhook 'finished'; correlaciona locutor
com participantes → preenche `speaker_name`). Confirmado que roda no transcription
gerenciado do Skribby, SEM precisar de credencial OpenAI própria (BYOK opcional).
Arquivos:
- `app/pipeline/skribby_client.py` `_model()` default
- `app/config.py` `SKRIBBY_MODEL` default
- `.env` local

## Limitações
- Só vale p/ reuniões NOVAS. Não há endpoint Skribby p/ re-transcrever gravação
  antiga com outro modelo → reuniões já feitas continuam "?".
- Se o modelo falhar em prod (algum plano/limite), o toast agora mostra o erro
  (graças à blindagem do Fix 1). Fallbacks c/ diarização + PT: `deepgram/nova-3-multilingual`,
  `assemblyai/universal-2`, `speechmatics/batch-standard`. Trocar via env `SKRIBBY_MODEL`.

## Pendências
- [ ] `pip install -r requirements.txt` no cPanel + restart. (Fix 1)
- [ ] Merge dos fixes p/ branch `dist` + redeploy.
- [ ] (opcional) Setar `SKRIBBY_MODEL=openai/gpt-4o-transcribe-diarize` nos env
      vars do cPanel (explícito), ou confiar no default do código.
- [ ] Testar 1 reunião nova e conferir se os nomes aparecem.
- [ ] **Rotacionar segredos vazados no print** (DIRECTOR_PASSWORD, SECRET_KEY,
      SUPABASE_SERVICE_KEY) — expostos no chat/imagem.
