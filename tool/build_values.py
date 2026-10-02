"""
Leest alle bronbestanden in data/, voegt ze samen tot een consensus per speler,
berekent Z-scores en auction-waardes, en schrijft:

    output/paste_block.csv   kolommen in de volgorde van je brontabbladen
    output/values.json       input voor de drafttool
    output/top.txt           leesbare top-N, om te sanity-checken

Draaien:  py tool\\build_values.py
Geen pip install nodig.

Elk bestand in data/ is een CSV met minstens deze kolommen:
    source, player_id, name, team, pos, GP, MPG, PTS, REB, AST, STL, BLK, TO,
    FGM, FGA, FTM, FTA, TPM, TPA
Ontbrekende attempts worden gereconstrueerd (zie reconstruct).
Een lege cel bij een tellende stat betekent nul.
Optioneel: LY_GP, LY_MPG, LY_PTS, ... (de echte stats van vorig seizoen, uit
fetch_espn.py). Die komen als "last" in values.json, enkel voor de weergave; ze
tellen niet mee in de Z-scores of de waardes.
"""

import csv
import json
import math
import os
import statistics
from collections import defaultdict

import names

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(HERE, "..", "output")

COUNTING = ["PTS", "REB", "AST", "STL", "BLK", "TO", "FGM", "FGA", "FTM", "FTA", "TPM", "TPA"]
# Categorieen waarvoor een Z-score berekend wordt. FG en FT zijn impactscores
# (procent minus poolgemiddelde, maal het aantal pogingen), niet het percentage
# zelf: een FT% van 95 op 1 poging per match is niets waard.
CATS = ["PTS", "TPM", "REB", "AST", "STL", "BLK", "FG", "FT", "TO"]
NEGATIVE = {"TO"}


def num(x, default=0.0):
    if x is None or x == "":
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def load_config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def load_sources():
    if not os.path.isdir(DATA):
        raise SystemExit(f"Map {os.path.normpath(DATA)} bestaat niet. "
                         "Draai eerst tool\\fetch_espn.py.")
    # Alleen bestanden die er als projectiebron uitzien. In data/ staat ook
    # draft_history.csv, en die mag hier niet als spelersprojectie binnenkomen.
    required = {"name", "GP", "PTS"}
    per_source, skipped = defaultdict(list), []
    for fn in sorted(os.listdir(DATA)):
        if not fn.lower().endswith(".csv"):
            continue
        with open(os.path.join(DATA, fn), encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            cols = set(reader.fieldnames or [])
            if not required.issubset(cols):
                skipped.append(f"{fn} (mist {', '.join(sorted(required - cols))})")
                continue
            for row in reader:
                src = (row.get("source") or os.path.splitext(fn)[0]).strip()
                row["source"] = src
                per_source[src].append(row)
    if skipped:
        print("overgeslagen, geen projectiebron: " + "; ".join(skipped))
    if not per_source:
        raise SystemExit(f"Geen bruikbare projectie-CSV's in {os.path.normpath(DATA)}.")
    return per_source


def reconstruct(row, anchor):
    """
    Vult ontbrekende FGA/FTA aan.

    Exacte route: uit de puntenidentiteit PTS = 2*FGM + TPM + FTM volgt FGM zodra
    FTM bekend is, en FGA = FGM / FG%.
    Zonder FTM is er een tweede onbekende. Dan wordt de verhouding FTA/FGA van de
    ankerbron voor die speler gebruikt:
        PTS = 2*FGA*fg + TPM + r*FGA*ft   met r = FTA/FGA
    wat FGA oplevert, en daarmee FTA, FGM en FTM.
    """
    fga, fta = num(row.get("FGA"), None), num(row.get("FTA"), None)
    if row.get("FGA") not in (None, "") and row.get("FTA") not in (None, ""):
        return row, "bron"

    fg = num(row.get("FG_PCT")) or None
    ft = num(row.get("FT_PCT")) or None
    pts, tpm = num(row.get("PTS")), num(row.get("TPM"))
    ftm = row.get("FTM")

    if ftm not in (None, "") and fg:
        fgm = (pts - tpm - num(ftm)) / 2.0
        row["FGM"], row["FGA"] = fgm, fgm / fg
        row["FTA"] = num(ftm) / ft if ft else row.get("FTA", "")
        return row, "afgeleid"

    if fg and ft and anchor:
        a_fga, a_fta = num(anchor.get("FGA")), num(anchor.get("FTA"))
        r = (a_fta / a_fga) if a_fga else 0.25
        denom = 2 * fg + r * ft
        if denom > 0:
            fga = (pts - tpm) / denom
            row["FGA"], row["FTA"] = fga, r * fga
            row["FGM"], row["FTM"] = fga * fg, r * fga * ft
            return row, "geschat"

    return row, "ontbreekt"


def per_game(row):
    gp = num(row.get("GP"))
    if gp <= 0:
        return None
    out = {"GP": gp, "MPG": num(row.get("MPG"))}
    for k in COUNTING:
        v = num(row.get(k))
        # Sommige bronnen geven al per-game waardes. Heuristiek: totalen zijn
        # altijd groter dan GP voor punten.
        out[k] = v / gp if num(row.get("PTS")) > gp else v
    return out


LAST_STATS = ("GP", "MPG", "PTS", "TPM", "REB", "AST", "STL", "BLK", "TO")


def last_season(row):
    """
    Vorig seizoen per wedstrijd uit de LY_-kolommen (seizoenstotalen), of None
    als ze ontbreken of LY_GP 0 is (rookie, oude CSV). FG%/FT% uit makes en
    attempts, None bij nul pogingen.
    """
    gp = num(row.get("LY_GP"))
    if gp <= 0:
        return None
    out = {"GP": round(gp, 3), "MPG": round(num(row.get("LY_MPG")), 3)}
    for k in LAST_STATS[2:]:
        out[k] = round(num(row.get("LY_" + k)) / gp, 3)
    fga, fta = num(row.get("LY_FGA")), num(row.get("LY_FTA"))
    out["fg_pct"] = round(num(row.get("LY_FGM")) / fga, 4) if fga > 0 else None
    out["ft_pct"] = round(num(row.get("LY_FTM")) / fta, 4) if fta > 0 else None
    return out


def merge(per_source, cfg):
    """Koppelt de bronnen op naam en geeft per speler het gemiddelde plus de spreiding."""
    anchor_rows = {names.normalize(r["name"]): r
                   for r in per_source.get(cfg["anchor_source"], [])}
    merged, notes = {}, defaultdict(int)

    for src, rows in per_source.items():
        for row in rows:
            key = names.normalize(row["name"])
            row, how = reconstruct(dict(row), anchor_rows.get(key))
            notes[how] += 1
            pg = per_game(row)
            if pg is None:
                continue
            slot = merged.setdefault(key, {
                "name": row["name"], "team": row.get("team", ""),
                "pos": row.get("pos", ""), "player_id": row.get("player_id") or key,
                "inj": row.get("inj", ""), "adp": num(row.get("adp")),
                "market_value": num(row.get("market_value")),
                "obs": defaultdict(list), "sources": [], "last": None,
            })
            slot["sources"].append(src)
            # Vorig seizoen enkel uit de ankerbron (ESPN): echte stats, geen consensus.
            if src == cfg["anchor_source"] and slot["last"] is None:
                slot["last"] = last_season(row)
            for k, v in pg.items():
                slot["obs"][k].append(v)

    players = []
    for key, s in merged.items():
        p = {k: s[k] for k in ("name", "team", "pos", "player_id", "inj",
                               "adp", "market_value", "last")}
        p["sources"] = sorted(set(s["sources"]))
        p["n_sources"] = len(p["sources"])
        for k, vals in s["obs"].items():
            p[k] = statistics.fmean(vals)
            p[k + "_sd"] = statistics.pstdev(vals) if len(vals) > 1 else None
        players.append(p)
    return players, dict(notes)


def zscores(players, cfg):
    """
    Twee passes: eerst een pool op basis van speelminuten, dan de pool herbepalen
    op basis van de gevonden waarde. Zo bepalen de spelers die echt gedraft worden
    de gemiddeldes, niet de hele lijst.
    """
    pool_size, weights = cfg["z_pool"], cfg["categories"]
    eligible = [p for p in players if p["GP"] >= cfg["min_gp"]]
    if len(eligible) < pool_size:
        pool_size = len(eligible)

    rank_key = lambda p: -(p["MPG"] * p["GP"])
    for _ in range(2):
        pool = sorted(eligible, key=rank_key)[:pool_size]
        fg_avg = sum(p["FGM"] for p in pool) / max(sum(p["FGA"] for p in pool), 1e-9)
        ft_avg = sum(p["FTM"] for p in pool) / max(sum(p["FTA"] for p in pool), 1e-9)

        for p in eligible:
            p["FG_pct"] = p["FGM"] / p["FGA"] if p["FGA"] else 0.0
            p["FT_pct"] = p["FTM"] / p["FTA"] if p["FTA"] else 0.0
            p["FG"] = (p["FG_pct"] - fg_avg) * p["FGA"]
            p["FT"] = (p["FT_pct"] - ft_avg) * p["FTA"]

        stats = {}
        for c in CATS:
            vals = [p[c] for p in pool]
            mu = statistics.fmean(vals)
            sd = statistics.pstdev(vals) or 1e-9
            stats[c] = (mu, sd)

        for p in eligible:
            total = 0.0
            for c in CATS:
                mu, sd = stats[c]
                z = (p[c] - mu) / sd
                if c in NEGATIVE:
                    z = -z
                p["z_" + c] = z
                total += weights.get(c, 0) * z
            p["z_total"] = total
        rank_key = lambda p: -p["z_total"]

    for p in players:
        if "z_total" not in p:
            p["z_total"] = None
    return eligible, {"fg_avg": fg_avg, "ft_avg": ft_avg, "pool": pool_size}


def auction_values(eligible, cfg):
    """
    Totale pot is teams * budget. Elke gedrafte speler kost minstens 1 dollar, dus
    alleen het restant is vrij te verdelen over het surplus boven replacement
    level. Replacement is de eerste speler die net buiten de draft valt.
    """
    n_drafted = cfg["teams"] * cfg["roster_spots"]
    pot = cfg["teams"] * cfg["budget"]
    ranked = sorted(eligible, key=lambda p: -p["z_total"])
    n_drafted = min(n_drafted, len(ranked))
    z_repl = ranked[n_drafted - 1]["z_total"] if n_drafted else 0.0

    surplus = [max(p["z_total"] - z_repl, 0.0) for p in ranked[:n_drafted]]
    total_surplus = sum(surplus) or 1e-9
    free = pot - n_drafted

    for i, p in enumerate(ranked):
        s = max(p["z_total"] - z_repl, 0.0)
        raw = 1 + s * free / total_surplus
        # Onder replacement level is een speler in een auction niets waard boven
        # het minimumbod; daar staat de waarde op 1 zolang hij nog draftbaar is.
        p["value"] = round(raw if i < n_drafted else max(0.0, raw), 1)
    return ranked, {"z_replacement": z_repl, "pot": pot, "drafted": n_drafted}


def risk_flags(ranked):
    """
    Met een enkele bron bestaat er geen spreiding tussen bronnen. Dan is dit een
    proxy op basis van geprojecteerde wedstrijden en blessurestatus, geen
    onzekerheidsinterval. Zodra er twee of meer bronnen zijn, wordt z_sd gevuld.
    """
    for p in ranked:
        sd_parts = [p.get(k + "_sd") for k in ("PTS", "REB", "AST", "MPG")]
        sd_parts = [s for s in sd_parts if s is not None]
        p["source_spread"] = round(statistics.fmean(sd_parts), 2) if sd_parts else None
        gp_risk = max(0.0, (72 - p["GP"]) / 72.0)
        inj = str(p.get("inj", "")).upper()
        inj_risk = {"OUT": 0.6, "DAY_TO_DAY": 0.15}.get(inj, 0.0)
        p["risk"] = round(min(1.0, gp_risk + inj_risk), 2)
        p["risk_basis"] = "bronspreiding" if p["source_spread"] is not None else "GP+blessure"


def write_outputs(ranked, cfg, meta):
    os.makedirs(OUT, exist_ok=True)

    block = os.path.join(OUT, "paste_block.csv")
    with open(block, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["RNK", "NAME", "POS", "TEAM", "PTS", "3P", "REB", "AST",
                    "STL", "BLK", "FG%", "FGA", "FT%", "FTA", "$ waarde", "ESPN $", "ADP"])
        for i, p in enumerate(ranked, 1):
            w.writerow([i, p["name"], p["pos"], p["team"],
                        round(p["PTS"], 3), round(p["TPM"], 3), round(p["REB"], 3),
                        round(p["AST"], 3), round(p["STL"], 3), round(p["BLK"], 3),
                        round(p["FG_pct"], 4), round(p["FGA"], 3),
                        round(p["FT_pct"], 4), round(p["FTA"], 3),
                        p["value"], p["market_value"], p["adp"]])

    payload = {
        "generated_for": "LoW 12-team H2H 8-cat auction",
        "config": {k: v for k, v in cfg.items() if not k.startswith("_")},
        "meta": meta,
        "players": [{
            "id": str(p["player_id"]), "name": p["name"], "team": p["team"],
            "pos": p["pos"], "inj": p["inj"],
            "value": p["value"], "market_value": p["market_value"], "adp": p["adp"],
            "z_total": round(p["z_total"], 3),
            "z": {c: round(p["z_" + c], 3) for c in CATS},
            "pg": {k: round(p[k], 3) for k in
                   ("GP", "MPG", "PTS", "TPM", "REB", "AST", "STL", "BLK", "TO",
                    "FGM", "FGA", "FTM", "FTA")},
            "fg_pct": round(p["FG_pct"], 4), "ft_pct": round(p["FT_pct"], 4),
            "last": p.get("last"),
            "risk": p["risk"], "risk_basis": p["risk_basis"],
            "sources": p["sources"],
        } for p in ranked],
    }
    with open(os.path.join(OUT, "values.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)

    lines = [f"{'#':>3}  {'speler':<26}{'pos':<10}{'tm':<5}{'$':>6}{'ESPN$':>7}"
             f"{'z':>7}{'risk':>6}   pts/3p/reb/ast/stl/blk"]
    for i, p in enumerate(ranked[:60], 1):
        lines.append(
            f"{i:>3}  {p['name'][:25]:<26}{p['pos'][:9]:<10}{p['team']:<5}"
            f"{p['value']:>6.0f}{p['market_value']:>7.0f}{p['z_total']:>7.2f}"
            f"{p['risk']:>6.2f}   "
            f"{p['PTS']:.1f}/{p['TPM']:.1f}/{p['REB']:.1f}/{p['AST']:.1f}/"
            f"{p['STL']:.1f}/{p['BLK']:.1f}")
    text = "\n".join(lines)
    with open(os.path.join(OUT, "top.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return text, block


def main():
    cfg = load_config()
    per_source = load_sources()
    players, notes = merge(per_source, cfg)
    eligible, zmeta = zscores(players, cfg)
    ranked, ameta = auction_values(eligible, cfg)
    risk_flags(ranked)
    meta = {"sources": sorted(per_source), "attempts": notes, **zmeta, **ameta}
    text, block = write_outputs(ranked, cfg, meta)

    print(text)
    print()
    print(f"bronnen        : {', '.join(sorted(per_source))}")
    print(f"spelers        : {len(players)} ingelezen, {len(eligible)} draftbaar "
          f"(min {cfg['min_gp']} wedstrijden), {zmeta['pool']} in de Z-pool")
    print(f"pool-gemiddelde: FG {zmeta['fg_avg']:.3f}  FT {zmeta['ft_avg']:.3f}")
    print(f"replacement    : z = {ameta['z_replacement']:.2f} "
          f"(speler {ameta['drafted']})")
    print(f"attempts       : {notes}")
    n_last = sum(1 for p in ranked if p.get("last"))
    print(f"vorig seizoen  : {n_last} van {len(ranked)} draftbare spelers "
          "(de rest is rookie, of de CSV heeft geen LY_-kolommen)")
    if len(per_source) == 1:
        print("LET OP: een bron, dus geen spreiding tussen bronnen. De risicokolom "
              "is een proxy op basis van geprojecteerde wedstrijden en blessurestatus.")
    print(f"geschreven naar {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
