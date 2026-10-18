"""Build the canonical replay input: data/turns.json.

User prompts come from two sources:
  * ~/.ollama/history (exact keystrokes, but it only covers the later part of session 1
    plus all of session 2), and
  * qwen_transcript.txt (covers everything, but it went through a PDF, which lost emoji,
    duplicated some page overlaps, and dropped a few prompts).
Where the history covers a turn, its text is used. The transcript supplies the earlier
turns and the original model output (thinking/answer), which is what verbatim mode
replays and what gives the ground truth for silent vs. answered.
"""
import json, difflib
from parse_transcript import parse

def load_history(path):
    out = []
    for l in open(path, encoding="utf-8"):
        l = l.rstrip("\n")
        if l.startswith("... ") and out:
            out[-1] += l[4:]
        else:
            out.append(l.strip())
    sessions, cur = [], []
    for l in out:
        if l == "/bye":
            sessions.append(cur); cur = []
        else:
            cur.append(l)
    if cur:
        sessions.append(cur)
    return sessions

def key(s):
    return "".join(ch for ch in s.lower() if ch.isalnum())[:40]

def merge(tx_turns, hist, prefix_ok):
    """Align history prompts onto transcript turns; history wins on text."""
    a = [key(t["user"]) for t in tx_turns]
    b = [key(h) for h in hist]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    out = []
    first_b = None
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                out.append(dict(tx_turns[i], user=hist[j], source="history+transcript"))
            first_b = j1 if first_b is None else first_b
        elif tag == "delete":       # transcript-only turns
            for i in range(i1, i2):
                t = tx_turns[i]
                if first_b is None and prefix_ok:
                    out.append(dict(t, source="transcript"))      # before history coverage
                elif t["user"] == "Send a messag" or not t["user"]:
                    if t["user"]:
                        continue                                    # PDF artifact
                    out.append(dict(t, source="transcript"))
                elif out and key(out[-1]["user"]) == key(t["user"]):
                    continue                                    # page-overlap duplicate
                else:
                    out.append(dict(t, source="transcript-only"))
        elif tag == "insert":       # history-only prompts: no record of the original output
            for j in range(j1, j2):
                out.append({"user": hist[j], "thinking": "", "answer": "", "done_thinking": None,
                            "answered": None, "source": "history-only", "line": None, "user_lost": False})
        else:                       # replace: same slot, history text, transcript output
            n = min(i2 - i1, j2 - j1)
            for k in range(n):
                out.append(dict(tx_turns[i1 + k], user=hist[j1 + k], source="history+transcript(fixed)"))
            for i in range(i1 + n, i2):
                out.append(dict(tx_turns[i], source="transcript-only"))
            for j in range(j1 + n, j2):
                out.append({"user": hist[j], "thinking": "", "answer": "", "done_thinking": None,
                            "answered": None, "source": "history-only", "line": None, "user_lost": False})
    return out

if __name__ == "__main__":
    S = parse("data/qwen_transcript.txt")
    H = load_history("data/ollama_cli_history.txt")
    assert len(S) == 2 and len(H) >= 2
    sessions = [merge(S[0]["turns"], H[0], True), merge(S[1]["turns"], H[1], False)]
    for T in sessions:   # page-overlap duplicates left after alignment (history shows one send)
        i = 1
        while i < len(T):
            if len(T[i]["user"]) > 3 and T[i]["user"] == T[i - 1]["user"]:
                drop = i if T[i]["source"] == "transcript-only" else i - 1
                del T[drop]
            else:
                i += 1
    # the user typed "ollama stop qwen3.5" into the chat by mistake; it was sent as a prompt
    json.dump([{"session": k + 1, "turns": T} for k, T in enumerate(sessions)],
              open("data/turns.json", "w"), indent=1, ensure_ascii=False)
    for k, T in enumerate(sessions, 1):
        from collections import Counter
        print(f"session {k}: {len(T)} turns", dict(Counter(t["source"] for t in T)),
              "orig silent:", sum(t["answered"] is False for t in T),
              "orig answered:", sum(t["answered"] is True for t in T))
        for j, t in enumerate(T):
            if t["source"] not in ("history+transcript", "transcript"):
                print("   ", j, t["source"], repr(t["user"][:70]))
