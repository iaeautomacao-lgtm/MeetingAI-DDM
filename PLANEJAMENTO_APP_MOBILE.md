# Planejamento — Meeting DDM como App de Smartphone (v2 com gravador)

_Documento de decisão — 14/07/2026_

## Veredito rápido

**Vai dar certo? SIM — com risco baixo/médio.** O motivo é que a parte difícil já está construída.

O backend atual já tem TUDO que um app presencial precisa do lado servidor:
- Transcrição de arquivo de áudio **com diarização** (quem falou) — `app/pipeline/audio.py` usa Azure `ConversationTranscriber`, que devolve `speaker_id`.
- Rota de upload de áudio — `POST /api/reunioes/upload`.
- Processamento assíncrono — `processar_audio_avulso` → mesmo pipeline de análise (decisões, pendências, tópicos, participantes, resumo) que já validamos.
- Dashboard, auth, Supabase, setores — prontos.

Ou seja: o modo presencial reaproveita ~80% do que existe. O trabalho de v2 é **majoritariamente no cliente** (o app que grava e envia), não no cérebro do sistema.

---

## v1 (hoje) vs v2 (presencial)

| | v1 — Reunião online | v2 — Reunião presencial |
|---|---|---|
| Captura | Bot Recall.ai entra no Teams/Zoom/Meet | App grava o áudio da sala pelo microfone |
| Entrada | URL da reunião | Arquivo de áudio gravado no celular |
| Transcrição | Recall (streaming) | Azure Speech / outro STT sobre o arquivo |
| Análise | Gemini | Gemini (**mesmo código**) |
| Dashboard | Já existe | **Mesmo dashboard** |

A única peça nova de verdade é **gravar + enviar o áudio**. O resto é reuso.

---

## Como virar app — 3 caminhos

### A) PWA (Progressive Web App) — rápido e barato
Transforma o site atual em "app instalável" pelo navegador. Grava áudio via `MediaRecorder` do navegador.
- ✅ Reusa 100% do frontend que já temos (HTML/JS).
- ✅ Sem loja de apps, sem aprovação Apple/Google, deploy instantâneo.
- ✅ Funciona Android + iOS.
- ⚠️ iOS limita gravação em segundo plano (tela apagada/app minimizado pode cortar). Para reunião com a tela ligada, funciona.
- ⚠️ "Instalar" é menos óbvio pro usuário (via menu do navegador).

### B) Capacitor (híbrido) — **recomendado**
Empacota o frontend web atual dentro de um app nativo real (vai pra App Store / Play Store). Usa plugin nativo de microfone.
- ✅ Reusa o frontend web quase inteiro — pouco reescrever.
- ✅ App nativo de verdade: ícone (Acordito 🦉), gravação em background estável, notificação push, cara de app.
- ✅ Um código → iOS + Android.
- ⚠️ Precisa conta de desenvolvedor: Apple US$99/ano, Google US$25 (única vez).
- ⚠️ Processo de publicação nas lojas (dias/semanas de review na Apple).

### C) React Native / Flutter — nativo do zero
Reescreve o frontend como app nativo puro.
- ✅ Máxima performance e recursos nativos.
- ❌ Reescrita grande do frontend — mais caro e lento. **Não recomendo agora** (o ganho não justifica; o frontend atual é simples e web serve bem).

**Recomendação:** PWA na v2.0 (validar rápido com a diretoria, custo quase zero) → Capacitor na v2.1 (app nas lojas com o Acordito). Mesmo frontend nas duas — o investimento não se perde.

---

## Transcrição presencial — a decisão técnica que importa

Áudio de sala é mais difícil que áudio de reunião online (ruído, pessoas longe do mic, sobreposição de falas). O STT precisa de **diarização** boa (separar quem fala) pra "Participantes" funcionar.

| Opção | Diarização | Situação | Observação |
|---|---|---|---|
| **Azure Speech** | Sim (`speaker_id`) | **Já integrado** (`audio.py`) | Caminho de menor esforço. Só ligar a chave e testar com áudio real. |
| Deepgram | Sim, muito boa | Trocar cliente | Costuma dar boa qualidade em PT-BR e preço competitivo. |
| AssemblyAI | Sim, muito boa | Trocar cliente | Forte em diarização; API simples. |
| Whisper (self-host) | Não nativa (precisa pyannote) | Infra própria | Barato em escala, mas mais infra pra manter. |

**Recomendação:** começar com **Azure** (já está no código) e validar a qualidade com uma gravação real de sala. Se a diarização decepcionar em ambiente ruidoso, testar Deepgram/AssemblyAI — a troca é isolada (só `audio.py`), não mexe no resto.

> Custos de STT variam ~US$0,20–1,00 por hora de áudio dependendo do provedor. **Confirmar preço vigente** antes de fechar — não travar decisão nesse número agora.

---

## Arquitetura v2 (fluxo presencial)

```
[App celular]
   grava áudio da reunião (mic)
        │  (para a gravação → upload)
        ▼
POST /api/reunioes/upload   ── já existe
        │
        ▼
processar_audio_avulso      ── já existe
   ├─ audio.transcrever()   ── Azure STT + diarização (já existe)
   └─ extrair_reuniao()     ── Gemini: decisões/pendências/etc (já existe)
        │
        ▼
Supabase → Dashboard        ── já existe
```

O que precisa ser **construído/ajustado**:
1. **Tela de gravação no app** (botão gravar/pausar/parar, timer, nome da reunião + setor).
2. **Upload robusto** de arquivos grandes (reunião de 1h ≈ 30–60 MB) — upload em pedaços/resiliente a queda de rede.
3. **Compressão de áudio** no celular antes de enviar (ex.: gravar em m4a/opus) — economiza banda e custo de STT.
4. **Feedback de status** (enviando → transcrevendo → pronto) no app.
5. **Deploy público do backend** (hoje é localhost) — pré-requisito comum ao v1 automático também.

---

## Riscos reais (honestos)

| Risco | Impacto | Mitigação |
|---|---|---|
| **Qualidade de áudio de sala** | Alto — mic ruim = transcrição ruim | Recomendar celular no centro da mesa; testar cedo com gravação real; considerar mic externo p/ salas grandes. |
| **Diarização em ambiente ruidoso** | Médio — "Participantes" pode sair errado | Validar Azure cedo; ter Deepgram/AssemblyAI como plano B. |
| **iOS gravação em background** | Médio (só afeta PWA) | Manter tela ligada durante gravação, ou usar Capacitor (resolve). |
| **LGPD / consentimento** | **Alto — jurídico** | Reunião presencial gravada exige avisar/consentir os presentes. Precisa de aviso no app + política. Como é escritório de advocacia, tratar com cuidado. |
| **Upload de arquivo grande em 4G** | Médio | Comprimir áudio + upload resiliente + permitir enviar depois no Wi-Fi. |
| **Custo de STT por hora** | Baixo/Médio | Comprimir áudio; monitorar volume de horas/mês. |
| **Deploy/infra pública** | Médio | Necessário de qualquer forma (v1 automático também precisa). |

---

## Roadmap sugerido

**Fase 0 — Pré-requisito (compartilhado com v1 automático)**
- Deploy público do backend + webhook. (Já pendente hoje.)

**Fase 1 — Validar o miolo presencial (1–2 dias, sem app)**
- Ligar chave Azure Speech, gravar um áudio real de reunião presencial pelo celular, subir via `/api/reunioes/upload`, ver se decisões/participantes saem bons.
- **Decisão go/no-go barata**: se a transcrição de sala prestar, o app é só embalagem.

**Fase 2 — PWA com gravador (v2.0)**
- Tela de gravação + upload no frontend web, marcada como instalável (PWA).
- Compressão de áudio no cliente. Aviso de consentimento LGPD.

**Fase 3 — App nas lojas (v2.1)**
- Empacotar com Capacitor, ícone Acordito, gravação em background, push.
- Publicar Play Store / App Store.

---

## Recomendação final

1. **Sim, vira app e vale a pena** — porque o backend já faz o trabalho pesado (transcrição com diarização + análise + dashboard).
2. **Não pule pra loja de app antes de validar o áudio.** Faça a **Fase 1** primeiro: uma gravação real de sala pelo Azure. É barato e responde a pergunta "vai dar certo?" de forma definitiva.
3. **Caminho de app:** PWA primeiro (barato, rápido), Capacitor depois (lojas, Acordito). Mesmo frontend — sem retrabalho.
4. **Trate LGPD/consentimento como item de projeto**, não detalhe — é escritório jurídico.

**Próximo passo concreto que eu recomendo:** rodar a Fase 1. Me passa (ou grava) um áudio de reunião presencial e a chave Azure Speech, que eu ligo o upload e a gente vê a qualidade real da transcrição de sala. Isso decide tudo.
