"""Prompts do formato animado. Cada etapa recebe só o que precisa (JSON compacto), nunca o histórico inteiro."""

RESEARCH_PROMPT = """Você é o pesquisador do canal de YouTube Shorts "{channel}" (nicho: {niche}).
Pauta: {topic}

Levante o que o vídeo precisa afirmar, em {language}. Regras:
- Só fatos bem estabelecidos. Se não tiver certeza, marque "estimate" e dê uma faixa nas premissas.
- Não invente fontes, estudos, nomes ou números. Em "source" diga o tipo de fonte (ex.: "física básica",
  "norma técnica", "dado de fabricante") e nunca um link inventado.
- Cálculos (velocidade, tempo, energia, custo) vão como "calculation", com a fórmula e as premissas.
- Inclua o que a pessoa deve fazer na vida real, quando a pauta envolver risco ou dinheiro.
- Em pauta hipotética ("e se…"), diga o que é ilustração e o que é física.

Responda SOMENTE com JSON:
{{"question": "a pergunta que o vídeo responde, em 1 frase",
  "facts": [{{"claim": "afirmação curta", "kind": "verified|calculation|estimate|illustrative",
             "value": número ou null, "formula": "se for cálculo", "assumptions": "premissas", "source": "tipo de fonte"}}],
  "safety": "orientação prática em 1 frase, ou \\"\\"",
  "avoid": ["afirmações populares que são falsas ou exageradas"]}}"""

ANIMATED_SCRIPT_PROMPT = """Você escreve roteiros de Shorts ANIMADOS (motion graphics 2D, personagens e objetos animados por
código) para o canal "{channel}". Nicho: {niche}

Escreva em {language} sobre: {topic}

Regras:
- {scenes} cenas, narração total de uns {seconds} segundos (cerca de {words} palavras).
- A primeira frase já coloca a pessoa na situação principal, com uma pergunta ou consequência concreta.
- Cada cena mostra algo que acontece na tela: um personagem faz algo, um objeto se move, um número aparece.
  Escreva em "visual" o que se vê, de forma concreta (quem, onde, o que se move, o que aparece de informação).
- O visual precisa ser possível com: cidade, rua, natureza, interior de casa ou estúdio neutro; pessoas
  estilizadas que andam, correm, reagem, olham para cima, mexem no celular, apontam, falam; objetos simples que caem, se movem,
  balançam; câmera que segue, aproxima, treme; velocímetro, régua de altura, cronômetro, contador, balões,
  setas, gráfico de barras.
- Se uma ação visível pede som, inclua até dois efeitos pontuais em sfx (por exemplo, estalo metálico).
  Use uma lista vazia quando a cena não precisar de efeito sonoro.
- Use os fatos da pesquisa. Números só os da pesquisa, com arredondamento honesto.
- Termine com uma conclusão que responde a pergunta, sem pedir like ou inscrição.
- Nada de violência gráfica: mostre a física e a consequência, não ferimentos.

Responda SOMENTE com JSON válido, sem markdown:
{{"title": "título curto e curioso (máx 70 caracteres, com #shorts no fim)",
  "description": "descrição de 2-3 linhas com hashtags",
  "tags": ["tag1", "tag2"],
  "cover_text": "2 a 5 palavras de impacto, com a palavra mais forte entre [colchetes]",
  "scenes": [{{"narration": "texto narrado", "visual": "o que acontece na tela",
               "sfx": [{{"word": "palavra exata da fala no momento da ação", "sound": "som concreto em termos curtos"}}]}}]}}"""

STORYBOARD_PROMPT = """Você é o diretor visual de um Short animado. Transforme o roteiro num JSON de composição que a
engine desenha sozinha. Você só escolhe e configura componentes do catálogo: não escreva código.

CATÁLOGO
{catalog}

CAMPOS PERMITIDOS (só estes; qualquer outro é rejeitado)
{fields}

MUNDO E UNIDADES
- Posições em metros: x para a direita, "height" para cima a partir do chão (o chão é height 0).
- upm = 200 (1 m = 200 unidades). Com zoom 1 a tela mostra 5,4 m de largura por 9,6 m de altura; o chão fica a
  78% da altura da tela quando a câmera usa o padrão. Uma pessoa tem 1,75 m. Um andar tem 3,2 m.
- Tempos em segundos a partir do início da cena. Para sincronizar com a fala use "at_word": "palavra" (a palavra
  exata da narração da cena) no lugar de start.
- Posições de tela (informativos sem alvo) em frações 0–1. Evite y > 0.8 (interface das plataformas).

REGRAS DE DIREÇÃO
- Declare cada personagem uma vez em "characters" com aparência fixa (look) e use "ref" nas cenas.
- Toda cena tem movimento visível: ação de personagem, ação de objeto ou movimento de câmera. Nada de cena parada.
- Mostre a ação do gancho já no primeiro segundo. Abra em detalhe ou plano médio, com o assunto grande e legível.
- Em cenas de 6 s ou mais, planeje mudanças de imagem conforme a narração traz informação nova (em geral a cada
  2–3 s). Descreva isso com ações e, quando revelar algo novo, um movimento de câmera do tipo cut dentro da cena.
  Um cut muda o enquadramento instantaneamente no start ou at_word. Pode usar x, height e zoom, ou target e frame_y.
  Use plano aberto brevemente para dar contexto e a seguir volte para o detalhe. Evite atravessar o cenário num pan
  quando quiser simplesmente trocar de assunto ou de altura.
- Se o roteiro marcar um efeito sonoro numa palavra, sincronize a ação correspondente com a mesma palavra.
- Reserve a faixa das legendas centrada em y=0.66 em todas as cenas. Posicione rostos, dados e detalhes da ação
  fora dessa faixa. Prefira um único dado legível junto ao elemento que ele explica.
- "studio" é só para números e comparações, e sempre com um objeto ou personagem grande (scale 1.5 a 3) animado
  no centro. Em temas técnicos, use time_of_day day e uma cor de fundo média (por exemplo, #314B64) com
  contraste para o objeto. Use night para iluminação escura intencional. Alterne estúdio com outros cenários
  quando a história mudar de lugar.
- speed, distance e timer só enquanto algo está de fato caindo ou se movendo na cena; nunca mostrando 0.
- No máximo 3 informativos por cena; textos curtos (callout até 60 caracteres). Sem texto fora dos informativos.
- Quedas usam a ação "fall" (a engine calcula gravidade de verdade); o velocímetro "speed" e a régua "distance"
  mostram os valores reais da queda. Números em counter/bars/callout precisam bater com os fatos.
- Use "time_warp" (câmera lenta) só no momento mais forte, e "shake"/"impact"/"flash" só em impactos.
- "enter" de cada cena: cut na maioria; whip, zoom, fade ou slide só quando a mudança de lugar ou ideia pedir.
- O mesmo objeto em cenas diferentes deve manter id, asset e posição coerentes.
- Campos opcionais que você não usar ficam de fora do JSON (não escreva 0 nem null).

ROTEIRO (cada cena já tem a duração e as palavras com o tempo em que são ditas)
{scenes}

FATOS
{facts}

EXEMPLO DE UMA CENA (formato; não copie o conteúdo)
{example}

Responda SOMENTE com o JSON completo:
{{"schema_version": 1, "title": "...", "theme": {{"accent": "{accent}"}},
  "characters": [{{"id": "...", "description": "...", "voice": "narrator|female|male", "look": {{...}}}}],
  "captions": {{"fixed_position": true, "y": 0.66, "emphasis": ["palavras importantes para destacar"]}},
  "cover_time": segundo do vídeo para a capa,
  "scenes": [{{"id": "s1_...", "start": 0, "end": duração, "narration": "...", "enter": {{...}},
              "environment": {{...}}, "characters": [...], "objects": [...], "camera": {{...}},
              "overlays": [...], "effects": [...], "time_warp": []}}]}}
Use exatamente {n} cenas, na ordem do roteiro."""

FIX_PROMPT = """O JSON de composição abaixo não passou na validação. Corrija só o que os erros apontam e devolva o JSON
completo, sem comentários.

ERROS
{errors}

JSON
{json}"""

QA_PROMPT = """Você é o editor de qualidade de Shorts animados. Avalie o storyboard abaixo como um editor exigente
avaliaria o vídeo pronto.

Critérios: gancho visual e narrativo no primeiro segundo; cada afirmação da narração aparece na tela; progressão
visual constante (nada parado); enquadramentos variados quando ajudam; tela limpa; personagens coerentes;
números iguais aos fatos; final que responde a pergunta.

Checagens automáticas já feitas:
{checks}

{visual}

Storyboard (resumo por cena):
{summary}

Responda SOMENTE com JSON:
{{"score": nota de 0 a 10, "issues": [{{"scene": "id da cena", "problem": "o que está fraco", "fix": "o que mudar,
concreto, com componentes do catálogo"}}]}}
Liste no máximo 3 problemas, só os que mudam a qualidade de verdade."""

SCENE_FIX_PROMPT = """Reescreva só esta cena do storyboard para resolver o problema. Mantenha id, start, end, narração e
os ids dos personagens e objetos que continuam. Use só componentes do catálogo.

CATÁLOGO
{catalog}

Em mudanças bruscas de enquadramento dentro da cena, use câmera cut com start (ou at_word) e x/height/zoom
ou target. Preserve a faixa de legendas (y=0.66) ao posicionar rostos e dados.

PROBLEMA: {problem}
COMO RESOLVER: {fix}

CENA
{scene}

Responda SOMENTE com o JSON da cena."""
