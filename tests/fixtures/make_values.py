"""
Builds tests/fixtures/values.json: about 200 players with real names from
data/draft_history.csv and generated stats, in exactly the shape that
tool/build_values.py writes. Deterministic (fixed seed), so tests can rely on it.

    py tests\\fixtures\\make_values.py

Then run the app on it:  $env:LOW_VALUES='tests/fixtures/values.json'; run.bat
The ids are not real ESPN ids, so headshots fall back to initials.
"""

import csv
import hashlib
import json
import os
import random
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
HISTORY = os.path.join(ROOT, "data", "draft_history.csv")
OUT = os.path.join(HERE, "values.json")
TARGET = 200
# Always present, so the FRD test cases (jokitch, de rosan, sengun, two Bridges) are
# reproducible. Seth Curry is excluded on purpose: the I/O matrix expects a bare
# "curry" to resolve to Stephen Curry, which only holds while he is the only Curry.
MUST = ["Nikola Jokic", "DeMar DeRozan", "Alperen Sengun", "Mikal Bridges", "Miles Bridges",
        "Victor Wembanyama", "Stephen Curry"]
EXCLUDE = {"seth curry"}
NBA = ["ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU", "IND",
       "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX",
       "POR", "SAC", "SAS", "TOR", "UTA", "WAS"]
POS = ["PG", "SG", "SF", "PF", "C", "PG/SG", "SG/SF", "SF/PF", "PF/C"]
CATS = ["PTS", "TPM", "REB", "AST", "STL", "BLK", "FG", "FT", "TO"]


def key(name):
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"['.]", "", s)
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", s)).strip()


def looks_real(name):
    parts = name.split()
    return len(parts) >= 2 and all(p[:1].isupper() for p in parts[:2]) and len(name) <= 28


def collect():
    rows = list(csv.DictReader(open(HISTORY, encoding="utf-8")))
    rows.sort(key=lambda r: (-int(r["year"]), -float(r["price"] or 0)))
    seen, out = set(), []
    for r in rows:
        n = r["name"].strip()
        if not looks_real(n) or key(n) in seen or key(n) in EXCLUDE:
            continue
        seen.add(key(n))
        out.append((n, float(r["price"] or 1)))
    must = [(n, next((p for m, p in out if key(m) == key(n)), 1.0)) for n in MUST]
    rest = [x for x in out if key(x[0]) not in {key(m) for m in MUST}]
    return must + rest[:TARGET - len(must)]


def last_season(rng, pg):
    """Last season per game near the projection, or None (a rookie) for about 1 in 8.
    Its own RNG, so adding it left every other fixture value unchanged."""
    if rng.random() < 0.125:
        return None
    j = lambda v: round(max(0.0, v * rng.uniform(0.8, 1.15)), 3)
    last = {"GP": float(rng.randint(30, 82)), "MPG": j(pg["MPG"])}
    for k in ("PTS", "TPM", "REB", "AST", "STL", "BLK", "TO"):
        last[k] = j(pg[k])
    last["fg_pct"] = round(min(0.7, pg["FGM"] / pg["FGA"] * rng.uniform(0.95, 1.05)), 4)
    last["ft_pct"] = round(min(0.95, pg["FTM"] / pg["FTA"] * rng.uniform(0.95, 1.05)), 4)
    return last


def main():
    rng = random.Random(2025)
    rng_last = random.Random(2026)
    picked = collect()
    players = []
    for name, price in picked:
        pid = str(4000000 + int(hashlib.md5(key(name).encode()).hexdigest(), 16) % 900000)
        gp = rng.randint(45, 80)
        pts = round(rng.uniform(6, 30), 3)
        pg = {"GP": gp, "MPG": round(rng.uniform(18, 36), 3), "PTS": pts,
              "TPM": round(rng.uniform(0, 4), 3), "REB": round(rng.uniform(2, 13), 3),
              "AST": round(rng.uniform(1, 10), 3), "STL": round(rng.uniform(0.3, 2), 3),
              "BLK": round(rng.uniform(0.1, 2.5), 3), "TO": round(rng.uniform(0.8, 4), 3)}
        pg["FGA"] = round(pts / 2.2, 3)
        pg["FGM"] = round(pg["FGA"] * rng.uniform(0.42, 0.6), 3)
        pg["FTA"] = round(rng.uniform(1, 8), 3)
        pg["FTM"] = round(pg["FTA"] * rng.uniform(0.6, 0.92), 3)
        z = {c: round(rng.uniform(-1.5, 2.5), 3) for c in CATS}
        z["TO"] = 0.0
        value = max(1.0, round(price * rng.uniform(0.85, 1.15), 1))
        players.append({
            "id": pid, "name": name, "team": rng.choice(NBA), "pos": rng.choice(POS),
            "inj": rng.choice(["ACTIVE"] * 12 + ["DAY_TO_DAY", "OUT"]),
            "value": value, "market_value": round(value * rng.uniform(0.7, 1.3), 1),
            "adp": 0, "z_total": round(sum(z.values()) / 2 + value / 10, 3), "z": z, "pg": pg,
            "fg_pct": round(pg["FGM"] / pg["FGA"], 4), "ft_pct": round(pg["FTM"] / pg["FTA"], 4),
            "last": last_season(rng_last, pg),
            "risk": round(rng.uniform(0, 0.6), 2), "risk_basis": "GP+blessure",
            "sources": ["espn"],
        })
    players.sort(key=lambda p: -p["value"])
    # ADP roughly follows value, with noise; the tail has no ADP (0), like ESPN.
    order = sorted(players, key=lambda p: -p["value"] * rng.uniform(0.75, 1.25))
    for i, p in enumerate(order, 1):
        p["adp"] = round(i + rng.uniform(-0.4, 0.4), 1) if i <= 170 else 0
    payload = {
        "generated_for": "LoW 12-team H2H 8-cat auction (TEST FIXTURE, generated stats)",
        "config": {"teams": 12, "budget": 200, "roster_spots": 13,
                   "categories": {c: (0 if c == "TO" else 1) for c in CATS},
                   "z_pool": 180, "min_gp": 25, "anchor_source": "espn"},
        "meta": {"sources": ["espn"], "fixture": True},
        "players": players,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    print(f"{len(players)} players -> {OUT}")


if __name__ == "__main__":
    main()
