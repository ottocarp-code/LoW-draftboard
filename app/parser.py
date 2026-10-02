"""
Command parser and name matching. The only place a command is interpreted:
typed text and the Whisper transcript (voice/listen.py) both arrive at POST /api/command
and run through `interpret` (F-30).

Grammar (F-29), English, an optional wake word in front:

    <player> to <team> for <amount>
    <player> to <team> <amount>          (for is optional)
    <player> mine [for] <amount>
    <player> to <team>                   (no amount -> amount prompt)
    nominate <player>                    (puts the player on the block)
    sold to <team> for <amount>          (the block player becomes a pick; for is optional)
    sold to <team>                       (no amount -> amount prompt)
    turn <team>
    skip
    go back                              (turn to the previous team; also: back, previous)
    undo [N]                             (with a player on the block: clears the block only)

Wake words `ok banana` and `draftbot` (plus transcription variants) are stripped.
Amounts are digits or English number words, with `$`, `dollar(s)` or `bucks`
before or after. No alias table (F-32): players are scored on bigram overlap with
the full name and the surname, a prefix bonus, and a phonetic key plus soundex as
a safety net (F-33), only against players that are still available (F-34).
"""

import re
import unicodedata

# ---------------------------------------------------------------- normalizing

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv)\b")
# The wake word on normalized text ("Ok, Banana." -> "ok banana"). voice/wake.py uses
# the same pattern, so the listener and the parser always agree on what counts as the
# wake word. "ok"/"okay" is a filler, so "ok banana", "okay banana" and a bare
# "banana" (Whisper sometimes drops the first word) all count, and so do accented
# spellings: "okiebannina", "oki banena", "okee banaan", "bananas", "banana's".
# "low-db" was dropped on 2026-10-02: Whisper heard it 4 times out of 37 and often
# as "Lode B", which is also a team.
WAKE_CORE = r"(?:draft\s?bot|(?:ok(?:ay|ey|ee|ie|i)?\s?)?ban+[aei]+n+[aei]*s?)"
WAKE_FILLER = r"(?:hey|ok|okay|okey|okee|okie|oki|uh|um|so)"
_WAKE = re.compile(rf"^(?:{WAKE_FILLER}\s+)*{WAKE_CORE}\b\s*")
SELF_WORDS = {"me", "mine", "myself", "self", "ik", "mij", "mijn"}


def normalize(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"['’`.]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _prep_raw(raw):
    """Keeps money markers that normalize() would otherwise drop."""
    s = str(raw or "")
    s = re.sub(r"(\d+)[.,]0{1,2}\b", r"\1", s)     # "55.00" -> "55"
    # Any other fraction ("2.5", "12.50") becomes one token that is not a number,
    # so it is rejected instead of normalize() turning 2.5 into 25.
    s = re.sub(r"(\d+)[.,](\d+)", r"\1dot\2", s)
    return s.replace("$", " dollars ")


def strip_wake(t):
    prev = None
    while prev != t:
        prev, t = t, _WAKE.sub("", t).strip()
    return t

# ---------------------------------------------------------------- numbers

_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9}
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_MONEY = {"dollar", "dollars", "buck", "bucks", "usd"}


def words_to_int(tokens):
    """
    English number words to an int, strictly: "eighty five" = 85,
    "one hundred five" = 105, "a hundred and twenty" = 120. Anything that is not a
    well-formed number ("five five", "hundred hundred") returns None instead of
    a wrong sum.
    """
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    hundreds, rest, last = None, 0, None   # last: kind of the previous token
    for i, w in enumerate(tokens):
        if w == "and":
            if hundreds is None or last != "hundred":
                return None
            last = "and"
            continue
        if w == "a":
            if i + 1 < len(tokens) and tokens[i + 1] == "hundred" and last is None:
                rest, last = 1, "one"
                continue
            return None
        if w == "hundred":
            if hundreds is not None or last not in (None, "one", "teen"):
                return None
            hundreds, rest, last = (rest or 1) * 100, 0, "hundred"
            continue
        if w in _TENS:
            if last not in (None, "hundred", "and"):
                return None
            rest, last = _TENS[w], "tens"
            continue
        if w in _TEENS:
            if last not in (None, "hundred", "and"):
                return None
            rest, last = _TEENS[w], "teen"
            continue
        if w in _ONES:
            if last in ("tens",):
                rest, last = rest + _ONES[w], "ones_after_tens"
                continue
            if last not in (None, "hundred", "and"):
                return None
            rest, last = _ONES[w], "one"
            continue
        return None
    if last == "and":
        return None
    return (hundreds or 0) + rest


def parse_amount(text):
    """Digits or number words, `$`/dollars/bucks allowed before or after. None if not a number."""
    toks = [t for t in normalize(text).split() if t not in _MONEY]
    if not toks:
        return None
    if len(toks) == 1 and toks[0].isdigit():
        return int(toks[0])
    return words_to_int(toks)


def _split_trailing_amount(t):
    """'miele fifty five dollars' -> ('miele', 55); ('miele', None) when there is no amount."""
    toks = t.split()
    for i in range(1, len(toks)):
        tail = toks[i:]
        amt = parse_amount(" ".join(tail))
        if amt is not None:
            return " ".join(toks[:i]), amt
    return t, None

# ---------------------------------------------------------------- similarity


def _bigrams(s):
    t = f" {s} "
    return [t[i:i + 2] for i in range(len(t) - 1)]


def dice(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    counts = {}
    for g in _bigrams(a):
        counts[g] = counts.get(g, 0) + 1
    hit, bb = 0, _bigrams(b)
    for g in bb:
        if counts.get(g, 0) > 0:
            hit += 1
            counts[g] -= 1
    return 2 * hit / (len(_bigrams(a)) + len(bb))


def soundex(s):
    s = re.sub(r"[^a-z]", "", s or "")
    if not s:
        return ""
    codes = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"),
             **dict.fromkeys("dt", "3"), "l": "4", **dict.fromkeys("mn", "5"), "r": "6"}
    out, prev = s[0].upper(), codes.get(s[0], "")
    for ch in s[1:]:
        code = codes.get(ch, "")
        if code and code != prev:
            out += code
        if ch not in "hw":
            prev = code
        if len(out) >= 4:
            break
    return (out + "000")[:4]


_PHON = (("tch", "ch"), ("sch", "sh"), ("ch", "c"), ("ck", "k"), ("ph", "f"),
         ("kh", "k"), ("gh", "g"), ("th", "t"), ("sh", "s"), ("ts", "s"), ("z", "s"),
         ("k", "c"), ("q", "c"), ("x", "cs"), ("y", "i"), ("w", "v"))


def phon(s):
    """Rough phonetic key for typing and transcription slips: jokitch ~ jokic, rosan ~ rozan."""
    s = (s or "").replace(" ", "")
    for a, b in _PHON:
        s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)


def vkey(s):
    """
    phon() with every vowel folded to one: Whisper mostly gets the consonants of a
    name right and the vowels wrong (alparan ~ alperen, senghan ~ sengun, rosen ~ rozan).
    """
    return re.sub(r"(.)\1+", r"\1", re.sub(r"[aeiou]", "a", phon(s)))


# A leading article that Whisper splits off a surname ("the rosen" = DeRozan).
_ARTICLES = {"the", "de", "da", "di", "le", "la", "du", "van", "von"}
# Nickname endings: wemby, steffie, ... -> the stem is a surname prefix.
_NICK_END = re.compile(r"(?:y|ie|ee)$")


def _variants(q):
    """The query plus its article-merged forms: "the rosen" -> therosen, derosen."""
    toks = q.split()
    out = [q]
    if len(toks) >= 2 and toks[0] in _ARTICLES:
        rest = " ".join(toks[2:])
        for art in dict.fromkeys([toks[0], "de" if toks[0] == "the" else toks[0]]):
            out.append((art + toks[1] + (" " + rest if rest else "")))
    return out


def _prefix_score(n):
    return 0.80 + min(n, 8) / 40


def _token_score(qt, nt):
    """One query token against one name token (token-by-token alignment)."""
    s = max(dice(qt, nt), 0.95 * dice(phon(qt), phon(nt)), 0.90 * dice(vkey(qt), vkey(nt)))
    if len(qt) >= 3 and nt.startswith(qt):
        s = max(s, _prefix_score(len(qt)))        # "ant" edwards = anthony edwards
    return s


class Name:
    """Precomputed match keys for one player."""
    __slots__ = ("n", "toks", "lasts", "ph", "ph_lasts", "vk_lasts", "sx")

    def __init__(self, name):
        n = normalize(name)
        toks = n.split()
        lasts = toks[1:] if len(toks) > 1 else toks[:]
        if len(toks) > 2:
            lasts.append("".join(toks[1:]))
        if len(toks) > 1:
            lasts.append("".join(toks[1:]))          # "de rozan" style surnames
        self.n = n
        self.toks = toks
        self.lasts = list(dict.fromkeys(lasts))
        self.ph = phon(n)
        self.ph_lasts = [phon(x) for x in self.lasts]
        self.vk_lasts = [vkey(x) for x in self.lasts]
        self.sx = {soundex(x) for x in self.lasts}


def _score_one(q, key):
    qc, qp, qv = q.replace(" ", ""), phon(q), vkey(q)
    s = dice(q, key.n)
    for last, pl, vl in zip(key.lasts, key.ph_lasts, key.vk_lasts):
        # The vowel-folded key alone is too loose on short surnames (rosen ~ duren),
        # so it only counts blended with the phonetic key.
        s = max(s, 0.98 * dice(q, last), 0.97 * dice(qc, last), 0.95 * dice(qp, pl),
                0.90 * (0.7 * dice(qv, vl) + 0.3 * dice(qp, pl)))
    s = max(s, 0.96 * dice(qp, key.ph))
    if len(qc) >= 3 and (key.n.startswith(q) or any(x.startswith(qc) for x in key.lasts)):
        s = max(s, _prefix_score(len(qc)))
    # Nickname form: "wemby" -> stem "wemb", a prefix of a surname.
    qt = q.split()
    if len(qt) == 1:
        stem = _NICK_END.sub("", qc)
        # A stem of 4+ letters: "gary" -> "gar" would hit Garland, "jerry" -> Jerome.
        if stem != qc and len(stem) >= 4 and any(x.startswith(stem) for x in key.lasts):
            s = max(s, _prefix_score(len(stem)) - 0.02)
    # Token-by-token alignment when the query has as many words as the name.
    if len(qt) >= 2 and len(qt) == len(key.toks):
        s = max(s, 0.96 * sum(_token_score(a, b) for a, b in zip(qt, key.toks)) / len(qt))
    if len(qc) >= 4 and soundex(qc) in key.sx:
        s = max(s, 0.78)
    return s


def score_name(q, key):
    """Score in [0, 1] of normalized query q against a Name key."""
    if not q or not key.n:
        return 0.0
    return min(max(_score_one(v, key) for v in _variants(q)), 1.0)


# Thresholds (F-35): below FOUND nothing is proposed; a top score below SURE, or a
# runner-up within GAP of the top, is ambiguous and needs a click to confirm.
FOUND, SURE, GAP, SHOW = 0.55, 0.80, 0.06, 0.40


def match_player(query, pool, n=6):
    """pool: iterable of (player, Name). Returns [(score, player)] best first."""
    q = normalize(query)
    if not q:
        return []
    scored = [(score_name(q, key), p) for p, key in pool]
    scored.sort(key=lambda t: -t[0])
    return scored[:n]


def _team_score(q, nt):
    """Score of normalized query q against one normalized team name or nickname."""
    s = dice(q, nt)
    if len(q) >= 2 and nt.startswith(q):
        s = max(s, 0.85)
    # Nicknames in this league are often anagrams of the real name (Emiel ->
    # Miele, see data/draft_history.csv 2021 vs 2024), so a letter-for-letter
    # anagram counts as a strong match.
    if len(q) >= 4 and sorted(q.replace(" ", "")) == sorted(nt.replace(" ", "")):
        s = max(s, 0.9)
    if len(q) >= 4 and soundex(q) == soundex(nt):
        s = max(s, 0.75)
    return s


def _drop_article(q):
    """ "an auto" -> "auto": Whisper puts an article in front of a team it mishears."""
    rest = re.sub(r"^(?:a|an|the)\s+", "", q)
    return rest or q


def _team_names(t, aliases):
    return [n for n in [normalize(t)] + [normalize(a) for a in (aliases or {}).get(t) or []] if n]


def _best_team_score(queries, t, aliases):
    """Best fuzzy score over the query forms (with and without a leading article), so a
    misspelled "the dud" still finds the nickname "the dude" and "dud" the team "Dude"."""
    return max(_team_score(q, n) for q in dict.fromkeys(queries) if q for n in _team_names(t, aliases))


def team_candidates(query, teams, aliases=None, n=3):
    """The `n` closest teams to a query that matched none, best first: [(team, score)]."""
    raw = normalize(query)
    if not raw:
        return []
    scored = sorted(((_best_team_score((raw, _drop_article(raw)), t, aliases), t) for t in teams),
                    key=lambda x: -x[0])
    return [(t, round(s, 3)) for s, t in scored[:n] if s > 0]


def match_team(query, teams, me=None, aliases=None):
    """
    Returns (team or None, reason). `aliases` is {team: [nickname]} from the
    settings: a nickname matches with the same rules as the team name itself
    (exact, dice, prefix, anagram, soundex), for typed and voice input alike.
    """
    raw = normalize(query)
    q = _drop_article(raw)
    if not q:
        return None, "empty"
    if q in SELF_WORDS:
        return me, "me"
    aliases = aliases or {}
    # Exact first on the query as given ("the dude" may itself be a nickname), and
    # only then without its article ("an auto" -> "auto").
    for exact in dict.fromkeys((raw, q)):
        for t in teams:
            names = _team_names(t, aliases)
            if exact in names:
                return t, "exact" if exact == names[0] else "alias"
    scored = [(_best_team_score((raw, q), t, aliases), t) for t in teams]
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] < 0.5:
        return None, "unknown"
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05:
        return None, "ambiguous"
    return scored[0][1], "match"

# ---------------------------------------------------------------- grammar


def parse_command(raw):
    """Text -> syntactic command. Team and player are still raw strings here."""
    t = strip_wake(normalize(_prep_raw(raw)))
    if not t:
        return {"kind": "empty"}

    m = re.match(r"^(?:undo|scratch that|terug)(?:\s+(.+))?$", t)
    if m:
        if not m.group(1):
            return {"kind": "undo", "count": 1}
        n = parse_amount(m.group(1))
        if n is None:
            return {"kind": "error", "message": f'"{m.group(1)}" is not a number of picks.'}
        return {"kind": "undo", "count": n}

    if t in ("skip", "pass", "next", "volgende"):
        return {"kind": "skip"}
    if t in ("go back", "back", "previous", "prev", "vorige"):
        return {"kind": "back"}

    # nominate <player>: never a turn command (turns are turn/clock/beurt, skip, go back).
    # "nm" is the typed shortcut; any "nomin..." word covers Whisper's nominee,
    # nomineen, nominates and nomina. No player or team has such a word in its name.
    m = re.match(r"^(?:nomin\w*|nm)(?:\s+(.+))?$", t)
    if m:
        if not m.group(1):
            return {"kind": "error", "message": "Nominate which player?"}
        return {"kind": "nominate", "name": m.group(1)}

    # sold [to] <team> [for] <amount>   /   sold [to] <team>
    # Whisper often hears "sold" as soul/sol/sole and "to" as the/two/too.
    m = re.match(r"^(?:sold|soul|sol|sole|solde)(?:\s+(.+))?$", t)
    if m:
        rest = re.sub(r"^(?:to|2|the|two|too)(?:\s+|$)", "", m.group(1) or "")
        if not rest:
            return {"kind": "error", "message": "Sold to which team?"}
        m2 = re.match(r"^(.+?)\s+(?:for|at)\s+(.+)$", rest)
        if m2:
            cmd = _pick(None, m2.group(1), m2.group(2))
        else:
            team, amount = _split_trailing_amount(rest)
            cmd = {"kind": "pick", "name": None, "team": team, "amount": amount,
                   "amount_text": None}
        if cmd["kind"] == "error":
            return cmd
        return {"kind": "sold", "team": cmd["team"], "amount": cmd["amount"],
                "amount_text": cmd["amount_text"]}

    m = re.match(r"^(?:turn|clock|beurt)\s+(?:to\s+|is\s+)?(.+)$", t)
    if m:
        return {"kind": "turn", "team": m.group(1)}

    # <player> mine [for] <amount>   /   <player> mine
    m = re.match(r"^(.+?)\s+(?:mine|to me|for me)(?:\s+(?:for\s+|at\s+)?(.+))?$", t)
    if m:
        return _pick(m.group(1), "me", m.group(2))

    # <player> to <team> for <amount>
    m = re.match(r"^(.+?)\s+to\s+(.+?)\s+(?:for|at)\s+(.+)$", t)
    if m:
        return _pick(m.group(1), m.group(2), m.group(3))

    # <player> to <team> [<amount>]
    m = re.match(r"^(.+?)\s+to\s+(.+)$", t)
    if m:
        team, amount = _split_trailing_amount(m.group(2))
        return {"kind": "pick", "name": m.group(1), "team": team, "amount": amount,
                "amount_text": None}

    # <team> for <amount>   /   <team> <amount>: short "sold", only with a player on
    # the block and a clearly matched team (interpret decides; otherwise a search).
    m = re.match(r"^(.+?)\s+(?:for|at)\s+(.+)$", t)
    if m:
        cmd = _pick(None, m.group(1), m.group(2))
        if cmd["kind"] == "pick":
            return {"kind": "short_sold", "team": cmd["team"], "amount": cmd["amount"],
                    "amount_text": cmd["amount_text"], "text": t, "with_for": True}
    team, amount = _split_trailing_amount(t)
    if team and amount is not None:
        return {"kind": "short_sold", "team": team, "amount": amount, "amount_text": None,
                "text": t, "with_for": False}

    return {"kind": "search", "text": t}


def _team_glued_to(q, teams, me, aliases):
    """
    "sold today" is "sold to Da(ve)": a "to" glued to the team. Retry without it, and
    then with the first two letters only; accepted only when that is one clear team.
    """
    n = normalize(q)
    if not n.startswith("to") or len(n) < 4:
        return None
    rest = n[2:].strip()
    team, _ = match_team(rest, teams, me, aliases)
    if team:
        return team
    starts = [t for t in teams if normalize(t).startswith(rest[:2])]
    return starts[0] if len(starts) == 1 else None


def _pick(name, team, amount_text):
    amount = parse_amount(amount_text) if amount_text else None
    if amount_text and amount is None:
        shown = re.sub(r"(\d+)dot(\d+)", r"\1.\2", amount_text)
        return {"kind": "error", "message": f'Amount "{shown}" not understood.'}
    return {"kind": "pick", "name": name, "team": team, "amount": amount,
            "amount_text": amount_text}


def interpret(raw, pool, teams, me, budget, aliases=None, block=False, team=None):
    """
    Interprets a command against the available pool (list of (player, Name)).
    Always returns a dict with `kind`; on doubt `ambiguous` with candidates, never a guess.
    `block`: a player is on the block, so "<team> for <amount>" means "sold to <team>".
    `team`: a team the user picked from team_candidates; it replaces the team text of
    the parsed command, so nothing else about the command changes.
    """
    cmd = parse_command(raw)
    kind = cmd["kind"]
    if team and kind in ("turn", "pick", "sold", "short_sold"):
        cmd = {**cmd, "team": team}

    if kind == "short_sold":
        team, _ = match_team(cmd["team"], teams, me, aliases)
        if not team:
            # Not a team: what it was before the shortcut existed (board search, or an
            # error with candidates for "<x> for <amount>" while someone is on the block).
            if block and cmd["with_for"]:
                return _team_error(cmd["team"], "unknown", teams, aliases, candidates=True,
                                   action="sold")
            return {"kind": "search", "text": cmd["text"]}
        if not block:
            return {"kind": "error", "message": f"Nobody is on the block: nominate a player "
                                                f"first, or type <player> to {team} for <amount>."}
        cmd = {**cmd, "kind": "sold"}
        kind = "sold"

    if kind == "undo":
        if cmd["count"] < 1:
            return {"kind": "error", "message": "Undo needs at least 1 pick."}
        return cmd

    if kind == "turn":
        team, why = match_team(cmd["team"], teams, me, aliases)
        if not team:
            return _team_error(cmd["team"], why, teams, aliases, candidates=True, action="turn")
        return {"kind": "turn", "team": team}

    if kind == "nominate":
        found = _resolve_player(cmd["name"], pool)
        if found["kind"] == "ambiguous":
            found.update(action="nominate", team=None, amount=None)
            return found
        if found["kind"] == "error":
            found["action"] = "nominate"      # a "Closest:" click nominates, not picks
            return found
        return {"kind": "nominate", "player": found["player"], "score": found["score"]}

    if kind not in ("pick", "sold"):
        return cmd

    team, why = match_team(cmd["team"], teams, me, aliases)
    if not team and kind == "sold":
        team = _team_glued_to(cmd["team"], teams, me, aliases)
    if not team:
        return _team_error(cmd["team"], why, teams, aliases, candidates=True, action=kind)

    amount = cmd["amount"]
    if amount is not None and not (0 < amount <= budget):
        return {"kind": "error", "message": f"Amount ${amount} is out of range (1-{budget})."}

    if kind == "sold":
        # The player is the one on the block; the caller (main.py) knows who that is.
        return {"kind": "sold", "team": team, "amount": amount}

    found = _resolve_player(cmd["name"], pool)
    if found["kind"] == "ambiguous":
        found.update(action="pick", team=team, amount=amount)
        return found
    if found["kind"] == "error":
        return found
    top_p, top_s = found["player"], found["score"]

    if amount is None:
        return {"kind": "need_amount", "player": top_p, "team": team, "score": round(top_s, 3)}
    return {"kind": "pick", "player": top_p, "team": team, "amount": amount,
            "score": top_s}


def _resolve_player(name, pool):
    """
    One player for a name, F-35 style: {kind: found, player, score}, or ambiguous
    with candidates (low top score, or a runner-up within GAP), or an error.
    """
    cands = match_player(name, pool)
    if not cands or cands[0][0] < FOUND:
        return {"kind": "error", "message": f'No available player found for "{name}".',
                "candidates": [{"score": round(s, 3), "player": p}
                               for s, p in cands[:3] if s >= SHOW]}
    top_s, top_p = cands[0]
    close = len(cands) > 1 and top_s - cands[1][0] < GAP
    if top_s < SURE or close:
        return {"kind": "ambiguous", "query": name,
                "candidates": [{"score": round(s, 3), "player": p}
                               for s, p in cands if s >= SHOW]}
    return {"kind": "found", "player": top_p, "score": round(top_s, 3)}


def _team_error(q, why, teams, aliases=None, candidates=False, action=None):
    """
    With `candidates`, the closest teams come along (team_candidates). The client
    offers them as buttons that run the same command again with `team` set, so the
    command is parsed once and player and amount stay exactly as they were heard.
    """
    msg = (f'Team "{q}" is ambiguous.' if why == "ambiguous"
           else f'Team "{q}" not recognised.')
    out = {"kind": "error", "message": msg, "teams": list(teams)}
    if candidates:
        out["team_candidates"] = [{"team": t, "score": s}
                                  for t, s in team_candidates(q, teams, aliases)]
        out["action"] = action        # "sold": main.py pins the block player for the buttons
    return out
