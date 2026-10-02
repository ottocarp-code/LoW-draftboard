"""
Pure helpers for the voice listener: wake-word detection on a transcript and the
Whisper hotword string. No audio or model imports here, so the tests can use it.

The wake word is recognised on the transcript itself (no separate wake-word
model), with the same pattern the server parser strips (app/parser.py WAKE_CORE),
so the listener and the parser never disagree on what counts as "ok banana".
"""

import os
import re
import sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from parser import WAKE_CORE, WAKE_FILLER, normalize  # noqa: E402

WAKE_WORD = "ok banana"
_WAKE_ONLY = re.compile(rf"^(?:{WAKE_FILLER}\s+)*{WAKE_CORE}$")
_FILLER_ONLY = re.compile(rf"^{WAKE_FILLER}$")
_LEAD_PUNCT = re.compile(r"^[\s,.:;!?\-–—\"']+")
_TRAIL_PUNCT = re.compile(r"[\s,.:;!?\"']+$")
MAX_WAKE_TOKENS = 3          # "draft bot" is 2 raw tokens at most, plus slack


def find_wake(text):
    """
    The command after the wake word, or None when the transcript does not start
    with it. Loose on case, punctuation and spacing: "Ok, banana. Steph Curry to
    Miele for $55." -> "Steph Curry to Miele for $55". The remainder is returned
    raw (not normalized), so the server still sees "$" and decimal points.
    An utterance that is only the wake word returns "" (not None).
    """
    toks = str(text or "").split()
    # Leading fillers, including the "ok" of "ok banana" ("Okay. Banana ...", "Uh, ok banana ...").
    start = 0
    while start < len(toks) and _FILLER_ONLY.match(normalize(toks[start]) or "-"):
        start += 1
    for k in range(1, min(MAX_WAKE_TOKENS, len(toks) - start) + 1):
        head = normalize(" ".join(toks[start:start + k]))
        if head and _WAKE_ONLY.match(head):
            # Prefer the longest wake phrase: "draft bot" over "draft" + "bot".
            longer = [j for j in range(k + 1, min(MAX_WAKE_TOKENS, len(toks) - start) + 1)
                      if _WAKE_ONLY.match(normalize(" ".join(toks[start:start + j])))]
            k = longer[-1] if longer else k
            rest = " ".join(toks[start + k:])
            return _TRAIL_PUNCT.sub("", _LEAD_PUNCT.sub("", rest))
    return None


def _cost(phrase):
    """
    Conservative Whisper token cost of a phrase: about 1 token per 3 characters,
    rounded up, plus 1 for the ", " separator. Names like "Champximmissioner" or
    "Jokic" split into many tokens, so a words-based estimate undercounts badly.
    """
    return -(-len(phrase) // 3) + 1


def build_hotwords(teams, aliases=None, players=(), budget=200):
    """
    The hotword string for Whisper: the wake word, the teams, their nicknames and
    as many of `players` (best available first) as fit in about `budget` tokens,
    estimated as 1 token per 3 characters plus separators (see _cost).
    faster-whisper silently cuts hotwords at 223 tokens, so the default stays below.
    """
    parts, seen, used = [], set(), 0.0

    def add(phrase):
        nonlocal used
        phrase = " ".join(str(phrase or "").split())
        key = phrase.lower()
        if not phrase or key in seen:
            return True
        c = _cost(phrase)
        if used + c > budget:
            return False
        parts.append(phrase)
        seen.add(key)
        used += c
        return True

    add(WAKE_WORD)
    for t in teams:
        add(t)
    for t in teams:
        for a in (aliases or {}).get(t) or []:
            add(a)
    for p in players:
        if not add(p):
            break
    return ", ".join(parts)


def estimate_tokens(hotwords):
    return sum(_cost(p) for p in hotwords.split(", ") if p)
