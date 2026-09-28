"""
Naamnormalisatie om bronnen op naam te koppelen (build_values.py).

    normalize("Nikola Jokić")        -> "nikola jokic"
    normalize("Jaren Jackson Jr.")   -> "jaren jackson"
    normalize("De'Aaron Fox")        -> "deaaron fox"

Alleen de standard library, zodat de ophaalscripts zonder pip install draaien (N-4).
"""

import re
import unicodedata

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv)\b")


def normalize(name):
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"['’`.]", "", s)          # De'Aaron -> deaaron, P.J. -> pj
    s = re.sub(r"[^a-z0-9]+", " ", s)       # koppeltekens en overige leestekens
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()
