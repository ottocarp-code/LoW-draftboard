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

- **Stand:** De rebuild en de spraakbesturing zijn gebouwd en gepusht (`a6db255`). De gebruiker heeft spraak getest met de headset: de zin kwam 0,7 s na het einde van de zin binnen. `nominate curry` faalt nog, zoals verwacht, want nominate/sold is nog niet gebouwd.
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
