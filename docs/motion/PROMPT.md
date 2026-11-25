# Prompt do formato: Shorts animados em Motion Graphics 2D/2.5D

Pedido original do formato, reescrito a partir da infraestrutura real do ShortPipeline. O plano e as decisões
estão em [PLANO.md](PLANO.md).

## 1. Objetivo

Adicionar ao ShortPipeline um novo tipo de vídeo, "animado": Shorts verticais (YouTube Shorts, TikTok, Reels)
feitos com motion graphics 2D/2.5D montados por código, no estilo dos vídeos de curiosidade científica, situações
hipotéticas ("e se…?") e explicações de acontecimentos.

A IA atua como roteirista e diretora: escreve o roteiro e descreve as cenas num JSON. Toda a animação é executada
por código, de forma determinística, sem geração de vídeo por IA. O resultado deve parecer editado por um
profissional, nunca uma sequência de imagens com zoom.

O ShortPipeline é público e multi-nicho: o formato serve a qualquer canal (ciência, finanças, culinária,
história…) e não pode conter nada específico de um canal real (nomes, temas, vozes, assets ou exemplos).

## 2. Ponto de partida: o que já existe (reutilize, não duplique)

- **Orquestração**: FastAPI + fila em SQLite (`db.py`, `worker.py`). Cada vídeo é um job com etapas persistidas
  (`config.KIND_STAGES`, `pipeline/runner.py`); um job interrompido retoma da etapa em que parou. Não há OpenBot,
  Docker nem PostgreSQL: não os introduza.
- **IAs**: CLIs autenticadas por OAuth (claude, codex, agy), sem API key, com modelo e reserva configuráveis por
  etapa e por canal. O modelo de cada etapa é o "agente" dela.
- **Pauta**: IA, RSS ou radar de tendências, com revisão editorial e temas guiados pelo Analytics.
- **Roteiro e revisão**: `pipeline/writing.py` e o revisor (`critique`).
- **Narração**: ElevenLabs com reserva no Edge TTS, com tempos por palavra.
- **Som**: biblioteca do usuário, pacotes CC0, SFX em cache, música por canal com `music.json`, ambiente nivelado.
- **Legendas**: destaque por palavra. **Motion Canvas 3.17** já instalado e renderizado headless pelo Chromium do
  Playwright.
- **Painel**: timeline, checagem do render, aprovação antes do render, publicação e Analytics.
- **Testes**: pytest com IA e voz simuladas e ffmpeg de verdade; ruff e `node --check` no CI.

Restrições: não alterar o fluxo dos tipos existentes (short, long, fonte, corte); sem serviços ou bancos novos;
dependências Node só dentro de `motion-canvas/`; tudo local, headless, em Linux.

## 3. Decisão de motor

Comparar Motion Canvas (já integrado, MIT) e Remotion (React; licença paga para empresas com 4 pessoas ou mais, o
que pesa para quem usa a ferramenta pública) por licença, determinismo por frame, velocidade headless, composição
por JSON e manutenção. O JSON de cena não pode depender do motor.

## 4. Direção de arte

Identidade própria e consistente (paleta e tipografia do canal sobre a mesma estrutura): vetor flat, personagens
articulados com proporções simplificadas, cenários urbanos, domésticos, naturais e industriais em camadas, 2.5D,
sombras suaves, objetos com volume simples, movimento com easing, informação integrada ao cenário, composição
cinematográfica.

Evitar: imagem parada com zoom; personagem inconsistente; cara de slide; tela poluída; transição genérica repetida;
movimento robótico; texto dentro de imagem gerada. Todo texto é renderizado por código, fora das áreas da interface
das plataformas.

## 5. Componentes

Parametrizados, determinísticos (função do frame, sem timers) e com o catálogo exposto à IA como enum:

- Personagem: rig em camadas com pivôs; roupa, cabelo, cores, acessórios e expressão trocáveis; idle, walk, run,
  talk, reaction, look_at, gesture, expression.
- Cenário: camadas com parallax (city, street, house, office, nature, industrial, sky).
- Objeto: animated, falling, rotating, vehicle, collision, highlight, exploded_view, cross_section (SVG; 3D só
  quando agregar).
- Câmera: pan, zoom, follow, shake, focus, transition, slow_motion.
- Informativos: callout, counter, speed, distance, measurement_line, comparison_chart, arrow, highlight_circle,
  timeline, progress, seguindo objetos em movimento.
- Efeitos: dust, smoke, impact, wind, motion_trail, light, speed_lines, rain, fire, discretos.

## 6. Física

Funções puras para gravidade, velocidade, aceleração, trajetória, rotação, colisão simples, pêndulo, veículo,
caminhada e corrida, interpolação, easing e câmera lenta. Número afirmado no vídeo vem de um cálculo registrado no
JSON com as premissas, e o vídeo distingue ilustração de cálculo.

## 7. JSON de composição

Schema versionado e validado; personagens declarados uma vez; cenas sincronizadas com a narração (tempos das
palavras); ações com início em segundo ou em palavra (`at_word`); câmera, informativos com alvo, efeitos,
transições; cálculos com premissas. Referências validadas antes do render; erro volta à IA com a mensagem exata.

## 8. Etapas (os "agentes" são etapas do pipeline)

ideia → pesquisa → roteiro → narração → storyboard → assets → som → preview → qualidade → render → revisão →
publicação, com aprendizado pelo Analytics. Cada etapa grava o seu resultado e não roda de novo se concluída.
A qualidade pede correção pontual da cena, nunca refaz o vídeo todo.

## 9. Assets

No repositório só assets próprios ou CC0 (`assets/motion/`); os do usuário em `data/motion-assets/`, fora do git;
`registry.json` com id, categoria, tags, dimensões, estilo, pivôs, animações, caminho, versão, origem e licença.
Consultar o catálogo antes de criar qualquer coisa; à IA vai um resumo compacto.

## 10. Custos e tokens

Cada etapa recebe só o que precisa; modelo forte em roteiro, storyboard e qualidade; cache de narração, SFX,
previews por cena e assets; cena aprovada não é regerada; sem API paga de vídeo.

## 11. Legendas

Destaque por palavra, alta legibilidade, posição que desvia de objetos e informativos, fora da interface das
plataformas.

## 12. Exportação

1080×1920, 9:16, 30 fps, MP4 (H.264 + AAC), preview em baixa resolução, local e headless.

## 13. MVP

Schema + validação + adaptador; personagem articulado (walk, idle, reaction); cenário urbano com parallax; queda
por gravidade; câmera (follow, zoom, shake); informativos (speed, distance); narração com legendas; preview por
cena; render final; testes de ponta a ponta. Demonstração: "E se um ar-condicionado caísse de um prédio enquanto
você anda na rua?", com números calculados e sem violência gráfica.

## 14. Entregáveis antes de implementar

Diagnóstico, decisão de motor, arquitetura, diretórios, etapas, componentes, schema, armazenamento, custos e tokens,
plano por fases com critério de pronto e riscos, em `docs/motion/`.
