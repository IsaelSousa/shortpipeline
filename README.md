<img src="assets/icon.svg" width="64" height="64" alt="">

# ShortPipeline

[English](README.en.md) · **Português**

Fábrica de vídeos para YouTube: gera **Shorts**, **vídeos longos** e **cortes** de vídeos longos de forma automática, para quantos canais você quiser, com um painel web que mostra em que etapa cada vídeo está e deixa configurar qual IA faz o quê.

As IAs de texto e imagem rodam pelas **CLIs logadas com a sua conta** (`claude`, `codex` e `agy`), sem API key. A narração usa o ElevenLabs (com o Edge TTS, grátis, como reserva).

```
Ideia → Roteiro → Narração → Imagens → Capa → Legendas → Som → Render → Revisão → Publicação
```

![Painel do pipeline: cada vídeo com a etapa em que está](docs/pipeline.png)

## Telas

| | |
|---|---|
| ![Vídeo pronto com as cenas geradas e os efeitos sonoros de cada uma](docs/video-cenas.png) | ![Revisão antes de publicar, com as notas do revisor de roteiro](docs/video-roteiro.png) |
| **Vídeo**: player, etapas com tempo, cenas com efeitos de som e ambiente | **Aprovação**: título, descrição, publicar, agendar ou enviar como rascunho; notas do revisor |
| ![Analytics do canal](docs/analytics.png) | ![Configuração de direção criativa do canal](docs/canais.png) |
| **Analytics**: views, retenção, inscritos, fontes de tráfego e o que o canal aprendeu | **Canais**: modelos por etapa, voz, prompts e direção criativa |

<sub>Capturas de um ambiente de demonstração: canais, vídeos e números fictícios.</sub>

## O que ele faz

| Etapa | O que acontece | Provedores |
|---|---|---|
| Ideia | escolhe a pauta: a IA sugere evitando repetir títulos, ou pega uma notícia nova de RSS | Claude / Codex / Gemini (agy) |
| Roteiro | título, descrição, tags e cenas (narração + prompt de imagem); depois um **revisor** dá nota ao gancho, ritmo, final e título e reescreve se ficar abaixo do corte | Claude / Codex / Gemini (agy) |
| Narração | voz por cena com o tempo de cada palavra; no `eleven_v3`, marcações de emoção (`[whispers]`, `[scared]`…) | ElevenLabs / Edge TTS |
| Imagens | uma imagem por cena; personagens com aparência fixa, usando a primeira imagem de cada um como referência nas seguintes | Codex / Gemini (agy) / placeholder |
| Capa | imagem com texto curto; entra nos primeiros frames e vai como thumbnail no upload | IA ou imagem de uma cena |
| Legendas | estilo karaokê, com a palavra falada destacada | — |
| Som | efeitos sonoros na palavra certa, ambiente por cena, whoosh nas transições e impacto nos sustos/revelações | ElevenLabs (com cache) ou sons sintetizados |
| Render | vários planos por cena (cortes no ritmo da fala), transições, efeitos do canal, flash/tremor nos impactos, música que abaixa quando a voz fala | ffmpeg |
| Revisão | espera sua aprovação no painel (opcional por canal) | — |
| Publicação | manual (baixar o MP4), **rascunho** (sobe privado, sem avisar inscritos, para terminar no YouTube Studio) ou automática, com agendamento | YouTube Data API |

Cada etapa com IA tem um provedor principal e um de reserva, usado quando o principal falha (cota, erro). As variáveis `*_API_KEY` são removidas do ambiente das CLIs, para nunca cair em cobrança por API.

### Direção criativa

Por canal: ritmo de cortes, desenho de som, emoção na voz, final em loop (a última frase emenda na primeira) e uma lista de **formatos** que o pipeline alterna (ex.: "POV em segunda pessoa", "mito ou verdade").

### Marca do canal

Elementos que se repetem em todo vídeo, para o público reconhecer o canal em um segundo, sem atrasar o gancho:

- **Narrador fixo**: um personagem que conta todos os vídeos, descrito em uma frase.
- **Bordão final**: a última frase de todo vídeo.
- **Série numerada**: cada short ganha o próximo número (ex.: "Episódio #12" na descrição e "EP. #012" num selo na capa).
- **Selo de nota**: a IA dá uma nota de 0 a 10 no roteiro, com o critério que você definir (ex.: dificuldade de uma receita, quanto uma notícia é exagerada), e uma barra animada mostra a nota nos últimos segundos.
- **Assinatura sonora**: um som curto, gerado uma vez, no ponto em que o vídeo volta ao começo.

Os estilos de som disponíveis são Neutro (serve para qualquer nicho), Terror e Tech.

### Pautas

Em **Canais → Pauta**, configure temas a explorar, temas a evitar e tom editorial. Pautas automáticas passam por uma seleção que compara as candidatas com os vídeos recentes do canal, incluindo a fila. Se as notícias dos feeds forem descartadas, a IA sugere alternativas. Uma pauta digitada à mão tem prioridade.

Ao criar um short, o botão **Pautas em alta** lista as buscas do momento no Google Trends, com as notícias relacionadas, para escolher uma com um clique.

### Timeline antes do render

Antes de renderizar, a aba **Timeline** do vídeo mostra as faixas como num editor (cenas, legendas, narração, efeitos e ambiente), com prévia tocando a voz e o som. Nela dá para:

- pedir uma correção para a IA, excluir uma cena ou um som e editar a narração de uma cena;
- inserir um efeito sonoro no ponto do cursor (whoosh, impacto, riser, blip, um efeito descrito em texto ou um áudio seu);
- ajustar o volume da voz, da música e dos efeitos no **Mixer de áudio**;
- trocar a imagem ou o vídeo de uma cena e, em **Imagem e animação**, comparar uma versão ampliada (Real-ESRGAN) e templates animados (Motion Canvas);
- depois do render, **Checar render**: resolução, duração e volume, e trechos escuros, parados ou em silêncio.

Em **Canais → Vídeo** ficam as transições entre cenas (*Whip Pan*, *Zoom Punch*, *Cinematográfica*, *Glitch* ou corte seco), o movimento de câmera (aproximação, panorâmica lateral ou vertical, ou **Automático**, que alterna) e os emojis animados nas legendas.

### Aprendizado com o Analytics

Com o canal conectado, o pipeline lê periodicamente o desempenho real dos vídeos (views, % assistida, curva de retenção) e uma IA agrupa os vídeos por **tema**, dá uma nota a cada tema e resume **o que repetir e o que evitar**. Os temas e os números de cada vídeo são o critério principal da etapa de pauta: ela gera candidatas nos temas que mais renderam (com histórias novas) e o editor descarta as dos temas que renderam pouco. As regras editoriais do canal continuam acima disso. A análise também sugere pautas novas, que viram Short com um clique em **Canais → Aprendizado automático**, onde fica a chave **Escolher temas pelo Analytics**. Esses aprendizados entram nos prompts de pauta, roteiro e revisor, e os formatos que rendem mais passam a ser escolhidos mais vezes. A página **Analytics** do painel mostra views, retenção, inscritos, fontes de tráfego e os vídeos publicados pelo pipeline.

### Vídeos longos

Mesmo fluxo em 16:9: roteiro longo com capítulos, uma imagem a cada N segundos, thumbnail 1280×720 e capítulos na descrição. A duração é configurável.

### Shorts animados (motion graphics)

Shorts em motion graphics 2D/2.5D montados por código, no estilo dos vídeos de curiosidade científica e de "e se…?": personagens articulados que andam, correm e reagem, cenários em camadas com parallax, objetos com física de verdade, câmera que segue a ação, velocímetro, régua de altura, contadores e legendas que desviam dos informativos. Nenhum vídeo ou imagem é gerado por IA: a IA pesquisa, escreve o roteiro e descreve as cenas num JSON, e a engine desenha cada quadro.

```
Ideia → Pesquisa → Roteiro → Narração → Storyboard → Assets → Som → Preview → Qualidade → Render → Revisão → Publicação
```

- **Pesquisa**: separa fato verificado, cálculo, estimativa e ilustração; os números do vídeo saem daí.
- **Storyboard**: a IA escolhe componentes do catálogo (`assets/motion/registry.json`) e sincroniza as ações com as palavras da narração. O JSON é validado ([schema](docs/motion/schema.v1.json)); erro volta para a IA corrigir.
- **Preview e qualidade**: preview em baixa resolução por cena, checagem de trechos parados e de números que não aparecem na tela, e uma revisão da IA que refaz só a cena fraca.
- **Render**: só as cenas que mudaram são renderizadas de novo; voz, música e efeitos usam a mesma mixagem dos shorts.

Crie em **Novo vídeo → Animado**. A aba **Animação** do job mostra o preview, a qualidade, a pesquisa e as cenas. Precisa da engine construída (veja [Motion Canvas](#motion-canvas-e-real-esrgan-opcionais)). Plano, decisões e limitações: [docs/motion/PLANO.md](docs/motion/PLANO.md).

### Cortes

Transforma um vídeo longo (link ou arquivo) em vários shorts:

```
Download → Transcrição → Seleção  ⟶  um job por trecho: Recorte → Capa → Legendas → Render → Revisão → Publicação
```

- **Transcrição** com tempo por palavra: Whisper local (CPU, grátis) ou ElevenLabs Scribe.
- **Seleção**: a IA escolhe os trechos com melhor gancho e explica por quê; os cortes começam e terminam em palavras inteiras.
- **Recorte**: reenquadra para 9:16 seguindo o rosto de quem fala (OpenCV/YuNet), com fundo desfocado ou recorte central como alternativa.

Use apenas vídeos seus ou que você tem permissão para recortar.

## Instalação

Requisitos:

- [`uv`](https://docs.astral.sh/uv/) e Python 3.12
- `ffmpeg` com libass
- Pelo menos uma CLI de IA logada: [`claude`](https://docs.claude.com/en/docs/claude-code), [`codex`](https://github.com/openai/codex) ou `agy` (Google Antigravity)
- Opcional: uma API key do [ElevenLabs](https://elevenlabs.io) (sem ela, a narração usa o Edge TTS e o som usa os pacotes de efeitos incluídos ou efeitos sintetizados)
- Opcional: Node.js, para os templates animados (Motion Canvas), e o Real-ESRGAN, para ampliar imagens (veja abaixo)

```bash
git clone https://github.com/IsaelSousa/shortpipeline
cd shortpipeline
uv run shortpipeline          # abre em http://localhost:8765
```

No painel:

- **Pipeline**: crie shorts, vídeos longos ou cortes e acompanhe cada etapa ao vivo. Num vídeo dá para ver roteiro, notas do revisor, imagens, som, timeline e log, aprovar, editar e refazer a partir de qualquer etapa.
- **Analytics**: métricas do canal e o que o pipeline aprendeu.
- **Canais**: modelos por etapa, voz, prompts, direção criativa, estilo visual, legendas, capa, revisão (com opção de aprovar antes do render), publicação e agenda automática. Os canais de terror e de tecnologia que vêm na instalação são só exemplos. Um canal criado com **Novo canal** começa neutro, sem nada de nicho nos prompts, formatos, efeitos ou sons: preencha o nicho e ajuste o resto.
- **Provedores**: status das CLIs, API key do ElevenLabs, transcrição, YouTube, Instagram, avisos e diagnóstico das conexões.

### Sons e música próprios

**Música de fundo**: coloque MP3s em `assets/music/<id-do-canal>/`. Um é sorteado por vídeo. A pasta fica fora do git.

Uma música que só faz sentido em certas histórias (ex.: um parabéns para festas) vai num `music.json` na mesma pasta, com a descrição de quando usar:

```json
{"parabens.mp3": "vídeos sobre aniversário ou festa: bolo, velas, convidados"}
```

A IA do roteiro recebe essas descrições e escolhe a música só quando a história combina. A escolha aparece na aba Roteiro e no campo `"music"` do roteiro, que você pode editar. As outras músicas da pasta continuam sendo sorteadas nos demais vídeos; se não houver nenhuma, o vídeo fica sem música.

**Biblioteca grátis pronta**: um comando baixa e organiza mais de mil efeitos e ambientes CC0 (domínio público, uso comercial livre) da [Kenney](https://kenney.nl) e de autores do [OpenGameArt](https://opengameart.org):

```bash
uv run shortpipeline-sounds          # ~1.100 sons em data/sound-packs/cc0-* (25 MB); --list mostra as fontes
```

Ficam em pacotes por tema (impactos, cotidiano, interface, sci-fi, criaturas, vinhetas, ambientes e ambientes sombrios), com o volume nivelado, palavras-chave em português e inglês para a busca e o crédito de cada arquivo em `CREDITS.md`. Monstros e ambientes sombrios só entram em canais de terror (e neutro); sons de interface só em neutro e tech. Os pacotes que você mesmo montar têm prioridade sobre esses.

**Efeitos e ambientes**: crie uma pasta em `data/sound-packs/` (também fora do git, para sons que você não pode redistribuir, como os do Pixabay) e nomeie os arquivos pelo tipo de som:

```
data/sound-packs/meus-sons/
  pack.json        {"styles": ["neutro"], "tags": {"ambience": ["cafe", "escritorio"]}}
  impact.mp3       usado nas revelações, no lugar do impacto padrão
  applause-1.mp3   variações do mesmo som: uma é sorteada a cada uso
  applause-2.mp3
  ambience-1.mp3   ambiente padrão quando o ElevenLabs não está disponível
  ambience-rain.mp3
```

- `whoosh`, `impact`, `riser` e `blip` substituem os sons padrão das transições e batidas.
- Qualquer outro nome (`applause`, `door`, `laugh`…) vira um efeito que o roteiro pode pedir. Ele é usado quando a descrição do efeito tem a palavra, em inglês ou português (ex.: "crowd clapping" ou "palmas" usam um `applause`). A IA do roteiro recebe a lista dos sons disponíveis.
- `ambience` e `ambience-<palavra>` são ambientes, escolhidos pela descrição da cena.
- O `pack.json` é opcional. `styles` limita o pacote a estilos de som do canal, e `tags` acrescenta palavras-chave.
- Na timeline, **Adicionar SFX** mostra os seus sons em **Sua biblioteca**.

Os seus sons têm prioridade sobre o ElevenLabs. Os pacotes CC0 de `assets/sound-packs/` só entram quando nada mais está disponível.

### Motion Canvas e Real-ESRGAN (opcionais)

**Motion Canvas e engine de animação.** Com o Node.js instalado, rode na pasta `motion-canvas/`:

```bash
npm ci
npx playwright install chromium   # o Chromium só renderiza os templates e os Shorts animados, localmente
npm run build                     # gera dist/scene.js (templates) e dist/engine.js (Shorts animados)
```

**Real-ESRGAN.** Coloque o executável `realesrgan-ncnn-vulkan` no PATH ou em `data/tools/realesrgan/`, com `realesrgan-x4plus.param` e `realesrgan-x4plus.bin` na subpasta `models/` ao lado dele. Precisa de Vulkan. A ampliação é opcional e mantém a imagem original. [Distribuição oficial](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0)

## Conectar o YouTube (upload, rascunho e Analytics)

1. No [Google Cloud Console](https://console.cloud.google.com/), crie um projeto e ative a **YouTube Data API v3** e a **YouTube Analytics API**.
2. Em *Google Auth Platform*, configure a tela de consentimento e adicione o seu e-mail como usuário de teste.
3. Crie uma credencial OAuth do tipo **App para computador** e salve o JSON em `data/youtube/client_secret.json` (ou informe o caminho no painel).
4. No painel, em **Canais**, clique em **Conectar YouTube** e escolha a conta do canal. Faça isso pelo próprio computador (`localhost`), porque o retorno do login aponta para `localhost`.

Enquanto o app do Google não passar pela verificação, os uploads feitos pela API ficam privados. A capa é enviada como thumbnail também nos rascunhos e agendados.

## Publicar no Instagram Reels

O envio usa a Meta Graph API v21.0 com upload direto do arquivo, sem precisar de domínio público nem ngrok.

1. Em [developers.facebook.com](https://developers.facebook.com/), crie um app do tipo Empresa e adicione a **Instagram Graph API**.
2. Gere um token de acesso de longa duração (60 dias) com as permissões `instagram_basic` e `instagram_content_publish`.
3. Pegue o **ID da conta Business do Instagram**.
4. No painel, em **Provedores** (ou em **Canais**), informe o token e o ID da conta.
5. Em **Canais → Revisão e publicação**, ligue o envio automático para o Reels, ou use o botão **Publicar no Reels** num vídeo pronto.

## Avisos no Telegram e no Discord

Receba um aviso com a capa quando um vídeo estiver esperando aprovação, for publicado ou falhar:

- **Telegram**: crie um bot pelo [@BotFather](https://t.me/BotFather), pegue o token e o seu Chat ID, preencha em **Provedores** e clique em **Enviar teste no Telegram**.
- **Discord**: num canal do seu servidor, crie um webhook em *Integrações*, copie a URL e salve em **Provedores**.

## Acesso pela rede

Por padrão o painel só aceita conexões do próprio computador. Para abrir no celular:

```bash
SHORTPIPELINE_HOST=0.0.0.0 uv run shortpipeline
```

O painel **não tem login**: quem acessar vê a configuração, incluindo a API key do ElevenLabs, o token do Instagram, o do bot do Telegram e o webhook do Discord, e pode criar ou publicar vídeos. Use só em rede de confiança, ou prefira uma VPN como o Tailscale.

## Dados

Tudo o que é seu fica em `data/`, que está fora do git: `config.json` (editado pelo painel, inclui as chaves e tokens), `pipeline.db` (fila e logs), `jobs/<id>/` (roteiro, áudios, imagens, legendas e `final.mp4`), `youtube/` (tokens OAuth), `learn/` (aprendizados), `sound-packs/` (seus sons), `sfx_cache/`, `previews/` e `tools/`.

Variáveis opcionais: `SHORTPIPELINE_PORT`, `SHORTPIPELINE_HOST`, `SHORTPIPELINE_DATA`, `ELEVENLABS_API_KEY`.

## Desenvolvimento

```bash
uv run --group dev pytest       # testes (precisam do ffmpeg)
uvx ruff check shortpipeline tests
```

Os testes rodam numa pasta de dados temporária, com a IA e a voz simuladas: não gastam cota nem precisam das CLIs logadas. Um deles gera um short inteiro, do roteiro ao `final.mp4`. O GitHub Actions roda tudo a cada push.

Onde fica cada parte:

| Pasta | O que tem |
|---|---|
| `shortpipeline/pipeline/` | as etapas: `writing` (ideia, roteiro, revisor), `media` (narração, imagens, capa, legendas), `assembly` (som, render, revisão, publicação), `clips` (cortes), `animated` (Shorts animados) e `runner` (ordem das etapas) |
| `shortpipeline/motion/` | Shorts animados: schema do JSON, catálogo, física, prompts e a ponte com a engine |
| `motion-canvas/engine/` | a engine de animação (personagens, cenários, objetos, câmera, informativos, efeitos, legendas) |
| `shortpipeline/routes/` | a API do painel: `jobs`, `timeline`, `channels` e `integrations` (YouTube, Analytics, avisos, diagnóstico) |
| `shortpipeline/providers/` | chamadas às CLIs de IA, voz, imagem e transcrição |
| `web/js/` | o painel, um arquivo por página (JavaScript puro, sem build) |
| `tests/` | testes com pytest |

## Uso responsável

- Siga as políticas do YouTube sobre conteúdo gerado por IA e marque o conteúdo alterado/sintético quando a plataforma pedir.
- O YouTube limita a monetização de conteúdo repetitivo ou reaproveitado sem contribuição própria; revise o que vai ao ar.
- Para cortes, use apenas material seu ou com autorização.

## Licença

Código sob a licença [MIT](LICENSE).

### Referências de motion design

- **mg-styles-15**, de Vincentwei1021. O código, os prompts, a documentação e os filmes originais do projeto estão sob MIT. Materiais de terceiros mantêm os próprios termos, entre eles fontes OFL e highlight.js sob BSD-3-Clause. [Licença MIT](https://github.com/Vincentwei1021/mg-styles-15/blob/main/LICENSE) · [Licenças dos materiais](https://github.com/Vincentwei1021/mg-styles-15#license)
- **motion-prompt**, de Shohei Ohtaki. Código, imagens e vídeos próprios podem ser usados comercialmente sob MIT. Preserve a linha de atribuição do elemento ao reutilizar seu código. Os posts incorporados pertencem aos respectivos autores. [Licença MIT](https://github.com/showheyohtaki/motion-prompt/blob/main/LICENSE) · [Avisos de terceiros](https://github.com/showheyohtaki/motion-prompt/blob/main/THIRD-PARTY-NOTICES.md)
- **animate**, de cth9191. O código próprio está sob MIT. [Licença MIT](https://github.com/cth9191/animate/blob/main/LICENSE)

Ao distribuir cópias ou partes substanciais do material MIT, inclua o aviso de copyright e o texto da licença original.

## Créditos

- [Motion Canvas](https://github.com/motion-canvas/motion-canvas), sob a licença MIT, para os templates animados.
- Efeitos e ambientes offline de [Kenney](https://kenney.nl) e de autores do [OpenGameArt](https://opengameart.org), sob CC0 (os incluídos e os baixados pelo `shortpipeline-sounds`, com o crédito de cada arquivo no `CREDITS.md` do pacote). Veja a [lista de arquivos, a licença e como adicionar pacotes](assets/sound-packs/README.md).
- Fontes [Anton](https://fonts.google.com/specimen/Anton), [Creepster](https://fonts.google.com/specimen/Creepster), [Montserrat](https://fonts.google.com/specimen/Montserrat) e [Inter](https://fonts.google.com/specimen/Inter), sob a [SIL Open Font License 1.1](https://openfontlicense.org) (texto de cada uma em `assets/fonts/` e `web/fonts/`).
- Detector de rostos [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) do OpenCV Zoo, sob a licença MIT (`assets/models/LICENSE-YuNet.txt`).
