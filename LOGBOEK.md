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
