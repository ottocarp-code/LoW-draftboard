import pytest

import draft as D

T = ["A", "B", "C", "D"]


def picks_for(counts, price=1):
    out, i = [], 0
    for t, n in counts.items():
        for _ in range(n):
            out.append({"player_id": str(i), "team": t, "price": price})
            i += 1
    return out


def test_max_bid():
    assert D.max_bid(200, 13) == 188
    assert D.max_bid(10, 1) == 10
    assert D.max_bid(5, 0) == 0
    assert D.max_bid(3, 5) == 0


def test_summarize():
    s = D.summarize(T, [{"player_id": "1", "team": "A", "price": 50}], 200, 13)
    assert s["A"] == {"spent": 50, "count": 1, "remaining": 150, "open": 12,
                      "max_bid": 139, "full": False}
    assert s["B"]["max_bid"] == 188


def test_validate_rejections():
    player = {"id": "9", "name": "X"}
    picks = [{"player_id": "9", "team": "A", "price": 5}]
    with pytest.raises(D.DraftError) as e:
        D.validate_pick(player, "B", 5, T, picks, 200, 13)
    assert e.value.status == 409 and "already drafted" in e.value.message
    full = picks_for({"A": 13})
    with pytest.raises(D.DraftError, match="already has 13"):
        D.validate_pick({"id": "x", "name": "Y"}, "A", 1, T, full, 200, 13)
    with pytest.raises(D.DraftError, match="above the max bid"):
        D.validate_pick({"id": "x", "name": "Y"}, "B", 189, T, [], 200, 13)
    assert D.validate_pick({"id": "x", "name": "Y"}, "B", 188, T, [], 200, 13) == 188
    with pytest.raises(D.DraftError):
        D.validate_pick({"id": "x", "name": "Y"}, "B", 0, T, [], 200, 13)
    with pytest.raises(D.DraftError):
        D.validate_pick({"id": "x", "name": "Y"}, "Z", 1, T, [], 200, 13)


def test_resolve_skips_full_teams():
    counts = {"A": 0, "B": 13, "C": 0, "D": 0}
    assert D.resolve_turn(1, T, counts, 13) == 2
    assert D.resolve_turn(5, T, counts, 13) == 2      # wraps
    assert D.resolve_turn(0, T, {t: 13 for t in T}, 13) is None


def test_skip_never_nominates_twice_in_a_row():
    # Old bug: raw index 1 (B, full) resolved to C; advancing the raw index to 2
    # gave C again. Advancing from the resolved team gives D.
    counts = {"A": 0, "B": 13, "C": 0, "D": 0}
    idx = 1
    seen = []
    for _ in range(6):
        seen.append(T[D.resolve_turn(idx, T, counts, 13)])
        idx = D.advance_turn(idx, T, counts, counts, 13)
    assert seen == ["C", "D", "A", "C", "D", "A"]
    assert all(a != b for a, b in zip(seen, seen[1:]))


def test_advance_uses_counts_before_the_pick():
    # A nominates and buys its 13th player: the turn goes to B, not C.
    before = {"A": 12, "B": 0, "C": 0, "D": 0}
    after = {"A": 13, "B": 0, "C": 0, "D": 0}
    assert D.advance_turn(0, T, before, after, 13) == 1


def test_advance_when_everyone_is_full():
    counts = {t: 13 for t in T}
    assert D.advance_turn(2, T, counts, counts, 13) == 2
