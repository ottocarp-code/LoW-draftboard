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


@pytest.mark.parametrize("wake", ["draftbot", "draft bot", "ok banana", "okay banana", "banana",
                                  "Ok, banana,", "hey ok banana", "OK Banana."])
def test_wake_words_are_stripped(wake):
    cmd = P.parse_command(f"{wake} sengun to lode for 12")
    assert cmd["kind"] == "pick" and cmd["name"] == "sengun" and cmd["amount"] == 12


# ---------------------------------------------------------------- I/O matrix rows

def test_pick(pool):
    r = run("derozan to emiel for 13", pool)
    assert r["kind"] == "pick" and r["player"]["name"] == "DeMar DeRozan"
    assert r["team"] == "Miele" and r["amount"] == 13


@pytest.mark.parametrize("text", ["ok banana steph curry to Miele for 55 $",
                                  "okay banana curry to miele for fifty five dollars",
                                  "banana stephen curry to miele 55 dollars",
                                  "Ok, bananas, curry to miele for $55"])
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


# ---------------------------------------------------------------- team nicknames

ALIASES = {"Miele": ["emiel", "amiel"], "Ceun": ["sun", "ceune"], "Gillese": ["gillis"]}


@pytest.mark.parametrize("q,team,why", [
    ("amiel", "Miele", "alias"), ("AMIEL", "Miele", "alias"), ("sun", "Ceun", "alias"),
    ("gillis", "Gillese", "alias"), ("miele", "Miele", "exact"),
    ("amiell", "Miele", "match"),      # fuzzy on a nickname, same rules as team names
    ("gilis", "Gillese", "match"),
])
def test_team_nicknames(q, team, why):
    assert P.match_team(q, TEAMS, "Notto", ALIASES) == (team, why)


def test_nicknames_work_in_commands(pool):
    r = P.interpret("ok banana curry to amiel for 10", pool, TEAMS, "Notto", 200, ALIASES)
    assert r["kind"] == "pick" and r["team"] == "Miele" and r["amount"] == 10
    r = P.interpret("turn sun", pool, TEAMS, "Notto", 200, ALIASES)
    assert r == {"kind": "turn", "team": "Ceun"}
    # without nicknames "sun" is no team
    assert P.interpret("turn sun", pool, TEAMS, "Notto", 200)["kind"] == "error"


def test_players_have_no_alias_table(pool):
    # Nicknames are for teams only (F-32): a team nickname never becomes a player.
    r = P.interpret("amiel to rj for 5", pool, TEAMS, "Notto", 200, ALIASES)
    assert r["kind"] != "pick" or "amiel" not in P.normalize(r["player"]["name"])


@pytest.mark.parametrize("wake", ["ok bananna", "okay bananas", "banana's", "uh ok banana", "so banana"])
def test_more_wake_variants_are_stripped(wake):
    cmd = P.parse_command(f"{wake} sengun to lode for 12")
    assert cmd["kind"] == "pick" and cmd["name"] == "sengun" and cmd["amount"] == 12


@pytest.mark.parametrize("text", ["bandana to rj for 5", "okafor to lode for 5", "low db to lode for 5"])
def test_wake_does_not_eat_names(text):
    cmd = P.parse_command(text)
    assert cmd["kind"] == "pick" and cmd["name"] == text.split(" to ")[0]


# ---------------------------------------------------------------- nominate / sold grammar

@pytest.mark.parametrize("text,expected", [
    ("nominate anthony edwards", {"kind": "nominate", "name": "anthony edwards"}),
    ("ok banana nominate curry", {"kind": "nominate", "name": "curry"}),
    ("sold to rj for 5", {"kind": "sold", "team": "rj", "amount": 5, "amount_text": "5"}),
    ("sold to rj 5 dollars", {"kind": "sold", "team": "rj", "amount": 5, "amount_text": None}),
    ("sold to rj", {"kind": "sold", "team": "rj", "amount": None, "amount_text": None}),
    ("okay banana sold to miele for fifty five dollars",
     {"kind": "sold", "team": "miele", "amount": 55, "amount_text": "fifty five dollars"}),
])
def test_nominate_and_sold_grammar(text, expected):
    assert P.parse_command(text) == expected


@pytest.mark.parametrize("text", ["nominate", "sold", "sold to"])
def test_nominate_and_sold_need_their_argument(text):
    assert P.parse_command(text)["kind"] == "error"


def test_nominate_no_longer_sets_the_turn(pool):
    # "nominate" was a turn synonym; turns are turn/clock/beurt now.
    assert P.parse_command("nominate roro")["kind"] == "nominate"
    assert run("clock roro", pool) == {"kind": "turn", "team": "RoRo"}
    assert run("beurt roro", pool) == {"kind": "turn", "team": "RoRo"}


def test_interpret_nominate(pool):
    r = run("nominate anthony edwards", pool)
    assert r["kind"] == "nominate" and r["player"]["name"] == "Anthony Edwards"


def test_interpret_nominate_unsure_is_ambiguous(pool):
    r = run("nominate steph", pool)
    assert r["kind"] == "ambiguous" and r["action"] == "nominate"
    assert {c["player"]["name"] for c in r["candidates"][:2]} == {"Stephen Curry", "Stephon Castle"}


def test_interpret_sold(pool):
    assert run("sold to rj for 5", pool) == {"kind": "sold", "team": "RJ", "amount": 5}
    assert run("sold to me", pool) == {"kind": "sold", "team": "Notto", "amount": None}
    assert run("sold to nobody for 5", pool)["kind"] == "error"
    assert run("sold to rj for 201", pool)["kind"] == "error"
    assert run("sold to rj for 2.5", pool)["kind"] == "error"


def test_pick_ambiguity_carries_the_pick_action(pool):
    assert run("bridges to rj for 5", pool)["action"] == "pick"


# ---------------------------------------------------------------- Whisper and nickname forms

def _top(query, pool):
    c = P.match_player(query, pool)
    return c[0][0], c[0][1]["name"], c[1][0]


@pytest.mark.parametrize("query,name", [
    ("the rosen", "DeMar DeRozan"), ("de rozen", "DeMar DeRozan"), ("the rozan", "DeMar DeRozan"),
    ("alparan senghan", "Alperen Sengun"), ("alperin sengoon", "Alperen Sengun"),
    ("wemby", "Victor Wembanyama"), ("ant edwards", "Anthony Edwards"),
])
def test_whisper_and_nickname_forms_are_sure(pool, query, name):
    top_s, top_name, second = _top(query, pool)
    assert top_name == name and top_s >= P.SURE and top_s - second >= P.GAP, (top_s, second)
    r = run(f"{query} to dave for 3", pool)
    assert r["kind"] == "pick" and r["player"]["name"] == name


def test_bare_nickname_prefix_stays_ambiguous(pool):
    r = run("ant to dave for 3", pool)
    assert r["kind"] == "ambiguous"
    assert "Anthony Edwards" in [c["player"]["name"] for c in r["candidates"]]


def test_steph_stays_ambiguous_until_one_is_gone(pool):
    assert run("steph to dave for 3", pool)["kind"] == "ambiguous"
    rest = [(p, k) for p, k in pool if p["name"] != "Stephon Castle"]
    r = run("steph to dave for 3", rest)
    assert r["kind"] == "pick" and r["player"]["name"] == "Stephen Curry"


@pytest.mark.parametrize("query", ["curry", "derozan", "sengun", "jokic", "embiid", "brunson"])
def test_vowel_folding_does_not_crowd_clear_names(pool, query):
    top_s, _, second = _top(query, pool)
    assert top_s >= P.SURE and top_s - second >= 0.15


@pytest.mark.parametrize("query,name", [("gary", "Gary Trent Jr."), ("wemby", "Victor Wembanyama")])
def test_nickname_rule_leaves_real_first_names_alone(pool, query, name):
    # "gary" -> stem "gar" must not pull in Garland; 4+ letter stems only.
    r = run(f"{query} to dave for 3", pool)
    assert r["kind"] == "pick" and r["player"]["name"] == name


def test_failed_nominate_error_carries_the_action(pool):
    r = run("nominate zzqx", pool)
    assert r["kind"] == "error" and r["action"] == "nominate"


# ---------------------------------------------------------------- lenient keywords and shortcuts

@pytest.mark.parametrize("text,name", [
    ("nm anthony edwards", "anthony edwards"),
    ("ok banana nominates cuddy barnes", "cuddy barnes"),           # real transcripts
    ("nomineen muhammad diawara", "muhammad diawara"),
    ("nomina tejae lanjoan sun", "tejae lanjoan sun"),
    ("nominee jokic", "jokic"),
])
def test_nominate_shortcut_and_whisper_forms(text, name):
    assert P.parse_command(text) == {"kind": "nominate", "name": name}


@pytest.mark.parametrize("text,team,amount", [
    ("ok banana soul to hotto for 20", "hotto", 20),                  # real transcripts
    ("Sol to Hotto for two dollars", "hotto", 2),
    ("sole to rj for 5", "rj", 5),
    ("sold the miele for 5", "miele", 5),
    ("sold two rj for 5", "rj", 5),
    ("sold too lode for $12", "lode", 12),
])
def test_sold_keyword_forms(text, team, amount):
    cmd = P.parse_command(text)
    assert cmd["kind"] == "sold" and cmd["team"] == team and cmd["amount"] == amount


def test_sold_today_is_sold_to_dave():
    r = P.interpret("sold today for $3", [], TEAMS, "Notto", 200)   # real: "Lode be sold today for $3"
    assert r == {"kind": "sold", "team": "Dave", "amount": 3}
    # a glued "to" that gives no single team stays an error
    assert P.interpret("sold tomorrow for 3", [], TEAMS, "Notto", 200)["kind"] == "error"


@pytest.mark.parametrize("text,team,amount", [
    ("notto for 5", "Notto", 5),
    ("miele 12", "Miele", 12),
    ("emiel for five dollars", "Miele", 5),
    ("rj at 3", "RJ", 3),
])
def test_short_sold_needs_a_block(pool, text, team, amount):
    r = P.interpret(text, pool, TEAMS, "Notto", 200, ALIASES, block=True)
    assert r == {"kind": "sold", "team": team, "amount": amount}
    without = P.interpret(text, pool, TEAMS, "Notto", 200, ALIASES)
    assert without["kind"] == "error" and "Nobody is on the block" in without["message"]


@pytest.mark.parametrize("text", ["curry 5", "bridges for 5", "jokic"])
def test_short_sold_leaves_other_text_alone(pool, text):
    # not a team: the same as before the shortcut (a board search without a block)
    assert P.interpret(text, pool, TEAMS, "Notto", 200, ALIASES)["kind"] == "search"


def test_short_sold_with_block_but_no_team_is_a_team_error(pool):
    r = P.interpret("bridges for 5", pool, TEAMS, "Notto", 200, ALIASES, block=True)
    assert r["kind"] == "error" and "bridges" in r["message"].lower()
