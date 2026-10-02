"""
Calibration: hear how Whisper spells the team names in your voice, on your mic,
and save those spellings as team nicknames.

    py voice/calibrate.py                        every team, base.en and small.en
    py voice/calibrate.py --teams Miele,Ceun     only these teams
    py voice/calibrate.py --models base.en       one model

For each team you say a whole command twice, "ok banana curry to <team> for ten",
because that is how the name sounds on draft night. The script prints what each
model heard (and how long it took), whether the wake word was recognised, and
which team the parser would pick. Spellings that are not already the team name
or a nickname are offered as new nicknames and saved through /api/settings; they
then show in the settings panel and match in typed and spoken commands.

The app must be running (default http://127.0.0.1:8000).
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from listen import RATE, Server, _utf8_console, load_model, pick_device, transcribe  # noqa: E402
from wake import build_hotwords, find_wake  # noqa: E402

import parser as cmdparser  # noqa: E402  (app/parser.py, put on sys.path by wake.py)
from parser import SELF_WORDS, normalize  # noqa: E402

TAKES = 2


def record(seconds, device):
    import sounddevice as sd
    audio = sd.rec(int(seconds * RATE), samplerate=RATE, channels=1, dtype="float32",
                   device=device)
    sd.wait()
    return audio[:, 0]


def heard_team(text):
    """The team part of a transcribed "ok banana curry to <team> for ten", or None."""
    cmd = find_wake(text)
    body = cmd if cmd is not None else text
    parsed = cmdparser.parse_command(body)
    if parsed.get("kind") != "pick":
        return cmd is not None, None
    return cmd is not None, normalize(parsed["team"])


def ask(question):
    try:
        return input(question).strip().lower()
    except EOFError:
        return ""


def main(argv=None):
    _utf8_console()
    ap = argparse.ArgumentParser(description="Record team names and save Whisper's spellings as nicknames.")
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--models", default="base.en,small.en", help="comma separated")
    ap.add_argument("--teams", help="comma separated subset (default: every team)")
    ap.add_argument("--device", help="input device index or part of its name")
    ap.add_argument("--seconds", type=float, default=3.5, help="recording length per take")
    ap.add_argument("--yes", action="store_true", help="save every new spelling without asking")
    args = ap.parse_args(argv)

    server = Server(args.server)
    try:
        state = server.get("/api/state")
    except OSError as e:
        raise SystemExit(f"The app is not reachable at {args.server} ({e}). Start it first (run.bat).")
    teams = [t["name"] for t in state["teams"]]
    aliases = {t: list(v) for t, v in (state.get("aliases") or {}).items()}
    wanted = teams
    if args.teams:
        want = {normalize(x) for x in args.teams.split(",")}
        wanted = [t for t in teams if normalize(t) in want]
        if not wanted:
            raise SystemExit(f"None of {args.teams} is a team. Teams: {', '.join(teams)}")

    device = pick_device(args.device)
    models = {m: load_model(m) for m in [m.strip() for m in args.models.split(",") if m.strip()]}
    hotwords = build_hotwords(teams, aliases)
    print(f"\nHotwords: {hotwords}\n")

    found = {t: [] for t in wanted}          # new spellings per team
    timing = {m: [] for m in models}
    wake_miss = {m: 0 for m in models}
    for team in wanted:
        for take in range(1, TAKES + 1):
            ask(f'[{team}, take {take}/{TAKES}] Press Enter, then say: '
                f'"ok banana curry to {team} for ten" ')
            audio = record(args.seconds, device)
            for name, model in models.items():
                t0 = time.perf_counter()
                text = transcribe(model, audio, hotwords)
                dt = time.perf_counter() - t0
                timing[name].append(dt)
                woke, heard = heard_team(text)
                wake_miss[name] += not woke
                match, why = cmdparser.match_team(heard or "", teams, None, aliases)
                print(f'  {name:9s} {dt:5.2f} s  "{text}"')
                print(f'  {"":9s}          wake word {"ok" if woke else "MISSED"}, team heard '
                      f'"{heard or "?"}" -> {match or "no match"} ({why})')
                known = {normalize(team)} | {normalize(a) for a in aliases.get(team, [])}
                if heard and heard not in known and heard not in found[team]:
                    found[team].append(heard)

    print("\nTiming per model (per take, audio of %.1f s):" % args.seconds)
    for name, ts in timing.items():
        print(f"  {name:9s} mean {sum(ts) / len(ts):.2f} s, max {max(ts):.2f} s, "
              f"wake word missed {wake_miss[name]}/{len(ts)}")

    # A spelling heard for two teams, or one that means "me", would make the server
    # reject the whole /api/settings post (and every accepted nickname with it).
    heard_for = {}
    for team, spellings in found.items():
        for s in spellings:
            heard_for.setdefault(s, set()).add(team)
    new = {}
    for team, spellings in found.items():
        for s in spellings:
            if s in SELF_WORDS:
                print(f'  "{s}" for {team} already means "me": not offered.')
                continue
            if len(heard_for[s]) > 1:
                print(f'  "{s}" was heard for {" and ".join(sorted(heard_for[s]))}: not offered.')
                continue
            owner = next((t for t in teams if t != team and
                          (normalize(t) == s or s in {normalize(a) for a in aliases.get(t, [])})),
                         None)
            if owner:
                print(f'  "{s}" for {team} is already {owner}: not offered.')
                continue
            if len(aliases.get(team, [])) + len(new.get(team, [])) >= 5:
                print(f'  {team} already has 5 nicknames: "{s}" not offered.')
                continue
            if args.yes or ask(f'Save "{s}" as a nickname of {team}? [y/N] ') in ("y", "yes", "j", "ja"):
                new.setdefault(team, []).append(s)
    if not new:
        print("\nNo new nicknames to save.")
        return 0
    merged = {t: aliases.get(t, []) + new.get(t, []) for t in teams}
    r = server.post("/api/settings", {"aliases": merged})
    if not r.get("ok"):
        print(f"\nNot saved: {r.get('message')}")
        return 1
    for t, v in new.items():
        print(f"Saved for {t}: {', '.join(v)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
