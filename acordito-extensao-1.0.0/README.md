# Extensão Chrome — Acordito (Meeting DDM)

Registra a reunião **da aba atual** sem copiar e colar link: clique no ícone → o popup já vem com
o link e o título da aba → *Enviar Acordito*. O bot entra, grava, transcreve e a ata aparece no
painel executivo.

Faz exatamente o que a tela pública `/` faz (`POST /api/gravacoes`), só que sem sair da reunião.

## Instalar (modo desenvolvedor)

1. Chrome → `chrome://extensions`
2. Ligar **Modo do desenvolvedor** (canto superior direito)
3. **Carregar sem compactação** → selecionar esta pasta (`acordito-extensao-1.0.0/`)
4. Fixar o ícone na barra (ícone de peça de quebra-cabeça → alfinete)

Servidor padrão: `https://meeting.grupoddm.ia.br`. Para testar contra o local, abrir as opções
(engrenagem no popup) e trocar para `http://127.0.0.1:5000`.

## Como usar

| Situação | O que fazer |
|---|---|
| Reunião aberta no Chrome (Teams web, Meet, Zoom web) | Clicar no ícone — link e título já vêm preenchidos |
| Reunião no app do Teams (sem aba) | Copiar o link do convite → clicar no ícone → **Colar link** |
| Registrar antes de começar | Preencher link + data/hora manualmente |

Informe o e-mail corporativo uma vez. A extensão consulta o cadastro aprovado no Meeting DDM,
preenche o nome e sugere o setor. Novos colaboradores passam a ser reconhecidos assim que forem
aprovados no painel, sem alterar a extensão. E-mail, setor, formato e local ficam salvos no Chrome.
Essa consulta facilita o preenchimento, mas não autentica a identidade de quem digita o e-mail.
Ao registrar, escolha entre acesso para todos do setor ou apenas gestores. A escolha fica no banco
e é aplicada pelo servidor ao listar e abrir a reunião.

Dados de usuários e setores são consultados no servidor sempre que o popup abre. Isso dispensa
atualizações para novos cadastros, mas não atualiza o código da extensão instalado no navegador.
Para receber novas funcionalidades automaticamente, distribua esta versão pela Chrome Web Store
ou por política corporativa. Instalações sem compactação exigem uma atualização manual para 1.2.0.

## Arquivos

| Arquivo | Papel |
|---|---|
| `manifest.json` | MV3. Permissões: `activeTab`, `storage`, `clipboardRead` |
| `popup.html/.css/.js` | Formulário e envio |
| `options.html/.js` | URL da API + e-mail corporativo + teste de conexão |
| `shared.js` | Validação de host de reunião, base da API, prefs |
| `icons/icon.png` | Marca DDM (cópia de `assets/logo-mark.png`) |

## Lado do servidor

A extensão roda em origem `chrome-extension://…`, que é cross-origin. Foi adicionado CORS em
[`app/__init__.py`](../app/__init__.py) **só** para os endpoints já públicos:

- `/api/health`, `/api/setores`, `/api/gravacoes`, `/api/extensao/usuario`

A consulta de usuário é feita por e-mail corporativo exato e devolve apenas nome e setor de
cadastros ativos e aprovados. Ela não disponibiliza a lista completa de usuários.

Sem `Access-Control-Allow-Credentials` → o cookie de sessão do diretor nunca trafega por essa via.
Rotas protegidas (`/api/reunioes`, `/api/dashboard/*`, …) continuam devolvendo 401 **sem** header
CORS, então o browser bloqueia mesmo que alguém tente.

Para restringir ao ID exato da extensão, colocar no `.env` do servidor:

```
EXTENSION_ORIGINS=chrome-extension://<id-da-extensao>
```

Vazio (default) = qualquer extensão Chrome pode chamar esses endpoints — que já são públicos na
internet de qualquer forma (`curl` ignora CORS). O ganho real de restringir é baixo; o controle de
abuso desses endpoints é rate-limit, ainda pendente.

## Limitações conhecidas

- **Sem rate-limit** em `/api/gravacoes`: endpoint público, qualquer um pode disparar bot. Vale
  para a tela `/` também — a extensão não muda o quadro.
- **ID instável**: carregada sem compactação, o Chrome sorteia o ID a cada máquina. Para ID fixo
  (e para poder usar `EXTENSION_ORIGINS`), publicar na Chrome Web Store ou empacotar `.crx` com
  chave fixa e distribuir por política de grupo.
- **Ícone único**: um PNG 904×860 serve os 3 tamanhos; o Chrome reduz. Se ficar borrado na barra,
  gerar 16/48/128 de verdade.
- Reunião precisa estar **em andamento ou prestes a começar**; com sala de espera, alguém tem de
  admitir o Acordito.

## Distribuir para a equipe

1. **Sem publicar:** zipar a pasta, cada um carrega sem compactação (some ao reinstalar o Chrome).
2. **Chrome Web Store (não listada):** publicar como *unlisted* e mandar o link. A extensão
   instalada por esse canal recebe atualizações automáticas; novos usuários não exigem publicação.
3. **Política de grupo (TI):** `ExtensionInstallForcelist` — instala em todas as máquinas do
   domínio. Precisa do Jair.
