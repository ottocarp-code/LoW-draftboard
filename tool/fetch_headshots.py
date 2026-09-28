"""
Downloadt de ESPN-headshots van alle spelers in output/values.json naar
data/headshots/<espn_id>.png, zodat het draftboard ook zonder wifi werkt.

    py tool\\fetch_headshots.py

Draaien op je eigen machine, niet in de Cowork-omgeving: die zit achter een
proxy die a.espncdn.com blokkeert.

De app serveert de map op /headshots. Ontbreekt een bestand, dan valt de
frontend terug op de ESPN-CDN en daarna op de initialen van de speler, dus dit
script is optioneel. Reken op ongeveer 10 MB voor 340 spelers.
"""

import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALUES = os.path.join(ROOT, "output", "values.json")
OUT = os.path.join(ROOT, "data", "headshots")
URL = "https://a.espncdn.com/i/headshots/nba/players/full/{}.png"
PAUSE = 0.12  # vriendelijk blijven voor de CDN


def main():
    if not os.path.exists(VALUES):
        raise SystemExit(f"{VALUES} ontbreekt. Draai eerst tool/build_values.py.")
    with open(VALUES, encoding="utf-8") as f:
        players = json.load(f).get("players", [])
    os.makedirs(OUT, exist_ok=True)

    done = skipped = failed = 0
    for i, p in enumerate(players, 1):
        pid = str(p.get("id") or "")
        if not pid.isdigit():
            continue
        dest = os.path.join(OUT, f"{pid}.png")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            skipped += 1
            continue
        req = urllib.request.Request(URL.format(pid), headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            if len(data) < 500:          # placeholder of lege respons
                failed += 1
                continue
            with open(dest, "wb") as f:
                f.write(data)
            done += 1
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            failed += 1
        if i % 25 == 0:
            print(f"  {i}/{len(players)} verwerkt")
        time.sleep(PAUSE)

    print(f"{done} gedownload, {skipped} stonden er al, {failed} niet gevonden.")
    print(f"Map: {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
