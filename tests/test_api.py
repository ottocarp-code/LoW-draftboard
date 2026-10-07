import glob
import json
import os

import pytest

import conftest


def cmd(c, text, source="typed"):
    return c.post("/api/command", json={"text": text, "source": source})


def state(c):
    return c.get("/api/state").json()


def pid(c, name):
    return next(p["id"] for p in c.get("/api/players").json()["players"] if p["name"] == name)


# ---------------------------------------------------------------- basics

def test_state_has_twelve_teams_and_league_from_config(client):
    s = state(client)
    assert [t["name"] for t in s["teams"]][:3] == ["RoRo", "RJ", "Gillese"]
    assert len(s["teams"]) == 12 and s["me"] == "Notto"
    assert s["league"] == {"teams": 12, "budget": 200, "roster_spots": 13}
    assert s["on_the_clock"] == "RoRo" and s["error"] is None
    assert s["available_count"] == 201          # 200 fixture players + the easter egg


def test_players_have_derived_espn_rank(client):
    ps = client.get("/api/players").json()["players"]
    assert [p["espn_rank"] for p in ps] == list(range(1, len(ps) + 1))
    with_adp = [p for p in ps if p["adp"]]
    assert [p["adp"] for p in with_adp] == sorted(p["adp"] for p in with_adp)
    assert all(p["adp"] == 0 for p in ps[len(with_adp):])       # no ADP last


def test_players_carry_last_season_and_active_categories(client, tmp_path, make_client):
    body = client.get("/api/players").json()
    # TO has weight 0 in the fixture config, so it is not an active category.
    assert body["categories"] == ["PTS", "TPM", "REB", "AST", "STL", "BLK", "FG", "FT"]
    ps = body["players"]
    assert all("last" in p for p in ps if p["id"] != "otto-carpentier")
    vets = [p for p in ps if p.get("last")]
    rookies = [p for p in ps if "last" in p and p["last"] is None]
    assert vets and rookies
    assert {"GP", "PTS", "TPM", "fg_pct", "ft_pct"} <= set(vets[0]["last"])
    # TO switched on: it shows up as a category, after the others (config order).
    data = json.load(open(conftest.FIXTURE, encoding="utf-8"))
    data["config"]["categories"]["TO"] = 1
    for p in data["players"]:
        p.pop("last", None)                 # an old values.json without `last`
    path = tmp_path / "values_to.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    body = make_client(values=str(path), db=tmp_path / "to.db").get("/api/players").json()
    assert body["categories"][-1] == "TO" and len(body["categories"]) == 9
    assert all("last" not in p for p in body["players"])


def test_views_are_served(client):
    for path in ("/", "/board", "/teams"):
        r = client.get(path)
        assert r.status_code == 200 and "app.js" in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_frontend_has_no_cdn_assets_and_no_innerhtml():
    static = os.path.join(conftest.ROOT, "app", "static")
    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(static, "app.js"), encoding="utf-8").read()
    assert "http" not in html
    assert "innerHTML" not in js and "localStorage" not in js and "sessionStorage" not in js


def test_board_picks_toggle_lives_in_the_url():
    static = os.path.join(conftest.ROOT, "app", "static")
    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    js = open(os.path.join(static, "app.js"), encoding="utf-8").read()
    css = open(os.path.join(static, "app.css"), encoding="utf-8").read()
    assert 'id="picksBtn" class="boardonly"' in html
    assert '"?picks=off"' in js and 'get("picks") === "off"' in js
    assert "body.nopicks:not(.teams) #history{display:none}" in css


# ---------------------------------------------------------------- I/O matrix

def test_pick_stores_and_advances_turn(client):
    r = cmd(client, "derozan to emiel for 13")
    assert r.status_code == 200 and r.json()["ok"]
    s = r.json()["state"]
    p = s["picks"][-1]
    assert (p["name"], p["team"], p["price"], p["source"]) == ("DeMar DeRozan", "Miele", 13, "typed")
    assert p["ts"] > 0 and p["player_id"] and p["turn_before"] == 0
    assert s["on_the_clock"] == "RJ"
    assert s["rev"] > 1


def test_voice_style_pick(client):
    r = cmd(client, "ok banana steph curry to Miele for 55 $", source="voice").json()
    assert r["ok"] and r["player"]["name"] == "Stephen Curry" and r["price"] == 55
    assert r["state"]["picks"][-1]["source"] == "voice"


def test_voice_words(client):
    r = cmd(client, "okay banana curry to miele for fifty five dollars", "voice").json()
    assert r["ok"] and r["player"]["name"] == "Stephen Curry" and r["team"] == "Miele"
    assert r["price"] == 55


@pytest.mark.parametrize("text,price", [("wembanyama to roro for eighty five", 85),
                                        ("wembanyama to roro for one hundred five", 105)])
def test_number_words(client, text, price):
    r = cmd(client, text).json()
    assert r["ok"] and r["price"] == price and r["team"] == "RoRo"


def test_wake_word_mine(client):
    r = cmd(client, "draftbot jokitch mine 40").json()
    assert r["ok"] and r["player"]["name"] == "Nikola Jokic" and r["team"] == "Notto"


def test_ambiguous_then_click(client):
    r = cmd(client, "bridges to rj for 5").json()
    assert r["kind"] == "ambiguous" and r["amount"] == 5 and r["team"] == "RJ"
    assert state(client)["picks"] == []                           # no pick until confirmed
    c = r["candidates"][0]
    assert "score" in c and c["player"]["name"].endswith("Bridges")
    r2 = client.post("/api/pick", json={"player_id": c["player"]["id"], "team": "RJ",
                                        "price": 5, "source": "click"}).json()
    assert r2["ok"] and r2["state"]["picks"][-1]["price"] == 5


def test_no_amount_prompt(client):
    r = cmd(client, "sengun to lode").json()
    assert r["kind"] == "need_amount" and r["team"] == "Lode"
    assert r["player"]["name"] == "Alperen Sengun"
    r2 = client.post("/api/pick", json={"player_id": r["player"]["id"], "team": r["team"],
                                        "price": 21}).json()
    assert r2["ok"] and r2["state"]["picks"][-1]["name"] == "Alperen Sengun"


def test_taken_rejected(client):
    assert cmd(client, "jokic to rj for 50").json()["ok"]
    before = state(client)
    r = client.post("/api/pick", json={"player_id": pid(client, "Nikola Jokic"),
                                       "team": "Dave", "price": 10})
    assert r.status_code == 409 and "already drafted" in r.json()["message"]
    assert state(client)["rev"] == before["rev"]


def test_over_max_bid_rejected(client):
    r = cmd(client, "jokic to rj for 189")
    assert r.status_code == 409 and "max bid" in r.json()["message"]
    assert state(client)["picks"] == []
    assert cmd(client, "jokic to rj for 188").json()["ok"]


def test_full_team_rejected(client):
    ps = client.get("/api/players").json()["players"]
    for p in ps[:13]:
        assert client.post("/api/pick", json={"player_id": p["id"], "team": "Dave",
                                              "price": 1}).status_code == 200
    r = client.post("/api/pick", json={"player_id": ps[13]["id"], "team": "Dave", "price": 1})
    assert r.status_code == 409 and "13" in r.json()["message"]
    assert len(state(client)["picks"]) == 13


def test_unknown_command_parts(client):
    assert cmd(client, "jokic to nobody for 5").status_code == 400
    assert cmd(client, "zzqx to rj for 5").status_code == 400
    assert cmd(client, "bridges").json()["kind"] == "search"


def test_turn_skip_is_skipped_for_full_team_and_never_twice(client):
    ps = client.get("/api/players").json()["players"]
    # Fill RJ (2nd in the nomination order).
    for p in ps[:13]:
        client.post("/api/pick", json={"player_id": p["id"], "team": "RJ", "price": 1})
    cmd(client, "turn roro")
    seen = [state(client)["on_the_clock"]]
    for p in ps[13:16]:
        seen.append(client.post("/api/pick", json={"player_id": p["id"], "team": "Dave",
                                                   "price": 1}).json()["state"]["on_the_clock"])
    assert seen == ["RoRo", "Gillese", "sexylexy", "Ceun"]
    assert "RJ" not in seen
    assert cmd(client, "skip").json()["team"] == "Champximmissioner"
    assert cmd(client, "turn rj").status_code == 409                 # full team cannot nominate


def test_undo_restores_turn_after_pick_and_after_turn_or_skip(client):
    cmd(client, "turn lode")
    cmd(client, "jokic to rj for 30")
    assert state(client)["on_the_clock"] == "Notto"
    cmd(client, "skip")
    cmd(client, "turn dave")
    r = cmd(client, "undo").json()
    assert r["ok"] and r["removed"][0]["name"] == "Nikola Jokic"
    s = r["state"]
    assert s["on_the_clock"] == "Lode" and s["picks"] == []
    assert next(t for t in s["teams"] if t["name"] == "RJ")["remaining"] == 200


def test_undo_empty_history(client):
    r = cmd(client, "undo")
    assert r.status_code == 400 and "Nothing to undo" in r.json()["message"]
    assert client.post("/api/undo", json={}).status_code == 400


def _make_picks(c, n):
    ps = c.get("/api/players").json()["players"]
    teams = [t["name"] for t in state(c)["teams"]]
    snaps = []
    for i in range(n):
        snaps.append(state(c))
        r = c.post("/api/pick", json={"player_id": ps[i]["id"], "team": teams[(i * 5) % 12],
                                      "price": 1 + i % 7})
        assert r.status_code == 200, r.json()
        if i % 9 == 4:
            c.post("/api/turn", json={})                    # a skip between picks
    return snaps


def _core(s):
    return (s["on_the_clock"], s["turn_idx"], [(t["name"], t["remaining"], t["count"], t["max_bid"])
                                                for t in s["teams"]], len(s["picks"]))


def test_undo_several_needs_confirmation_then_restores(client):
    snaps = _make_picks(client, 10)
    r = cmd(client, "undo three").json()
    assert r["kind"] == "confirm_undo" and len(r["picks"]) == 3
    assert r["picks"][0]["seq"] > r["picks"][-1]["seq"]            # newest first
    assert len(state(client)["picks"]) == 10                        # nothing removed yet
    r2 = client.post("/api/undo", json={"count": 3}).json()
    assert r2["ok"] and len(r2["removed"]) == 3
    assert _core(r2["state"]) == _core(snaps[7])


def test_back_to_here(client):
    snaps = _make_picks(client, 46)
    picks = state(client)["picks"]
    target = picks[39]                                               # pick #40 of 46
    prev = client.post("/api/undo/preview", json={"to_seq": target["seq"]}).json()
    assert prev["ok"] and len(prev["picks"]) == 6
    r = client.post("/api/undo", json={"to_seq": target["seq"]}).json()
    assert r["ok"] and len(r["removed"]) == 6
    assert _core(r["state"]) == _core(snaps[40])


def test_undo_more_than_picks(client):
    _make_picks(client, 2)
    r = cmd(client, "undo 3")
    assert r.status_code == 400 and "only 2" in r.json()["message"]
    assert client.post("/api/undo", json={"count": 3}).status_code == 400
    assert len(state(client)["picks"]) == 2


def test_new_draft_reset(client, tmp_path):
    _make_picks(client, 5)
    client.post("/api/settings", json={"me": "Dave"})
    assert client.post("/api/reset", json={}).status_code == 400
    assert client.post("/api/reset", json={"confirm": "new draft"}).status_code == 400
    assert len(state(client)["picks"]) == 5
    r = client.post("/api/reset", json={"confirm": "NEW DRAFT"}).json()
    assert r["ok"]
    s = r["state"]
    assert s["picks"] == [] and s["on_the_clock"] == s["nom_order"][0] and s["me"] == "Dave"
    backups = glob.glob(str(tmp_path / "backups" / "draft-*.json"))
    assert len(backups) == 1
    data = json.load(open(backups[0], encoding="utf-8"))
    assert len(data["picks"]) == 5


def test_missing_values_json(make_client, tmp_path):
    c = make_client(values=str(tmp_path / "nope.json"))
    s = state(c)
    assert s["error"] and "pipeline" in s["error"].lower() and len(s["teams"]) == 12
    assert c.get("/api/players").json()["players"] == []
    r = cmd(c, "jokic to rj for 5")
    assert r.status_code == 503 and "pipeline" in r.json()["message"].lower()
    assert c.get("/board").status_code == 200


# ---------------------------------------------------------------- settings, export, files

def test_settings_rename_and_order(client):
    cmd(client, "jokic to miele for 20")
    teams = [t["name"] for t in state(client)["teams"]]
    new = [("Emiel" if t == "Miele" else t) for t in teams]
    order = list(reversed(new))
    r = client.post("/api/settings", json={"teams": new, "nom_order": order, "me": "Emiel"}).json()
    assert r["ok"]
    s = r["state"]
    assert s["picks"][0]["team"] == "Emiel" and s["me"] == "Emiel" and s["nom_order"] == order
    assert s["rosters"]["Emiel"][0]["name"] == "Nikola Jokic"
    bad = client.post("/api/settings", json={"teams": new[:-1]})
    assert bad.status_code == 400
    dup = client.post("/api/settings", json={"teams": ["x"] * 12})
    assert dup.status_code == 400


def test_export(client):
    cmd(client, "jokic to rj for 20")
    e = client.get("/api/export").json()
    assert e["picks"][0]["name"] == "Nikola Jokic"
    assert {"player_id", "name", "team", "price", "source", "ts"} <= set(e["picks"][0])
    assert len(e["teams"]) == 12 and e["league"]["budget"] == 200


def test_headshots(client, tmp_path):
    assert client.get("/headshots/123.png").status_code == 404      # folder does not exist yet
    (tmp_path / "headshots").mkdir()
    (tmp_path / "headshots" / "123.png").write_bytes(b"\x89PNG fake")
    r = client.get("/headshots/123.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get("/headshots/..%2Fdraft.db").status_code == 404


def test_names_are_stored_raw_and_escaped_by_the_client(client):
    # Team names with markup are allowed data; the frontend renders with textContent.
    teams = [t["name"] for t in state(client)["teams"]]
    teams[0] = "<img src=x onerror=alert(1)>"
    assert client.post("/api/settings", json={"teams": teams}).status_code == 200
    assert state(client)["teams"][0]["name"] == teams[0]


# ---------------------------------------------------------------- acceptance

def test_full_draft_of_156_picks(client):
    ps = client.get("/api/players").json()["players"]
    teams = [t["name"] for t in state(client)["teams"]]
    it = iter(ps)
    for rnd in range(13):
        for t in teams:
            line = next(x for x in state(client)["teams"] if x["name"] == t)
            price = min(line["max_bid"], 3 + (rnd * 7 + len(t)) % 20)
            r = client.post("/api/pick", json={"player_id": next(it)["id"], "team": t,
                                               "price": price})
            assert r.status_code == 200, r.json()
    s = state(client)
    assert len(s["picks"]) == 156
    assert all(t["count"] == 13 and t["remaining"] >= 0 and t["full"] for t in s["teams"])
    assert s["on_the_clock"] is None
    r = client.post("/api/pick", json={"player_id": next(it)["id"], "team": teams[0], "price": 1})
    assert r.status_code == 409


def test_restart_keeps_picks_budgets_and_turn(make_client, tmp_path):
    db = tmp_path / "persist.db"
    c1 = make_client(db=db)
    cmd(c1, "turn ceun")
    cmd(c1, "jokic to rj for 44")
    cmd(c1, "sengun mine 12")
    before = _core(state(c1))
    c2 = make_client(db=db)
    assert _core(state(c2)) == before
    assert state(c2)["on_the_clock"] == "Lode"


def test_reorder_mid_draft_keeps_turn_and_undo(client):
    cmd(client, "turn lode")
    assert cmd(client, "jokic to rj for 30").json()["state"]["on_the_clock"] == "Notto"
    s = state(client)
    new_order = list(reversed(s["nom_order"]))
    r = client.post("/api/settings", json={"nom_order": new_order}).json()
    assert r["ok"] and r["state"]["nom_order"] == new_order
    assert r["state"]["on_the_clock"] == "Notto"
    u = cmd(client, "undo").json()
    assert u["ok"] and u["state"]["on_the_clock"] == "Lode"


def test_skip_when_every_roster_is_full(client):
    ps = client.get("/api/players").json()["players"]
    teams = [t["name"] for t in state(client)["teams"]]
    it = iter(ps)
    for t in teams:
        for _ in range(13):
            assert client.post("/api/pick", json={"player_id": next(it)["id"], "team": t,
                                                  "price": 1}).status_code == 200
    r = cmd(client, "skip").json()
    assert r["ok"] and r["message"] == "Every roster is full." and "None" not in r["message"]
    assert client.post("/api/turn", json={}).json()["message"] == "Every roster is full."


@pytest.mark.parametrize("text", ["go back", "back", "previous", "ok banana go back"])
def test_go_back_moves_the_turn_to_the_previous_team(client, text):
    cmd(client, "turn lode")
    r = cmd(client, text).json()
    assert r["ok"] and r["team"] == "Champximmissioner"
    assert r["state"]["on_the_clock"] == "Champximmissioner"
    assert cmd(client, "skip").json()["team"] == "Lode"


def test_go_back_button_route(client):
    r = client.post("/api/turn", json={"step": -1}).json()
    assert r["ok"] and r["team"] == "Dave"                # RoRo -> wraps to the last team


# ---------------------------------------------------------------- team nicknames

def test_nicknames_saved_matched_and_in_state(client):
    r = client.post("/api/settings", json={"aliases": {"Miele": ["emiel", "Amiel"], "Ceun": "sun, ceune"}})
    assert r.status_code == 200, r.json()
    s = r.json()["state"]
    assert s["aliases"]["Miele"] == ["emiel", "Amiel"] and s["aliases"]["Ceun"] == ["sun", "ceune"]
    assert s["aliases"]["RJ"] == []
    assert cmd(client, "curry to amiel for 10").json()["team"] == "Miele"
    assert client.post("/api/turn", json={"team": "sun"}).json()["team"] == "Ceun"
    assert client.get("/api/export").json()["aliases"]["Miele"] == ["emiel", "Amiel"]


def test_nicknames_follow_a_rename_and_survive_a_restart(make_client, tmp_path):
    db = tmp_path / "n.db"
    c = make_client(db=db)
    c.post("/api/settings", json={"aliases": {"Miele": ["amiel"]}})
    teams = [("Emiel" if t["name"] == "Miele" else t["name"]) for t in state(c)["teams"]]
    assert c.post("/api/settings", json={"teams": teams}).json()["ok"]
    assert state(c)["aliases"]["Emiel"] == ["amiel"] and "Miele" not in state(c)["aliases"]
    c2 = make_client(db=db)
    assert state(c2)["aliases"]["Emiel"] == ["amiel"]


@pytest.mark.parametrize("aliases,needle", [
    ({"Miele": ["rj"]}, "already used by RJ"),                    # another team's name
    ({"Miele": ["Lode"]}, "already used by Lode"),
    ({"Miele": ["zon"], "Ceun": ["ZON"]}, "already used"),       # two teams, one nickname
    ({"Miele": ["a", "b", "c", "d", "e", "f"]}, "more than 5"),
    ({"Miele": ["x" * 31]}, "longer than 30"),
    ({"Miele": ["!!"]}, "no letters"),
    ({"Miele": ["me"]}, "means \"me\""),
    ({"Nobody": ["x"]}, "unknown team"),
    (["emiel"], "must be an object"),
])
def test_nickname_validation(client, aliases, needle):
    before = state(client)["aliases"]
    r = client.post("/api/settings", json={"aliases": aliases})
    assert r.status_code == 400 and needle.lower() in r.json()["message"].lower()
    assert state(client)["aliases"] == before


def test_rename_onto_a_nickname_is_rejected(client):
    client.post("/api/settings", json={"aliases": {"Miele": ["amiel"]}})
    teams = [("amiel" if t["name"] == "RJ" else t["name"]) for t in state(client)["teams"]]
    r = client.post("/api/settings", json={"teams": teams})
    assert r.status_code == 400 and "already used" in r.json()["message"]
    assert "RJ" in [t["name"] for t in state(client)["teams"]]


def test_nicknames_are_deduplicated(client):
    r = client.post("/api/settings", json={"aliases": {"Miele": ["amiel", "Amiel", " ", "Miele"]}})
    assert r.json()["state"]["aliases"]["Miele"] == ["amiel"]


# ---------------------------------------------------------------- nominate and sold

def block(c):
    return state(c)["block"]


def test_nominate_puts_the_player_on_the_block(client):
    cmd(client, "turn lode")
    rev = state(client)["rev"]
    r = cmd(client, "nominate anthony edwards")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["ok"] and body["kind"] == "nominate" and body["nominator"] == "Lode"
    b = body["state"]["block"]
    assert b["player"]["name"] == "Anthony Edwards" and b["nominator"] == "Lode" and b["ts"] > 0
    assert body["state"]["rev"] > rev and body["state"]["picks"] == []
    assert body["state"]["on_the_clock"] == "Lode"          # nominating does not move the turn


def test_nominate_unsure_then_click_nominates(client):
    r = cmd(client, "nominate steph").json()
    assert r["kind"] == "ambiguous" and r["action"] == "nominate" and block(client) is None
    castle = next(c["player"]["id"] for c in r["candidates"] if c["player"]["name"] == "Stephon Castle")
    r2 = client.post("/api/nominate", json={"player_id": castle, "source": "click"}).json()
    assert r2["ok"] and r2["state"]["block"]["player"]["name"] == "Stephon Castle"
    assert r2["state"]["block"]["source"] == "click"


def test_nominate_while_occupied_is_refused(client):
    cmd(client, "nominate anthony edwards")
    rev = state(client)["rev"]
    r = cmd(client, "nominate jokic")
    assert r.status_code == 409
    assert r.json()["message"] == "Anthony Edwards is on the block: say sold or undo."
    # an unsure name gives the same error instead of candidates
    assert cmd(client, "nominate steph").status_code == 409
    r = client.post("/api/nominate", json={"player_id": pid(client, "Nikola Jokic")})
    assert r.status_code == 409 and "on the block" in r.json()["message"]
    assert block(client)["player"]["name"] == "Anthony Edwards" and state(client)["rev"] == rev


def test_nominate_taken_player_is_refused(client):
    cmd(client, "jokic to rj for 30")
    r = client.post("/api/nominate", json={"player_id": pid(client, "Nikola Jokic")})
    assert r.status_code == 409 and "already drafted" in r.json()["message"]
    assert block(client) is None
    assert client.post("/api/nominate", json={}).status_code == 400
    assert client.post("/api/nominate", json={"player_id": "nope"}).status_code == 404


def test_sold_turns_the_block_into_a_pick(client):
    cmd(client, "turn lode")
    cmd(client, "nominate anthony edwards")
    r = cmd(client, "sold to RJ for 5$")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["ok"] and body["kind"] == "pick" and body["sold"]
    assert body["message"].startswith("Sold:")
    s = body["state"]
    p = s["picks"][-1]
    assert (p["name"], p["team"], p["price"]) == ("Anthony Edwards", "RJ", 5)
    assert s["block"] is None and s["on_the_clock"] == "Notto"     # turn advances as with a pick
    # undo of that pick works unchanged, and does not bring the block back
    u = cmd(client, "undo").json()
    assert u["ok"] and u["kind"] == "undo" and u["state"]["picks"] == []
    assert u["state"]["on_the_clock"] == "Lode" and u["state"]["block"] is None


def test_sold_without_amount_prompts_for_the_block_player(client):
    cmd(client, "nominate anthony edwards")
    r = cmd(client, "sold to rj").json()
    assert r["kind"] == "need_amount" and r["team"] == "RJ" and r["sold"]
    assert r["player"]["name"] == "Anthony Edwards" and block(client) is not None
    r2 = client.post("/api/pick", json={"player_id": r["player"]["id"], "team": "RJ",
                                        "price": 7}).json()
    assert r2["ok"] and r2["state"]["block"] is None and r2["state"]["picks"][-1]["price"] == 7


@pytest.mark.parametrize("text,status", [("sold to rj for 195", 409),      # over max bid
                                         ("sold to nobody for 5", 400),   # unknown team
                                         ("sold to rj for 201", 400)])    # out of range
def test_sold_invalid_keeps_the_block(client, text, status):
    cmd(client, "nominate anthony edwards")
    r = cmd(client, text)
    assert r.status_code == status and not r.json()["ok"]
    s = state(client)
    assert s["picks"] == [] and s["block"]["player"]["name"] == "Anthony Edwards"


def test_sold_to_a_full_team_keeps_the_block(client):
    ps = client.get("/api/players").json()["players"]
    first13 = [p for p in ps if p["name"] != "Anthony Edwards"][:13]
    for p in first13:
        client.post("/api/pick", json={"player_id": p["id"], "team": "Dave", "price": 1})
    cmd(client, "nominate anthony edwards")
    before = block(client)
    assert before["player"]["name"] == "Anthony Edwards"
    r = cmd(client, "sold to dave for 1")
    assert r.status_code == 409 and "13" in r.json()["message"]
    assert block(client) == before and len(state(client)["picks"]) == 13


def test_sold_with_an_empty_block(client):
    r = cmd(client, "sold to RJ for 5")
    assert r.status_code == 400 and r.json()["message"] == "Nobody is on the block."
    assert state(client)["picks"] == []


@pytest.mark.parametrize("text", ["undo", "undo 3"])
def test_typed_undo_with_a_block_clears_only_the_block(client, text):
    cmd(client, "jokic to rj for 30")
    cmd(client, "nominate anthony edwards")
    r = cmd(client, text).json()
    assert r["ok"] and r["kind"] == "unblock" and "off the block" in r["message"]
    s = r["state"]
    assert s["block"] is None and len(s["picks"]) == 1
    # the next undo removes the pick again
    assert cmd(client, "undo").json()["kind"] == "undo"


def test_undo_button_and_clear_route_with_a_block(client):
    cmd(client, "jokic to rj for 30")
    cmd(client, "nominate anthony edwards")
    r = client.post("/api/undo", json={"count": 1}).json()
    assert r["kind"] == "unblock" and len(r["state"]["picks"]) == 1
    cmd(client, "nominate anthony edwards")
    r = client.post("/api/block/clear", json={}).json()
    assert r["ok"] and r["state"]["block"] is None and len(r["state"]["picks"]) == 1
    assert client.post("/api/block/clear", json={}).status_code == 400


def test_back_to_here_removes_picks_even_with_a_block(client):
    for t in ("jokic to rj for 30", "curry to miele for 40"):
        cmd(client, t)
    cmd(client, "nominate anthony edwards")
    first = state(client)["picks"][0]["seq"]
    r = client.post("/api/undo", json={"to_seq": first}).json()
    assert r["kind"] == "undo" and len(r["state"]["picks"]) == 1
    assert r["state"]["block"]["player"]["name"] == "Anthony Edwards"


def test_one_step_pick_clears_the_block_only_for_the_same_player(client):
    cmd(client, "nominate curry")
    r = cmd(client, "jokic to rj for 10").json()
    assert r["ok"] and r["state"]["block"]["player"]["name"] == "Stephen Curry"
    r = cmd(client, "curry to rj for 10").json()
    assert r["ok"] and r["state"]["block"] is None


def test_block_survives_a_restart(make_client, tmp_path):
    db = tmp_path / "block.db"
    c1 = make_client(db=db)
    cmd(c1, "turn ceun")
    cmd(c1, "nominate anthony edwards")
    c2 = make_client(db=db)
    b = block(c2)
    assert b["player"]["name"] == "Anthony Edwards" and b["nominator"] == "Ceun"
    assert cmd(c2, "sold to rj for 5").json()["ok"] and block(c2) is None


def test_reset_clears_the_block(client):
    cmd(client, "nominate anthony edwards")
    r = client.post("/api/reset", json={"confirm": "NEW DRAFT"}).json()
    assert r["ok"] and r["state"]["block"] is None


def test_typed_nominate_of_a_drafted_player_does_not_block_him(client):
    cmd(client, "jokic to rj for 30")
    r = cmd(client, "nominate jokic")
    b = block(client)
    # only available players are searched (F-34): Jokic is never put on the block
    assert b is None or b["player"]["name"] != "Nikola Jokic"
    assert all(c["player"]["name"] != "Nikola Jokic" for c in r.json().get("candidates") or [])


def test_failed_nominate_error_carries_the_action_to_the_client(client):
    r = cmd(client, "nominate zzqx")
    assert r.status_code == 400 and r.json()["action"] == "nominate" and block(client) is None


def test_rename_follows_the_block_nominator(client):
    cmd(client, "turn miele")
    cmd(client, "nominate anthony edwards")
    teams = [("Emiel" if t["name"] == "Miele" else t["name"]) for t in state(client)["teams"]]
    r = client.post("/api/settings", json={"teams": teams}).json()
    assert r["ok"] and r["state"]["block"]["nominator"] == "Emiel"
    assert client.get("/api/export").json()["block"]["nominator"] == "Emiel"


def test_block_is_in_the_export(client):
    cmd(client, "nominate anthony edwards")
    assert client.get("/api/export").json()["block"]["player"]["name"] == "Anthony Edwards"


def test_short_sold_after_a_nomination(client):
    cmd(client, "turn lode")
    cmd(client, "nm anthony edwards")
    assert block(client)["player"]["name"] == "Anthony Edwards"
    r = cmd(client, "rj for 5")
    assert r.status_code == 200, r.json()
    p = r.json()["state"]["picks"][-1]
    assert (p["name"], p["team"], p["price"]) == ("Anthony Edwards", "RJ", 5)
    assert block(client) is None


def test_short_sold_without_a_block_is_refused(client):
    r = cmd(client, "rj for 5")
    assert r.status_code == 400 and "Nobody is on the block" in r.json()["message"]
    assert state(client)["picks"] == []


def test_voice_soul_to_is_sold(client):
    cmd(client, "nominate anthony edwards")
    r = cmd(client, "ok banana soul to rj for 5", source="voice").json()
    assert r["ok"] and r["kind"] == "pick" and r["sold"]


def test_easter_egg_otto_is_draftable_for_one_dollar(client, tmp_path):
    ps = client.get("/api/players").json()["players"]
    otto = next(p for p in ps if p["name"] == "Otto Carpentier")
    assert otto["value"] == 1
    # no ADP: ranked after every player that has one
    assert all(otto["espn_rank"] > p["espn_rank"] for p in ps if p.get("adp"))
    r = cmd(client, "otto carpentier to rj for 1").json()
    assert r["ok"] and r["state"]["picks"][-1]["name"] == "Otto Carpentier"


def test_headshot_route_serves_a_jpg_too(make_client, tmp_path):
    heads = tmp_path / "headshots"                     # the folder make_client serves
    heads.mkdir(exist_ok=True)
    (heads / "otto-carpentier.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")
    c = make_client()
    r = c.get("/headshots/otto-carpentier.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert c.get("/headshots/nobody.png").status_code == 404


def test_team_candidate_completes_the_pick(client):
    r = cmd(client, "anthony edwards to an auto for 5")
    body = r.json()
    assert r.status_code == 400 and body["team_candidates"][0]["team"] == "Notto"
    assert body["command"] == "anthony edwards to an auto for 5"
    r2 = client.post("/api/command", json={"text": body["command"], "team": "Notto",
                                           "source": "click"}).json()
    assert r2["ok"] and (r2["state"]["picks"][-1]["team"], r2["state"]["picks"][-1]["price"]) == ("Notto", 5)


def test_voice_event_carries_team_candidates(client):
    cmd(client, "nominate anthony edwards")
    r = cmd(client, "ok banana sold to gin for 5", source="voice").json()
    ev = r["voice_event"]
    assert not ev["ok"] and ev["team_candidates"][0]["team"] == "Gillese"
    r2 = client.post("/api/command", json={"text": ev["command"], "team": "Gillese",
                                           "source": "voice-click"}).json()
    p = r2["state"]["picks"][-1]
    assert r2["ok"] and r2["sold"] and (p["team"], p["price"], p["source"]) == ("Gillese", 5, "voice-click")


def test_failed_sold_names_the_block_player_for_the_buttons(client):
    cmd(client, "nominate anthony edwards")
    edwards = block(client)["player"]["id"]
    body = cmd(client, "sold to gin for 5").json()
    assert body["action"] == "sold" and body["block_player_id"] == edwards
    # a failed pick has nothing on the block to pin
    body = cmd(client, "jayson tatum to gin for 5").json()
    assert body["action"] == "pick" and "block_player_id" not in body


def _click(client, body, team):
    return client.post("/api/command", json={"text": body["command"], "team": team,
                                             "expect_block": body["block_player_id"],
                                             "source": "click"})


def test_team_button_sells_when_the_block_is_unchanged(client):
    cmd(client, "nominate anthony edwards")
    r = _click(client, cmd(client, "sold to gin for 5").json(), "Gillese")
    p = r.json()["state"]["picks"][-1]
    assert r.status_code == 200 and (p["name"], p["team"], p["price"]) == ("Anthony Edwards", "Gillese", 5)


def test_stale_sold_button_never_sells_another_player(client):
    # review: heard with Tatum on the block, clicked after Edwards was nominated
    cmd(client, "nominate jayson tatum")
    body = cmd(client, "sold to gin for 5").json()
    cmd(client, "undo")                           # clears the block only
    cmd(client, "nominate anthony edwards")
    r = _click(client, body, "Gillese")
    assert r.status_code == 409 and "changed" in r.json()["message"]
    s = state(client)
    assert s["picks"] == [] and s["block"]["player"]["name"] == "Anthony Edwards"


def test_sold_to_an_unknown_team_with_an_empty_block_offers_no_buttons(client):
    body = cmd(client, "sold to gin for 5").json()
    assert body["message"] == "Nobody is on the block." and "team_candidates" not in body


def test_stale_pick_button_never_picks_another_player(client):
    # review: the heard player was drafted elsewhere before the click
    body = cmd(client, "anthony edwards to an auto for 5").json()
    assert body["action"] == "pick" and body["player_id"]
    cmd(client, "anthony edwards to rj for 3")
    r = client.post("/api/command", json={"text": body["command"], "team": "Notto",
                                          "expect_player": body["player_id"], "source": "click"})
    assert r.status_code == 409 and "changed since it was heard" in r.json()["message"]
    assert [p["team"] for p in state(client)["picks"]] == ["RJ"]


def test_team_button_for_a_renamed_team_is_refused(client):
    body = cmd(client, "anthony edwards to an auto for 5").json()
    r = client.post("/api/command", json={"text": body["command"], "team": "Nottoo",
                                          "expect_player": body["player_id"], "source": "click"})
    assert r.status_code == 400 and "no longer exists" in r.json()["message"]
    assert state(client)["picks"] == []


def test_unsure_player_and_unknown_team_offer_no_team_buttons(client):
    # review round 5: "bridges" was unsure; a team click later picked Miles Bridges
    body = cmd(client, "bridges to an auto for 5").json()
    assert "not recognised" in body["message"] and "team_candidates" not in body
    cmd(client, "mikal bridges to rj for 3")
    assert [p["name"] for p in state(client)["picks"]] == ["Mikal Bridges"]
