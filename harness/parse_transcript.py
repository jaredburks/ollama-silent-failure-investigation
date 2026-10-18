"""Parse the CLI session log (qwen_transcript.txt) into sessions of turns.

Each turn: user text, original thinking text, original answer text, and whether
the original turn produced an answer ("...done thinking." followed by text).
"""
import json, re, sys

NOISE = {"Send a message (/? for help)", "Use Ctrl + d or /bye to exit."}

def clean(s):
    return s.replace("\u200b", "").replace("\f", "").rstrip()

def parse(path):
    lines = [clean(l) for l in open(path, encoding="utf-8")]
    sessions, cur, turn, mode = [], None, None, None

    def close_turn():
        nonlocal turn
        if turn is not None and cur is not None:
            for k in ("user", "thinking", "answer"):
                turn[k] = re.sub(r"[ \t]+", " ", turn[k]).strip()
            turn["answered"] = turn["done_thinking"] and bool(turn["answer"])
            cur["turns"].append(turn)
        turn = None

    for i, l in enumerate(lines, 1):
        if re.match(r"C:\\Users\\\w+>ollama run qwen3\.5\s*$", l):
            close_turn()
            cur = {"model": "qwen3.5", "start_line": i, "turns": []}
            sessions.append(cur); mode = None; continue
        if cur is None:
            continue
        if l.startswith("C:\\Users\\"):           # back at the shell prompt
            close_turn(); cur = None; continue
        if l.startswith(">>>"):
            text = l[3:].strip()
            if text in NOISE or text == "":
                # bare ">>>" can precede a prompt that the PDF wrapped onto the next line
                close_turn(); mode = "await_user" if text == "" else None; continue
            if text == "/bye":
                close_turn(); continue
            close_turn()
            turn = {"line": i, "user": text, "thinking": "", "answer": "", "done_thinking": False}
            mode = "user"; continue
        if mode == "await_user" and l.strip() == "Thinking...":
            turn = {"line": i, "user": "", "thinking": "", "answer": "", "done_thinking": False}
            mode = "thinking"; continue
        if mode == "await_user" and l.strip():
            turn = {"line": i, "user": l.strip(), "thinking": "", "answer": "", "done_thinking": False}
            mode = "user"; continue
        if turn is None:
            continue
        if l.strip() == "Thinking...":
            mode = "thinking"; continue
        if l.strip() == "...done thinking.":
            turn["done_thinking"] = True; mode = "answer"; continue
        if mode == "user":
            if l.startswith("... "):              # CLI hard wrap: no space at the join
                turn["user"] += l[4:]
            elif l.strip():                       # PDF soft wrap: join with a space
                turn["user"] += " " + l.strip()
        elif mode in ("thinking", "answer"):
            turn[mode] += "\n" + l
    close_turn()

    # The source document was assembled from overlapping copy-pastes, so some
    # blocks of turns appear twice back to back (PDF page overlap). The CLI
    # history file (~/.ollama/history) confirms each was sent once. Drop a block
    # of n turns that exactly repeats the preceding n user messages, unless the
    # messages are trivially short ("?"), which the history shows were real repeats.
    # n == 1 repeats are only dropped when the model output is also identical,
    # which cannot happen by sampling at temperature 1.
    for s in sessions:
        T = s["turns"]; i = 1; dropped = []
        while i < len(T):
            hit = False
            for n in range(min(4, i, len(T) - i), 0, -1):
                a, b = T[i - n:i], T[i:i + n]
                if [t["user"] for t in a] != [t["user"] for t in b]:
                    continue
                if any(len(t["user"]) <= 3 for t in a):
                    continue
                if n == 1 and (a[0]["thinking"], a[0]["answer"]) != (b[0]["thinking"], b[0]["answer"]) \
                        and a[0]["user"] != "What should I do":
                    continue
                dropped += [t["line"] for t in b]; del T[i:i + n]; hit = True; break
            if not hit:
                i += 1
        s["dropped_duplicate_lines"] = dropped
    # Prompts lost in PDF extraction (a bare ">>>" followed directly by
    # "Thinking..."; most likely emoji-only input) are kept with empty text and
    # flagged, because they still occupied context in the original session.
    for s in sessions:
        for t in s["turns"]:
            t["user_lost"] = t["user"] == ""
    return [s for s in sessions if s["turns"]]

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "data/qwen_transcript.txt"
    dst = sys.argv[2] if len(sys.argv) > 2 else "data/sessions.json"
    S = parse(src)
    json.dump(S, open(dst, "w"), indent=1, ensure_ascii=False)
    for k, s in enumerate(S, 1):
        n = len(s["turns"]); silent = sum(not t["answered"] for t in s["turns"])
        print(f"session {k}: line {s['start_line']}, {n} turns, {silent} unanswered in original")
