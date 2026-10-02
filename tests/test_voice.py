import os
import sys

import pytest

import conftest

sys.path.insert(0, os.path.join(conftest.ROOT, "voice"))

import wake  # noqa: E402
from listen import FRAME, Segmenter  # noqa: E402  (no audio/model imports at module level)


def cmd(c, text, source="voice", heard=None):
    body = {"text": text, "source": source}
    if heard is not None:
        body["heard"] = heard
    return c.post("/api/command", json=body)


def state(c):
    return c.get("/api/state").json()


def voice(c):
    return state(c)["voice"]


# ---------------------------------------------------------------- find_wake

@pytest.mark.parametrize("text,expected", [
    ("ok banana steph curry to Miele for 55 dollars", "steph curry to Miele for 55 dollars"),
    ("Ok, banana. Steph Curry to Miele for $55.", "Steph Curry to Miele for $55"),
    ("Okay banana, Jokic to RJ for 30.", "Jokic to RJ for 30"),
    ("OK Banana sengun to lode", "sengun to lode"),
    ("Banana, undo three", "undo three"),
    ("Okay, bananas, jokic to rj for 30", "jokic to rj for 30"),
    ("Ok banana's jokic to rj for 30", "jokic to rj for 30"),
    ("ok bananna jokic to rj for 30", "jokic to rj for 30"),
    ("Okay, banana. Undo.", "Undo"),
    ("banana skip", "skip"),
    ("Hey, banana, turn roro.", "turn roro"),
    ("Uh, ok banana bridges to rj for 5", "bridges to rj for 5"),
    ("Okay. Banana undo 3", "undo 3"),
    # accented spellings (German/Dutch-sounding TTS voices, "okee banaan")
    ("Okiebannina, nominate Jalen Johnson", "nominate Jalen Johnson"),
    ("Oki Banena, sold to Lode for $12", "sold to Lode for $12"),
    ("Okie Banena, Victor Wembanyama to RJ", "Victor Wembanyama to RJ"),
    ("Okee banaan, undo", "undo"),
    ("ok banana", ""),
    ("Okay, banana.", ""),
])
def test_find_wake_variants(text, expected):
    assert wake.find_wake(text) == expected


@pytest.mark.parametrize("text", [
    "curry to miele for 55", "", "   ", "ok", "Okay.", "so what", "hey",
    "I would like a banana", "the banana", "Bandana to rj for 5", "banner to rj for 5",
    "Bannon to rj for 5", "Okafor to rj for 5", "okay so what",
    # the old wake word no longer wakes the app (often heard as the team "Lode")
    "low-db nominate curry", "Lode B, nominate Luka Doncic", "ODB, sold to RJ for $5",
])
def test_find_wake_negatives(text):
    assert wake.find_wake(text) is None


def test_find_wake_keeps_money_and_decimals_raw():
    # The server's parser must still see "$" and "2.5" (rejected, not read as 25).
    assert wake.find_wake("ok banana jokic to rj for $2.5") == "jokic to rj for $2.5"


def test_listener_and_parser_agree_on_the_wake_word():
    import parser as P
    for t in ["ok banana", "Ok, banana,", "okay banana", "OK Banana.", "banana", "bananas",
              "hey banana", "okay so banana", "Uh, um, ok banana", "draftbot"]:
        rest = wake.find_wake(f"{t} sengun to lode for 12")
        assert rest == "sengun to lode for 12", t
        assert P.parse_command(f"{t} sengun to lode for 12")["name"] == "sengun", t


# ---------------------------------------------------------------- hotwords

TEAMS = ["RoRo", "RJ", "Gillese", "sexylexy", "Ceun", "Champximmissioner",
         "Lode", "Notto", "stijn", "Miele", "elianus", "Dave"]


def test_hotwords_order_and_content():
    hw = wake.build_hotwords(TEAMS, {"Miele": ["emiel", "amiel"]}, ["Nikola Jokic", "Luka Doncic"])
    parts = hw.split(", ")
    assert parts[0] == "ok banana"
    assert parts[1:13] == TEAMS
    assert parts[13:15] == ["emiel", "amiel"]
    assert parts[15:] == ["Nikola Jokic", "Luka Doncic"]


def test_hotwords_budget_is_respected():
    players = [f"Player Number{i} Junior" for i in range(500)]
    hw = wake.build_hotwords(TEAMS, {"Miele": ["emiel"]}, players)
    assert wake.estimate_tokens(hw) <= 200
    assert "emiel" in hw and all(t in hw for t in TEAMS)     # teams and nicknames go first
    assert "Player Number0 Junior" in hw and "Player Number499 Junior" not in hw


def test_hotword_estimate_is_character_based_and_conservative():
    # Long one-word names cost many real tokens (base.en: the 12 teams plus top-60
    # fixture players measured 273 tokens under the old words x 1.5 estimate).
    assert wake._cost("Champximmissioner") == 7          # ceil(17 / 3) + separator
    assert wake._cost("RJ") == 2
    players = [f"Giannis Antetokounmpo{i}" for i in range(100)]
    hw = wake.build_hotwords(TEAMS, {"Miele": ["emiel", "amiel"]}, players)
    assert wake.estimate_tokens(hw) <= 200
    # about 1 token per 3 characters plus 1 per separator stays under the 223 cut
    assert len(hw) / 3 + hw.count(",") < 223


def test_hotwords_dedupe_and_skip_empty():
    hw = wake.build_hotwords(["Miele", "miele "], {"Miele": ["", "Miele", "emiel"]}, ["", "Emiel"])
    assert hw == "ok banana, Miele, emiel"


# ---------------------------------------------------------------- segmenter (pure)

def test_segmenter_cuts_after_silence_and_caps_length():
    seg = Segmenter(silence_ms=400, max_s=8.0, pad_ms=200, min_ms=300)
    out = []
    frames = [0.0] * 20 + [0.9] * 30 + [0.05] * 20
    for i, p in enumerate(frames):
        u = seg.push(i, p)
        if u is not None:
            out.append(u)
    assert len(out) == 1
    u = out[0]
    assert 20 - seg.pad_frames in u and 20 in u              # pre-roll kept
    assert len(u) <= seg.pad_frames + 30 + seg.silence_frames
    # a long monologue is cut at max_s
    seg = Segmenter(max_s=2.0)
    cuts = [seg.push(i, 0.9) for i in range(200)]
    assert any(c is not None and len(c) <= int(2.0 * 16000 / FRAME) for c in cuts)


def test_segmenter_ignores_clicks():
    seg = Segmenter(min_ms=300)
    res = [seg.push(i, p) for i, p in enumerate([0.9, 0.9] + [0.0] * 40)]
    assert all(r is None for r in res)


# ---------------------------------------------------------------- voice event in state

def test_voice_pick_goes_straight_in_and_is_shown(client):
    r = cmd(client, "steph curry to Miele for 55 dollars",
            heard="Ok banana, Steph Curry to Miele for 55 dollars.").json()
    assert r["ok"] and r["kind"] == "pick"
    s = state(client)
    assert s["picks"][-1]["source"] == "voice" and s["picks"][-1]["price"] == 55
    ev = s["voice"]["event"]
    assert ev["kind"] == "pick" and ev["ok"] and ev["heard"].startswith("Ok banana, Steph")
    assert "Stephen Curry to Miele for $55" in ev["message"] and ev["resolved"] is None
    assert "state" not in ev


def test_typed_commands_leave_the_voice_event_alone(client):
    cmd(client, "jokic to rj for 30", source="typed")
    assert voice(client)["event"] is None


def test_voice_ambiguous_then_click_on_any_screen(client):
    r = cmd(client, "bridges to rj for 5").json()
    assert r["kind"] == "ambiguous" and not state(client)["picks"]
    ev = voice(client)["event"]
    assert ev["kind"] == "ambiguous" and ev["team"] == "RJ" and ev["amount"] == 5
    assert {c["player"]["name"] for c in ev["candidates"]} >= {"Mikal Bridges", "Miles Bridges"}
    mikal = next(c["player"]["id"] for c in ev["candidates"] if c["player"]["name"] == "Mikal Bridges")
    p = client.post("/api/pick", json={"player_id": mikal, "team": "RJ", "price": 5,
                                       "source": "voice"}).json()
    assert p["ok"]
    rev = state(client)["rev"]
    assert client.post("/api/voice/resolve", json={"id": ev["id"], "message": p["message"]}).json()["ok"]
    s = state(client)
    assert s["rev"] > rev and s["voice"]["event"]["resolved"].startswith("Mikal Bridges")
    # a stale id is refused
    assert client.post("/api/voice/resolve", json={"id": ev["id"] + 5}).status_code == 409


def test_voice_event_cannot_be_resolved_twice(client):
    cmd(client, "bridges to rj for 5")
    ev = voice(client)["event"]
    first = client.post("/api/voice/resolve", json={"id": ev["id"], "message": "Mikal Bridges to RJ"})
    assert first.status_code == 200 and first.json()["state"]["voice"]["event"]["resolved"]
    rev = state(client)["rev"]
    again = client.post("/api/voice/resolve", json={"id": ev["id"], "message": "Miles Bridges to RJ"})
    assert again.status_code == 409 and not again.json()["ok"]
    s = state(client)
    assert s["voice"]["event"]["resolved"] == "Mikal Bridges to RJ" and s["rev"] == rev


def test_voice_need_amount(client):
    r = cmd(client, "sengun to lode").json()
    assert r["kind"] == "need_amount"
    ev = voice(client)["event"]
    assert ev["kind"] == "need_amount" and ev["player"]["name"] == "Alperen Sengun"
    assert ev["team"] == "Lode" and not state(client)["picks"]


@pytest.mark.parametrize("text,needle", [
    ("jokic to rj for 195", "max bid"),
    ("jokic to rj for 201", "out of range"),
    ("jokic to nobody for 5", "not recognised"),
])
def test_voice_rejections_are_shown_and_change_nothing(client, text, needle):
    before = state(client)
    r = cmd(client, text)
    assert r.status_code in (400, 409) and not r.json()["ok"]
    after = state(client)
    assert after["picks"] == before["picks"] and after["turn_idx"] == before["turn_idx"]
    ev = after["voice"]["event"]
    assert ev["kind"] == "error" and not ev["ok"] and needle in ev["message"].lower()


def test_voice_taken_player_rejected(client):
    cmd(client, "jokic to rj for 30", source="typed")
    r = cmd(client, "jokic to roro for 40")
    assert not r.json()["ok"]
    ev = voice(client)["event"]
    # Only available players are matched (F-34): the taken Jokic is never proposed.
    assert ev["kind"] in ("error", "ambiguous") and len(state(client)["picks"]) == 1
    assert all(c["player"]["name"] != "Nikola Jokic" for c in ev.get("candidates") or [])


def test_voice_not_a_command_is_an_error_event(client):
    r = cmd(client, "what a steal")
    assert r.status_code == 400
    ev = voice(client)["event"]
    assert ev["kind"] == "error" and "not a command" in ev["message"]


@pytest.mark.parametrize("text", ["undo", "undo three", "undo 3", "scratch that",
                                  "ok banana undo two", "terug"])
def test_undo_by_voice_is_rejected_and_removes_nothing(client, text):
    for t in ("jokic to rj for 30", "curry to miele for 40", "sengun to lode for 10"):
        cmd(client, t, source="typed")
    before = state(client)
    r = cmd(client, text, heard=f"Ok banana, {text}.")
    assert r.status_code == 400
    body = r.json()
    assert not body["ok"] and body["kind"] == "error" and body["message"] == "Undo picks by typing."
    after = state(client)
    assert after["picks"] == before["picks"] and after["turn_idx"] == before["turn_idx"]
    ev = after["voice"]["event"]
    assert ev["kind"] == "error" and ev["message"] == "Undo picks by typing."
    assert ev["heard"] == f"Ok banana, {text}."
    # the same text typed still works as before
    typed = cmd(client, text, source="typed").json()
    assert typed["kind"] in ("undo", "confirm_undo")
    if typed["kind"] == "undo":
        assert len(state(client)["picks"]) == 2


def test_voice_turn_and_go_back_still_work(client):
    cmd(client, "jokic to rj for 30", source="typed")
    assert cmd(client, "turn lode").json()["ok"]
    assert state(client)["on_the_clock"] == "Lode"
    assert cmd(client, "go back").json()["ok"]            # moves the turn, removes no pick
    assert len(state(client)["picks"]) == 1


def test_newer_event_replaces_older(client):
    cmd(client, "sengun to lode")
    first = voice(client)["event"]["id"]
    cmd(client, "jokic to rj for 30")
    ev = voice(client)["event"]
    assert ev["id"] > first and ev["kind"] == "pick"


def test_voice_has_no_reset_route(client):
    cmd(client, "jokic to rj for 30", source="typed")
    for t in ("new draft", "reset", "reset draft", "new draft confirm"):
        cmd(client, t)
    assert len(state(client)["picks"]) == 1


# ---------------------------------------------------------------- heartbeat and mute

def test_listener_off_until_heartbeat_then_times_out(client):
    store = client.app.state.store
    now = [1000.0]
    store.clock = lambda: now[0]
    assert voice(client)["status"] == "off"
    rev = state(client)["rev"]
    r = client.post("/api/voice/heartbeat", json={"model": "base.en"}).json()
    assert r == {"ok": True, "muted": False}
    v = voice(client)
    assert v["status"] == "listening" and v["model"] == "base.en"
    assert state(client)["rev"] > rev                     # off -> listening bumps rev
    rev = state(client)["rev"]
    now[0] += 3
    client.post("/api/voice/heartbeat", json={"model": "base.en"})
    assert state(client)["rev"] == rev                    # a routine heartbeat does not
    now[0] += 10
    assert voice(client)["status"] == "listening"         # 10 s is still alive
    now[0] += 0.5
    assert voice(client)["status"] == "off"               # more than 10 s: off
    # typing keeps working with the listener off (N-1)
    assert client.post("/api/command", json={"text": "jokic to rj for 30", "source": "typed"}).json()["ok"]


def test_mute_toggle_and_listener_honours_it(client):
    client.post("/api/voice/heartbeat", json={"model": "base.en"})
    rev = state(client)["rev"]
    r = client.post("/api/voice/mute", json={"muted": True}).json()
    assert r["ok"] and r["state"]["voice"]["status"] == "muted" and r["state"]["rev"] > rev
    assert client.post("/api/voice/heartbeat", json={"model": "base.en"}).json()["muted"] is True
    # a muted voice command is not executed and not recorded
    r = cmd(client, "jokic to rj for 30").json()
    assert r["kind"] == "muted" and state(client)["picks"] == [] and voice(client)["event"] is None
    # typing still works while muted
    assert cmd(client, "jokic to rj for 30", source="typed").json()["ok"]
    client.post("/api/voice/mute", json={"muted": False})
    assert voice(client)["status"] == "listening"
    assert client.post("/api/voice/mute", json={"muted": "yes"}).status_code == 400


def test_voice_state_is_not_persisted(make_client, tmp_path):
    db = tmp_path / "keep.db"
    c1 = make_client(db=db)
    c1.post("/api/voice/heartbeat", json={"model": "base.en"})
    c1.post("/api/voice/mute", json={"muted": True})
    cmd(c1, "sengun to lode")
    c2 = make_client(db=db)
    v = voice(c2)
    assert v["status"] == "off" and v["muted"] is False and v["event"] is None


# ---------------------------------------------------------------- nominate / sold by voice

def test_voice_nominate_is_seen_by_every_screen(make_client, tmp_path):
    db = tmp_path / "two.db"
    a, b = make_client(db=db), make_client(db=db)
    rev = state(b)["rev"]
    r = cmd(a, "nominate anthony edwards", heard="Ok banana, nominate Anthony Edwards.").json()
    assert r["ok"] and r["kind"] == "nominate" and r["voice_event"]["nominator"] == "RoRo"
    # the other window sees it on its next poll (same database, a new rev)
    s = state(b)
    assert s["rev"] > rev and s["block"]["player"]["name"] == "Anthony Edwards"


def test_voice_nominate_ambiguous_carries_the_action(client):
    r = cmd(client, "nominate steph").json()
    assert r["kind"] == "ambiguous"
    ev = voice(client)["event"]
    assert ev["action"] == "nominate" and len(ev["candidates"]) >= 2


def test_voice_sold(client):
    cmd(client, "nominate anthony edwards")
    r = cmd(client, "sold to rj for five dollars").json()
    assert r["ok"] and r["kind"] == "pick" and r["sold"]
    s = state(client)
    assert s["block"] is None and s["picks"][-1]["source"] == "voice"
    assert s["voice"]["event"]["sold"] is True


@pytest.mark.parametrize("text", ["undo", "ok banana undo", "undo 3"])
def test_voice_undo_with_a_block_clears_only_the_block(client, text):
    cmd(client, "jokic to rj for 30", source="typed")
    cmd(client, "nominate anthony edwards")
    r = cmd(client, text)
    assert r.status_code == 200 and r.json()["kind"] == "unblock"
    s = state(client)
    assert s["block"] is None and len(s["picks"]) == 1
    # without a block a voice undo is refused again and removes nothing
    r = cmd(client, text)
    assert r.status_code == 400 and r.json()["message"] == "Undo picks by typing."
    assert len(state(client)["picks"]) == 1
