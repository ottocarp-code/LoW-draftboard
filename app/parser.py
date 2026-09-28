"""
Command parser and name matching. The only place a command is interpreted:
typed text and (later) the Whisper transcript both arrive at POST /api/command
and run through `interpret` (F-30).

Grammar (F-29), English, an optional wake word in front:

    <player> to <team> for <amount>
    <player> to <team> <amount>          (for is optional)
    <player> mine [for] <amount>
    <player> to <team>                   (no amount -> amount prompt)
    turn <team>
    skip
    undo [N]

Wake words `draftbot` and `low-db` (plus transcription variants) are stripped.
Amounts are digits or English number words, with `$`, `dollar(s)` or `bucks`
before or after. No alias table (F-32): players are scored on bigram overlap with
the full name and the surname, a prefix bonus, and a phonetic key plus soundex as
a safety net (F-33), only against players that are still available (F-34).
"""

import re
import unicodedata

# ---------------------------------------------------------------- normalizing

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv)\b")
_WAKE = re.compile(
    r"^(?:(?:hey|ok|okay)\s+)?"
    r"(?:draft\s?bot|low\s?db|low\s?d\s?b|low\s+dee\s+bee|low\s+deebee)\b\s*")
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


class Name:
    """Precomputed match keys for one player."""
    __slots__ = ("n", "lasts", "ph", "ph_lasts", "sx")

    def __init__(self, name):
        n = normalize(name)
        toks = n.split()
        lasts = toks[1:] if len(toks) > 1 else toks[:]
        if len(toks) > 2:
            lasts.append("".join(toks[1:]))
        if len(toks) > 1:
            lasts.append("".join(toks[1:]))          # "de rozan" style surnames
        self.n = n
        self.lasts = list(dict.fromkeys(lasts))
        self.ph = phon(n)
        self.ph_lasts = [phon(x) for x in self.lasts]
        self.sx = {soundex(x) for x in self.lasts}


def score_name(q, key):
    """Score in [0, 1] of normalized query q against a Name key."""
    if not q or not key.n:
        return 0.0
    qc, qp = q.replace(" ", ""), phon(q)
    s = dice(q, key.n)
    for last, pl in zip(key.lasts, key.ph_lasts):
        s = max(s, 0.98 * dice(q, last), 0.97 * dice(qc, last), 0.95 * dice(qp, pl))
    s = max(s, 0.96 * dice(qp, key.ph))
    if len(qc) >= 3 and (key.n.startswith(q) or any(x.startswith(qc) for x in key.lasts)):
        s = max(s, 0.80 + min(len(qc), 8) / 40)
    if len(qc) >= 4 and soundex(qc) in key.sx:
        s = max(s, 0.78)
    return min(s, 1.0)


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


def match_team(query, teams, me=None):
    """Returns (team or None, reason)."""
    q = normalize(query)
    if not q:
        return None, "empty"
    if q in SELF_WORDS:
        return me, "me"
    scored = []
    for t in teams:
        nt = normalize(t)
        if q == nt:
            return t, "exact"
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
        scored.append((s, t))
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

    m = re.match(r"^(?:turn|clock|nominate|beurt)\s+(?:to\s+|is\s+)?(.+)$", t)
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

    return {"kind": "search", "text": t}


def _pick(name, team, amount_text):
    amount = parse_amount(amount_text) if amount_text else None
    if amount_text and amount is None:
        shown = re.sub(r"(\d+)dot(\d+)", r"\1.\2", amount_text)
        return {"kind": "error", "message": f'Amount "{shown}" not understood.'}
    return {"kind": "pick", "name": name, "team": team, "amount": amount,
            "amount_text": amount_text}


def interpret(raw, pool, teams, me, budget):
    """
    Interprets a command against the available pool (list of (player, Name)).
    Always returns a dict with `kind`; on doubt `ambiguous` with candidates, never a guess.
    """
    cmd = parse_command(raw)
    kind = cmd["kind"]

    if kind == "undo":
        if cmd["count"] < 1:
            return {"kind": "error", "message": "Undo needs at least 1 pick."}
        return cmd

    if kind == "turn":
        team, why = match_team(cmd["team"], teams, me)
        if not team:
            return _team_error(cmd["team"], why, teams)
        return {"kind": "turn", "team": team}

    if kind != "pick":
        return cmd

    team, why = match_team(cmd["team"], teams, me)
    if not team:
        return _team_error(cmd["team"], why, teams)

    amount = cmd["amount"]
    if amount is not None and not (0 < amount <= budget):
        return {"kind": "error", "message": f"Amount ${amount} is out of range (1-{budget})."}

    cands = match_player(cmd["name"], pool)
    if not cands or cands[0][0] < FOUND:
        return {"kind": "error", "message": f'No available player found for "{cmd["name"]}".',
                "candidates": [{"score": round(s, 3), "player": p}
                               for s, p in cands[:3] if s >= SHOW]}

    top_s, top_p = cands[0]
    close = len(cands) > 1 and top_s - cands[1][0] < GAP
    if top_s < SURE or close:
        return {"kind": "ambiguous", "team": team, "amount": amount, "query": cmd["name"],
                "candidates": [{"score": round(s, 3), "player": p}
                               for s, p in cands if s >= SHOW]}

    if amount is None:
        return {"kind": "need_amount", "player": top_p, "team": team, "score": round(top_s, 3)}
    return {"kind": "pick", "player": top_p, "team": team, "amount": amount,
            "score": round(top_s, 3)}


def _team_error(q, why, teams):
    msg = (f'Team "{q}" is ambiguous.' if why == "ambiguous"
           else f'Team "{q}" not recognised.')
    return {"kind": "error", "message": msg, "teams": list(teams)}
