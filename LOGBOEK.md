# Logboek

## 2026-09-28 — Rebuild draftboard-app (bmad-build, planning)

- **Probleem:** Fase 1 bestaat al, maar is enkel op gesimuleerde data gedraaid. Er zitten bugs in: de beurt kan dubbel vallen, undo zet de beurt verkeerd terug, de bedragprompt loopt dood, namen gaan zonder escaping in de HTML en getalwoorden worden fout opgeteld. Daarnaast crasht `build_values.py` omdat `tool/names.py` ontbreekt.
- **Opties/checks:** Harden fase 1, marktprijsmodule, prijsmodel op eigen historiek, of rebuild. De codebase is door een subagent in kaart gebracht (contract van `values.json`, API en parser).
- **Keuze:** Rebuild van enkel `app/`, met de pipeline uitgesteld (`_bmad-output/deferred-work.md`). De oude code verhuist naar `_legacy/app/`. Verder: vanilla JS, prijs boven max bid weigeren, settingspaneel met de 2025-defaults, minimale `tool/names.py` terugzetten.
- **Spraak (bijgestuurd):** Spraak komt er nu al, via lokale Whisper met wake word "low-db", als apart vervolgplan direct na de rebuild. De rebuild maakt de parser er al klaar voor (wake word, "55 $", "dollars"). Logins en optimizer blijven uit scope.
- **Aanpassingen:** BMad is geïnstalleerd (`_bmad/`). Het plan staat in `_bmad-output/plan-rebuild-draftboard-app.md`. Er is nog geen code gewijzigd.

## 2026-09-28 — Rebuild draftboard-app gebouwd

- **Probleem:** De app moest opnieuw gebouwd worden volgens de FRD. Er moesten ook meerdere picks tegelijk terug kunnen, en een nieuwe draft met twee bevestigingen.
- **Checks:** 118 tests zijn groen. Een scripted browsertest op twee vensters slaagde (30 checks). Na de review bleven er 5 fixes over: de beurt na een nieuwe nominatievolgorde, decimale bedragen, de bedragprompt die openblijft, "Turn to None" en "back to here" met het toetsenbord. 5 bevindingen zijn afgewezen, met redenen in de triage log van het plan.
- **Keuze:** "emiel" matcht "Miele" via de anagramregel voor teamnamen (in 2021 heette het team Emiel). Echte bijnamen per team komen in het spraakplan.
- **Aanpassingen:** De nieuwe `app/` bestaat uit store, draft, parser, main en een static frontend. Verder: `tool/names.py`, `tests/` met een fixture, en README en `run.bat` zijn bijgewerkt. De oude code staat in `_legacy/app/`. Het plan heeft status `built`.

## 2026-09-28 — Git

- De repo is lokaal aangemaakt met het persoonlijke e-mailadres (enkel voor deze repo) en een eerste commit (`bf52266`). Remote: `ottocarp-code/LoW-draftboard`. Het pushen wacht tot de GitHub-repo bestaat. Tooling, `_legacy/` en lokale data staan in `.gitignore`.

## 2026-09-28 — Spraakbesturing (planning)

- **Probleem:** Picks inspreken met het wake word "low-db". Teamnamen zoals emiel, Ceun en Gillese worden slecht getranscribeerd.
- **Checks:** Research door een subagent (bronnen in `.claude/logs/voice-research.md`). faster-whisper 1.2.1, ctranslate2 4.8.2 en sounddevice installeren op Python 3.13/Windows. Porcupine heeft geen persoonlijke licentie. openWakeWord vraagt een training en heeft geen release sinds feb 2024.
- **Keuze:** Een lokale listener in `voice/` die het wake word in de transcriptie herkent, `base.en` op int8 en een headset. Picks gaan meteen in, met een banner op elk scherm. Bijnamen per team plus een kalibratiescript.
- **Aanpassingen:** Het plan staat in `_bmad-output/plan-voice-control.md`. Los daarvan toont de teamsview de max bid nu op een eigen regel (nog niet gecommit).

## 2026-09-28 — Spraakbesturing gebouwd

- **Probleem:** Picks inspreken met "low-db", en bijnamen voor teams die slecht getranscribeerd worden.
- **Checks:** 210 tests zijn groen. End-to-end met synthetische spraak: ongeveer 1,6 s van einde zin tot pick met base.en (small.en ongeveer 5 s). De review leverde 8 fixes op: dubbele pick via de banner, het "pauze na low-db"-venster geschrapt omdat het zinnen zonder wake word doorstuurde, kalibratie, mute, fillers, het hotwordbudget en de README. 3 bevindingen zijn afgewezen.
- **Keuze:** Undo van picks gaat enkel via typen (heronderhandeld door de gebruiker tijdens de bouw). De test met de echte stem, headset en zaal gebeurt door de gebruiker.
- **Aanpassingen:** `voice/` (listen, wake, calibrate), bijnamen in de settings en de parser, de spraakbanner en micro-indicator, de routes `/api/voice/*`. Ook `.claude/STATE.md` is aangemaakt. Het volgende plan is nominate/sold.

## 2026-09-28 — Einde sessie

- **Stand:** De rebuild en de spraakbesturing zijn gebouwd en gepusht (`a6db255`). De gebruiker heeft spraak getest met de laptopmicro (rechtgezet op 2026-10-02, stond eerder als headset): de zin kwam 0,7 s na het einde van de zin binnen. `nominate curry` faalt nog, zoals verwacht, want nominate/sold is nog niet gebouwd.
- **Volgende stap:** Het plan voor nominate/sold via `/bmad-build`. Alle beslissingen staan in `_bmad-output/deferred-work.md` en `.claude/STATE.md`. Daarna de kalibratierun van de gebruiker.
- **Open in de werkboom:** `run.bat` gebruikt nu de `.venv`, en `.gitignore` negeert `.venv/`. Beide zijn nog niet gecommit.

## 2026-09-29 — Spraak: nauwkeurigheid en snelheid (actieplan)

- **Probleem:** Test en kalibratie van spraak gaven slechte resultaten. De vraag was of een ander wake word en andere teamnamen helpen, en of de performance beter kan.
- **Checks:** Het meeste uit de aangereikte lijst zit er al in (faster-whisper, int8, en, VAD, beam 1). De laptop heeft geen NVIDIA GPU. Bench met TTS: base.en 0,66 s, small.en 2,5 s en 2,0 s met 8 threads. 60 spelers als hotwords kosten 0,1 tot 0,6 s.
- **Keuze:** Eerst meten op echte opnames. Daarna komen de quick wins, dan een Engels wake word en call signs per team, en pas dan de modelkeuze (distil-small.en, fallback). GPU, turbo en CoreML vallen af.
- **Aanpassingen:** Het plan staat in `_bmad-output/plan-voice-accuracy.md`. Er is nog geen code gewijzigd.
- **Overleg:** De gebruiker kiest de gelaagde modelopzet. base.en draait altijd, en small.en neemt pas over als team of speler niet duidelijk matcht. Zo komt de winst in nauwkeurigheid zonder vaste vertraging. Met distil-small.en en beam 5 in de fallback beslist de bench.

## 2026-09-29 — Nominate/sold gebouwd (voor het spraaktraject)

- **Probleem:** Een speler wordt eerst genomineerd en pas later verkocht, maar de app kende enkel de pick in één stap. Whisper-vormen ("the rosen", "alparan senghan") en bijnamen ("wemby", "ant edwards") vonden de speler niet.
- **Keuze:** Nominate/sold gaat voor het spraaktraject, want de opnames van fase 0 moeten de definitieve commando's gebruiken. Fase 0+1 van het spraaktraject staat in `deferred-work.md`. Een tweede nominate geeft een fout. Een undo met een speler op het blok leegt enkel het blok. De pick in één stap blijft werken.
- **Checks:** 270 tests zijn groen (210 voordien). De review gaf 4 fixes: "gary" was ambigu door de bijnaamregel, de "Closest:"-klik na een mislukte nominate maakte een pick, bij een rename bleef de oude teamnaam op het blok staan, en een test ontbrak. 1 bevinding over de volgorde van foutmeldingen is afgewezen.
- **Aanpassingen:** De parser kent nu nominate/sold en drie nieuwe scoreregels. Het blok staat in `settings` (store), met de routes `/api/nominate` en `/api/block/clear` en een blokpaneel op elk scherm. Het plan staat in `_bmad-output/plan-nominate-sold.md`, het detaillog in `.claude/logs/nominate-sold.md`.

## 2026-10-02 — Fix: nominate via klik op het bord

- **Probleem:** Na `nominate johnson` opende een klik op een kaart van het bord de pickprompt in plaats van te nomineren. Enkel de knoppen in de kandidatenrij nomineerden.
- **Keuze:** Een klik op het bord nomineert zolang er een nominate loopt: de commandobalk begint met "nominate", of de rij "Nominate:" staat open. Anders blijft het de pickprompt.
- **Checks/aanpassingen:** `onPlayerClick` en `nominating()` in `app/static/app.js`. 270 tests groen. Headless Chrome: getypt+klik, Enter+klik en een gewone klik werken alle drie zoals bedoeld.

## 2026-10-02 — Spraak: spike met een gesloten vocabulaire voor spelersnamen

- **Probleem:** Whisper verminkt spelersnamen. De vraag was of we de uitvoer kunnen beperken tot de spelers in de pool (grammar/constrained decoding). De gebruiker reikte de NBA-pronunciation guide aan als testdata.
- **Checks:** Een bench op 464 NBA-clips (310 pool, 154 niet-pool). whisper.cpp met GBNF kapt namen af en is slechter en trager, dus afgevallen. Een eigen trie-constrained beam search op faster-whisper haalt 75% top-1 (82% met beam 24), tegenover 37% voor het huidige pad. Na de beslisregel: 50% meteen juist en 0% fout, met 2% false accepts op niet-pool. Detail staat in `.claude/logs/grammar-spike.md`.
- **Keuze:** Nog geen. Het is veelbelovend, maar de latency is 2,3 tot 7,4 s per clip in de naïeve vorm. Er is ook nog geen test met echte commando's en onze eigen stemmen. De beslissing ligt bij de gebruiker.
- **Aanpassingen:** Geen in de app. De scripts staan in de scratchpad.

## 2026-10-02 — Spike: snelheid van het gesloten vocabulaire

- **Probleem:** Trie-decoding duurde 2,3 tot 7,4 s per zin, en dat is te traag.
- **Checks:** Alle namen exhaustief scoren kost ongeveer 33 s, en het croppen van de encoder-output breekt de scores. Een hybride (de huidige matcher geeft een top-4, Whisper scoort enkel die) haalt top-1 77% en 58% meteen juist, met 0% fout, tegenover 37% nu. Dat kost ongeveer 0,2 tot 0,4 s extra, dus zo'n 1,0 tot 1,1 s per zin.
- **Keuze:** De hybride is de kandidaat. De gebruiker koos optie 3: eerst snelheid, dan een test op eigen stemmen. Stap 2 vraagt een opnametool, en die is nog niet gebouwd (eerst akkoord vragen).
- **Aanpassingen:** Geen in de app. Detail staat in `.claude/logs/grammar-spike.md`.

## 2026-10-02 — Microfoon niet langer vastgelegd

- **Probleem:** De "headset mic" stond als locked decision in `STATE.md`, maar de gebruiker herinnert zich niet die keuze gemaakt te hebben.
- **Keuze:** Geschrapt uit de locked decisions. De micro (headset of laptop) blijft open en wordt gemeten met `voice/record.py`, met een set per micro.
- **Aanpassingen:** De regel in `.claude/STATE.md` is aangepast. Rechtzetting: alle tests tot nu toe, ook de kalibratie, liepen met de laptopmicro. "Headset" is op 3 plaatsen in `STATE.md` en `LOGBOEK.md` verbeterd.

## 2026-10-02 — Spraak: eerste echte opnames (37 takes, laptopmicro)

- **Probleem:** Het hybride pad meten op de eigen stem, niet enkel op de NBA-clips.
- **Checks:** Het wake word "low-db" werd maar 4 van de 37 keer herkend, en het klinkt als team "Lode". Spelers: de hybride 21/25 meteen juist, tegenover 16/25 nu (0 fout). Teams: 14/17 tegenover 10/17, maar met 1 fout team door een bug in het spike-script. Een deel van de missers komt van de parser: "sold" wordt gehoord als "soul" of "sol", en "to" valt weg.
- **Keuze:** Nog geen. Openstaand: een nieuw wake word kiezen en testen, quick wins in de parser, en de hybride pas inbouwen na een fix van de span-bug.
- **Aanpassingen:** `voice/record.py`, een test, en `data/recordings/` in `.gitignore`. Niet gecommit. Detail staat in `.claude/logs/grammar-spike.md`.

## 2026-10-02 — Wake word: "low-db" vervangen door "ok banana"

- **Probleem:** "low-db" werd in de opnames maar 4 van de 37 keer herkend, en klinkt als "Lode B" (botst met team Lode).
- **Opties:** auctioneer, hey draftboard, computer, ok banana. De gebruiker kiest **ok banana** (gewone Engelse woorden met een vaste spelling, en bijna nooit gezegd in geroezemoes).
- **Checks:** TTS met 5 stemmen: 24/30 meteen herkend. De 6 missers (Duitse stem: "Okiebannina", "Oki Banena") worden herkend sinds het patroon accentvarianten toelaat (okie/oki/okee, banena/banaan). Er zijn negatieve tests voor banner, Bannon, bandana, "the banana", "low-db" en "Lode B". 281 tests groen.
- **Aanpassingen:** `WAKE_CORE`/`WAKE_FILLER` (`app/parser.py`), `app.js` WAKE, `voice/wake.py` (hotword), de teksten in listen/calibrate/record, de tests en de README. `draftbot` blijft werken. Niet gecommit.

## 2026-10-02 — Parser: lossere sleutelwoorden en typ-shortcuts

- **Probleem:** Whisper hoort "sold" als soul/sol, "to" als the/two of geplakt ("sold today"), en "nominate" als nominates/nomineen. Typen moet ook korter kunnen.
- **Keuze:** sold accepteert sold/soul/sol/sole/solde. Na sold telt to/2/the/two/too. Een geplakte "to" wordt opnieuw geprobeerd, en enkel aanvaard als er één duidelijk team uitkomt. Elk "nomin..."-woord en `nm` betekent nominate. `<team> for <bedrag>` of `<team> <bedrag>` betekent "sold to", maar enkel met een speler op het blok en een herkend team. Anders blijft het gedrag zoals vroeger.
- **Checks:** Geen enkele speler of team heeft deze woorden in zijn naam. 304 tests groen, met de echte transcripties als testgevallen. In headless Chrome filtert het bord correct op `nm jal`, `soul to rj` en `rj for 5`, zonder JS-fouten.
- **Aanpassingen:** `app/parser.py` (`parse_command`, `interpret(block=)`, `_team_glued_to`), `app/main.py` (geeft block door) en `app.js` (`nameFragment`, `NOMINATE`). Plus tests. Niet gecommit.

## 2026-10-02 — Easter egg: Otto Carpentier, draftable voor $1

- **Vraag:** De gebruiker wil zichzelf als draftbare speler voor $1, met een eigen (AI-)foto.
- **Keuze:** Hij wordt toegevoegd bij het laden van de pool (`store.EASTER_EGG`), niet in `values.json`, zodat een pipeline-run hem niet weghaalt. Value $1, PF BOS, geen ADP. De foto staat in `data/headshots/otto-carpentier.jpg` (genegeerd door git, dus niet op GitHub). De headshot-route aanvaardt nu ook `.jpg`.
- **Checks:** 306 tests groen. Er is een screenshot op een testinstantie met de echte data: de kaart staat er met de foto.

## 2026-10-02 — Teamkeuze met knoppen bij een onbekend team

- **Probleem:** "Mitchell Robinson to an auto for 5" gaf enkel "Team not recognised", terwijl spelers bij twijfel wel kandidaatknoppen krijgen.
- **Keuze:** De top 3 teams komen als knoppen met een tekstscore, zowel getypt als in de spraakbanner. Een knop stuurt het oorspronkelijke commando opnieuw, met het gekozen team als data (`team`), dus speler en bedrag blijven exact zoals gehoord. Een lidwoord vooraan valt weg ("an auto" wordt "auto"), maar exacte namen en bijnamen met een lidwoord gaan voor. Een team wordt nooit automatisch gekozen.
- **Review (bmad-build, 2 rondes):** In de eerste versie bouwde een knop het commando opnieuw als tekst, en daardoor werd een team als "Team 13" verkocht voor $13. Dat is herontworpen. Een verouderde knop kon ook de speler verkopen die op dat moment op het blok staat; die klik wordt nu geweigerd als het blok veranderd is. De triage staat in `_bmad-output/plan-team-candidate-buttons.md`.
- **Aanpassingen:** `parser.py` (`team_candidates`, `_drop_article`, `interpret(team=)`, `action` in de teamfout), `main.py` (`team` in `/api/command`, `command` en de blokspeler bij een mislukte sold), `store.py` (`VOICE_EVENT_FIELDS`) en `app.js` (`teamPrompt`, de bannerknoppen, `blockChanged`). Commits `5cd9c60` en `24eb817`, plus de fix van ronde 2. 324 tests groen, en beide stromen en de blokcheck zijn getest in headless Chrome.
