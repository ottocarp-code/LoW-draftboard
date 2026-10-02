"""
Record a test set of real voice commands: for each line of a script built from the
running app (teams and players), you say the command, the take is cut at the end
of the sentence by the same VAD as the listener, and a 16 kHz wav plus the
expected text land in data/recordings/<speaker>/ (manifest.jsonl). That set is the
benchmark for the voice accuracy plan (phase 0).

    py voice/record.py --speaker otto                 about 35 commands
    py voice/record.py --speaker otto --players 20    more players
    py voice/record.py --speaker otto --device Headset

Per take: Enter records, s skips, q stops. After a take you see what base.en heard
(as the listener would hear it); Enter keeps it, r records it again. Running the
same command again resumes where you stopped. The app must be running.
"""

import argparse
import json
import os
import queue
import random
import re
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from listen import (FRAME, RATE, Segmenter, Server, StreamVad, _utf8_console,  # noqa: E402
                    hotwords_from_server, load_model, pick_device, transcribe)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "recordings")
AMOUNTS = [1, 2, 3, 5, 7, 10, 12, 15, 18, 20, 25, 33, 40, 48, 55, 61, 72, 85, 99, 120]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build_script(teams, players, n_players=15, n_extra=5, n_picks=5, seed=7):
    """
    The commands to record, as dicts {id, say, expect}. players: names, best first.
    The top `n_players` plus `n_extra` drawn from the rest get a nomination, every
    team gets a "sold to", and `n_picks` one-step picks mix both. Deterministic per seed.
    """
    rng = random.Random(seed)
    top = list(players[:n_players])
    rest = list(players[n_players:])
    chosen = top + rng.sample(rest, min(n_extra, len(rest)))
    script = []
    for p in chosen:
        script.append({"id": f"nominate-{slug(p)}", "say": f"ok banana nominate {p}",
                       "expect": {"kind": "nominate", "player": p}})
    for t in teams:
        a = rng.choice(AMOUNTS)
        script.append({"id": f"sold-{slug(t)}-{a}", "say": f"ok banana sold to {t} for {a} dollars",
                       "expect": {"kind": "sold", "team": t, "amount": a}})
    for p, t in zip(rng.sample(chosen, min(n_picks, len(chosen))), rng.sample(teams, min(n_picks, len(teams)))):
        a = rng.choice(AMOUNTS)
        script.append({"id": f"pick-{slug(p)}-{slug(t)}-{a}", "say": f"ok banana {p} to {t} for {a} dollars",
                       "expect": {"kind": "pick", "player": p, "team": t, "amount": a}})
    return script


def record_utterance(device, wait_s=6.0, max_s=8.0):
    """One utterance from the mic, cut by the listener's VAD; None if nobody spoke in time."""
    import numpy as np
    import sounddevice as sd
    vad, seg = StreamVad(), Segmenter(max_s=max_s)
    q = queue.Queue()
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=FRAME,
                        device=device, callback=lambda d, f, t, s: q.put(d[:, 0].copy())):
        t0, buf = time.monotonic(), np.zeros(0, dtype="float32")
        while True:
            buf = np.concatenate([buf, q.get()])
            while len(buf) >= FRAME:
                frame, buf = buf[:FRAME], buf[FRAME:]
                utt = seg.push(frame, vad(frame))
                if utt is not None:
                    return np.concatenate(utt)
            if seg.cur is None and time.monotonic() - t0 > wait_s:
                return None


def save_wav(path, audio):
    import numpy as np
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def ask(question):
    try:
        return input(question).strip().lower()
    except EOFError:
        return "q"


def main(argv=None):
    _utf8_console()
    ap = argparse.ArgumentParser(description="Record real voice commands as a test set.")
    ap.add_argument("--speaker", required=True, help="who speaks (folder name), e.g. otto")
    ap.add_argument("--server", default="http://127.0.0.1:8000")
    ap.add_argument("--device", help="input device index or part of its name")
    ap.add_argument("--players", type=int, default=15, help="top players by rank to nominate")
    ap.add_argument("--extra", type=int, default=5, help="extra players drawn from the rest")
    ap.add_argument("--picks", type=int, default=5, help="one-step picks (player to team for amount)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--model", default="base.en", help="model for the check after each take")
    args = ap.parse_args(argv)

    server = Server(args.server)
    try:
        state = server.get("/api/state")
        players = server.get("/api/players").get("players") or []
    except OSError as e:
        raise SystemExit(f"The app is not reachable at {args.server} ({e}). Start it first (run.bat).")
    teams = [t["name"] for t in state["teams"]]
    names = [p["name"] for p in sorted(players, key=lambda p: p.get("espn_rank") or 1e9)]
    script = build_script(teams, names, args.players, args.extra, args.picks, args.seed)

    folder = os.path.join(OUT, slug(args.speaker))
    os.makedirs(folder, exist_ok=True)
    manifest = os.path.join(folder, "manifest.jsonl")
    done = set()
    if os.path.exists(manifest):
        with open(manifest, encoding="utf-8") as f:
            done = {json.loads(line)["id"] for line in f if line.strip()}
    todo = [s for s in script if s["id"] not in done]
    print(f"{len(script)} commands, {len(done)} already recorded, {len(todo)} to go. Folder: {folder}")

    device = pick_device(args.device)
    model = load_model(args.model)
    hotwords = hotwords_from_server(server)
    print('\nSay each line as you would on draft night, in one breath with "ok banana".\n')
    for i, item in enumerate(todo, 1):
        while True:
            a = ask(f'[{i}/{len(todo)}] Enter = record, s = skip, q = stop.   Say: "{item["say"]}" ')
            if a == "q":
                print("Stopped. Run the same command again to continue.")
                return 0
            if a == "s":
                break
            print("  listening...")
            audio = record_utterance(device)
            if audio is None:
                print("  Nothing heard. Try again.")
                continue
            t0 = time.perf_counter()
            heard = transcribe(model, audio, hotwords)
            asr = time.perf_counter() - t0
            print(f'  heard ({len(audio) / RATE:.1f} s, asr {asr:.2f} s): "{heard}"')
            if ask("  Enter = keep, r = record again: ") == "r":
                continue
            fname = item["id"] + ".wav"
            save_wav(os.path.join(folder, fname), audio)
            with open(manifest, "a", encoding="utf-8") as f:
                f.write(json.dumps({**item, "file": fname, "speaker": args.speaker,
                                    "heard": heard, "asr_s": round(asr, 3), "model": args.model,
                                    "recorded": time.strftime("%Y-%m-%d %H:%M:%S")},
                                   ensure_ascii=False) + "\n")
            break
    print(f"\nDone: {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
