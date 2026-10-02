"""The last-season statline: fetch_espn.projection_row (LY_ columns) and the `last`
block that build_values writes. Last season is display only, never in the valuation."""

import csv
import json

import pytest

import build_values
import fetch_espn

PROJ = {"0": 2000.0, "1": 60.0, "2": 100.0, "3": 500.0, "6": 380.0, "11": 180.0,
        "13": 700.0, "14": 1300.0, "15": 450.0, "16": 500.0, "17": 150.0, "18": 400.0,
        "28": 34.0, "42": 76.0}
LAST = {"0": 2117.0, "1": 54.0, "2": 95.0, "3": 435.0, "6": 306.0, "11": 150.0,
        "13": 760.0, "14": 1374.0, "15": 461.0, "16": 514.0, "17": 136.0, "18": 362.0,
        "28": 33.5, "42": 68.0}


def entry(last=True):
    stats = [{"id": f"10{fetch_espn.SEASON}", "statSourceId": 1, "statSplitTypeId": 0,
              "stats": PROJ},
             {"id": f"01{fetch_espn.SEASON}", "statSourceId": 0, "statSplitTypeId": 1,
              "stats": {"0": 999.0, "42": 1.0}}]       # a split, not the season totals
    if last:
        stats.append({"id": f"00{fetch_espn.SEASON - 1}", "statSourceId": 0,
                      "statSplitTypeId": 0, "stats": LAST})
    return {"player": {"id": 4278073, "fullName": "Shai Gilgeous-Alexander", "proTeamId": 25,
                       "eligibleSlots": [0, 1], "injuryStatus": "ACTIVE", "stats": stats,
                       "ownership": {"averageDraftPosition": 1.4}}}


def test_projection_row_reads_last_season_statline():
    r = fetch_espn.projection_row(entry())
    assert r["PTS"] == 2000.0 and r["GP"] == 76.0           # the projection is unchanged
    assert r["LY_PTS"] == 2117.0 and r["LY_GP"] == 68.0 and r["LY_TPM"] == 136.0
    assert set(fetch_espn.COLUMNS) >= {"LY_" + k for k in fetch_espn.LY_STATS}
    assert set(r) == set(fetch_espn.COLUMNS)


def test_projection_row_without_last_season_leaves_ly_empty():
    r = fetch_espn.projection_row(entry(last=False))
    assert r["PTS"] == 2000.0
    assert all(r["LY_" + k] == "" for k in fetch_espn.LY_STATS)


def row(**extra):
    base = {"source": "espn", "player_id": "1", "name": "Some Player", "team": "OKC",
            "pos": "PG", "GP": "76", "MPG": "34", "PTS": "2000", "REB": "380", "AST": "500",
            "STL": "100", "BLK": "60", "TO": "180", "FGM": "700", "FGA": "1300",
            "FTM": "450", "FTA": "500", "TPM": "150", "TPA": "400"}
    base.update(extra)
    return base


def test_last_season_per_game():
    ly = {"LY_" + k: str(LAST[fetch_espn.STAT[k]]) for k in fetch_espn.LY_STATS}
    last = build_values.last_season(row(**ly))
    assert last["GP"] == 68 and last["PTS"] == pytest.approx(31.132, abs=1e-3)
    assert last["TPM"] == pytest.approx(2.0, abs=1e-3)
    assert last["fg_pct"] == pytest.approx(760 / 1374, abs=1e-4)
    assert last["ft_pct"] == pytest.approx(461 / 514, abs=1e-4)


def test_last_season_absent_or_zero_attempts():
    assert build_values.last_season(row()) is None                  # old CSV, no LY columns
    assert build_values.last_season(row(LY_GP="", LY_PTS="")) is None    # rookie
    assert build_values.last_season(row(LY_GP="0")) is None
    last = build_values.last_season(row(LY_GP="3", LY_PTS="6", LY_FGM="0", LY_FGA="0",
                                        LY_FTM="0", LY_FTA=""))
    assert last["PTS"] == 2.0 and last["fg_pct"] is None and last["ft_pct"] is None


def run_pipeline(tmp_path, monkeypatch, rows):
    data, out = tmp_path / "data", tmp_path / "output"
    data.mkdir(parents=True)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(data / "espn.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    monkeypatch.setattr(build_values, "DATA", str(data))
    monkeypatch.setattr(build_values, "OUT", str(out))
    cfg = build_values.load_config()
    cfg["z_pool"], cfg["min_gp"], cfg["roster_spots"] = 5, 1, 1
    players, notes = build_values.merge(build_values.load_sources(), cfg)
    eligible, zmeta = build_values.zscores(players, cfg)
    ranked, ameta = build_values.auction_values(eligible, cfg)
    build_values.risk_flags(ranked)
    build_values.write_outputs(ranked, cfg, {**zmeta, **ameta})
    return {p["name"]: p for p in json.load(open(out / "values.json", encoding="utf-8"))["players"]}


def test_values_json_last_block_and_valuation_unchanged(tmp_path, monkeypatch):
    ly = {"LY_" + k: str(LAST[fetch_espn.STAT[k]]) for k in fetch_espn.LY_STATS}
    rows = [row(name=f"Player {i}", player_id=str(i), PTS=str(1500 + 100 * i))
            for i in range(6)]
    with_ly = [dict(r, **(ly if i % 2 else {"LY_GP": ""})) for i, r in enumerate(rows)]
    new = run_pipeline(tmp_path / "a", monkeypatch, with_ly)
    old = run_pipeline(tmp_path / "b", monkeypatch, rows)          # CSV without LY columns
    assert new["Player 1"]["last"]["PTS"] == pytest.approx(31.132, abs=1e-3)
    assert new["Player 0"]["last"] is None
    assert all(p["last"] is None for p in old.values())
    for name, p in old.items():                                     # last season never feeds values
        q = new[name]
        assert (q["value"], q["z_total"], q["z"], q["pg"]) == (p["value"], p["z_total"], p["z"], p["pg"])
