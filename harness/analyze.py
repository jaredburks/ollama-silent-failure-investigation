"""Summarise replay runs: empty-answer rate per condition and its link to done_reason.

    python harness/analyze.py runs/          -> results/summary.csv, results/summary.md, plots
"""
import collections, csv, glob, json, os, sys

def load(path):
    env, turns = None, []
    for l in open(path, encoding="utf-8"):
        r = json.loads(l)
        if r["type"] == "env":
            env = r
        else:
            turns.append(r)
    return env, turns

def summarise(turns):
    n = len(turns)
    empty = [t for t in turns if t["answer_empty"] and not t["error"]]
    length = [t for t in turns if t["done_reason"] == "length"]
    both = [t for t in empty if t["done_reason"] == "length"]
    distress = [t for t in turns if t["user"].strip().lower().rstrip("!") in
                ("i need help", "please", "what should i do") or "someone to talk to" in t["user"]]
    return {
        "turns": n,
        "errors": sum(bool(t["error"]) for t in turns),
        "empty": len(empty),
        "empty_rate": round(len(empty) / n, 3) if n else None,
        "done_length": len(length),
        "empty_and_length": len(both),
        "empty_not_length": len(empty) - len(both),
        "first_empty_turn": min((f"s{t['session']}t{t['turn']}" for t in empty), default="",
                                key=lambda s: (s[1], int(s.split("t")[1])) if s else (9, 0)),
        "distress_turns": len(distress),
        "distress_answered": sum(not t["answer_empty"] for t in distress),
        "max_prompt": max((t["prompt_eval_count"] or 0) for t in turns) if turns else 0,
        "median_wall_s": sorted(t["wall_s"] for t in turns)[n // 2] if n else None,
    }

def main(rundir, outdir):
    os.makedirs(outdir, exist_ok=True)
    rows, per_turn = [], {}
    for p in sorted(glob.glob(os.path.join(rundir, "*.jsonl"))):
        env, turns = load(p)
        if not turns:
            continue
        c = env["condition"]
        s = summarise(turns)
        rows.append({"file": os.path.basename(p), "mode": c["mode"], "num_ctx": c["num_ctx"],
                     "think": c["think"], "seed": c["seed"], **s})
        per_turn[os.path.basename(p)] = (c, turns)
    rows.sort(key=lambda r: (r["mode"], r["num_ctx"], r["think"], r["seed"]))
    if rows:
        with open(os.path.join(outdir, "summary.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    # aggregate over seeds
    agg = collections.OrderedDict()
    for r in rows:
        k = (r["mode"], r["num_ctx"], r["think"])
        a = agg.setdefault(k, collections.Counter())
        for f in ("turns", "empty", "done_length", "empty_and_length", "distress_turns", "distress_answered"):
            a[f] += r[f]
        a["seeds"] += 1
    md = ["| mode | num_ctx | thinking | seeds | turns | empty answers | empty rate | empty with done_reason=length | distress msgs answered |",
          "|---|---|---|---|---|---|---|---|---|"]
    for (mode, ctx, think), a in agg.items():
        md.append(f"| {mode} | {ctx} | {think} | {a['seeds']} | {a['turns']} | {a['empty']} | "
                  f"{a['empty'] / a['turns']:.0%} | {a['empty_and_length']}/{a['empty']} | "
                  f"{a['distress_answered']}/{a['distress_turns']} |")
    open(os.path.join(outdir, "summary.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))
    # figures: harness/plots.py

def plot(per_turn, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    live = {k: v for k, v in per_turn.items() if v[0]["mode"] == "live" and v[0]["seed"] == 1}
    ctxs = sorted({c["num_ctx"] for c, _ in live.values()})
    if not ctxs:
        return
    fig, axes = plt.subplots(len(ctxs), 2, figsize=(12, 3.2 * len(ctxs)), squeeze=False, sharex="col")
    for i, ctx in enumerate(ctxs):
        for j, sess in enumerate((1, 2)):
            ax = axes[i][j]
            for think, color in (("on", "#2a6fdb"), ("off", "#8a8a8a")):
                hit = [v for v in live.values() if v[0]["num_ctx"] == ctx and v[0]["think"] == think]
                if not hit:
                    continue
                T = [t for t in hit[0][1] if t["session"] == sess]
                x = [t["turn"] for t in T]
                y = [(t["prompt_eval_count"] or 0) + (t["eval_count"] or 0) for t in T]
                ax.plot(x, y, color=color, lw=1.4, label=f"thinking {think}: prompt + output tokens")
                ex = [t["turn"] for t in T if t["answer_empty"]]
                ey = [(t["prompt_eval_count"] or 0) + (t["eval_count"] or 0) for t in T if t["answer_empty"]]
                ax.scatter(ex, ey, color="#d6402b" if think == "on" else "#f0a03c", s=22, zorder=3,
                           label=f"thinking {think}: empty answer")
            ax.axhline(ctx, color="black", ls="--", lw=1)
            ax.set_title(f"session {sess}, num_ctx={ctx}", fontsize=10)
            ax.set_ylabel("tokens")
            if i == len(ctxs) - 1:
                ax.set_xlabel("turn")
            ax.spines[["top", "right"]].set_visible(False)
    axes[0][0].legend(fontsize=7, frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "tokens_per_turn.png"), dpi=150)
    print("wrote", os.path.join(outdir, "tokens_per_turn.png"))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "runs", sys.argv[2] if len(sys.argv) > 2 else "results")
