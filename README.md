<img src="docs/img/logo.png" width="64" align="right" alt="League of Wildcards">

# League of Wildcards Draftboard

Publieke draftboard-app voor de offline auction van de league: 12 teams, H2H
8-cat (PTS, 3PM, REB, AST, STL, BLK, FG%, FT%), $200 per team, 13 plekken.

De volledige requirements staan in **[docs/FRD.md](docs/FRD.md)**. Dit bestand
beschrijft alleen hoe je het draait.

## Starten

```
py -m pip install -r requirements.txt

py tool\fetch_espn.py        projecties ophalen        -> data\espn.csv
py tool\build_values.py      waardes berekenen         -> output\values.json
py tool\fetch_headshots.py   ESPN-foto's cachen        -> data\headshots\
run.bat                      app starten               -> http://localhost:8000
```

Draaien op je eigen machine, niet in de Cowork-omgeving: die zit achter een
bedrijfsproxy die ESPN, FantasyPros, Yahoo en a.espncdn.com blokkeert met een
403 op CONNECT. Je gewone netwerk komt er wel bij.

De ophaalscripts gebruiken alleen de standard library. Alleen de app zelf heeft
dependencies.

## Twee views

| URL | Inhoud |
|---|---|
| `/board` | pickhistorie links, beurtbalk, budgetten van alle teams, bord met beschikbare spelers |
| `/teams` | twaalf kolommen van dertien plekken, in de vorm van de oude draftsheets |

Beide kunnen tegelijk open staan in twee vensters op twee schermen. Ze pollen
elke drie seconden dezelfde server en lopen dus vanzelf gelijk.

## Commando's

Eén grammatica, Engelstalig, want een enkel taalmodel herkent Engelse
eigennamen beter dan een mengeling met Nederlandse structuurwoorden. Dat telt
zodra de spraaklaag erbij komt.

```
derozan to emiel for 13        pick toewijzen
wembanyama to roro for eighty five
turn roro                      beurt handmatig zetten
skip                           beurt doorschuiven
sengun mine 12                 pick voor jezelf ("me" in de instellingen)
undo                           laatste pick terug
undo 3                         laatste drie picks terug, na bevestiging
```

Bedragen mogen cijfers of Engelse getalwoorden zijn. Een voorafgaand `draftbot`
wordt genegeerd, net als het wake word `low-db` (ook `low db`, `lowdb`,
`low dee bee`) voor de spraaklaag. `$`, `dollars` en `bucks` mogen voor of na
het bedrag. Een bedrag boven de max bid wordt geweigerd. Typen filtert het bord
live mee.

Bij twijfel over de naam gokt de app niet, maar toont ze kandidaten met hun
score. Er is geen aliastabel: matching gebeurt op bigram-overlap, een prefixbonus,
een fonetische sleutel en soundex,
en uitsluitend tegen de nog beschikbare spelers. Zie F-32 tot F-36 in de FRD.

## Structuur

```
app/
  main.py        API, headshot-route en statische frontend (FastAPI)
  store.py       SQLite-stand (picks, instellingen, beurt) en inladen van values.json
  draft.py       pure regels: budgetten, max bid, validatie, beurtvolgorde
  parser.py      commandoparser, getalwoorden, naam- en teammatching
  static/        index.html, app.css, app.js, logo.png (vanilla JS, geen build)
tool/
  fetch_espn.py       projecties ophalen
  build_values.py     Z-scores en auction-waardes
  names.py            naamnormalisatie voor build_values.py
  fetch_headshots.py  ESPN-foto's lokaal cachen
  parse_history.py    negen jaar draftgeschiedenis uitlezen
  config.json         league-parameters en categorie-toggles
tests/
  fixtures/      make_values.py en values.json: 200 echte namen, gegenereerde stats
  test_*.py      parser, draftregels en API
_legacy/app/     de vorige versie van de app, enkel ter referentie
docs/            FRD.md en de designs
data/            bronbestanden, draft.db, backups/, headshots
output/          values.json, paste_block.csv, top.txt
```

## Draaien zonder pipeline (fixture)

Zolang er geen echte ESPN-data is, draait de app op de testfixture. `LOW_VALUES`
kiest het values.json-bestand, `LOW_DB` de database (standaard `data\draft.db`).

```
py -m pip install -r requirements.txt
py -m pytest tests -q
$env:LOW_VALUES='tests/fixtures/values.json'; $env:LOW_DB='data/demo.db'
py -m uvicorn main:app --app-dir app --port 8000
```

Ontbreekt values.json, dan start de app toch en toont ze een melding om de
pipeline te draaien. Zodra het bestand er is, laadt ze het zonder herstart.

## Meer dan één pick terug, en een nieuwe draft

`undo 3` (of `undo three`) haalt de laatste drie picks weg, en elke pick in de
linkerkolom heeft een knop "back to here". Beide vragen één bevestiging met de
lijst van picks die verdwijnen; beurt en budgetten gaan exact terug naar de stand
voor de oudste. "New draft" staat in het instellingenpaneel (tandwiel) en vraagt
twee bevestigingen, de tweede door `NEW DRAFT` te typen. Eerst schrijft de server
de volledige stand naar `data/backups/draft-<tijdstip>.json`. Teams, volgorde en
"me" blijven staan.

De commandoparser staat op de server, niet in de browser. Daardoor komen straks
het toetsenbord en de Whisper-transcriptie op hetzelfde endpoint binnen
(`POST /api/command` met een `source`-veld).

De draftstand staat in SQLite (`data/draft.db`), niet in browseropslag, zodat
ze een herstart midden in de draft overleeft en alle schermen dezelfde waarheid
zien.

## Categorieën aanpassen

In `tool/config.json` staat elke categorie op 1. Zet er een op 0 om een
punt-build door te rekenen, of hoger dan 1 om zwaarder te wegen. Draai daarna
`build_values.py` opnieuw en vergelijk `output/top.txt`. Turnovers staan op 0,
want de league speelt 8-cat.

## Nog te bouwen

Spraaklaag, marktprijsmodule, tweede projectiebron, prijsmodel op de eigen
draftgeschiedenis, en fase 2 met logins en teampagina's. Zie de tabel met
openstaande punten onderaan de FRD.
