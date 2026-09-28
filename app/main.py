"""
LoW Draftboard: API and static frontend (FastAPI).

    py -m uvicorn main:app --app-dir app --port 8000        (or run.bat)

Environment:
    LOW_VALUES     path to values.json   (default output/values.json)
    LOW_DB         path to the SQLite db (default data/draft.db); backups go to
                   <db folder>/backups
    LOW_HEADSHOTS  headshot cache folder (default data/headshots)

Routes (FRD section 8, plus multi-undo and reset):
    GET  /, /board, /teams      the single-page app (both views)
    GET  /api/players           player pool with values, ESPN rank, headshot id
    GET  /api/state             budgets, max bids, picks, rosters, turn, rev
    POST /api/command           {text, source}  free text through the parser
    POST /api/pick              {player_id, team, price, source}
    POST /api/undo              {} | {count} | {to_seq}
    POST /api/turn              {team} to set, {} or {step: 1} to skip, {step: -1} to go back
    POST /api/settings          {teams?, nom_order?, me?, aliases?}  aliases: {team: [nickname]}
    POST /api/voice/heartbeat   {model, muted?}  from voice/listen.py; returns {muted}
    POST /api/voice/mute        {muted}          the header mic toggle
    POST /api/voice/resolve     {id, message}    a click settled the pending voice event
    POST /api/reset             {confirm: "NEW DRAFT"}  backup first, then clear picks
    GET  /api/export            the full state as JSON
    GET  /headshots/{id}.png    local headshot cache, 404 when missing
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fastapi import Body, FastAPI  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import parser as cmdparser  # noqa: E402
from draft import DraftError  # noqa: E402
from store import ROOT, Store  # noqa: E402

STATIC = os.path.join(HERE, "static")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
PUBLIC_FIELDS = ("id", "name", "team", "pos", "inj", "value", "market_value", "adp",
                 "z_total", "z", "pg", "fg_pct", "ft_pct", "risk", "risk_basis", "sources",
                 "espn_rank", "value_rank")


def public(p):
    return {k: p[k] for k in PUBLIC_FIELDS if k in p}


def fail(message, status=400, **extra):
    return JSONResponse({"ok": False, "kind": "error", "message": message, **extra},
                        status_code=status)


def create_app(db_path=None, values_path=None, headshots=None):
    store = Store(db_path, values_path)
    heads = headshots or os.environ.get("LOW_HEADSHOTS", os.path.join(ROOT, "data", "headshots"))
    app = FastAPI(title="LoW Draftboard")
    app.state.store = store

    def ok(kind, message, **extra):
        return {"ok": True, "kind": kind, "message": message, **extra, "state": store.state()}

    def do_pick(player_id, team, price, source):
        try:
            player, price = store.add_pick(player_id, team, price, source)
        except DraftError as e:
            return fail(e.message, e.status)
        return ok("pick", f'{player["name"]} to {team} for ${price}.',
                  player=public(player), team=team, price=price)

    def do_undo(count=None, to_seq=None):
        try:
            removed = store.undo(count, to_seq)
        except DraftError as e:
            return fail(e.message, e.status)
        if len(removed) == 1:
            r = removed[0]
            msg = f'Undone: {r["name"]} ({r["team"]}, ${r["price"]}).'
        else:
            msg = f"Undone {len(removed)} picks."
        return ok("undo", msg, removed=removed)

    # ---------------------------------------------------------------- API
    @app.get("/api/players")
    def players():
        with store.lock:
            store.pool.refresh()
            return {"rev": store.pool.rev, "error": store.pool.error,
                    "meta": store.pool.meta, "league": store.pool.league(),
                    "players": [public(p) for p in store.pool.players]}

    @app.get("/api/state")
    def state():
        return store.state()

    @app.post("/api/command")
    def command(payload: dict = Body(...)):
        text = str(payload.get("text") or "")[:300]
        source = str(payload.get("source") or "typed")[:16]
        if source != "voice":
            return run_command(text, source)
        with store.lock:
            if store.voice_state()["muted"]:
                # The listener honours mute itself; this guards a stale listener.
                return {"ok": False, "kind": "muted", "message": "Voice is muted."}
            if cmdparser.parse_command(text)["kind"] == "undo":
                # Undo of picks is typing or clicking only, never by voice (plan boundary):
                # a misheard "undo" must not remove a pick.
                res = fail("Undo picks by typing.", 400)
            else:
                res = run_command(text, source)
            body, status = res, 200
            if isinstance(res, JSONResponse):
                body, status = json.loads(res.body), res.status_code
            body = {k: v for k, v in body.items() if k != "state"}
            if body["kind"] in ("search", "empty"):
                body.update(ok=False, kind="error",
                            message=f'Heard "{text}", but that is not a command.')
                status = 400
            ev = store.voice_event(payload.get("heard") or text, body)
            out = {**body, "voice_event": ev}
            if isinstance(res, dict) and "state" in res:
                out["state"] = store.state()          # includes the new voice event
            return JSONResponse(out, status_code=status)

    def run_command(text, source):
        with store.lock:
            res = cmdparser.interpret(text, store.available(), store.teams, store.me,
                                      store.pool.league()["budget"], store.aliases)
            kind = res["kind"]

            if kind == "pick":
                return do_pick(res["player"]["id"], res["team"], res["amount"], source)

            if kind == "need_amount":
                return {"ok": False, "kind": "need_amount", "player": public(res["player"]),
                        "team": res["team"],
                        "message": f'Amount missing for {res["player"]["name"]} to {res["team"]}.'}

            if kind == "ambiguous":
                return {"ok": False, "kind": "ambiguous", "team": res["team"],
                        "amount": res["amount"], "query": res["query"],
                        "candidates": [{"score": c["score"], "player": public(c["player"])}
                                       for c in res["candidates"]],
                        "message": f'Which player do you mean by "{res["query"]}"?'}

            if kind == "undo":
                if res["count"] == 1:
                    return do_undo(1)
                try:
                    removed = store.undo_preview(count=res["count"])
                except DraftError as e:
                    return fail(e.message, e.status)
                return {"ok": False, "kind": "confirm_undo", "count": res["count"],
                        "picks": removed,
                        "message": f'Undo the last {res["count"]} picks?'}

            if kind in ("skip", "back"):
                team = store.skip(back=kind == "back")
                return ok("turn", f"Turn to {team}." if team else "Every roster is full.", team=team)

            if kind == "turn":
                try:
                    store.set_turn(res["team"])
                except DraftError as e:
                    return fail(e.message, e.status)
                return ok("turn", f'Turn set to {res["team"]}.', team=res["team"])

            if kind == "error":
                if store.pool.error:
                    return fail(store.pool.error, 503)
                extra = {}
                if res.get("candidates"):
                    extra["candidates"] = [{"score": c["score"], "player": public(c["player"])}
                                           for c in res["candidates"]]
                if res.get("teams"):
                    extra["teams"] = res["teams"]
                return fail(res["message"], 400, **extra)

            if kind == "empty":
                return {"ok": False, "kind": "empty", "message": ""}
            return {"ok": False, "kind": "search", "text": res.get("text", ""), "message": ""}

    @app.post("/api/pick")
    def pick(payload: dict = Body(...)):
        for k in ("player_id", "team", "price"):
            if payload.get(k) in (None, ""):
                return fail(f"{k} is missing.", 400)
        return do_pick(str(payload["player_id"]), str(payload["team"]), payload["price"],
                       str(payload.get("source") or "click")[:16])

    @app.post("/api/undo")
    def undo(payload: dict = Body(default={})):
        payload = payload or {}
        try:
            if payload.get("to_seq") is not None:
                return do_undo(to_seq=int(payload["to_seq"]))
            return do_undo(count=int(payload.get("count", 1)))
        except (TypeError, ValueError):
            return fail("count and to_seq must be whole numbers.", 400)

    @app.post("/api/undo/preview")
    def undo_preview(payload: dict = Body(default={})):
        payload = payload or {}
        try:
            if payload.get("to_seq") is not None:
                removed = store.undo_preview(to_seq=int(payload["to_seq"]))
            else:
                removed = store.undo_preview(count=int(payload.get("count", 1)))
        except DraftError as e:
            return fail(e.message, e.status)
        except (TypeError, ValueError):
            return fail("count and to_seq must be whole numbers.", 400)
        return {"ok": True, "picks": removed}

    @app.post("/api/turn")
    def turn(payload: dict = Body(default={})):
        payload = payload or {}
        if payload.get("team"):
            team, _ = cmdparser.match_team(str(payload["team"]), store.teams, store.me,
                                           store.aliases)
            if payload["team"] in store.teams:
                team = payload["team"]
            if not team:
                return fail(f'Unknown team "{payload["team"]}".', 404)
            try:
                store.set_turn(team)
            except DraftError as e:
                return fail(e.message, e.status)
            return ok("turn", f"Turn set to {team}.", team=team)
        team = store.skip(back=str(payload.get("step", 1)) == "-1")
        return ok("turn", f"Turn to {team}." if team else "Every roster is full.", team=team)

    @app.post("/api/settings")
    def settings(payload: dict = Body(...)):
        try:
            store.update_settings(payload.get("teams"), payload.get("nom_order"), payload.get("me"),
                                  payload.get("aliases"))
        except DraftError as e:
            return fail(e.message, e.status)
        return ok("settings", "Settings saved.")

    # ---------------------------------------------------------------- voice
    @app.post("/api/voice/heartbeat")
    def voice_heartbeat(payload: dict = Body(default={})):
        payload = payload or {}
        muted = payload.get("muted")
        muted = store.voice_heartbeat(payload.get("model"),
                                      None if muted is None else bool(muted))
        return {"ok": True, "muted": muted}

    @app.post("/api/voice/mute")
    def voice_mute(payload: dict = Body(...)):
        if not isinstance(payload.get("muted"), bool):
            return fail("muted must be true or false.", 400)
        store.voice_mute(payload["muted"])
        return ok("voice", "Voice muted." if payload["muted"] else "Voice on.")

    @app.post("/api/voice/resolve")
    def voice_resolve(payload: dict = Body(...)):
        try:
            eid = int(payload.get("id"))
        except (TypeError, ValueError):
            return fail("id must be a whole number.", 400)
        if not store.voice_resolve(eid, payload.get("message")):
            return fail("That voice event is already settled or no longer the latest.", 409)
        return ok("voice", "Voice event settled.")

    @app.post("/api/reset")
    def reset(payload: dict = Body(default={})):
        if (payload or {}).get("confirm") != "NEW DRAFT":
            return fail('Reset needs {"confirm": "NEW DRAFT"}.', 400)
        path, n = store.reset()
        return ok("reset", f"New draft started. {n} picks backed up to "
                  f"{os.path.relpath(path, ROOT) if path.startswith(ROOT) else path}.",
                  backup=path)

    @app.get("/api/export")
    def export():
        return JSONResponse(store.export(), headers={
            "Content-Disposition": 'attachment; filename="low-draft-export.json"'})

    # ---------------------------------------------------------------- files
    @app.get("/headshots/{name}")
    def headshot(name: str):
        # Checked on every request, so the cache folder may appear after startup.
        pid = name[:-4] if name.endswith(".png") else None
        if not pid or not _ID.match(pid):
            return Response(status_code=404)
        path = os.path.join(heads, f"{pid}.png")
        if not os.path.isfile(path):
            return Response(status_code=404)
        return FileResponse(path, media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/")
    @app.get("/board")
    @app.get("/teams")
    def index():
        return FileResponse(os.path.join(STATIC, "index.html"),
                            headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
