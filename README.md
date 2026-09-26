# tips-xgs

Todos os dias: vai ao [xGScore](https://xgscore.io/) buscar os jogos do
dia e as probabilidades de cada mercado na página de preview de cada
jogo (resultado final, ambas marcam, over/under de golos, resultado
exato, etc.), vai à **Betclic** buscar as odds desses mesmos jogos, e
gera um painel HTML por jogo que:

1. Ordena os acontecimentos do jogo por probabilidade (maior → menor).
2. Cruza cada acontecimento com a odd da Betclic e calcula o **valor**
   da aposta: `valor = probabilidade × odd`. Um valor de **1.00×** é o
   ponto de equilíbrio; acima disso a aposta tem valor esperado
   positivo segundo o modelo do xGScore (ex.: probabilidade 70% e odd
   2.00 → **1.40×**, exatamente o exemplo dado).
3. No topo do painel, lista as melhores apostas de valor do dia,
   juntando todos os jogos.

Vê uma demo (dados inventados, só para mostrar o layout) em
[`examples/demo/`](examples/demo/).

## ⚠️ Antes de correr: falta calibrar

Este projeto foi construído sem acesso de rede a `xgscore.io` /
`betclic.pt` (o ambiente onde foi desenvolvido bloqueia esses domínios
por política da organização), por isso **nenhum seletor CSS ou caminho
de API foi verificado contra as páginas reais**. Toda a extração de
dados vive em [`config.yaml`](config.yaml) — nada disso está
"hardcoded" no código — e vem com placeholders (`selector: null`) que
precisas de preencher depois de inspecionar as páginas reais, uma
única vez. Ver [`docs/CALIBRATION.md`](docs/CALIBRATION.md) para o
passo a passo (10-20 minutos com o dev tools do browser).

Sem essa calibração, `python -m tipsxgs run` corre sem erros mas produz
um painel vazio (com avisos no log a dizer exatamente o que falta).

## Instalação

macOS/Linux (bash/zsh):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
playwright install chromium
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
playwright install chromium
```

Se o PowerShell bloquear o `Activate.ps1` por política de execução, corre
antes (uma vez por sessão): `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.
Todos os outros comandos deste README (`python -m tipsxgs run`, `pytest`,
etc.) funcionam da mesma forma em qualquer terminal, uma vez o venv
ativado.

## Uso

```bash
# corre a pipeline completa para hoje: xGScore -> Betclic -> painel HTML
python -m tipsxgs run -v

# para um dia específico
python -m tipsxgs run --date 2026-09-12

# volta a gerar o HTML a partir dos dados já guardados (sem voltar a fazer scraping)
python -m tipsxgs report --date 2026-09-12
```

O painel fica em `data/<AAAA-MM-DD>/index.html` — abre diretamente no
browser. Os dados brutos ficam em `data/<AAAA-MM-DD>/games.json`.

## Correr todos os dias

### Opção A — GitHub Actions (recomendada, não precisa do teu computador ligado)

[`.github/workflows/daily.yml`](.github/workflows/daily.yml) já está
pronto: corre todos os dias às 08:00 UTC, guarda o resultado em `data/`
(commit automático) e publica o painel no GitHub Pages. Só precisas de:

1. Calibrar o `config.yaml` (ver acima).
2. Ativar o GitHub Pages no repositório: Settings → Pages → Source →
   "GitHub Actions".
3. `git push` — a partir daí corre sozinho. Também podes disparar
   manualmente em Actions → "Daily xGScore + Betclic run" → Run workflow.

### Opção B — cron na tua máquina/servidor

```cron
# todos os dias às 9h
0 9 * * * cd /caminho/para/tips-xgs && .venv/bin/python scripts/run_daily.py >> logs/tipsxgs.log 2>&1
```

### Opção C — systemd timer

```ini
# /etc/systemd/system/tipsxgs.service
[Service]
Type=oneshot
WorkingDirectory=/caminho/para/tips-xgs
ExecStart=/caminho/para/tips-xgs/.venv/bin/python scripts/run_daily.py

# /etc/systemd/system/tipsxgs.timer
[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true
[Install]
WantedBy=timers.target
```

## Arquitetura

```
config.yaml                    <- ÚNICO sítio a editar para calibrar a extração
src/tipsxgs/
  config.py                    carrega/valida config.yaml
  browser.py                   sessão Playwright (ambos os sites são SPA -> precisam de JS)
  extract.py                   extração genérica: JSON embutido, seletores CSS, parsing de números
  markets.py                   vocabulário canónico de mercados/resultados + labels PT
  models.py                    Fixture, Prediction, OddsOffer, ValueBetEntry, MatchedGame
  xgscore/fixtures.py           jogos do dia
  xgscore/preview.py            probabilidades de um jogo (a página de preview)
  betclic/odds.py               lista de jogos + odds da Betclic
  matching.py                   emparelha fixture <-> odds por nomes das equipas (fuzzy) + data
  valuebets.py                   probabilidade implícita, overround, edge, valor, ranking
  storage.py                     grava/lê data/<data>/games.json
  report.py                      gera data/<data>/index.html (Jinja2)
  pipeline.py                    liga tudo: scrape -> match -> compute -> store -> report
  cli.py                          `python -m tipsxgs run|report`
scripts/
  inspect_site.py                ajuda a calibrar: guarda HTML/JSON reais de uma URL
  demo_data.py                    gera o painel com dados inventados (ver examples/demo)
  run_daily.py                    wrapper para cron/systemd
docs/CALIBRATION.md               como preencher o config.yaml
tests/                             testes unitários (matching, cálculo de valor, mercados, storage)
```

### Porque é que a extração é toda por configuração?

xGScore e Betclic são ambos SPAs (dados carregados via JavaScript) — o
`config.yaml` suporta duas estratégias para cada página, sem precisar
tocar em código:

- **JSON embutido/capturado**: muitos destes sites carregam os dados via
  chamadas fetch/XHR a uma API, ou embutem o estado inicial num
  `<script>` (`__NEXT_DATA__`, `__NUXT__`, etc.). `json_path` usa
  [JMESPath](https://jmespath.org) para apontar para o valor certo.
- **Seletores CSS**: `selector` (+ `attr` para atributos como `href`).

`scripts/inspect_site.py` (ver `docs/CALIBRATION.md`) diz-te qual das
duas se aplica a cada página.

### Cálculo de valor

Para cada resultado com probabilidade do modelo e odd da Betclic:

- `probabilidade_implícita = 1 / odd`
- `probabilidade_justa` = `probabilidade_implícita` normalizada para
  remover a margem da casa de apostas (o *overround*) — só quando
  todos os resultados desse mercado têm odd conhecida.
- `edge = probabilidade_modelo - probabilidade_justa`
- `valor = probabilidade_modelo × odd` — **1.00× é o ponto de
  equilíbrio**; o exemplo dado (70% e odd 2.00 → 1.40×) é exatamente
  este cálculo.

Todos os resultados de um jogo (de todos os mercados extraídos) são
também ordenados por probabilidade, do mais para o menos provável —
essa é a vista "ordem de acontecimentos" pedida.

## Testes

```bash
pytest
```

Os testes cobrem o emparelhamento (matching), o cálculo de valor e a
normalização de mercados com dados inventados — não dependem de
acesso à rede (ao contrário dos scrapers, que só podem ser validados a
sério depois de calibrados contra as páginas reais).

## Limitações conhecidas

- Como não foi possível validar contra as páginas reais durante o
  desenvolvimento, é preciso o passo de calibração acima antes de
  confiar em qualquer resultado.
- O emparelhamento entre xGScore e Betclic é por semelhança de nomes
  das equipas + data — se os nomes forem muito diferentes entre sites,
  pode ser preciso ajustar `min_match_confidence` no `config.yaml`.
- Scraping de sites de terceiros pode quebrar quando eles mudam de
  layout; `docs/CALIBRATION.md` explica como voltar a calibrar sem
  tocar em código.
