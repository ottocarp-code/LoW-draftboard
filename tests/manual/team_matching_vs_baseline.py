# Manual check, not collected by pytest (2026-10-02): without articles, match_team must equal the parser of
# 5ab556a (before the team buttons). Real league teams and calibration nicknames, 40
# random one-letter edits per name and nickname, plus a few real transcripts.
import sys, random, subprocess, importlib.util, os, tempfile
ROOT = r"D:\Documenten\Personal\LoW"; sys.path.insert(0, os.path.join(ROOT, "app"))
import parser as NEW
base = os.path.join(tempfile.gettempdir(), "parser_5ab556a.py")
open(base, "wb").write(subprocess.run(["git", "show", "5ab556a:app/parser.py"], cwd=ROOT, capture_output=True).stdout)
spec = importlib.util.spec_from_file_location("parser_base", base); OLD = importlib.util.module_from_spec(spec); spec.loader.exec_module(OLD)
T = ['RoRo','RJ','Gillese','sexylexy','Ceun','Champximmissioner','Lode','hotto','stijn','Miele','elianus','Dave']
AL = {'sexylexy': ['sexy lexi'], 'Ceun': ['kun'], 'Lode': ['lode for', 'loda'], 'stijn': ['stan'], 'Dave': ['day']}
random.seed(1); letters = "abcdefghijklmnopqrstuvwxyz"; qs = set()
for name in [n for t in T for n in [t] + AL.get(t, [])]:
    for _ in range(40):
        w = list(name.lower()); k = random.randrange(len(w)); op = random.choice("dis")
        if op == "d" and len(w) > 2: del w[k]
        elif op == "i": w.insert(k, random.choice(letters))
        else: w[k] = random.choice(letters)
        qs.add("".join(w))
qs |= {"gin", "today", "auto", "otto", "stan", "lexi", "me", "mine"}
qs = {q for q in qs if not q.startswith(("a ", "an ", "the "))}
diff = [q for q in sorted(qs) if OLD.match_team(q, T, "hotto", AL) != NEW.match_team(q, T, "hotto", AL)]
print(len(qs), "queries without an article; differences:", len(diff), diff[:10])
