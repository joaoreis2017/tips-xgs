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

- `xgscore.fixtures` — lista de jogos do dia (equipa casa/fora, liga,
  hora, e o link para a página de preview de cada jogo).
- `xgscore.preview` — os mercados/probabilidades dentro da página de um
  jogo (a mesma configuração serve para todos os jogos, já que a
  estrutura da página deve ser igual).
- `betclic.fixtures` — lista de jogos de futebol na Betclic para hoje,
  incluindo o link para a página de odds completas de cada jogo.
- `betclic.odds` — mercados/odds dentro da página de um jogo específico.

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
