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
nominate anthony edwards       speler op het blok, genomineerd door het team aan de beurt
sold to rj for 5               de speler op het blok wordt een pick (for mag weg)
sold to rj                     idem, de app vraagt het bedrag
derozan to emiel for 13        pick in één stap, zonder blok
wembanyama to roro for eighty five
turn roro                      beurt handmatig zetten (ook: clock roro)
skip                           beurt doorschuiven
go back                        beurt terug naar het vorige team
sengun mine 12                 pick voor jezelf ("me" in de instellingen)
undo                           laatste pick terug; staat er iemand op het blok, dan enkel het blok leeg
undo 3                         laatste drie picks terug, na bevestiging (ook hier: eerst het blok)
```

**Het blok.** Op draftavond wordt een speler eerst genomineerd en pas later
verkocht. `nominate <speler>` zet hem groot bovenaan elk scherm, met wie hem
nomineerde en de max bid van elk team. `sold to <team> for <bedrag>` maakt er een
gewone pick van: dezelfde regels als een pick (max bid, volle roster) en de beurt
schuift door. Een ongeldige sold laat het blok staan. Er staat maar één speler
tegelijk op het blok; een tweede `nominate` geeft "X is on the block: say sold or
undo." `undo` haalt de speler van het blok zonder picks te raken, net als de knop
"Clear" in het blokpaneel. Een pick in één stap van dezelfde speler en een nieuwe
draft maken het blok ook leeg. Het blok staat in SQLite en overleeft een herstart.
`nominate` zet de beurt niet meer; dat doen `turn`, `clock`, `skip` en `go back`.

Bedragen mogen cijfers of Engelse getalwoorden zijn. Een voorafgaand `draftbot`
wordt genegeerd, net als het wake word `ok banana` (ook `okay banana`, een los
`banana`, `bananas`) voor de spraaklaag. `$`, `dollars` en `bucks` mogen voor of na
het bedrag. Een bedrag boven de max bid wordt geweigerd. Typen filtert het bord
live mee.

Bij twijfel over de naam gokt de app niet, maar toont ze kandidaten met hun
score. Er is geen aliastabel: matching gebeurt op bigram-overlap, een prefixbonus,
een fonetische sleutel en soundex,
en uitsluitend tegen de nog beschikbare spelers. Zie F-32 tot F-36 in de FRD.
Voor Whisper-spellingen en bijnamen zijn er drie extra regels: een los lidwoord
wordt aan het volgende woord geplakt (`the rosen` is DeRozan), woorden worden één
op één naast de naam gelegd met een sleutel die klinkers gelijkstelt (`alparan
senghan` is Sengun, `ant edwards` is Edwards), en een bijnaam op -y/-ie/-ee telt
als begin van een achternaam (`wemby` is Wembanyama). Een kale `ant` of `steph`
blijft een vraag met kandidaten.

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
voice/
  listen.py      spraaklistener: micro, VAD, Whisper, wake word, naar /api/command
  calibrate.py   teamnamen inspreken en Whisper-spellingen als bijnaam bewaren
  wake.py        wake-word-detectie en hotwords (pure functies)
  requirements.txt  eigen dependencies (faster-whisper, sounddevice, numpy)
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

De commandoparser staat op de server, niet in de browser. Daardoor komen het
toetsenbord en de Whisper-transcriptie op hetzelfde endpoint binnen
(`POST /api/command` met een `source`-veld).

De draftstand staat in SQLite (`data/draft.db`), niet in browseropslag, zodat
ze een herstart midden in de draft overleeft en alle schermen dezelfde waarheid
zien.

## Spraak

Een aparte listener (`voice/`) luistert op de micro van de app-laptop, transcribeert
lokaal met Whisper (faster-whisper, CPU, int8) en stuurt enkel zinnen die beginnen
met het wake word **ok banana** naar `POST /api/command` met `source: "voice"`. Het is
dezelfde parser als de commandobalk. Een duidelijke pick gaat meteen in. Elk
scherm toont dan een spraakbanner met wat er gehoord is en wat er gebeurde.

```
ok banana steph curry to miele for 55 dollars    pick, meteen opgeslagen
ok banana bridges to rj for 5                    kandidaten in de banner, één klik op eender welk scherm
ok banana sengun to lode                         knop in de banner opent de bedragprompt
ok banana nominate anthony edwards               speler op het blok, op elk scherm
ok banana sold to rj for five                    de speler op het blok wordt een pick
ok banana turn dave  /  ok banana skip  /  ok banana go back
```

Undo van picks gaat **nooit** met spraak: "ok banana undo" haalt geen pick weg en de
banner zegt "Undo picks by typing." Typ `undo` of klik. Staat er een speler op het
blok, dan haalt "ok banana undo" enkel die van het blok; picks blijven altijd staan. Een reset kan ook niet met
spraak. Zinnen zonder wake word worden niet verstuurd. Zeg het commando in
dezelfde adem als "ok banana": na een pauze komt de rest binnen als een aparte zin
zonder wake word, en die wordt genegeerd.

**Installeren** (los van de app, eigen dependencies):

```
py -m pip install -r voice\requirements.txt
```

**Eerste run.** De eerste keer downloadt de listener het model van Hugging Face
(base.en is 145 MB, small.en 484 MB). Daarna laadt hij het uit de lokale cache
(`local_files_only`) en werkt hij zonder internet. Doe de eerste run dus thuis.

**Kalibreren.** Met de app aan zeg je per team twee keer "ok banana curry to <team>
for ten". Het script toont per model wat Whisper hoorde, hoe lang dat duurde en
of het wake word herkend werd. Nieuwe spellingen (bv. "amiel" voor Miele) kan je
meteen als bijnaam opslaan. Die staan daarna in het instellingenpaneel en werken
ook bij typen.

```
py voice\calibrate.py                         alle teams, base.en en small.en
py voice\calibrate.py --teams Miele,Ceun --models base.en
```

**Testset opnemen.** `voice/record.py` toont een script met echte commando's
(nominate, sold to elk team en enkele picks, uit de draaiende app) en bewaart per
take een wav en de verwachte tekst in `data/recordings/<spreker>/` (niet in git).
Dat is de benchmark voor de spraaknauwkeurigheid. Een tweede run met dezelfde
`--speaker` gaat verder waar je stopte; neem een nieuwe naam voor een nieuwe set
(andere micro, ander wake word).

```
py voice\record.py --speaker otto-laptop      ongeveer 37 commando's
py voice\record.py --speaker otto-headset --device "Headset"
```

**Draaien**, naast `run.bat`:

```
py voice\listen.py                            base.en, standaardmicro, http://127.0.0.1:8000
py voice\listen.py --model small.en           nauwkeuriger, maar trager
py voice\listen.py --list-devices             micro's oplijsten
py voice\listen.py --device "Headset"         micro kiezen op index of een stuk van de naam
```

Elke zin wordt gelogd met zijn latency. Op deze laptop (Core Ultra 7 165U, geen
GPU) duurde het met synthetische spraak ongeveer 1,6 s van einde zin tot resultaat
met base.en, en ongeveer 5 s met small.en. De andere schermen zien het bij hun
volgende poll (maximaal 3 s later).

**In de app.** Rechts in de header staat de spraakindicator: *listening*, *muted*
of *voice off* (geen heartbeat meer sinds 10 s). Klik erop om te muten of te
unmuten. Gemute luistert de listener nog, maar stuurt hij niets. Bijnamen per team
vul je in het instellingenpaneel in, in het veld "also called…" naast de naam
(komma-gescheiden, max 5 per team, 1 tot 30 tekens). Een bijnaam mag niet de naam
of bijnaam van een ander team zijn. Bijnamen gelden enkel voor teams, niet voor
spelers (F-32).

**Microtips.** Een headset of clip-on micro vangt minder geroezemoes dan de
ingebouwde laptopmicro (welke micro het beste werkt, meten we met `voice/record.py`).
Zeg "ok banana" duidelijk en
zonder haast, en noem het bedrag als laatste ("for 55"). Luistert de listener te
veel mee, verhoog dan `--threshold` (standaard 0.5). Knipt hij zinnen te vroeg af,
verhoog dan `--silence-ms` (standaard 400). Werkt de listener niet of crasht hij,
dan blijft de commandobalk gewoon werken.

## Noodexport naar Excel

Loopt de app vast of werkt ze op draftavond niet vlot genoeg, dubbelklik dan
`export.bat`. Dat leest `data\draft.db` rechtstreeks (read-only) en opent
`exports\LoW draft <datum> <uur>.xlsx`. De app hoeft daarvoor niet te draaien, en
een app die nog openstaat merkt er niets van. Elke pick staat in de database
zodra hij gemaakt is, dus de export heeft alles tot de laatste geslaagde pick.

De sheet heeft de vorm van de oude draftsheets: per team een prijs- en een
spelerskolom, de budgetrij van 200, de picks, en onderaan Uitgegeven, Resterend
en Max bid als formules. Zo kan je in Excel verder draften. Het tabblad "Picks"
geeft de picks in volgorde.

Wil je de exacte opmaak van de originele sheet, zet die dan als
`data\draft_template.xlsx` (of geef `--template <bestand>` mee). Het script kopieert
dan het laatste tabblad "Auction <jaar>" naar een nieuw tabblad voor dit jaar,
zet de huidige teamnamen erin en vervangt de picks. Opmaak en formules blijven.

Test het eens voor de draft, bv. met een paar picks in de demo-database:
`py tool\export_xlsx.py --db data\demo.db --open`.

## Categorieën aanpassen

In `tool/config.json` staat elke categorie op 1. Zet er een op 0 om een
punt-build door te rekenen, of hoger dan 1 om zwaarder te wegen. Draai daarna
`build_values.py` opnieuw en vergelijk `output/top.txt`. Turnovers staan op 0,
want de league speelt 8-cat.

## Nog te bouwen

Marktprijsmodule, tweede projectiebron, prijsmodel op de eigen
draftgeschiedenis, en fase 2 met logins en teampagina's. Zie de tabel met
openstaande punten onderaan de FRD. De spraaklaag staat daar nog als open punt,
maar is intussen gebouwd (zie Spraak hierboven).
