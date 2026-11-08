# Manual do utilizador Vitrail

## Bem-vindo ao Vitrail

O Vitrail é uma plataforma de sinalética digital (digital signage): difunde conteúdos (vídeos, imagens, páginas web, feeds de notícias, áudio) em ecrãs geridos por players, a partir de uma interface web centralizada.

![O painel: indicadores da rede, mapa do parque, atividade recente](/help/img/dashboard.webp)

### Conceitos-chave

- **Organização**: o seu espaço de trabalho. Conteúdos, players e utilizadores estão isolados das outras organizações.
- **Player**: o software instalado no dispositivo ligado a um ecrã (NUC Linux, Raspberry Pi, PC Windows, box Android, Chromebox, BrightSign, ou uma simples extensão Chrome). Recebe as instruções do servidor — nunca o contrário — e continua a funcionar offline.
- **Média**: um conteúdo importado (vídeo, imagem, documento) ou dinâmico (página web, feed, entrada HDMI).
- **Playlist**: uma sequência de médias reproduzida em ciclo.
- **Agendamento (schedule)**: quando e em que players uma playlist é difundida.
- **Evento**: uma difusão pontual ou acionada que tem prioridade sobre o agendamento normal.
- **Campanha**: publicidade de anunciantes intercalada nos seus ciclos, vendida como quota de voz (retail media).

### O percurso típico

1. **Registar um player**: gere um token de aprovisionamento, instale o player e ele aparece em Players.
2. **Importar conteúdo** para a Mediateca.
3. **Criar uma playlist** com esse conteúdo.
4. **Agendar** a playlist num ou vários players.

O ecrã mostra o conteúdo poucos segundos depois de guardar o agendamento.

> Falta-lhe um menu ou uma ação? É provavelmente uma questão de perfil: pergunte ao administrador da organização (ver «Utilizadores, perfis e segurança»).

## Players


![A lista de players: estado, site, versão, última ligação](/help/img/players.webp)
### Registar um player

Um player junta-se à organização através de um **token de aprovisionamento**:

1. **Players → Provisioning** → **Novo token** (barra superior).
2. Escolha o número máximo de players e uma expiração (ou «Sem expiração»).
3. Copie o token (`sfp_…`) e forneça-o na instalação do player junto com o URL do servidor.

No primeiro arranque, o player troca o token pela sua identidade permanente e aparece em **Players**. Um token ativo pode ser **revogado** (deixa de registar; os players já registados continuam) e depois eliminado.

![Aprovisionamento: tokens de registo e geração de payload](/help/img/players-provisioning.webp)

### Aprovisionamento em lote e pen USB

O painel **Gerar um payload** prepara a configuração de várias máquinas de uma vez: modo por máquina ou definições partilhadas, importação CSV, resolução (Auto/HD/FHD/4K/8K/personalizada), Wi-Fi, reassociação de um player existente (lista com pesquisa). O payload aplica-se por pen USB nos players Linux preparados, ou por cartão SD no BrightSign.

### Supervisionar e configurar à distância

A lista de Players mostra o estado (online / offline / suspensão programada) com a data do último contacto. O painel de um player mostra: máquina, ecrã, rede, fuso horário, inventário de médias, captura de ecrã recente, capacidades de descodificação.

Sem SSH, pode enviar: resolução, rotação, volume, som, motor de renderização, fuso horário, limite de largura de banda. O botão **«Info no ecrã»** mostra um painel de diagnóstico diretamente no ecrã do player (nome, rede, programa atual, média em reprodução). Botões pontuais: reiniciar a aplicação, reiniciar a máquina, forçar a ressincronização, captura de ecrã. O botão **«Comandos em massa»** da barra superior envia o mesmo comando a um alvo inteiro (organização, site, grupo de sites, grupo de players); uma pré-visualização lista os ecrãs afetados **antes** do envio, e os comandos destrutivos (reinício, sair da aplicação, manutenção) exigem uma caixa de confirmação **e o seu PIN**.

Duas definições de «campanhas» vivem também neste painel: **Excluído das campanhas publicitárias** (opt-out) e o **teto de ocupação publicitária** (ver Campanhas).

![O painel de um player: máquina, ecrã, rede, ações remotas](/help/img/player-drawer.webp)

### Grupos e sincronização LAN

Os **grupos de players** servem de alvo de difusão e suportam a **sincronização LAN**: vários players da mesma rede local reproduzem o mesmo vídeo imagem a imagem (mural de ecrãs). A sincronização é fiável quando o grupo é **homogéneo** (mesmo hardware) e os players partilham o mesmo relógio (ver NTP). Um membro do grupo pode ser designado **relé NTP**.

### Extensão Chrome (sem hardware)

A extensão Chrome transforma um navegador em player: ideal para testar ou para um posto existente. Carregue a extensão (modo de programador), introduza o URL do servidor e um token `sfp_…`. Limites: sem sincronização LAN, modo offline reduzido. Para um verdadeiro quiosque ChromeOS, use o player ChromeOS PWA.

## Sites

Um **site** representa um local físico (loja, agência). Cada player está associado a um site.

- **Fuso horário**: todo o agendamento corre na hora local do site. Um player associado é alinhado automaticamente com o fuso do site (aviso em caso de diferença, correção à distância a partir do painel).
- **Horário de funcionamento**: dias e horas, com **exceções datadas** (feriado, inventário, evento noturno) e fecho automático nos **feriados** (calendário regional opcional). Um dia sem horário está fechado. Estes horários comandam a alimentação dos ecrãs (ver «Ecrãs e alimentação») e o assistente conhece-os («o site X está aberto ao domingo?»).
- **Servidor NTP**: para que todos os players do site partilhem exatamente o mesmo relógio (indispensável à sincronização LAN).
- **Coordenadas**: posicione o site no mapa (usado pelos relatórios geográficos e pelo portal do anunciante).
- **Categorias excluídas**: as categorias de indústria proibidas de publicidade neste site (ver Campanhas).
- O separador **Grupos de sites** cria conjuntos (região, insígnia) utilizáveis como alvo em agendamentos, eventos, campanhas e atualizações.

Ao passar o cursor sobre um site (lista), uma dica resume os seus players e a ocupação publicitária a 7 dias.

![Os sites: fuso horário, horários de abertura, coordenadas](/help/img/sites.webp)

![Os grupos de sites (região, insígnia) utilizáveis como alvo](/help/img/site-groups.webp)

## Mediateca


![A mediateca: pastas, miniaturas, filtros por tipo](/help/img/media.webp)
### Importar

**Mediateca → Importar**: vídeos, imagens, documentos (PDF). O separador **Fotos livres** usa Unsplash/Pexels com atribuição automática. Um vídeo é transcodificado automaticamente para um formato universal: o conteúdo anterior continua a ser difundido durante o processamento, nenhum ecrã fica preto. Se a política de **renditions** da organização estiver ativa, um vídeo 4K gera também uma versão Full HD — cada player recebe a resolução adequada ao seu ecrã.

![Importar media (ficheiros, fotos livres)](/help/img/media-upload.webp)

### Organizar

- **Pastas** e subpastas (coluna esquerda), movimentação em massa.
- **Etiquetas (tags)**: taxonomia por espaços de nomes (Mediateca → Tags), atribuição múltipla e **filtragem por etiquetas ao nível do player** (um player só reproduz os conteúdos que correspondem às suas etiquetas).
- Pesquisa, filtro por tipo (imagens/vídeos/áudio/documentos/páginas web), paginação.

### Gerir o ciclo de vida

- **Substituir o ficheiro** de um média sem mudar a sua identidade: as playlists que o usam não mexem, a troca é atómica no fim da transcodificação.
- **Eliminar com segurança**: a janela de impacto lista playlists, agendamentos, eventos e cestos que usam o média, e o estado de difusão, antes da eliminação em cascata.
- **Quarentena**: bloquear um média imediatamente em todo o parque (mesmo offline), depois desbloquear ou limpar a cache.
- **Conformidade**: cada vídeo tem um veredicto (pronto / difundível / não conforme) sobre a sua codificação, com reanálise e modo passthrough (manter o ficheiro original sem recodificar).

![O painel de um media: pré-visualização, metadados, conformidade, ciclo de vida](/help/img/media-drawer.webp)

## Modelos (templates)

Os **modelos** definem composições multizona (vídeo principal + faixa + logótipo…). O editor trabalha na **resolução do canvas** declarada (FHD, 4K, vertical, LED à medida) — escolha a resolução do ecrã de destino. Uma playlist associada a um modelo alimenta as suas zonas; um aviso aparece se a resolução do modelo não corresponder ao ecrã.

![Os modelos multizona, com a sua resolução de canvas](/help/img/templates.webp)

![O editor de modelos: zonas, camadas e propriedades](/help/img/templates-editor.webp)

## Playlists

1. **Playlists → Nova playlist**, depois adicione médias (multisseleção, pesquisa, pastas).
2. Defina a ordem, a duração de exibição das imagens/documentos e a zona (modelos multizona). Os **vídeos mostram a sua duração nativa** — lê-se, não se regula.
3. As alterações acumulam-se como **rascunho**: o botão **Publicar** envia-as aos players de uma vez (troca limpa, nunca um estado vazio).

O cabeçalho do editor e cada cartão de playlist mostram **o número de conteúdos e a duração total** do ciclo; o total acompanha as suas alterações em direto, rascunho incluído.

![As playlists: duração total, número de itens, estado de publicação](/help/img/playlists.webp)

![O editor de playlist: ordem, durações, regras por item, rascunho a publicar](/help/img/playlist-editor.webp)

![Adicionar media: pesquisa, pastas, seleção múltipla](/help/img/playlist-add-media.webp)

### Pré-visualizar uma playlist

O botão de **reprodução** — no cartão de uma playlist ou no editor — percorre o ciclo como o faria um ecrã. Numa playlist associada a um **modelo multizona**, a pré-visualização compõe todas as zonas ao mesmo tempo, na proporção do modelo, avançando cada zona com o seu próprio temporizador.

É uma pré-visualização, não o espelho de um ecrã: cada zona começa no início do seu ciclo, e a rotação, os spots de campanha e a filtragem por etiquetas não são reproduzidos aqui. Os feeds, as páginas web e as entradas HDMI aparecem com o seu nome no seu lugar e tamanho reais — são produzidos no ecrã, no momento da difusão.

### Regras de difusão por item

Cada item pode ter a sua própria regra: dias da semana, faixa horária, intervalo de datas de validade — na hora local do player. As **exceções por alvo** afinam: determinado player ou grupo reproduz o item com uma regra diferente. Um item sem regra é perpétuo.

### Playlist de rotação (N itens por volta)

Uma playlist pode ser **aninhada dentro de outra** como um item (botão **Adicionar uma playlist** no editor). O seu ajuste de **Rotação** decide o comportamento:

- **Todos os itens**: a sub-playlist toca inteira em cada volta.
- **N por volta — em ordem**: N item(ns) por volta, os seguintes na volta seguinte (com 5 vídeos e 2 por volta: 1-2, depois 3-4, depois 5-1…).
- **N por volta — aleatório**: ordem misturada, mas nenhum item repete até todos terem passado; depois volta a misturar.

Só é permitido um nível de aninhamento; uma playlist referenciada como sub-playlist não pode ser eliminada (retire-a primeiro das playlists-mãe). As regras e etiquetas por item vivem nos itens **da sub-playlist**. A rotação permanece **sincronizada** entre ecrãs de um grupo LAN, e a **simulação de linha do tempo** mostra a sequência real volta a volta. Se a mesma sub-playlist aparecer **várias vezes** numa volta, todas as ocorrências tocam o **mesmo item na mesma volta** (sorteio partilhado, garantia de determinismo) — para variar dentro de uma volta, aumente «Itens por volta».

Estas definições **seguem o rascunho**, tal como os conteúdos: ao alterá-las aparece o aviso «Alterações não publicadas» e os ecrãs continuam a reproduzir o ciclo publicado até clicar em **Publicar** (ou, numa playlist governada sob moderação, até à **aprovação**).

![Aninhar uma sub-playlist e definir a sua rotação (N itens por volta)](/help/img/playlist-add-playlist.webp)

![A simulação da timeline: o desenrolar real volta a volta](/help/img/playlist-simulation.webp)

## Cestos de áudio

Os **cestos de áudio** difundem um fundo sonoro na loja, independente do conteúdo visual: música de fundo, jingles a intervalos ou a horas fixas, com **ducking** automático (a música baixa durante um jingle). Cada player tem um **papel de áudio**: conteúdos padrão (som dos vídeos), só áudio, ou misto (fundo sonoro + vídeos silenciados). O **painel de controlo de loja** (LAN) permite à equipa local agir sem conta no CMS. Cada cartão de cesto mostra **o número de faixas e a duração total**. Os relatórios de direitos musicais apoiam-se nas reproduções comprovadas.

![Os cestos de áudio: música de fundo, jingles, ducking](/help/img/audio-baskets.webp)

![O conteúdo de um cesto de áudio e as suas regras de difusão](/help/img/audio-baskets-edit.webp)

## Agendamento

Um **agendamento** diz o que difundir (uma playlist), onde (players, grupos, sites, grupos de sites, etiquetas) e quando (dias, faixas, intervalo de validade, prioridade).

1. **Agendamento** → crie uma regra, escolha playlist, alvos e janela temporal.
2. Os players atualizam-se em segundos.
3. O **calendário unificado** sobrepõe programas visuais e de áudio, eventos e campanhas (legenda com ícones). Filtre por tipo (pastilhas Tudo/Visuais/Áudio/Eventos/Campanhas) ou por **alvo** (grupo de sites, site, player); a **exportação CSV** segue os filtros ativos. Em sobreposição, ganha a **prioridade** mais alta.

![O calendário unificado: agendamentos, eventos e campanhas sobrepostos](/help/img/schedules.webp)

![Criar um agendamento: playlist, alvos, janela e prioridade](/help/img/schedule-new.webp)

![Simular o agendamento de um player ao longo de um dia](/help/img/schedule-simulation.webp)

As redes com vários níveis (sede, regiões, lojas) compõem a sua programação com a **Governação hierárquica** — ver a secção dedicada mais abaixo.

## Governação hierárquica (redes multi-local)

A **Governação** serve às redes em que vários níveis decidem o que é exibido: uma sede, regiões, lojas. Cada nível compõe **a sua** parte da programação, e os ecrãs emitem a **soma** dos níveis de que dependem. Uma instalação de um só local não precisa dela: sem nó, nada muda (o campo «Nó proprietário» nem sequer aparece).

![A governação hierárquica: nacional, regional, local](/help/img/governance.webp)

### As cinco noções

- **O nó** é um nível da organização. É o seu **nível** na árvore (raiz = 0) que fixa a ordem nacional → local, não o seu «tipo», que é apenas uma etiqueta.
- **O perímetro** é o conjunto de ecrãs que um nó comanda: ligam-se-lhe ecrãs, grupos de ecrãs, locais ou grupos de locais. O perímetro de um nó **inclui o dos seus descendentes** — basta ligar os locais aos nós de loja.
- **A camada**: cada programa ligado a um nó produz uma camada. Um ecrã compila todas as camadas dos nós de que depende. É o que mostra a coluna «Programa compilado», **para esse ecrã e nesse instante**.
- **A regra** diz quanto cada nível pode tomar. A mais usada é «**conteúdos por volta**»: com 1, cada nível coloca um conteúdo por volta e **roda** os seus conteúdos.
- **O administrador de nó** decide por esse nó. ⚠️ Uma permissão **nunca** basta: é esta atribuição que autoriza a escrever.

### Quem pode o quê

O administrador de um nó age sobre **o seu nó e toda a sua subárvore**. Vê os níveis acima **em leitura apenas** e **não vê de todo** os ramos vizinhos. Três gestos sobem sempre um degrau: **desligar** um conteúdo da governação, **retirar a moderação** ou **levantar uma restrição**, e **validar** uma submissão — o validador deve administrar um nó **pai**, e ninguém valida a sua própria submissão. Criar um nó **raiz** é reservado ao administrador de organização.

- **Governação — Diretor**: constrói a estrutura — nós, perímetros, administradores, regras. Lê o conteúdo, não o produz.
- **Governação — Programador**: cria os **programas** e as **listas** dos seus nós, submete a aprovação.
- **Governação — Editor**: produz o conteúdo (listas, media) e submete-o. Não elimina nenhum media, não programa.
- **Governação — Validador**: aprova, rejeita ou pede alterações na sua subárvore.

Estes quatro papéis carregam uma **semântica de perímetro**: o seu portador só age na sua subárvore, e **o conteúdo não governado é-lhe invisível**.

### O conteúdo governado

Uma lista, um media, um modelo, um evento e uma configuração VOD podem pertencer a um nó (campo «Nó proprietário»). Sem nó, o objeto pertence à organização e comporta-se como antes. Um objeto ligado só pode ser modificado pelos administradores do seu nó ou de um nó pai; se o nó estiver marcado **«Conteúdo sujeito a aprovação»**, **submete-se** em vez de publicar, e é a validação que publica. Esta moderação é **herdada para baixo**.

⚠️ **Dois mal-entendidos que custam caro.** Ligar uma lista a um nó decide **quem a edita**; não a **emite** — a emissão vem de um **programa** ligado ao mesmo nó. E o **papel** diz o que se pode fazer, a **atribuição de administrador** diz **onde**.

### Visar apenas parte dos ecrãs de um nó

Por omissão, um programa ligado a um nó emite em **todos** os seus ecrãs. Para visar apenas uma parte, acrescente-lhe **destinos**: **restringem** o perímetro, nunca o alargam, e um nível inferior nunca pode restringir uma camada **herdada**. Um destino que não retém nenhum ecrã é recusado nomeando-o, e o número de ecrãs retidos é apresentado. **Deixar um programa sem destino é muitas vezes a escolha certa**: cobre então todo o seu nó, incluindo os locais acrescentados mais tarde.

### Exemplo completo: entrada e saída de loja

Objetivo: em cada loja, o ecrã de **entrada** e o de **saída** emitem um conteúdo **a mais** do que os outros, e o responsável da loja muda ele próprio os seus conteúdos e programas.

**A árvore** — `Nacional` → `Dpt-01` → `Site-01`, `Site-02`.

**O perímetro** — liga-se **o local** ao nó de loja. O departamento e o nacional não têm **nenhuma atribuição**: herdam da subárvore.

**Dois grupos de ecrãs** — «Entradas» contém o ecrã de entrada **de cada** loja, «Saídas» as saídas. O grupo marca o **papel** do ecrã, o nó marca a **loja**: o cruzamento dos dois designa o ecrã certo, sem criar um grupo por loja.

**Os conteúdos** — cada loja possui **as suas próprias** listas: local, entrada, saída. 🔑 Uma lista partilhada entre duas lojas só pode ser modificada pelo seu proprietário — o outro responsável nem sequer a consegue ler.

**Os programas** — um por nó, mais dois por loja:

- **Nacional** — programa «SC Nacional», **sem destino**: todos os ecrãs da rede.
- **Dpt-01** — programa «SC Dpt», **sem destino**: todos os ecrãs do departamento.
- **Site-01** — programa «SC Site-01», dirigido aos ecrãs da loja: o conteúdo local.
- **Site-01** — programa «SC Entrada Site-01», dirigido ao grupo «Entradas»: apenas a entrada.
- **Site-01** — programa «SC Saída Site-01», dirigido ao grupo «Saídas»: apenas a saída.

Com «conteúdos por volta = 1» em cada nó, os ecrãs comuns emitem **3 conteúdos por volta** (nacional + departamento + local) e tanto a entrada como a saída emitem **4**.

**Acrescentar uma loja** são então cinco gestos: criar o nó sob o departamento, ligar-lhe o local, criar as suas três listas, criar os seus três programas, acrescentar o ecrã de entrada ao grupo «Entradas» e o de saída ao grupo «Saídas». Os programas nacional e de departamento não precisam de ser tocados.

### Compor um perímetro à escala

O botão **«Adicionar ecrãs»** abre uma pesquisa **do lado do servidor**: filtre por natureza (ecrã, grupo de ecrãs, local, grupo de locais), selecione **vários destinos de uma vez**, e cada linha indica **quantos ecrãs representa**. Um ecrã ainda ligado a **nenhum** nó é proposto e **etiquetado**: é assim que um esquecimento de instalação se vê e se repara.

### Reorganizar e diagnosticar

Um nó pode ser **movido** para outro pai: caminhos, níveis e emissão de toda a sua subárvore acompanham. Não pode ser movido para um dos seus próprios descendentes, nem para um ramo que não administra.

Quando a pré-visualização de um ecrã está vazia, a mensagem **nomeia a causa**: sem nó, sem programa no nó, programa inativo, sem lista, **sem regra horária** (nunca estará ativo), ou fora da sua janela nesse instante.


## Eventos

Um **evento** tem prioridade temporária sobre o agendamento: promoção, anúncio, conteúdo acionado.

- Conteúdo: uma playlist ou um único média. Alvo: organização, site, grupo ou player — e os tipos podem ser **misturados** num mesmo evento («este site» + «estes 3 ecrãs», como as campanhas): as seleções somam-se e o resumo nomeia tudo o que foi incluído. «Toda a organização» substitui as outras seleções.
- Tipos: **manual** (acionado a pedido), **agendado** (janela data/hora, opcionalmente recorrente).
- **Spot horário**: num evento agendado em «Reproduzir uma vez», ative a repetição a intervalo fixo (ex.: um spot a cada 30 minutos). O campo só aparece nessa combinação.
- **Fuso horário de referência** (evento agendado): define o que «18:00» significa. Por omissão, o do servidor. Numa rede espalhada por vários países, escolha-o explicitamente — um evento ativa-se num **único instante**, não às 18:00 em cada país. O fuso é indicado ao lado do horário na lista.
- ⚠️ Não confundir com o **embargo**, que é um instante **absoluto** (UTC): não depende de nenhum fuso e não é afetado por esta definição.
- Opção **«manter os ecrãs ligados»**: mantém a exibição durante o evento mesmo fora do horário de funcionamento.
- No fim, o player volta exatamente ao seu agendamento (hora atual).
- Um evento **(re)ativado a meio da janela** com um média nunca distribuído pode demorar alguns minutos a aparecer (o player descarrega primeiro o ficheiro — nunca um ecrã preto). Ative/agende com antecedência para uma troca instantânea.

![Os eventos: manuais ou agendados, com o seu estado](/help/img/events.webp)

![Um evento: conteúdo, alvo, tipo, spot horário, ecrãs ligados](/help/img/event-edit.webp)

## Difusão a pedido (VOD)

A página **On-Demand** difunde um conteúdo imediatamente, por cima do agendamento, sem tocar nas playlists. Uma **config VOD** agrupa médias e um alvo: **players selecionados** (do mesmo site) ou um **site inteiro** — caso em que qualquer player adicionado ao site mais tarde é considerado automaticamente; os médias são pré-descarregados, o acionamento é instantâneo: **Uma vez** ou **Em ciclo** (até Stop). A permissão `vod : trigger` sozinha chega para uma conta «loja». No fim, o agendamento retoma à hora atual.

![As configurações de difusão a pedido](/help/img/vod.webp)

![Uma config VOD: media pré-descarregados e players alvo](/help/img/vod-edit.webp)

> Particularidades **BrightSign**: o arranque e a paragem podem demorar **até 2 segundos** (relé local integrado) — é normal. Durante a difusão, a playlist fica suspensa (um único fluxo de vídeo por hardware nestes players) e retoma depois à hora atual. O pré-descarregamento inicial pode demorar com ficheiros 4K: enquanto um média não estiver em cache, é lido em streaming (arranque adiado).

## Entrada HDMI

O média **«Entrada HDMI»** mostra qualquer fonte ligada à entrada HDMI do player (descodificador de TV, box, consola) — reprodução puramente local. Compatível: BrightSign com entrada HDMI física (gamas XT, 4K114x, XD1230).

- **Em playlist**: uma faixa muda para a fonte e depois retoma a playlist; os players sem entrada ignoram o item. Sem sinal, o ecrã mostra «No Signal Detected» (nunca um ecrã preto).
- **A pedido**: através de uma config VOD, botões **Mudar para HDMI / Voltar à playlist** (retoma à hora atual).
- **Página local**: cada BrightSign compatível serve `http://<ip>:8888/control` — mudar/voltar a partir de qualquer telemóvel da loja, sem conta nem servidor (ativação + PIN por player).
- Salvaguardas: uma comutação ativa é terminada quando o ecrã se desliga; cada sessão é rastreada (auditoria + prova de reprodução assinada com a duração real).

## Feeds e páginas web

### Feeds (fluxos de notícias)

Um **feed** é uma fonte consultada pelo servidor: RSS/Atom, Google News, YouTube, meteorologia, cripto, finanças, redes sociais (via proxy de feeds). Modos de exibição: faixa deslizante, carrossel, grelha, artigo em ecrã inteiro, composição dividida, lista, mural social, gráfico. Opções: **resumo IA** dos artigos (uma frase legível ao longe), **moderação** (validar cada artigo antes de difundir), miniaturas em cache no player (funciona offline).

### Páginas web (URL Display)

Mostre uma página web no ecrã: modo **WebView** (renderização em direto no player) ou **captura no servidor** (o servidor fotografa a página periodicamente — para páginas que recusam a integração ou exigem autenticação do lado do servidor). Uma página web é um média como outro qualquer: etiquetas, playlists, agendamento.

![Página web (URL Display): modo WebView ou captura do servidor](/help/img/media-web-page.webp)

## Geração por IA

O Vitrail gera imagens, vídeos, música e vozes-off a partir de uma descrição. O média gerado entra na mediateca normalmente.

- **Pré-requisito**: as chaves de IA da organização (**Configurações → Chaves IA**) — fal.ai (imagens/vídeos/música/voz), ElevenLabs (áudio pro), Anthropic (assistente de redação e Studio). Paga ao seu próprio fornecedor; sem chave, a função fica inativa.
- **Onde**: Mediateca → **Gerar (IA)** para um recurso; **Studio** para uma campanha completa a partir de um briefing (conceitos por formato, custo total mostrado antes de gerar).
- **Prompts**: os modelos trabalham em inglês — o **assistente de redação** transforma a sua ideia (qualquer língua) num prompt inglês otimizado + prompt negativo. Simplicidade: sujeito + ação + estilo; para vídeo acrescente câmara e luz; nunca meta-instruções («conteúdo promocional…» acaba desenhado na imagem).
- **Edição**: recorte de fundo, retoque por instrução, variações múltiplas, imagem → vídeo (descreva apenas o movimento).
- Uma **estimativa de custo** é mostrada antes de cada geração.

![Geração por IA: imagem, vídeo, música ou voz a partir de uma descrição](/help/img/media-generate-ai.webp)

## Gerador promo

O **Gerador promo** cria um cartaz promocional (imagem ou vídeo curto) a partir de um produto, um preço e um layout. O resultado vai para a mediateca e é difundido como qualquer outro média.

- **Onde**: Mediateca → **Gerador promo**.
- **Um percurso em seis etapas**: **Para quem?** · **O produto** · **Texto e preço** · **Layout** · **O fundo** · **Retoques livres**. Só uma etapa está aberta de cada vez, para que todos os seus campos caibam no ecrã; fechada, a etapa **mostra o seu valor**. Abrem-se por qualquer ordem.
- **«Para quem?» primeiro**: a minha insígnia ou um anunciante — o **manual de marca deduz-se** (cores, tipo de letra, logótipo, menções) em vez de ser escolhido.
- **Partir de um URL de produto**: cole o endereço de uma ficha e o nome, o preço e a foto são extraídos. Tudo continua modificável: é uma ajuda ao preenchimento, não uma fonte de verdade.
- **O preço é obrigatório.** **Gerar** fica apagado enquanto faltar, e o aviso sob a pré-visualização diz o que falta **e leva à etapa certa**. O mesmo aviso assinala problemas de legibilidade, revalidados pelo servidor antes de produzir.
- **A IA só faz o fundo** (e recorta o produto). Preço, desconto, nome e menções legais são colocados pelo compositing a partir do que escreveu — logo, exatos.
- **Encadear**: «Refazer com outro produto» mantém marca, layout, fundo e menções; as **predefinições** recuperam uma configuração completa.

![O gerador promo: um percurso em seis etapas à esquerda, a pré-visualização ao centro](/help/img/promo.webp)

### Modo série — um layout, N produtos

O comutador **Um visual / Série**, no topo, substitui a pré-visualização por uma **tabela**: uma linha por visual. O percurso da esquerda continua a definir o que é **comum** (marca, layout, fundo, menções, moeda); a tabela só transporta o que **varia** — produto, slogan, preço, preço riscado, desconto.

- **Três formas de a preencher, cumuláveis**: adicionar uma linha à mão, **importar um CSV** ou **colar de uma folha de cálculo** (Excel, Google Sheets). Os cabeçalhos são reconhecidos em português, francês e inglês, por qualquer ordem. ⚠️ Sem cabeçalho reconhecido, as colunas são lidas **pela ordem** e o ecrã avisa — verifique a tabela.
- **A importação acrescenta**, não substitui: pode importar dois ficheiros ou completar à mão.
- **Uma linha sem preço não trava a série**: é realçada, nomeada no aviso e ignorada. O botão indica quantos visuais vão realmente ser produzidos.
- Cada visual é **nomeado a partir do seu produto**, caso contrário chegariam todos com o mesmo nome à mediateca.

![Modo série: uma linha por visual, a linha sem preço é nomeada e ignorada](/help/img/promo-serie.webp)

## Manuais de marca

Um **manual de marca** declara de uma vez as cores, o tipo de letra, o logótipo, as menções legais e o tom de uma marca. O **Gerador promo** usa-o depois para preencher cada visual.

- **Dois âmbitos**: um manual para a sua **organização** e um por **anunciante**. Quando um visual é feito para um anunciante, aplica-se o dele; caso contrário, o da organização.
- **Onde**: Gerador promo → botão **Manuais de marca e fontes** na barra superior. Reservado ao administrador da organização.
- **Um manual só substitui o que declara**: uma cor não assinalada significa «o manual não diz nada», e o modelo mantém a sua. É isso que permite impor uma única cor de destaque sem apagar as outras.
- **Preenche, não bloqueia**: num visual concreto, o que escrever prevalece sobre o manual. As menções legais são copiadas uma única vez — se as apagar de propósito, não voltam.
- **O logótipo e o nome nunca são desenhados pela IA**: um fundo gerado recebe apenas a paleta e o tom, como atmosfera a atingir. Logótipo, nome e menções são colocados depois pelo compositing, logo são exactos. O botão «Colocar o logótipo da marca» adiciona-o como camada móvel.
- Enquanto não existir nenhum manual, nada muda: os visuais mantêm as cores do seu modelo.

## Campanhas (retail media)

A página **Campanhas** vende os seus ecrãs como inventário publicitário: um anunciante compra uma **quota de voz (SOV)** — uma percentagem do tempo de antena — num período e num conjunto de ecrãs.

### Anunciantes e exclusão concorrencial

Crie os seus **anunciantes** (página Anunciantes): cada um recebe uma pasta «Anunciantes/<nome>» e uma ou várias **categorias de indústria**. Em cada **site**, liste as categorias **excluídas**: os anunciantes em causa não podem segmentar nem difundir nesse site (aplicado na segmentação, ocupação, orçamento, relatório, portal e difusão).

![Os anunciantes e as suas categorias de indústria](/help/img/advertisers.webp)

![Um anunciante: categorias, acesso ao portal, tipos de campanha permitidos](/help/img/advertiser-edit.webp)

### Criar e publicar uma campanha

Uma campanha = período (+ janela horária diária opcional), **SOV vendida em %**, preço (por SOV ou fixo, introduzido manualmente — um **orçamento indicativo** é calculado a partir das tarifas por ecrã), alvos (cumuláveis: org, sites, grupos de sites, grupos, players) e criativos (vídeos/imagens, rotação ponderada). Estados: rascunho → publicada (agendada / ao vivo / terminada), pausa (remoção imediata dos ecrãs), retoma, anulação.

- **Inventário**: a projeção de ocupação avisa aos 80 % e bloqueia aos 100 % do **teto** de cada ecrã (teto ajustável por player ou site — ex.: ecrã de caixa limitado a 20 %); um org-admin pode forçar (sobrevenda assumida).
- **Tarifas**: € por 1 % de SOV por dia, herdadas org → site → player.
- **SOV alcançável**: um aviso âmbar assinala quando a SOV pedida excede o que o ciclo realmente agendado permite, com um botão «Usar X %».
- **Duração máxima dos criativos**: ajustável por org (padrão 30 s) — recusa ao adicionar e nova verificação ao publicar.
- **Aprovação de criativos** (opcional, por org): todo o criativo novo nasce «Pendente» e deve ser aprovado antes de ser difundido.
- **Calendário**: Gantt mensal das campanhas com carga por dia (âmbar/vermelho).
- **Importação**: campanha completa a partir de um JSON (pré-visualização dry-run, criada como rascunho, publicação manual), também **por API** com uma chave `sfi_`.

![As campanhas: anunciante, período, SOV, estado e calendário de carga](/help/img/campaigns.webp)

![Uma campanha: alvos, criativos, SOV alcançável e orçamento](/help/img/campaign-edit.webp)

### Difusão, prova e relatório

Os criativos são **intercalados no ciclo existente** à frequência da SOV vendida — nunca dois spots seguidos (no máximo um anúncio por volta de ciclo; o excedente torna-se subserviço medido e alertado). Cada passagem emite uma **prova de reprodução assinada** pelo ecrã. O **relatório do anunciante** dá passagens, tempo de antena, SOV servida vs vendida, detalhe hierárquico grupos → sites → ecrãs, montante — exportação **PDF white-label** e **ligação pública protegida** (palavra-passe, allowlist de IP). Notificações: campanha iniciada / terminada / **subservida**.

## Portal do anunciante

O **portal** (`/portal`) é o espaço white-label dos seus anunciantes: cada um só vê **as suas** campanhas.

- **Abrir um acesso**: painel do anunciante → secção Acesso ao portal → convidar por email (palavra-passe inicial mostrada uma única vez). Uma conta de anunciante aterra sempre no portal, nunca no CMS.
- **O anunciante pode**: acompanhar as suas campanhas e relatórios (PDF), **criar uma campanha** (sites no mapa — os incompatíveis com a sua categoria ficam a cinzento —, período, SOV ou **Exclusivo** = 100 %, disponibilidade agregada ok/apertado/cheio e **orçamento em direto**), carregar os seus criativos (quotas ajustáveis, padrão 20 ficheiros / 1024 MB — sempre revistos antes da difusão), **submeter para validação**, corrigir e resubmeter se forem pedidas alterações, guardar **listas de sites**, escolher o **idioma** (5 disponíveis).
- Se a organização ativar a **«Seleção por ecrã (portal)»**, o anunciante pode marcar ecrãs específicos em cada site.
- Um **sino** informa-o das decisões (mais um email se o assinalar na decisão).

## Aprovações (validações)

A página **Aprovações** centraliza os pedidos de aprovação — atualmente as campanhas (submetidas do CMS ou do portal).

1. **Submeter**: «Submeter para aprovação» (um único pedido ativo por recurso). Uma campanha em revisão não pode ser publicada.
2. **Revisão**: o validador vê tudo — criativos reproduzíveis, anunciante, período, SOV pedida e alcançável, orçamento, alvos nomeados, ocupação projetada com o detalhe das campanhas já em curso.
3. **Decisão**: aprovar / rejeitar / pedir alterações (motivo obrigatório), com opção de **email ao anunciante** (assinalada por defeito). A aprovação aprova também os criativos pendentes do pedido.
4. **Resubmissão** após correções; histórico conservado.

Os validadores (permissões `approvals`) veem a fila de toda a organização e um **sino** na barra superior; exportações **CSV/PDF** da fila; os pedidos em estado terminal podem ser retirados da lista (rasto conservado na auditoria).

![A fila de validações, com pesquisa e exportações](/help/img/approvals.webp)

![A revisão de um pedido: criativos, ocupação prevista, decisão](/help/img/approval-review.webp)

## Relatórios e análises

- **Executive Dashboard**: KPI da rede, **Network Health Score**, tendências — filtros por site/grupo, exportação **PDF white-label** (o seu logótipo), envio **agendado por email**.
- Painéis especializados: NOC (saúde do parque), conteúdo, geo (mapa dos sites), audiência.
- **Proof of Play**: cada reprodução é registada, encadeada (Merkle) e **assinada pelo player** — verificação de integridade e **certificado** exportável. Os relatórios de direitos musicais apoiam-se nisso.
- **Ligações de partilha**: publique um relatório só de leitura protegido (palavra-passe, allowlist de IP) para um cliente ou a direção.
- **Conectores BI**: três fluxos CSV (chave API `sfr_`) para Power BI, Tableau, Excel, Metabase.

## Notificações

**Configurações → Notificações**: **canais** (webhook JSON ou **email**, até 20 destinatários) e **regras** que lhes associam eventos: player offline (a suspensão programada não toca; um parque não acordado após a abertura, sim), feed em erro, implementação OTA falhada, campanhas (iniciada/terminada/subservida), validações (submetida/aprovada/rejeitada/alterações). Botão de envio de teste em cada canal.

## Assistente IA e Jeanine

O **assistente** (botão em baixo à direita ou **Ctrl+Shift+A**) conhece a sua conta e esta documentação, e responde no seu idioma.

- **Leitura**: players (estado, porque está um ecrã desligado), playlists («quem a reproduz»), sites e **horários de funcionamento**, agendamentos, médias (tempo de antena comprovado, nunca reproduzidos), campanhas (estado, relatório), sessões HDMI, alertas.
- **Ações**: **prepara** (nunca executa sozinho) — adicionar/retirar médias de uma playlist, criar playlist/feed/evento/agendamento, reiniciar players, captura, ecrã on/off, comutação HDMI, VOD, fuso horário, arrumar médias em pastas, **atualização OTA dos players** (última versão estável). Confirma com um botão; as ações sensíveis são só para org-admin.
- **Jeanine (Telegram)**: o mesmo assistente por mensagens. Ligue a sua conta em **Perfil → cartão Mensagens** (`/link CÓDIGO` para o bot); o org-admin gere as contas ligadas em Configurações → Mensagens. As ações sensíveis (reinício, desligar ecrã, apagar agendamento, OTA…) exigem o seu **código PIN de 6 dígitos** (definido no perfil; uma ação, 2 minutos, bloqueio após 3 erros, mensagem apagada da conversa — nunca por voz).
- **Voz**: envie uma mensagem de voz (≤ 2 min) — transcrição no idioma do seu perfil, resposta em texto + nota de voz (chaves fal.ai e ElevenLabs necessárias).
- Custos: o assistente usa **as chaves IA da sua organização** e respeita a sua quota.

## Atualizações dos players (OTA)

**Configurações → Atualizações** dirige as atualizações à distância de todos os tipos de players. **Nenhuma atualização automática sem a sua aprovação.**

- **Inventário**: versão atual vs última disponível **por plataforma**, filtros combinados (SO, versão, estado, site, grupo).
- **Catálogo**: as suas versões publicadas (SemVer, canal, plataforma).
- **Importar uma versão** (Linux/RPi/Windows/Android): por **URL** ou por **ficheiro** (.tar.gz/.apk) — plataforma e versão **detetadas automaticamente**, com pré-visualização antes de confirmar; o arquivo é armazenado no seu servidor, os players descarregam-no de lá.
- **Versões servidas** (BrightSign/ChromeOS): estes players obtêm o seu código **com a atualização do servidor**; **declare** a versão servida para a tornar implantável. **Fixação**: atualizar o servidor **não** avança um player até implantar a versão — ideal para testar num ambiente de testes antes do parque.
- **Fluxo recomendado**: publicar em **Beta** (invisível para o parque) → implementar num grupo de teste → **Promover a estável** → implementar em larga escala.
- **Implementação**: versão + alvos (player, grupo, site, etiquetas, org) + estratégia (imediata, gradual, agendada) + **janelas horárias** (transferência / instalação em hora local — sem reinícios a meio do dia). Seguimento por player (transferência → pronto → instalação → sucesso/falha), anel de progresso, pausa/retoma/anulação. Um player offline aplica no regresso.
- **Pelo assistente**: «atualiza os players» propõe a última estável de cada plataforma aos players em atraso (org-admin; PIN por Telegram).

## Ecrãs e alimentação

O Vitrail liga e desliga os seus ecrãs segundo o **horário de funcionamento do site** — o player fica ligado, só o ecrã é comandado.

1. Preencha os horários do site (com exceções e feriados) e ative o **auto-power** (margens opcionais antes/depois).
2. Em cada player: **Seguir os horários do site** (recomendado), janela personalizada, sempre ligado, ou manual.
3. Método conforme o equipamento: controlador **RS232/IP** (ecrãs profissionais), **HDMI-CEC**, ou o recurso **corte da saída de vídeo** (o ecrã entra em suspensão).

Cada player conhece as suas janelas de alimentação **com 14 dias de antecedência**: se o servidor estiver inacessível, comanda o seu ecrã sozinho. Um player desligado pelo programa é marcado **«Suspensão programada»** — sem alerta; se não voltar após a abertura, dispara um alerta. Os botões Ligar/Desligar do painel são pontuais; um evento pode «manter os ecrãs ligados».

## Servidor e duração das codificações

Cada vídeo importado é **recodificado** para que todos os ecrãs o consigam ler — é a tarefa mais pesada do servidor. A página **Configurações → Servidor** explica porque demora o que demora.

![A página Servidor: capacidade de codificação, débitos medidos, fila](/help/img/server.webp)

**Capacidade de codificação** — a linha que explica quase tudo: **aceleração por hardware ativa** ou não. Sem placa gráfica utilizável, a codificação corre no processador e é bem mais lenta. **Débitos medidos** = as velocidades realmente observadas nos seus próprios ficheiros. **Disco de trabalho** = espaço livre onde o worker escreve os ficheiros temporários.

> **«Nenhum worker de média responde»** não é um detalhe visual: nenhuma codificação pode terminar. Esta informação vem do **worker**, não do servidor web — quando ele se cala, a página di-lo em vez de mostrar valores desatualizados.

**Antes de lançar uma codificação, o servidor mede**: codifica cerca de dez segundos do **seu** ficheiro com o comando exato que será usado e extrapola. Três casos: **menos de 20 min**, arranca sozinho · **de 20 min a 4 h**, decide você e a média fica em **Decisão necessária** · **mais de 4 h**, é recusado por omissão, podendo um administrador forçar. Uma recusa não é um beco sem saída: o ecrã propõe codificar em **definição inferior**, cada uma com a sua própria estimativa.

Esta página é reservada ao **titular da licença**. Se o seu servidor for administrado por um prestador, o ecrã indica-o: a capacidade e a fila dependem da exploração dele.

## Utilizadores, perfis e segurança

**Perfis fornecidos** — esta lista contém apenas os direitos que o servidor aplica realmente:

- **Administrador de organização**: tudo, dentro da sua organização.
- **Designer**: media e templates (criar/editar/eliminar), playlists (criar/editar).
- **Programador**: programação, eventos e VOD (criar/editar/acionar); leitura de players, playlists, media.
- **Responsável de campanhas**: campanhas de ponta a ponta (criar, publicar, relatórios); leitura de media, templates, relatórios.
- **Aprovador**: analisar, aprovar ou rejeitar pedidos; leitura de media, playlists, templates.
- **Leitor de relatórios**: apenas consulta de relatórios.
- **Operador de loja**: controlar os cabazes áudio da sua loja.
- **Gestor de governança**: configurar a hierarquia de governança (nós, delegações); leitura de conteúdos.
- **Editor de governança**: compor o conteúdo do seu nó (listas, mídias, feeds) e submetê-lo a aprovação; **não elimina mídias**.
- **Validador de governança**: decidir sobre os pedidos de aprovação do seu âmbito; **nunca a sua própria submissão**, e apenas a partir de um nó superior.
- **Programador de site**: programar a difusão dos **nós que administra** (o seu alcance vem da sua atribuição de nó, não da permissão sozinha).
- **Observador**: apenas leitura em tudo.
- **Anunciante (portal)**: as suas campanhas e relatórios, a partir do portal.

> **Os menus adaptam-se ao perfil**: o que um utilizador não pode usar fica oculto. Um menu desaparecido significa uma permissão de leitura em falta, não uma avaria.

> Os perfis **Utilizador API** e **Player** não concedem nada e já não são propostos: as integrações usam **chaves API** e os players um **token de máquina**.

> **Perfil personalizado**: crie-o e depois **clique na sua linha** para marcar as permissões. Os perfis de sistema são só de leitura; as permissões a cinzento (em breve) correspondem a funcionalidades ainda não desenvolvidas.

- **Configurações → Usuários e Papéis**: utilizadores, **grupos** (os perfis do grupo somam-se aos da conta; âmbito org/site/grupo de players) e **perfis personalizados** compostos por permissões atómicas `módulo : operação` (ver a lista acima).
- A eliminação de um utilizador é uma **desativação** (o email fica reservado); eliminar uma conta de anunciante desliga-a do portal.
- **2FA (TOTP)**: ativável por utilizador, obrigatória para os administradores.
- **Chaves API**: exportações BI (`sfr_`), importação de campanhas (`sfi_`) — valor mostrado uma única vez, revogáveis.
- **Configurações → Segurança**: política de sessão, tentativas de ligação.
- Toda a ação sensível fica registada no **registo de auditoria**.

## Perfil e preferências

**Configurações → Perfil**: nome, email, palavra-passe, **idioma da interface** (francês, inglês, espanhol, português, alemão — o assistente e os emails seguem-no), tema claro/escuro (botão na barra superior), 2FA, **cartão Mensagens — Telegram** (ligação Jeanine + **código PIN** das ações sensíveis), reativação das bolhas de ajuda.

## Resolução rápida de problemas

- **Player offline**: verifique alimentação, rede, URL do servidor. Fora do horário de funcionamento, «Suspensão programada» é normal (o auto-power desligou o ecrã; algumas boxes cortam também a rede).
- **«No Signal Detected»**: a fonte HDMI ligada não emite (desligada, desconectada) — a imagem volta sozinha quando o sinal regressa.
- **«Média indisponível»**: player desatualizado para esse tipo de conteúdo, ou transcodificação do servidor por terminar.
- **Ecrã preto/congelado**: verifique a transcodificação; num mural sincronizado, mantenha o grupo homogéneo; «Info no ecrã» mostra o diagnóstico no local.
- **Sem som**: verifique o papel de áudio do player (padrão / só áudio / misto), o volume enviado e o silêncio.
- **O conteúdo não muda**: player online? O agendamento aponta mesmo para esse player/grupo? Qualquer alteração envia normalmente uma sincronização imediata.
- **Offline**: os players nativos reproduzem o conteúdo localmente (playlists, vídeos, feeds em cache) mesmo com o servidor em baixo; a extensão Chrome depende mais da rede.

> Precisa de mais? Pergunte ao assistente (Ctrl+Shift+A) — ele conhece este manual e o estado da sua conta.
