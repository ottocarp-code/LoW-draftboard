"""
Pure draft rules: budgets, max bid, pick validation and the nomination turn.
No I/O here; store.py feeds in the current picks and settings.

Turn model. `turn_idx` points into the nomination order. The team that actually
nominates is the first team at or after `turn_idx` that still has an open roster
spot (F-38). After a pick or a skip the turn moves to the team after the one that
*resolved*, not after the raw index: moving from the raw index made a team
nominate twice in a row when a full team sat in front of it.
"""


class DraftError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message = message
        self.status = status


def max_bid(remaining, open_slots):
    """F-22: remaining budget minus $1 for every other open roster spot."""
    if open_slots <= 0:
        return 0
    return max(0, remaining - (open_slots - 1))


def summarize(teams, picks, budget, spots):
    """Per team: spent, count, remaining, open, max_bid, full."""
    spent = {t: 0 for t in teams}
    count = {t: 0 for t in teams}
    for p in picks:
        if p["team"] in spent:
            spent[p["team"]] += int(p["price"])
            count[p["team"]] += 1
    out = {}
    for t in teams:
        remaining = budget - spent[t]
        open_slots = max(0, spots - count[t])
        out[t] = {"spent": spent[t], "count": count[t], "remaining": remaining,
                  "open": open_slots, "max_bid": max_bid(remaining, open_slots),
                  "full": open_slots == 0}
    return out


def validate_pick(player, team, price, teams, picks, budget, spots):
    """Raises DraftError when the pick may not be stored (F-36, over max bid)."""
    if team not in teams:
        raise DraftError(f'Unknown team "{team}".', 404)
    if player is None:
        raise DraftError("Unknown player.", 404)
    try:
        price = int(price)
    except (TypeError, ValueError):
        raise DraftError("Price must be a whole number.", 400)
    if price < 1:
        raise DraftError("Price must be at least $1.", 400)
    if any(str(p["player_id"]) == str(player["id"]) for p in picks):
        who = next(p["team"] for p in picks if str(p["player_id"]) == str(player["id"]))
        raise DraftError(f'{player["name"]} is already drafted by {who}.', 409)
    line = summarize(teams, picks, budget, spots)[team]
    if line["full"]:
        raise DraftError(f"{team} already has {spots} players.", 409)
    if price > line["max_bid"]:
        raise DraftError(f'${price} is above the max bid of {team} (${line["max_bid"]}).', 409)
    return price


def resolve_turn(turn_idx, order, counts, spots):
    """Index in `order` of the team that nominates, skipping full teams. None if all full."""
    n = len(order)
    if n == 0:
        return None
    start = turn_idx % n
    for k in range(n):
        i = (start + k) % n
        if counts.get(order[i], 0) < spots:
            return i
    return None


def advance_turn(turn_idx, order, counts_before, counts_after, spots):
    """
    Turn after a pick or skip. The nominator is resolved with the counts *before*
    the pick (the buyer may just have filled up), the next nominator with the
    counts after it.
    """
    n = len(order)
    if n == 0:
        return 0
    cur = resolve_turn(turn_idx, order, counts_before, spots)
    if cur is None:
        return turn_idx % n
    nxt = resolve_turn(cur + 1, order, counts_after, spots)
    return nxt if nxt is not None else (cur + 1) % n


def retreat_turn(turn_idx, order, counts, spots):
    """The opposite of a skip: the turn goes to the previous team that is not full."""
    n = len(order)
    if n == 0:
        return 0
    cur = resolve_turn(turn_idx, order, counts, spots)
    if cur is None:
        return turn_idx % n
    for k in range(1, n):
        i = (cur - k) % n
        if counts.get(order[i], 0) < spots:
            return i
    return cur


def counts_of(teams, picks):
    c = {t: 0 for t in teams}
    for p in picks:
        if p["team"] in c:
            c[p["team"]] += 1
    return c
