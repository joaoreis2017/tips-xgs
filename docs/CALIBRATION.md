# Calibrar o `config.yaml`

Este projeto não foi testado contra as páginas reais do xGScore/Betclic:
o ambiente onde foi construído tem o acesso de rede a esses domínios
bloqueado por política da organização. Toda a extração de dados é por
isso feita através de `config.yaml` (seletores CSS / caminhos JSON), sem
nada disso "hardcoded" no código — só precisas de preencher esse ficheiro
depois de veres as páginas reais. Uma vez calibrado, não voltas a tocar
no código.

## Passo 1 — instalar localmente

Ver instruções de instalação (macOS/Linux e Windows/PowerShell) no
[`README.md`](../README.md#instalação).

## Passo 2 — inspecionar cada página

```bash
# página inicial / lista de jogos do dia
python scripts/inspect_site.py https://xgscore.io/

# uma página de preview de um jogo concreto
python scripts/inspect_site.py https://xgscore.io/bundesliga/union-berlin-schalke/preview

# lista de jogos de futebol na Betclic
python scripts/inspect_site.py https://www.betclic.pt/futebol-s1

# página de um jogo específico na Betclic (odds completas)
python scripts/inspect_site.py "<url do jogo na betclic>"
```

Isto guarda em `inspect_out/<slug>/`:
- `page.html` — o HTML já renderizado (depois do JavaScript correr).
- `captured_json/*.json` — todas as respostas JSON que a página pediu
  (muito provavelmente é aqui que estão as probabilidades/odds reais,
  já que ambos os sites parecem ser SPAs).
- `embedded_json/*.json` — blobs JSON encontrados dentro de `<script>`
  (padrão comum em sites Next.js/Nuxt).

Abre esses ficheiros. Se encontrares os números que queres num JSON,
usas `json_path` (uma expressão [JMESPath](https://jmespath.org), testa
em jmespath.org antes de colar no config). Se só aparecem no HTML
renderizado, abre `page.html` num browser, `Inspecionar elemento` no
número que queres, e copia um seletor CSS estável — usa `selector`
(e `attr` para atributos como `href`/`datetime`).

## Passo 3 — preencher `config.yaml`

Cada mercado/resultado extraído fica como um `field` com uma chave (`key`)
arbitrária, e depois é traduzido para o vocabulário canónico do painel
(`market_aliases`, ex.: `"1x2.home"`, `"btts.yes"`,
`"over_under_2.5.over"`) — ver `src/tipsxgs/markets.py` para a lista
completa de mercados/labels já conhecidos (podes adicionar mais).

Quando um mercado vem como um **array inteiro** com uma linha por
resultado (ex.: over/under com uma linha para cada valor de golos, ou um
handicap com uma linha por valor) — em vez de escreveres um `field` por
linha, usa `array_markets` (ver `xgscore.preview.array_markets` no
`config.yaml` já calibrado como exemplo, e `markets.expand_array_market`
no código): um único `json_path` para o array todo, mais dois "moldes"
(`market_template`/`outcome_template`) que descrevem como o `label` de
cada linha se transforma no mercado/resultado canónico, ex.:
`over_under_{label}` + `over` para golos totais, ou `handicap_home` +
`{label}` quando é o próprio valor da linha (ex. "-1.5") que é o
resultado.

A Betclic tem uma variante do mesmo problema, mas com uma forma de JSON
diferente: cada linha de um mercado (`selectionMatrix`) é um objeto com
uma lista `selections`, cada uma com um `name` em português (ex. "Acima
de 2,5") em vez de um valor numérico isolado — por isso usa-se
`selection_matrix_markets` (ver `betclic.odds.selection_matrix_markets`
no `config.yaml`, já calibrado para golos totais, e
`betclic.odds._expand_selection_matrix_markets` no código) em vez de
`array_markets`: um `json_path` até ao `selectionMatrix` inteiro, um
`name_pattern` (regex com grupos nomeados `direction` e `line`) que
extrai a direção/linha de cada `name`, um `direction_map` que traduz a
palavra em português para `over`/`under` (ou outro par), e o mesmo tipo
de `market_template` de antes.

- `xgscore.fixtures` — lista de jogos do dia (equipa casa/fora, liga,
  hora, e o link para a página de preview de cada jogo).
- `xgscore.preview` — os mercados/probabilidades dentro da página de um
  jogo (a mesma configuração serve para todos os jogos, já que a
  estrutura da página deve ser igual).
- `betclic.fixtures` — lista de jogos de futebol na Betclic para hoje,
  incluindo o link para a página de odds completas de cada jogo.
- `betclic.odds` — mercados/odds dentro da página de um jogo específico.

## `xgscore.results` — calibrar a análise de acerto

CALIBRADO (2026-11-14), a partir de uma captura real da página
(`https://xgscore.io/xg-statistics`): um array JSON simples de jogos,
cada um com `played`, `datetime`, `tournament.name`, `teams.h/a.name` e
`fullTimeGoals.h/a` — ver a secção já preenchida em `config.yaml` e o
módulo `src/tipsxgs/xgscore/results.py`.

`python -m tipsxgs calibrate` usa isto para comparar as probabilidades
já guardadas em `data/<dia>/games.json` contra o que realmente
aconteceu em cada jogo, respondendo a coisas como "os meus 'over 2.5'
previstos a 70-79% acertam mesmo perto de 70-79% das vezes, ou o
modelo está demasiado confiante nesse mercado?" — ver
`src/tipsxgs/calibration.py`.

Explicitamente pedido (2026-11-14, depois levado mais longe): cada
**mercado exato + resultado específico** fica completamente separado,
nunca misturado com outro -- vitórias em casa separadas de vitórias
fora (e do empate), "over" separado de "under", "1X" separado de "X2"
na dupla hipótese (com "12" excluído por completo -- não é só tratado
à parte, nunca aparece em lado nenhum, no relatório nem no ajuste de
valor das apostas, porque nunca é apostado), e **cada linha tratada à
parte**: over/under 1.5 nunca é misturado com 2.5/3.5/4.5/5.5, e o
mesmo para o total de cada equipa (`home_total_0.5`, `home_total_1.5`,
..., `away_total_0.5`, `away_total_1.5`, ...) -- cada combinação exata
de mercado + linha + resultado tem a sua própria tabela/escalão,
porque linhas diferentes do mesmo mercado podem estar calibradas de
forma muito diferente (over 1.5 é quase certo, over 4.5 é um "longshot"
-- misturá-los esconderia isso). Linhas de número inteiro (over/under
1, 2, 3, ...) são excluídas por completo (2026-11-16) -- só as de
meio-número (0.5, 1.5, 2.5, ...) são seguidas, por serem as únicas
realmente apostadas. O handicap (`handicap_home`/`handicap_away`)
também entrou na calibração (2026-11-17) -- a linha, nestes dois
mercados, vem no `outcome` em vez de no nome do mercado (ex.
`handicap_home` com outcome `"-1.5"`), mas segue a mesma regra: uma
linha de número inteiro ("0", "1", ...) pode empatar exatamente e é
excluída, só as de meio-número ficam.

**Limitação confirmada (na própria captura):** a página tem um toggle
próprio "Week / Yesterday / Today" que por defeito mostra **Yesterday**
(ontem) — não foi encontrado nenhum parâmetro de URL que escolha outro
dia. Isto significa que só é possível obter os resultados de **ontem**,
nunca um dia arbitrário do passado. Por isso, `calibrate` só tenta
fazer scraping quando o dia em falta é mesmo "ontem" (relativo ao
momento em que corre) — qualquer outro dia sem `results.json` fica
simplesmente sem dados até esse dia ser "ontem" numa run futura. Corre
`python -m tipsxgs calibrate` todos os dias (ex. logo depois de `run`,
no mesmo cron) para ires acumulando histórico dia a dia; se quiseres
preencher dias mais antigos em falta, precisas de descobrir que pedido
os botões "Today"/"Week" disparam (inspecionar com as devtools do
browser ao clicar neles) e recalibrar esta secção.

```bash
python scripts/inspect_site.py https://xgscore.io/xg-statistics
```

Se a estrutura mudar no futuro: tal como `xgscore.fixtures`, pode vir
num JSON (`json_list_path` + `fields` com `json_path`) ou só no HTML
renderizado (`list_item_selector` + `fields` com `selector`/`attr`) —
confirma em `page.html`/`captured_json/*.json` dentro de
`inspect_out/<slug>/`. `fields` aceita `league`, `home_team`,
`away_team`, `kickoff` (mesmo significado que em `xgscore.fixtures`), e
o resultado final — ou dois campos numéricos `score_home`/`score_away`
(o caso já calibrado), ou um único campo `score` como texto (ex.
"2-1", separado automaticamente).

Testa com:

```bash
python -m tipsxgs calibrate --since 2026-10-01 -v
```

Se não encontrar nenhum par (previsão, resultado real), o aviso diz
exatamente o que falta — ou não há `data/<dia>/games.json` guardado
para nenhum dia, ou `xgscore.results` ainda não está calibrado.

## O histórico já alimenta as próprias apostas do dia

Explicitamente pedido (2026-11-14): assim que um mercado + escalão de
probabilidade acumula **pelo menos 30 jogos** com resultado real
emparelhado (ver `calibration.DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE`),
`python -m tipsxgs run` passa a usar essa taxa de acerto real — não a
probabilidade do modelo — para calcular `valor`/`edge` de cada aposta,
automaticamente, sem precisares de correr nada à parte nem mudar
`config.yaml`. Isto acontece em `pipeline.run_daily`, que chama
`calibration.load_accumulated_calibration` (lê tudo o que já está em
`data/`, sem scraping) antes de `valuebets.compute_all`.

Quando isto acontece, o painel mostra um selo "real: X% (Nj)" por
baixo da probabilidade do modelo, nas três tabelas onde isso importa
(múltipla do dia, apostas de probabilidade média, melhores apostas de
valor de cada jogo) — a probabilidade do modelo em si nunca é alterada
(continua a decidir em que "banda" uma aposta entra), só o cálculo de
valor é que passa a usar o número real uma vez que há amostra
suficiente. Enquanto não houver 30 jogos nesse escalão específico, o
comportamento é exatamente o mesmo de antes (probabilidade do modelo).

## Passo 4 — testar

```bash
python -m tipsxgs run -v
```

Corre com `-v` para ver logs detalhados de quantos jogos/mercados foram
encontrados em cada etapa. Se um passo continuar a devolver 0 resultados,
o aviso no log diz exatamente qual secção do `config.yaml` calibrar.
Repete o `inspect_site.py` + ajusta o `config.yaml` até `python -m tipsxgs
run -v` extrair tudo corretamente — não precisas voltar a tocar no
código Python.

## Sobre o emparelhamento (matching) e os nomes das equipas

Se os nomes das equipas forem muito diferentes entre os dois sites (ex.
abreviaturas, "1.FC" vs "FC", acentos), pode ser preciso baixar
`min_match_confidence` em `config.yaml`, ou (melhor) normalizar os nomes
o mais possível já na extração (ex. remover "FC"/"SAD" no seletor via
`regex`, ou tratar isso num pequeno passo extra caso o desalinhamento
seja sistemático).
