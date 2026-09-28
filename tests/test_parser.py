import json

import pytest

import parser as P

TEAMS = ["RoRo", "RJ", "Gillese", "sexylexy", "Ceun", "Champximmissioner",
         "Lode", "Notto", "stijn", "Miele", "elianus", "Dave"]


@pytest.fixture(scope="module")
def pool():
    import conftest
    with open(conftest.FIXTURE, encoding="utf-8") as f:
        players = json.load(f)["players"]
    return [(p, P.Name(p["name"])) for p in players]


def run(text, pool, teams=TEAMS, me="Notto"):
    return P.interpret(text, pool, teams, me, 200)


# ---------------------------------------------------------------- numbers

@pytest.mark.parametrize("text,value", [
    ("13", 13), ("thirteen", 13), ("eighty five", 85), ("eighty-five", 85),
    ("one hundred five", 105), ("one hundred and five", 105), ("a hundred", 100),
    ("hundred", 100), ("one hundred twenty five", 125), ("twenty", 20), ("zero", 0),
    ("fifty five dollars", 55), ("55 $", 55), ("$55", 55), ("55 bucks", 55),
    ("dollars 12", 12), ("forty", 40), ("fourty two", 42), ("nineteen", 19),
])
def test_amounts(text, value):
    assert P.parse_amount(P._prep_raw(text)) == value


@pytest.mark.parametrize("text", ["five five", "twenty thirty", "hundred hundred",
                                  "eighty and five", "one two", "fifty abc", "", "dollars"])
def test_bad_amounts_are_not_summed(text):
    assert P.parse_amount(text) is None


# ---------------------------------------------------------------- grammar

@pytest.mark.parametrize("text,kind", [
    ("undo", "undo"), ("skip", "skip"), ("turn roro", "turn"), ("bridges", "search"),
    ("", "empty"), ("draftbot", "empty"), ("derozan to rj for 5", "pick"),
])
def test_command_kinds(text, kind):
    assert P.parse_command(text)["kind"] == kind


@pytest.mark.parametrize("text,count", [("undo", 1), ("undo 3", 3), ("undo three", 3),
                                        ("draftbot undo two", 2)])
def test_undo_count(text, count):
    assert P.parse_command(text) == {"kind": "undo", "count": count}


@pytest.mark.parametrize("wake", ["draftbot", "draft bot", "low-db", "low db", "lowdb",
                                  "low dee bee", "hey low-db", "Low-DB,"])
def test_wake_words_are_stripped(wake):
    cmd = P.parse_command(f"{wake} sengun to lode for 12")
    assert cmd["kind"] == "pick" and cmd["name"] == "sengun" and cmd["amount"] == 12


# ---------------------------------------------------------------- I/O matrix rows

def test_pick(pool):
    r = run("derozan to emiel for 13", pool)
    assert r["kind"] == "pick" and r["player"]["name"] == "DeMar DeRozan"
    assert r["team"] == "Miele" and r["amount"] == 13


@pytest.mark.parametrize("text", ["low-db steph curry to Miele for 55 $",
                                  "low db curry to miele for fifty five dollars",
                                  "lowdb stephen curry to miele 55 dollars",
                                  "low dee bee curry to miele for $55"])
def test_voice_style(pool, text):
    r = run(text, pool)
    assert r["kind"] == "pick", r
    assert r["player"]["name"] == "Stephen Curry" and r["team"] == "Miele" and r["amount"] == 55


@pytest.mark.parametrize("text,amount", [("wembanyama to roro for eighty five", 85),
                                         ("wembanyama to roro for one hundred five", 105)])
def test_number_words(pool, text, amount):
    r = run(text, pool)
    assert r["kind"] == "pick" and r["player"]["name"] == "Victor Wembanyama"
    assert r["team"] == "RoRo" and r["amount"] == amount


def test_wake_word_and_mine(pool):
    r = run("draftbot jokitch mine 40", pool)
    assert r["kind"] == "pick" and r["player"]["name"] == "Nikola Jokic"
    assert r["team"] == "Notto" and r["amount"] == 40


def test_ambiguous_bridges(pool):
    r = run("bridges to rj for 5", pool)
    assert r["kind"] == "ambiguous" and r["team"] == "RJ" and r["amount"] == 5
    names = [c["player"]["name"] for c in r["candidates"][:2]]
    assert sorted(names) == ["Mikal Bridges", "Miles Bridges"]
    assert all("score" in c for c in r["candidates"])


def test_bridges_resolves_once_one_is_gone(pool):
    rest = [(p, k) for p, k in pool if p["name"] != "Mikal Bridges"]
    r = run("bridges to rj for 5", rest)
    assert r["kind"] == "pick" and r["player"]["name"] == "Miles Bridges"


def test_no_amount(pool):
    r = run("sengun to lode", pool)
    assert r["kind"] == "need_amount" and r["player"]["name"] == "Alperen Sengun"
    assert r["team"] == "Lode"


# ---------------------------------------------------------------- FRD-tested names

@pytest.mark.parametrize("query,name", [("jokitch", "Nikola Jokic"), ("de rosan", "DeMar DeRozan"),
                                        ("sengun", "Alperen Sengun"), ("derozan", "DeMar DeRozan"),
                                        ("wembanyama", "Victor Wembanyama")])
def test_frd_names(pool, query, name):
    r = run(f"{query} to dave for 3", pool)
    assert r["kind"] == "pick" and r["player"]["name"] == name


def test_only_available_players_are_matched(pool):
    rest = [(p, k) for p, k in pool if p["name"] != "Nikola Jokic"]
    r = run("jokic to dave for 3", rest)
    assert r["kind"] != "pick" or r["player"]["name"] != "Nikola Jokic"


def test_unknown_team_and_out_of_range(pool):
    assert run("jokic to zzz for 5", pool)["kind"] == "error"
    assert run("jokic to rj for 0", pool)["kind"] == "error"
    assert run("jokic to rj for 201", pool)["kind"] == "error"
    assert run("jokic to rj for five five", pool)["kind"] == "error"


@pytest.mark.parametrize("q,team", [("roro", "RoRo"), ("rj", "RJ"), ("emiel", "Miele"),
                                    ("champ", "Champximmissioner"), ("me", "Notto"),
                                    ("STIJN", "stijn"), ("sexy lexy", "sexylexy")])
def test_team_matching(q, team):
    assert P.match_team(q, TEAMS, "Notto")[0] == team


def test_normalize_names():
    import names
    assert names.normalize("Nikola Jokić") == "nikola jokic"
    assert names.normalize("Jaren Jackson Jr.") == "jaren jackson"
    assert names.normalize("De'Aaron Fox") == "deaaron fox"
    assert names.normalize("Karl-Anthony Towns") == "karl anthony towns"
    assert names.normalize("Dereck Lively II") == "dereck lively"


@pytest.mark.parametrize("text", ["jokic to rj for 2.5", "jokic to rj for $12.5",
                                  "jokic to rj for 12.50", "jokic mine 2,5"])
def test_decimal_fractions_are_rejected(pool, text):
    r = run(text, pool)
    assert r["kind"] == "error" and "not understood" in r["message"]


@pytest.mark.parametrize("text,amount", [("jokic to rj for 55.00", 55), ("jokic to rj for $12.0", 12)])
def test_zero_fractions_still_work(pool, text, amount):
    r = run(text, pool)
    assert r["kind"] == "pick" and r["amount"] == amount


def test_decimal_message_shows_the_amount(pool):
    assert '"2.5"' in run("jokic to rj for 2.5", pool)["message"]
