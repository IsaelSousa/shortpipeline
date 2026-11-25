# Shorts animados (motion graphics 2D/2.5D): plano e decisões

Pedido do formato: [PROMPT.md](PROMPT.md). Schema publicado: [schema.v1.json](schema.v1.json).
Exemplo completo: [examples/ar-condicionado.json](examples/ar-condicionado.json).

## 1. Diagnóstico: o que o formato reaproveita

| Necessidade | Já existia | Onde |
|---|---|---|
| Fila, estado por etapa, retomada | jobs em SQLite com etapas persistidas | `db.py`, `worker.py`, `pipeline/runner.py` |
| "Agentes" com modelo por tarefa | modelo e reserva por etapa e por canal (OAuth, sem API key) | `config.MODEL_STAGES`, `Ctx.text` |
| Pauta e aprendizado | pauta por IA/RSS/tendências, temas guiados pelo Analytics | `writing.stage_ideia`, `learn.py`, `trends.py` |
| Roteiro e revisor | roteiro com revisor que dá nota e reescreve | `writing.stage_roteiro`, `writing.critique` |
| Narração com tempos por palavra | ElevenLabs + Edge TTS, `timings.json` por cena | `media.stage_narracao`, `providers/tts.py` |
| Desenho de som | SFX por palavra, ambiente nivelado, biblioteca do usuário, música por canal | `assembly.stage_som`, `sound.py`, `render.pick_music` |
| Mixagem final | voz + música com ducking + efeitos, mixer por job | `render.audio_filters` (extraída do `render_video`) |
| Capa | fundo + texto com destaque | `render.build_cover` |
| Chromium headless | Playwright do Motion Canvas | `motion-canvas/` |
| Revisão humana e publicação | aprovação antes do render e antes de publicar, upload, Reels, avisos | `assembly.stage_revisao`, `upload.py` |

Nada de OpenBot, Docker, PostgreSQL ou Remotion foi introduzido. Os tipos existentes (short, long, fonte, corte) não
mudaram de fluxo; o único código compartilhado alterado foi a extração da mixagem de áudio para uma função
(`audio_filters`), coberta pelos testes de ponta a ponta do short.

## 2. Decisão de motor

| Critério | Motion Canvas (já instalado) | Remotion | Engine própria em Canvas 2D (escolhida) |
|---|---|---|---|
| Licença para ferramenta pública | MIT | paga para empresas com 4+ pessoas | MIT (do projeto) |
| Determinismo por quadro | sim (gerador de cenas) | sim (`useCurrentFrame`) | sim: cada quadro é `draw(json, t)` |
| Composição por JSON | precisa de um interpretador por cima | precisa de um interpretador por cima | é o próprio interpretador |
| Dependências novas | nenhuma | React, bundler, renderer próprio | nenhuma (usa o Chromium e o esbuild já presentes) |
| Render por trecho/cena | possível | possível | nativo: qualquer intervalo de quadros |

Os dois frameworks são feitos para cenas escritas à mão em código. Aqui a cena vem de um JSON, então o que importa é
o interpretador. Com o Canvas 2D direto, cada quadro é uma função pura do JSON e do tempo, sem estado entre quadros:
o mesmo trecho sai idêntico em qualquer execução, uma cena pode ser renderizada sozinha (cache e preview por cena) e
não há licença nem dependência nova. O Motion Canvas continua sendo usado nos templates de cena dos shorts comuns.
O JSON não depende do motor: trocar a engine é escrever outro interpretador do mesmo schema.

## 3. Arquitetura

```
ideia ─► pesquisa ─► roteiro ─► narração ─► storyboard ─► assets ─► som ─► preview ─► qualidade ─► render ─► revisão ─► publicação
 (IA)      (IA)       (IA+       (voz +       (IA: JSON     (catá-    (SFX,   (540p,    (checagem     (1080p,   (humano)    (YouTube,
                     revisor)   tempos por    validado,     logo)    ambien-  15 fps,   automática    30 fps,              Reels)
                                 palavra)     corrigido)              te)     cache)    + IA; refaz   cache,
                                                                                         só a cena)   mixagem,
                                                                                                      capa)
```

- **Python** (`shortpipeline/motion/`): schema (Pydantic), catálogo, física, prompts e a ponte com a engine
  (prepara o JSON com os tempos reais da narração, renderiza cada cena com cache e junta as cenas).
- **Etapas** (`shortpipeline/pipeline/animated.py`): pesquisa, storyboard, assets, preview, qualidade e o render
  final, chamado pela etapa `render` existente quando o job é `animado`.
- **Engine** (`motion-canvas/engine/`, empacotada em `dist/engine.js`): roda no Chromium headless pela ponte
  `motion-canvas/animate.mjs`, que envia os quadros direto ao ffmpeg (sem gravar milhares de imagens).
- **Painel**: botão "Animado" no novo vídeo; aba "Animação" no job com o preview, o relatório de qualidade, os
  fatos da pesquisa, as cenas do storyboard e "Aprovar e renderizar".

## 4. Diretórios

```
shortpipeline/motion/      schema.py  catalog.py  physics.py  prompts.py  render.py
shortpipeline/pipeline/    animated.py              (etapas do formato)
motion-canvas/engine/      index.js (composição)  character.js  environment.js  objects.js  camera.js
                           overlays.js  effects.js  captions.js  physics.js  util.js
motion-canvas/animate.mjs  ponte headless → ffmpeg
assets/motion/registry.json  catálogo versionado (no git; tudo desenhado por código, MIT)
data/motion-assets/          assets e registry do usuário (fora do git)
docs/motion/                 PROMPT.md  PLANO.md  schema.v1.json  examples/
data/jobs/<id>/              storyboard.json  preview.mp4  motion/preview/<cena>-<hash>.mp4
                             motion/final/<cena>-<hash>.mp4  final.mp4  cover/
```

## 5. Etapas ("agentes") e modelos

| Etapa | Papel do pedido | Modelo usado | Entrada (compacta) | Saída |
|---|---|---|---|---|
| `ideia` | Research Agent (temas) | `ideia` | histórico, regras, Analytics | pauta |
| `pesquisa` | Research Agent (fatos) | `ideia` | pauta | fatos com tipo (verificado, cálculo, estimativa, ilustração), orientação prática |
| `roteiro` | Script Agent | `roteiro` + revisor `critica` | pauta, fatos | cenas com narração e "visual" |
| `narracao` | Audio Director (voz) | voz do canal | narração | áudio e tempos por palavra |
| `storyboard` | Visual Director | `roteiro`; correções `critica` | catálogo resumido, cenas com tempos, fatos, 1 cena de exemplo | JSON validado |
| `assets` | Asset Manager | — | storyboard | relatório de uso do catálogo |
| `som` | Audio Director (SFX, ambiente, música) | — | roteiro, tempos | trilha de efeitos |
| `preview` | Rendering Agent | — | storyboard | preview por cena (cache) |
| `qualidade` | QA Agent | `critica`; correções `roteiro` | checagens automáticas + resumo do storyboard | nota, problemas, cenas refeitas |
| `render` | Rendering Agent | — | storyboard | final por cena (cache), mixagem, capa |
| `revisao` / `upload` | revisão humana e publicação | — | — | — |
| (contínuo) | Analytics Agent | `critica` | métricas | temas e formatos que rendem (`learn.py`) |

Nenhuma chave de modelo nova: cada etapa nova usa o modelo de uma etapa existente.

## 6. Componentes da engine (MVP implementado)

- **Personagem**: rig com cabeça, pescoço, tronco, braço, antebraço, mão, coxa, canela, pé, olhos (piscam), boca,
  sobrancelhas, cabelo (6 estilos) e acessórios (óculos, boné, fone, mochila), com pivôs em ombro, cotovelo, quadril
  e joelho. Ações: `walk` e `run` (passada atrelada à distância: o pé não desliza), `idle` (respiração e peso),
  `reaction` (surprised, jump_back, cover), `look_up`, `point`, `talk`, `shrug`, `expression`. Membros de trás mais
  escuros e sombra no chão dão profundidade.
- **Cenários**: `city`/`street` (céu, horizonte em duas camadas, prédios com janelas, fachada lateral, calçada,
  rua, postes, árvores, prédio principal com andares definidos), `nature`, `room`, `studio`; parallax por camada,
  horário do dia (dia, pôr do sol, noite, nublado), primeiro plano opcional.
- **Objetos**: ar-condicionado, suporte, caixa, bola, vaso, celular, carro, pedra, moeda; ações `appear`, `vanish`,
  `fall` (gravidade, quique, rachaduras e peças soltas no impacto), `move`, `rotate`, `wobble` (pêndulo), `shake`;
  sombra que cresce conforme o objeto se aproxima do chão.
- **Câmera**: `pan`, `zoom`, `focus`, `follow` (com enquadramento do alvo), `shake`, `roll`; entradas de cena `cut`,
  `fade`, `whip` (com desfoque), `zoom`, `slide`; câmera lenta por trecho (`time_warp`).
- **Informativos**: `speed` e `distance` (valores reais da física do alvo), `timer`, `counter`, `callout`, `highlight`,
  `arrow`, `title` (com [destaque]), `bars`.
- **Efeitos**: `impact`, `dust`, `smoke`, `speed_lines`, `light`, `flash`, `wind`, `rain`.
- **Legendas**: grupos curtos, palavra falada em destaque, números e palavras de ênfase sempre coloridos, posição
  que desvia das áreas ocupadas pelos informativos e da interface das plataformas.

## 7. Schema

Versionado (`schema_version: 1`), validado com Pydantic (`shortpipeline/motion/schema.py`) e publicado em
[schema.v1.json](schema.v1.json) (um teste garante que o arquivo está igual ao código). Pontos principais:

- Unidades: metros (`x`, `height` acima do chão), segundos a partir do início da cena, frações de tela (0–1).
- `at_word` em ações, movimentos de câmera, informativos e efeitos: o tempo vem da palavra da narração.
- Personagens declarados uma vez (`characters[].look`); as cenas referenciam por `ref`.
- Validação de referências: personagem declarado, alvo existente na cena, ids únicos, cenas contínuas, enums dos
  componentes, limites de texto e de quantidade de informativos.
- `facts`: o que o vídeo afirma, com o tipo e as premissas; as quedas ganham um fato calculado automaticamente
  (`physics.fall_facts`).
- O início e o fim das cenas vêm da narração real, não do que a IA escreveu (`motion.render.prepare`).

## 8. Armazenamento

Sem banco novo. O job guarda no SQLite só metadados pequenos (`research`, `storyboard` com caminho e versão,
`assets`, `preview`, `qa`, `cover`, `video`); o storyboard fica em `storyboard.json` no diretório do job (editável e
legível pelo painel). Os vídeos de cada cena ficam com o hash do conteúdo no nome: o cache guarda só a versão atual
de cada cena.

## 9. Economia de tokens

- Cada etapa recebe só a sua parte em JSON compacto: o storyboard não vê o histórico do canal, a qualidade vê um
  resumo de uma linha por cena, não o JSON inteiro.
- O catálogo vai como uma linha por asset (cerca de 400 tokens), não o registry.
- Um único exemplo de cena guia o formato (cerca de 350 tokens).
- Correções são pontuais: erro de validação volta com a lista de erros; a qualidade refaz no máximo 2 cenas, e
  só abaixo da nota mínima do canal.
- Nada de IA no render: a engine desenha. Preview e final reaproveitam as cenas que não mudaram.

## 10. Custos estimados por vídeo (40 s, 7 cenas)

| Item | Estimativa | Observação |
|---|---|---|
| Tokens de IA | ~18 mil de entrada e ~11 mil de saída | pesquisa 2k/1k, roteiro 3k/1k, revisor 3k/1k, storyboard 7k/6k, qualidade 3k/0,5k, correções eventuais |
| Custo de IA | dentro da assinatura (OAuth) | sem cobrança por chamada; conta para o limite de uso do plano |
| Voz ElevenLabs | ~600 créditos (≈1 por caractere no multilingual v2) | Edge TTS como reserva gratuita |
| SFX ElevenLabs | ~40 por efeito e ~200 por ambiente, com cache | sem créditos: biblioteca local e sons sintetizados |
| Render | preview ~0,4× e final ~2,5× a duração do vídeo | medido na demonstração: 51,8 s de vídeo, preview em 22 s, final em 131 s (16 núcleos) |
| Geração de imagem ou vídeo por IA | 0 | não é usada |

## 11. Fases

| Fase | Entrega | Critério de pronto | Estado |
|---|---|---|---|
| 1. MVP | schema, engine, personagem, cidade, queda, câmera, informativos, legendas, etapas, preview, qualidade, render, painel, testes | um Short animado completo sai pelo pipeline e passa nos testes de ponta a ponta | feito |
| 2. Edição | editar parâmetros de uma cena no painel e refazer só o preview dela; trocar look do personagem | uma mudança numa cena não re-renderiza as outras (o cache já faz isso no código) | a fazer |
| 3. Catálogo | mais cenários (industrial, escritório, céu), veículos animados, vista explodida, corte transversal, mais rigs (criança, animal) | um segundo nicho sai sem componente novo | a fazer |
| 4. Assets do usuário | importar SVG em camadas com pivôs para `data/motion-assets/`, validar e catalogar | um personagem importado anima com as mesmas ações | a fazer |
| 5. Retenção | retenção por cena do Analytics no aprendizado do formato | o storyboard recebe quais tipos de cena seguram o público | a fazer |

## 12. Riscos e limitações

- **Qualidade do movimento**: o rig 2D é simples (membros como traços arredondados). Fica limpo e legível, mas está
  longe de animação feita à mão. É o maior risco de qualidade e a razão da fase 3.
- **Catálogo limita a variedade**: com 9 objetos e 4 cenários, pautas fora do catálogo saem genéricas. O schema
  rejeita asset desconhecido, então a IA não "inventa" um objeto que a engine não sabe desenhar.
- **Tempo de render**: o Chromium headless é mais lento que o ffmpeg puro; o cache por cena e o preview em baixa
  resolução compensam nas revisões.
- **Física ilustrativa**: quedas sem resistência do ar. O fato calculado registra a premissa; objetos leves e
  quedas longas ficam acima da velocidade real (velocidade terminal).
- **Precisão da IA**: a pesquisa só marca e separa o que é fato, estimativa e cálculo; ela não consulta a internet.
  Os números do vídeo ainda passam pela revisão humana antes da publicação.
- **Legendas**: a posição evita os informativos registrados, mas não detecta todos os objetos do cenário.

## 13. Demonstração (medida)

Pauta: "E se um ar-condicionado caísse de um prédio enquanto você estivesse andando na rua?", num canal neutro de
teste, com Claude por OAuth e voz do Edge TTS.

| Etapa | Resultado |
|---|---|
| Pesquisa | 12 fatos: 3 verificados, 4 cálculos, 4 estimativas |
| Roteiro | 7 cenas, 119 palavras; revisor deu 7, reescreveu, depois 8 |
| Narração | 51,8 s (Edge TTS) |
| Storyboard | válido depois de 2 correções automáticas; 33 ações, 20 informativos; só assets do catálogo |
| Preview | 22 s (540×960, 15 fps) |
| Qualidade | nota 6: gancho lento e cenas de estúdio vazias; as duas correções de cena foram descartadas por zeros em campos opcionais |
| Render final | 131 s, 8,6 MB, 1080×1920 |
| Total | 7,8 min |

O que a demonstração mostrou e foi corrigido em seguida:

- palavras grudadas na legenda (o contorno comia o espaço da fonte condensada);
- legenda dentro do círculo de destaque;
- barras de comparação quebradas quando a IA definia `x`;
- zeros e nulos da IA em campos opcionais derrubando correções (agora `schema.clean` os remove antes de validar,
  e a correção de cena ganha uma segunda chance com os erros);
- direção: o prompt passou a exigir ação nos 2 primeiros segundos, estúdio só com um elemento grande e animado e
  velocímetro, régua e cronômetro só enquanto algo se move.

