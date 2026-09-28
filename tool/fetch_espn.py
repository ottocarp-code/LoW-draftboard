"""
Haalt de ESPN-projecties voor seizoen 2026-27 op en schrijft data/espn.csv.

Draaien op je eigen Windows-machine (niet in de Cowork-omgeving, die zit achter
een proxy die ESPN blokkeert):

    py tool\\fetch_espn.py

Geen pip install nodig, alles uit de standard library.

Bron: https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/2027
      /segments/0/leaguedefaults/3?view=kona_player_info
Geen login. De publieke /players-route geeft maximaal 50 spelers alfabetisch en
negeert de filter-header; de leaguedefaults-route respecteert hem wel.

Statline 102027 = statSourceId 1 (projectie), statSplitTypeId 0.
Tellende stats zijn SEIZOENSTOTALEN. MPG (28) en GP (42) staan los.
"""

import csv
import json
import os
import urllib.error
import urllib.request

SEASON = 2027  # ESPN noemt seizoen 2026-27 "2027"
POOL_SIZE = 600  # aantal spelers opvragen, gesorteerd op percentOwned
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "espn.csv")

URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/"
    f"{SEASON}/segments/0/leaguedefaults/3?view=kona_player_info"
)

# Empirisch geverifieerd op de game logs: 13/14 met 19 = FGM/FGA/FG%,
# 15/16 met 20 = FTM/FTA/FT%, 17/18 met 21 = 3PM/3PA/3P%.
STAT = {
    "PTS": "0", "BLK": "1", "STL": "2", "AST": "3", "REB": "6", "TO": "11",
    "FGM": "13", "FGA": "14", "FTM": "15", "FTA": "16", "TPM": "17", "TPA": "18",
    "MPG": "28", "GP": "42",
}

TEAMS = {
    0: "FA", 1: "ATL", 2: "BOS", 3: "NOP", 4: "CHI", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GSW", 10: "HOU", 11: "IND", 12: "LAC", 13: "LAL", 14: "MIA",
    15: "MIL", 16: "MIN", 17: "BKN", 18: "NYK", 19: "ORL", 20: "PHI", 21: "PHX",
    22: "POR", 23: "SAC", 24: "SAS", 25: "OKC", 26: "UTA", 27: "WAS", 28: "TOR",
    29: "MEM", 30: "CHA",
}

SLOTS = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C"}

COLUMNS = [
    "source", "player_id", "name", "team", "pos", "inj", "adp", "market_value",
    "pct_owned", "GP", "MPG", "PTS", "REB", "AST", "STL", "BLK", "TO",
    "FGM", "FGA", "FTM", "FTA", "TPM", "TPA",
]


def fetch(limit):
    filt = {"players": {"limit": limit, "offset": 0,
                        "sortPercOwned": {"sortAsc": False, "sortPriority": 1}}}
    req = urllib.request.Request(URL, headers={
        "x-fantasy-filter": json.dumps(filt),
        "x-fantasy-platform": "kona-PROD",
        "x-fantasy-source": "kona",
        "accept": "application/json",
        "user-agent": "Mozilla/5.0",
    })
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def projection_row(entry):
    p = entry.get("player", entry)
    line = next((s for s in p.get("stats", [])
                 if s.get("id") == f"10{SEASON}" and s.get("stats")), None)
    if line is None:
        return None
    v = line["stats"]

    def g(key):
        x = v.get(STAT[key])
        return "" if x is None else round(float(x), 2)

    own = p.get("ownership") or {}
    pos = "/".join(SLOTS[s] for s in sorted(p.get("eligibleSlots", [])) if s in SLOTS)
    return {
        "source": "espn",
        "player_id": p.get("id"),
        "name": p.get("fullName", ""),
        "team": TEAMS.get(p.get("proTeamId"), "?"),
        "pos": pos,
        "inj": p.get("injuryStatus", ""),
        "adp": round(own.get("averageDraftPosition") or 0, 1),
        "market_value": round(own.get("auctionValueAverage") or 0, 1),
        "pct_owned": round(own.get("percentOwned") or 0, 1),
        **{k: g(k) for k in ("GP", "MPG", "PTS", "REB", "AST", "STL", "BLK", "TO",
                             "FGM", "FGA", "FTM", "FTA", "TPM", "TPA")},
    }


def main():
    try:
        payload = fetch(POOL_SIZE)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ESPN gaf HTTP {e.code}. Endpoint of filterformaat gewijzigd.")
    except urllib.error.URLError as e:
        raise SystemExit(f"Geen verbinding met ESPN: {e.reason}. "
                         "Draai dit script op je eigen machine, niet achter de bedrijfsproxy.")

    players = payload.get("players", payload)
    rows = [r for r in (projection_row(e) for e in players) if r]
    if not rows:
        raise SystemExit("Geen projecties gevonden. Controleer of ESPN de 2026-27 "
                         "projecties al gepubliceerd heeft (statline 10%d)." % SEASON)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    missing = sum(1 for r in rows if r["FTA"] == "" or r["FGA"] == "")
    print(f"{len(players)} spelers opgehaald, {len(rows)} met projectie.")
    print(f"{missing} rijen zonder FGA of FTA (worden gereconstrueerd in build_values.py).")
    print(f"Geschreven naar {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
