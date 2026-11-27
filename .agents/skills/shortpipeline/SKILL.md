---
name: shortpipeline
description: Opera o ShortPipeline pela API local para criar Shorts, Shorts animados e vídeos longos, acompanhar jobs, revisar roteiros, aprovar etapas e obter o MP4.
---

Use o servidor local e a fila do ShortPipeline. A produção continua no app, e o painel permite editar a timeline e conferir as etapas.

Execute `python3 <pasta-da-skill>/scripts/pipeline.py --help`. O servidor padrão é `http://127.0.0.1:8765`. Se estiver desligado e o pedido exigir execução, inicie `uv run shortpipeline` na raiz do projeto. Use `--port` antes do subcomando se o servidor local estiver em outra porta.

- Identifique o canal com `channels`. Exemplos de IDs: `covarasa` e `tecnohype1`. Crie com `create CANAL --kind short|animado|long --topic "pauta" --count N`. Omita a pauta se o usuário pedir escolha automática. Se pediu revisão do roteiro, passe `--review-script`. O servidor precisa estar com a revisão após roteiro habilitada no canal. Se faltar, informe a opção no painel e só mude a configuração do canal se o usuário autorizar.
- Guarde os IDs retornados. Use `wait JOB [JOB ...]` para aguardar a próxima pausa ou conclusão, e `status JOB` para ler etapa, erro, roteiro em revisão e links. Se expirar, retome pelos mesmos IDs. Se uma criação falhar por timeout, confira os jobs recentes antes de tentar enfileirar de novo.
- Em revisão, mostre o roteiro quando for o ponto de parada pedido. Use `approve JOB ETAPA` após autorização do usuário para aquela etapa. Para aprovar uma pauta dentre as opções, use `approve-idea JOB INDICE`, com índice a partir de zero. Para substituir só a primeira fala, use `edit-hook JOB "nova fala"` durante a revisão de roteiro. O app retoma na narração com a edição.
- Entregue o campo `download` quando estiver disponível. A URL aponta para o MP4 com o título do vídeo no nome do arquivo.
- O helper cria e retoma produções locais em canais com publicação manual. Se o canal usa envio automático ou rascunho, use o painel para decidir o modo antes de enfileirar ou retomar. Preserve as regras editoriais e as configurações do canal.
