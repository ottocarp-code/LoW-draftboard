"""
Voice listener: captures the mic of the app laptop, cuts it into utterances with
the Silero VAD that ships with faster-whisper, transcribes offline with Whisper,
and forwards only utterances that start with the wake word "ok banana" to
POST /api/command with source "voice". The server runs the same parser as the
typed command bar (F-30) and publishes the result in /api/state, so every screen
shows what was heard.

    py -m pip install -r voice/requirements.txt
    py voice/listen.py                      base.en, default mic, http://127.0.0.1:8000
    py voice/listen.py --model small.en     more accurate, slower
    py voice/listen.py --list-devices       pick a --device (index or part of the name)

The first run downloads the model (base.en 145 MB) from Hugging Face; after that
it loads with local_files_only and works without internet (N-2). The typed
command bar does not depend on this process (N-1).
"""

import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wake import build_hotwords, estimate_tokens, find_wake  # noqa: E402

RATE = 16000
FRAME = 512                  # Silero VAD window at 16 kHz (32 ms)
HEARTBEAT_S = 3
REFRESH_S = 15
TOP_PLAYERS = 60             # best available players offered as hotwords


# ---------------------------------------------------------------- console

def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def _utf8_console():
    # Windows consoles default to cp1252; a transcript with "Jokić" must not crash us.
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# ---------------------------------------------------------------- server

class Server:
    def __init__(self, base, timeout=4):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def _call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="GET" if body is None else "POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:     # 4xx carries a JSON body with the message
            try:
                return json.loads(e.read().decode("utf-8"))
            except ValueError:
                return {"ok": False, "message": f"HTTP {e.code}"}

    def get(self, path):
        return self._call(path)

    def post(self, path, body):
        return self._call(path, body)


def hotwords_from_server(server):
    """Wake word, teams, nicknames and the best available players, from the live state."""
    state = server.get("/api/state")
    players = server.get("/api/players").get("players") or []
    taken = {str(p["player_id"]) for p in state.get("picks") or []}
    avail = [p["name"] for p in sorted(players, key=lambda p: p.get("espn_rank") or 1e9)
             if str(p["id"]) not in taken][:TOP_PLAYERS]
    teams = [t["name"] for t in state.get("teams") or []]
    return build_hotwords(teams, state.get("aliases") or {}, avail)


# ---------------------------------------------------------------- VAD

class StreamVad:
    """
    Silero VAD (the model bundled with faster-whisper) run frame by frame, with
    its recurrent state carried across frames, so speech is detected while it
    streams in instead of on a finished recording.
    """

    def __init__(self):
        import numpy as np
        from faster_whisper.vad import get_vad_model
        self.np = np
        self.session = get_vad_model().session
        self.reset()

    def reset(self):
        np = self.np
        self.h = np.zeros((1, 1, 128), dtype="float32")
        self.c = np.zeros((1, 1, 128), dtype="float32")
        self.context = np.zeros(64, dtype="float32")

    def __call__(self, frame):
        np = self.np
        x = np.concatenate([self.context, frame]).astype("float32")[None, :]
        out, self.h, self.c = self.session.run(None, {"input": x, "h": self.h, "c": self.c})
        self.context = frame[-64:]
        return float(np.asarray(out).reshape(-1)[0])


class Segmenter:
    """
    Turns per-frame speech probabilities into utterances. An utterance starts at
    a frame above `threshold` (with `pad_ms` of audio before it), ends after
    `silence_ms` below `threshold - 0.15`, and is cut at `max_s`. Pure logic, so
    it can be tested without audio.
    """

    def __init__(self, frame=FRAME, rate=RATE, threshold=0.5, silence_ms=400,
                 max_s=8.0, pad_ms=200, min_ms=300):
        self.frame, self.rate = frame, rate
        self.on, self.off = threshold, max(threshold - 0.15, 0.01)
        ms = lambda v: max(1, int(round(v * rate / 1000 / frame)))  # noqa: E731
        self.silence_frames, self.pad_frames = ms(silence_ms), ms(pad_ms)
        self.min_frames = ms(min_ms)
        self.max_frames = int(max_s * rate / frame)
        self.pre, self.cur, self.quiet, self.voiced = [], None, 0, 0

    def push(self, frame, prob):
        """Returns a finished utterance (list of frames) or None."""
        if self.cur is None:
            if prob >= self.on:
                self.cur, self.quiet, self.voiced = self.pre + [frame], 0, 1
                self.pre = []
            else:
                self.pre = (self.pre + [frame])[-self.pad_frames:]
            return None
        self.cur.append(frame)
        if prob >= self.on:
            self.voiced += 1
            self.quiet = 0
        elif prob < self.off:
            self.quiet += 1
        if self.quiet >= self.silence_frames or len(self.cur) >= self.max_frames:
            done, voiced = self.cur, self.voiced
            self.cur, self.quiet, self.voiced = None, 0, 0
            if voiced >= self.min_frames:
                return done
        return None


# ---------------------------------------------------------------- model

def load_model(name, threads=0):
    """Offline first (local_files_only); only when the model is missing, download it once."""
    from faster_whisper import WhisperModel
    t0 = time.perf_counter()
    try:
        m = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads,
                         local_files_only=True)
        how = "from the local cache"
    except Exception:  # noqa: BLE001 - not downloaded yet (huggingface raises several types)
        log(f"Model {name} is not cached yet: downloading it once (needs internet)...")
        m = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)
        how = "downloaded; later runs work offline"
    log(f"Model {name} loaded {how} in {time.perf_counter() - t0:.1f} s.")
    return m


def transcribe(model, audio, hotwords):
    segments, _ = model.transcribe(audio, language="en", beam_size=1,
                                   condition_on_previous_text=False,
                                   without_timestamps=True, vad_filter=False,
                                   hotwords=hotwords or None)
    return " ".join(s.text.strip() for s in segments).strip()


# ---------------------------------------------------------------- devices

def pick_device(spec):
    """--device: an index, or part of an input device's name. None = system default."""
    if spec in (None, ""):
        return None
    import sounddevice as sd
    if str(spec).isdigit():
        return int(spec)
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and str(spec).lower() in d["name"].lower():
            return i
    raise SystemExit(f'No input device matches "{spec}". Run with --list-devices.')


def list_devices():
    import sounddevice as sd
    default_in = sd.default.device[0]
    print("Input devices (use --device <index> or part of the name):")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            api = sd.query_hostapis(d["hostapi"])["name"]
            mark = "*" if i == default_in else " "
            print(f" {mark}{i:3d}  {d['name']}  ({api}, {d['max_input_channels']} ch)")


# ---------------------------------------------------------------- main loop

class Listener:
    def __init__(self, args):
        self.args = args
        self.server = Server(args.server)
        self.muted = False
        self.hotwords = build_hotwords([], {}, [])
        self.stop = threading.Event()

    # Background: heartbeat every 3 s (the header shows "voice off" without it) and
    # a hotword refresh every 15 s (teams renamed, nicknames added, players taken).
    def _heartbeat(self):
        while not self.stop.is_set():
            try:
                r = self.server.post("/api/voice/heartbeat", {"model": self.args.model})
                if "muted" in r:           # an error response must not unmute us
                    muted = bool(r["muted"])
                    if muted != self.muted:
                        log("Muted from the app: listening but sending nothing." if muted
                            else "Unmuted from the app.")
                    self.muted = muted
                else:
                    log(f"Heartbeat refused: {r.get('message', r)}")
            except (OSError, ValueError) as e:
                log(f"Heartbeat failed ({e}); is the app running at {self.args.server}?")
            self.stop.wait(HEARTBEAT_S)

    def _refresh(self):
        while not self.stop.is_set():
            try:
                hw = hotwords_from_server(self.server)
                if hw != self.hotwords:
                    self.hotwords = hw
                    log(f"Hotwords updated (~{estimate_tokens(hw):.0f} tokens).")
            except (OSError, ValueError, KeyError) as e:
                log(f"Could not refresh hotwords ({e}).")
            self.stop.wait(REFRESH_S)

    def handle(self, frames, t_end):
        """frames: one utterance; t_end: wall clock at its end."""
        import numpy as np
        audio = np.concatenate(frames)
        dur = len(audio) / RATE
        if self.muted:
            log(f"[muted] {dur:.1f} s of speech ignored.")
            return
        t0 = time.perf_counter()
        text = transcribe(self.model, audio, self.hotwords)
        t_asr = time.perf_counter() - t0
        if not text:
            return
        cmd = find_wake(text)
        if cmd is None:
            log(f'  ({dur:.1f} s, asr {t_asr:.2f} s) no wake word: "{text}"')
            return
        if not cmd:
            log(f'  ({dur:.1f} s, asr {t_asr:.2f} s) wake word only: "{text}" '
                f'(say the command in the same breath)')
            return
        t1 = time.perf_counter()
        try:
            r = self.server.post("/api/command", {"text": cmd, "heard": text, "source": "voice"})
        except (OSError, ValueError) as e:
            log(f'  "{text}" -> could not reach the app ({e}).')
            return
        total = time.perf_counter() - t_end
        log(f'> "{text}"  ->  {r.get("kind")}: {r.get("message", "")}  '
            f'[{dur:.1f} s audio, asr {t_asr:.2f} s, server {time.perf_counter() - t1:.2f} s, '
            f'end-of-speech to result {total:.2f} s]')

    def run(self):
        import numpy as np
        import sounddevice as sd
        self.model = load_model(self.args.model, self.args.threads)
        vad = StreamVad()
        seg = Segmenter(silence_ms=self.args.silence_ms, max_s=self.args.max_s,
                        threshold=self.args.threshold)
        try:
            self.hotwords = hotwords_from_server(self.server)
        except (OSError, ValueError, KeyError) as e:
            log(f"App not reachable yet at {self.args.server} ({e}); retrying in the background.")
        for fn in (self._heartbeat, self._refresh):
            threading.Thread(target=fn, daemon=True).start()

        q = queue.Queue(maxsize=int(30 * RATE / FRAME))       # ~30 s of backlog at most

        def on_audio(indata, frames, t, status):
            if status:
                log(f"audio: {status}")
            try:
                q.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass

        device = pick_device(self.args.device)
        with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=FRAME,
                            device=device, callback=on_audio):
            name = sd.query_devices(device if device is not None else sd.default.device[0])["name"]
            log(f'Listening on "{name}". Say "ok banana" followed by a command. Ctrl+C stops.')
            buf = np.zeros(0, dtype="float32")
            while True:
                buf = np.concatenate([buf, q.get()])
                while len(buf) >= FRAME:
                    frame, buf = buf[:FRAME], buf[FRAME:]
                    utt = seg.push(frame, vad(frame))
                    if utt is not None:
                        self.handle(utt, time.perf_counter())
                        vad.reset()


def main(argv=None):
    _utf8_console()
    ap = argparse.ArgumentParser(description='Voice listener for the LoW draftboard ("ok banana ...").')
    ap.add_argument("--model", default="base.en",
                    help="Whisper model: base.en (default, 145 MB) or small.en (484 MB, slower)")
    ap.add_argument("--server", default="http://127.0.0.1:8000", help="draftboard app URL")
    ap.add_argument("--device", help="input device index or part of its name (see --list-devices)")
    ap.add_argument("--list-devices", action="store_true", help="list input devices and exit")
    ap.add_argument("--threads", type=int, default=0, help="CPU threads for Whisper (0 = default)")
    ap.add_argument("--silence-ms", type=int, default=400, help="silence that ends an utterance")
    ap.add_argument("--max-s", type=float, default=8.0, help="longest utterance in seconds")
    ap.add_argument("--threshold", type=float, default=0.5, help="VAD speech threshold")
    args = ap.parse_args(argv)
    if args.list_devices:
        list_devices()
        return 0
    try:
        Listener(args).run()
    except KeyboardInterrupt:
        log("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
