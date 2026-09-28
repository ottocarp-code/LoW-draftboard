"""
Persistent draft state in SQLite (F-45, F-47) plus the player pool from
output/values.json.

The server is the single source of truth (F-44). Every mutation runs under one
lock and one transaction and bumps `rev`, so clients re-render only when the
state really changed. Each pick stores `turn_before`, the turn index at the
moment it was made; undo restores exactly that value instead of stepping back,
which stays correct across skips, manual turns and full teams.
"""

import json
import os
import sqlite3
import threading
import time
from datetime import datetime

import draft
from parser import Name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_VALUES = os.path.join(ROOT, "output", "values.json")
DEFAULT_DB = os.path.join(ROOT, "data", "draft.db")

# The 2025 teams (data/draft_history.csv) in display order; `me` defaults to Notto.
DEFAULT_TEAMS = ["RoRo", "RJ", "Gillese", "sexylexy", "Ceun", "Champximmissioner",
                 "Lode", "Notto", "stijn", "Miele", "elianus", "Dave"]
DEFAULT_ME = "Notto"

SCHEMA = """
CREATE TABLE IF NOT EXISTS picks(
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,
  player_id   TEXT    NOT NULL UNIQUE,
  name        TEXT    NOT NULL,
  team        TEXT    NOT NULL,
  price       INTEGER NOT NULL,
  source      TEXT    NOT NULL DEFAULT 'typed',
  ts          REAL    NOT NULL,
  turn_before INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""

# ---------------------------------------------------------------- player pool


class Pool:
    """values.json, reloaded when the file changes so a pipeline run needs no restart."""

    def __init__(self, path):
        self.path = path
        self._mtime = None
        self.players, self.by_id, self.keys = [], {}, {}
        self.config, self.meta, self.error = {}, {}, None
        self.rev = 0
        self.refresh()

    def refresh(self):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            if self._mtime is not None or self.error is None:
                self._set_missing()
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                payload = json.load(f)
            self._load(payload)
            self.error = None
        except (OSError, ValueError, KeyError, TypeError) as e:
            self._set_missing(f"{self.path} could not be read ({e}). Run the pipeline again: "
                              "py tool\\build_values.py")
        self._mtime = mtime
        self.rev += 1

    def _set_missing(self, msg=None):
        self.players, self.by_id, self.keys = [], {}, {}
        self.config, self.meta = {}, {}
        self.error = msg or (f"{os.path.normpath(self.path)} is missing. Run the pipeline first: "
                             "py tool\\fetch_espn.py, then py tool\\build_values.py.")
        self._mtime = None
        self.rev += 1

    def _load(self, payload):
        cfg = payload.get("config") or {}
        for k in ("teams", "budget", "roster_spots"):
            if not isinstance(cfg.get(k), int):
                raise KeyError(f"config.{k}")
        players = []
        for raw in payload.get("players") or []:
            p = dict(raw)
            p["id"] = str(p["id"])
            p["adp"] = p.get("adp") or 0
            players.append(p)
        # ESPN rank (F-16, F-18): values.json has no ESPN rank field, so it is
        # derived from ADP ascending, no ADP (0) last, ties broken by -z_total.
        by_espn = sorted(players, key=lambda p: (p["adp"] <= 0, p["adp"],
                                                 -(p.get("z_total") or 0), p["name"]))
        for i, p in enumerate(by_espn, 1):
            p["espn_rank"] = i
        by_value = sorted(players, key=lambda p: (-(p.get("value") or 0),
                                                  -(p.get("z_total") or 0), p["name"]))
        for i, p in enumerate(by_value, 1):
            p["value_rank"] = i
        self.players = by_espn
        self.by_id = {p["id"]: p for p in players}
        self.keys = {p["id"]: Name(p["name"]) for p in players}
        self.config = cfg
        self.meta = {"generated_for": payload.get("generated_for", ""),
                     "sources": (payload.get("meta") or {}).get("sources", [])}

    def league(self):
        """League parameters. Only when values.json is missing do fallbacks apply."""
        if self.error:
            return {"teams": len(DEFAULT_TEAMS), "budget": 200, "roster_spots": 13}
        return {k: self.config[k] for k in ("teams", "budget", "roster_spots")}

# ---------------------------------------------------------------- store


class Store:
    def __init__(self, db_path=None, values_path=None):
        self.db_path = db_path or os.environ.get("LOW_DB", DEFAULT_DB)
        self.pool = Pool(values_path or os.environ.get("LOW_VALUES", DEFAULT_VALUES))
        self.backup_dir = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "backups")
        self.lock = threading.RLock()
        d = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(d, exist_ok=True)
        self.con = sqlite3.connect(self.db_path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)
        cols = {r["name"] for r in self.con.execute("PRAGMA table_info(picks)")}
        if "turn_before" not in cols:     # a draft.db from the legacy app
            self.con.execute("ALTER TABLE picks ADD COLUMN turn_before INTEGER NOT NULL DEFAULT 0")
        self._seed()
        self.con.commit()

    # ---------- settings ----------
    def _get(self, k, default=None):
        row = self.con.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
        return json.loads(row["v"]) if row else default

    def _put(self, k, v):
        self.con.execute("INSERT INTO settings(k,v) VALUES(?,?) "
                         "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))

    def _bump(self):
        self._put("rev", int(self._get("rev", 0)) + 1)

    def _seed(self):
        n = self.pool.league()["teams"]
        teams = self._get("teams")
        if not teams:
            teams = (DEFAULT_TEAMS + [f"Team {i}" for i in range(len(DEFAULT_TEAMS) + 1, n + 1)])[:n]
            self._put("teams", teams)
        elif len(teams) < n:          # the league grew (it played with 14 teams until 2021)
            teams = teams + [f"Team {i}" for i in range(len(teams) + 1, n + 1)]
            self._put("teams", teams)
        if self._get("me") not in teams:
            self._put("me", DEFAULT_ME if DEFAULT_ME in teams else teams[0])
        order = self._get("nom_order") or []
        if sorted(order) != sorted(teams):
            self._put("nom_order", [t for t in order if t in teams] +
                      [t for t in teams if t not in order])
        if self._get("turn_idx") is None:
            self._put("turn_idx", 0)
        if self._get("rev") is None:
            self._put("rev", 1)

    @property
    def teams(self):
        return self._get("teams", [])

    @property
    def me(self):
        return self._get("me")

    @property
    def nom_order(self):
        return self._get("nom_order", [])

    @property
    def turn_idx(self):
        return int(self._get("turn_idx", 0))

    # ---------- reads ----------
    def picks(self):
        return [dict(r) for r in self.con.execute("SELECT * FROM picks ORDER BY seq")]

    def available(self):
        """(player, Name) pairs that are still undrafted, for the parser (F-34)."""
        self.pool.refresh()
        taken = {r["player_id"] for r in self.con.execute("SELECT player_id FROM picks")}
        return [(p, self.pool.keys[p["id"]]) for p in self.pool.players if p["id"] not in taken]

    def state(self):
        with self.lock:
            self.pool.refresh()
            lg = self.pool.league()
            teams, picks = self.teams, self.picks()
            order, idx = self.nom_order, self.turn_idx
            lines = draft.summarize(teams, picks, lg["budget"], lg["roster_spots"])
            ci = draft.resolve_turn(idx, order, draft.counts_of(teams, picks), lg["roster_spots"])
            clock = order[ci] if ci is not None else None
            rosters = {t: [] for t in teams}
            for p in picks:
                rosters.setdefault(p["team"], []).append(
                    {"seq": p["seq"], "player_id": p["player_id"], "name": p["name"],
                     "price": p["price"]})
            return {
                "rev": int(self._get("rev", 0)),
                "players_rev": self.pool.rev,
                "error": self.pool.error,
                "league": lg,
                "teams": [{"name": t, **lines[t], "is_me": t == self.me,
                           "on_clock": t == clock} for t in teams],
                "me": self.me,
                "nom_order": order,
                "turn_idx": idx,
                "on_the_clock": clock,
                "picks": picks,
                "rosters": rosters,
                "available_count": len(self.pool.by_id.keys() - {p["player_id"] for p in picks}),
            }

    # ---------- mutations ----------
    def add_pick(self, player_id, team, price, source="typed"):
        with self.lock:
            self.pool.refresh()
            lg = self.pool.league()
            teams, picks = self.teams, self.picks()
            player = self.pool.by_id.get(str(player_id))
            price = draft.validate_pick(player, team, price, teams, picks,
                                        lg["budget"], lg["roster_spots"])
            before = draft.counts_of(teams, picks)
            after = dict(before)
            after[team] = after.get(team, 0) + 1
            idx = self.turn_idx
            new_idx = draft.advance_turn(idx, self.nom_order, before, after, lg["roster_spots"])
            with self.con:
                self.con.execute(
                    "INSERT INTO picks(player_id,name,team,price,source,ts,turn_before) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (player["id"], player["name"], team, price, str(source or "typed")[:16],
                     time.time(), idx))
                self._put("turn_idx", new_idx)
                self._bump()
            return player, price

    def undo_preview(self, count=None, to_seq=None):
        """The picks that an undo would remove, newest first. Raises DraftError if invalid."""
        picks = self.picks()
        if not picks:
            raise draft.DraftError("Nothing to undo: there are no picks yet.", 400)
        if to_seq is not None:
            seqs = [p["seq"] for p in picks]
            if int(to_seq) not in seqs:
                raise draft.DraftError(f"Pick #{to_seq} does not exist.", 404)
            removed = [p for p in picks if p["seq"] > int(to_seq)]
            if not removed:
                raise draft.DraftError("That is already the latest pick; nothing to remove.", 400)
        else:
            count = 1 if count is None else int(count)
            if count < 1:
                raise draft.DraftError("Undo needs at least 1 pick.", 400)
            if count > len(picks):
                raise draft.DraftError(
                    f"Cannot undo {count} picks: there are only {len(picks)}.", 400)
            removed = picks[-count:]
        return list(reversed(removed))

    def undo(self, count=None, to_seq=None):
        with self.lock:
            removed = self.undo_preview(count, to_seq)
            oldest = removed[-1]
            with self.con:
                self.con.execute("DELETE FROM picks WHERE seq >= ?", (oldest["seq"],))
                self._put("turn_idx", int(oldest["turn_before"]))
                self._bump()
            return removed

    def set_turn(self, team):
        with self.lock:
            order = self.nom_order
            if team not in order:
                raise draft.DraftError(f'Unknown team "{team}".', 404)
            lg = self.pool.league()
            if draft.counts_of(self.teams, self.picks()).get(team, 0) >= lg["roster_spots"]:
                raise draft.DraftError(f"{team} is full and cannot nominate.", 409)
            with self.con:
                self._put("turn_idx", order.index(team))
                self._bump()
            return team

    def skip(self, back=False):
        """Moves the turn to the next team, or with back=True to the previous one."""
        with self.lock:
            lg = self.pool.league()
            counts = draft.counts_of(self.teams, self.picks())
            if back:
                new_idx = draft.retreat_turn(self.turn_idx, self.nom_order, counts,
                                             lg["roster_spots"])
            else:
                new_idx = draft.advance_turn(self.turn_idx, self.nom_order, counts, counts,
                                             lg["roster_spots"])
            with self.con:
                self._put("turn_idx", new_idx)
                self._bump()
            order = self.nom_order
            ci = draft.resolve_turn(new_idx, order, counts, lg["roster_spots"])
            return order[ci] if ci is not None else None

    def update_settings(self, teams=None, nom_order=None, me=None):
        """
        teams: the full list in display order; position i renames old teams[i]
        (picks, nomination order and `me` follow the rename).
        nom_order: a permutation of the (new) team names. me: one of the teams.
        """
        with self.lock:
            old = self.teams
            new = old
            if teams is not None:
                if not isinstance(teams, list) or len(teams) != len(old):
                    raise draft.DraftError(f"Exactly {len(old)} team names are required.", 400)
                new = [str(t).strip() for t in teams]
                if any(not t or len(t) > 40 for t in new):
                    raise draft.DraftError("Team names must be 1 to 40 characters.", 400)
                if len({t.lower() for t in new}) != len(new):
                    raise draft.DraftError("Team names must be unique.", 400)
            rename = dict(zip(old, new))
            order = [rename.get(t, t) for t in self.nom_order]
            if nom_order is not None:
                if not isinstance(nom_order, list) or sorted(map(str, nom_order)) != sorted(new):
                    raise draft.DraftError("The nomination order must list every team once.", 400)
                order = [str(t) for t in nom_order]
            cur_me = rename.get(self.me, self.me)
            if me is not None:
                if me not in new:
                    raise draft.DraftError(f'"{me}" is not one of the teams.', 400)
                cur_me = me
            # turn_idx and every turn_before are indexes into the order; keep them
            # pointing at the same (resolved) team when the order changes.
            old_order, picks = self.nom_order, self.picks()
            spots = self.pool.league()["roster_spots"]

            def remap(idx, done):
                if not old_order:
                    return idx
                ci = draft.resolve_turn(idx, old_order, draft.counts_of(old, done), spots)
                team = old_order[ci if ci is not None else idx % len(old_order)]
                return order.index(rename.get(team, team))

            with self.con:
                for i, p in enumerate(picks):
                    tb = remap(int(p["turn_before"]), picks[:i])
                    self.con.execute("UPDATE picks SET team=?, turn_before=? WHERE seq=?",
                                     (rename.get(p["team"], p["team"]), tb, p["seq"]))
                self._put("turn_idx", remap(self.turn_idx, picks))
                self._put("teams", new)
                self._put("nom_order", order)
                self._put("me", cur_me)
                self._bump()

    def export(self):
        with self.lock:
            s = self.state()
            return {"exported_at": datetime.now().isoformat(timespec="seconds"),
                    "league": s["league"], "meta": self.pool.meta, "teams": s["teams"],
                    "me": s["me"], "nom_order": s["nom_order"], "turn_idx": s["turn_idx"],
                    "on_the_clock": s["on_the_clock"], "picks": s["picks"],
                    "rosters": s["rosters"]}

    def reset(self):
        """New draft: back up the full export first, then clear picks and the turn."""
        with self.lock:
            data = self.export()
            os.makedirs(self.backup_dir, exist_ok=True)
            path = os.path.join(self.backup_dir,
                                f"draft-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, ensure_ascii=False)
            with self.con:
                self.con.execute("DELETE FROM picks")
                self._put("turn_idx", 0)
                self._bump()
            return path, len(data["picks"])

    def close(self):
        self.con.close()
