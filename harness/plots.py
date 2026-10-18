"""Figures for the incident report.  python harness/plots.py runs results"""
import glob, json, os, statistics, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"      # categorical slots 1-3 (validated)
INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": MUTED,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF})

def load(p):
    L = [json.loads(l) for l in open(p, encoding="utf-8")]
    return L[0]["condition"], L[1:]

def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)

def fig_rates(runs, out):
    ctxs = [4096, 8192, 32768]
    rate = {}
    for c, T in runs:
        if c["mode"] != "live":
            continue
        ok = [t for t in T if not t["error"]]
        rate.setdefault((c["num_ctx"], c["think"]), []).append(100 * sum(t["answer_empty"] for t in ok) / len(ok))
    fig, ax = plt.subplots(figsize=(7, 3.8))
    w = 0.36
    for k, (think, col) in enumerate((("on", BLUE), ("off", ORANGE))):
        xs = [i + (k - 0.5) * w for i in range(len(ctxs))]
        means = [statistics.mean(rate[(c, think)]) for c in ctxs]
        ax.bar(xs, means, w - 0.04, color=col, label=f"thinking {think}", zorder=2)
        for x, c in zip(xs, ctxs):
            ax.scatter([x] * len(rate[(c, think)]), rate[(c, think)], s=14, color=INK, zorder=3,
                       label="individual seed" if (k == 0 and c == 4096) else None)
        for x, m in zip(xs, means):
            ax.text(x, m + 2, f"{m:.0f}%", ha="center", va="bottom", color=INK, fontsize=9)
    ax.set_xticks(range(len(ctxs)), [f"num_ctx {c}" for c in ctxs])
    ax.set_ylabel("turns with an empty answer (%)"); ax.set_ylim(0, 100)
    ax.set_title("Empty answers by context window and thinking mode\n(qwen3.5 9.7B, 119 replayed turns, 3 seeds each)",
                 fontsize=10.5, color=INK, loc="left")
    style(ax); ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig1_empty_rate.png"), dpi=160); plt.close(fig)

def fig_budget(runs, out):
    c, T = next((c, T) for c, T in runs if c["mode"] == "live" and c["num_ctx"] == 4096
                and c["think"] == "on" and c["seed"] == 1)
    T = [t for t in T if t["session"] == 1]
    x = [t["turn"] for t in T]
    p = [t["prompt_eval_count"] for t in T]
    o = [t["eval_count"] for t in T]
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(x, p, 0.85, color=BLUE, zorder=2)
    ax.bar(x, o, 0.85, bottom=p, color=[ORANGE if t["answer_empty"] else AQUA for t in T], zorder=2)
    from matplotlib.patches import Patch
    handles = [Patch(color=BLUE, label="prompt (conversation history)"),
               Patch(color=AQUA, label="generated, reached an answer"),
               Patch(color=ORANGE, label="generated, cut off in thinking (empty answer)")]
    ax.axhline(4096, color=INK, ls="--", lw=1)
    ax.text(-0.5, 4170, "num_ctx = 4096 (Ollama's automatic default for an 8 GB GPU)", fontsize=8.5, color=INK2)
    d0 = next(t["turn"] for t in T if t["user"] == "I need help")
    ax.axvspan(d0 - 0.5, x[-1] + 0.5, color=GRID, alpha=0.6, zorder=1, lw=0)
    ax.text(d0 - 0.2, 4170, "distress messages:\n0 of 7 answered", fontsize=8.5, color=INK2, va="bottom")
    ax.set_xlim(-0.8, x[-1] + 0.8); ax.set_ylim(0, 5000)
    ax.set_xlabel("turn (session 1 replay, seed 1)"); ax.set_ylabel("tokens")
    fig.suptitle("One 4096-token window per turn: as history grows, thinking runs out of room before any answer token", fontsize=10.5, color=INK, x=0.01, ha="left")
    style(ax); ax.legend(handles=handles, frameon=False, fontsize=8.5, ncol=3, loc="lower left",
                         bbox_to_anchor=(0, 1.0), borderaxespad=0.2)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig2_token_budget.png"), dpi=160); plt.close(fig)

def fig_selfreports(out):
    d = json.load(open(os.path.join(os.path.dirname(out.rstrip("/")) or ".", "analysis", "self_reports.json")))
    order = [("timeout_error", "timeout / error / glitch"), ("safety_filter", "safety filter"),
             ("message_limit", "message length limit"), ("token_limit_mentioned", "\"token limit\" (one of several guesses)"),
             ("context_window_thinking", "thinking filled the context window (actual cause)")]
    n = len(d["items"])
    vals = [sum(k in i["labels"] for i in d["items"]) for k, _ in order]
    fig, ax = plt.subplots(figsize=(8, 3.2))
    y = list(range(len(order)))[::-1]
    ax.barh(y, vals, 0.6, color=BLUE, zorder=2)
    for yy, v in zip(y, vals):
        ax.text(v + 0.15, yy, f"{v} of {n}", va="center", fontsize=9, color=INK)
    ax.set_yticks(y, [lbl for _, lbl in order]); ax.set_xlim(0, n)
    ax.set_xlabel("answers citing this cause (one answer can cite several)")
    fig.suptitle(f"What the model said caused its silences ({n} explanations)", fontsize=10.5, color=INK, x=0.01, ha="left")
    ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)
    fig.tight_layout(); fig.savefig(os.path.join(out, "fig3_self_reports.png"), dpi=160); plt.close(fig)

if __name__ == "__main__":
    rundir, out = (sys.argv[1:3] + ["runs", "results"])[:2] if len(sys.argv) > 1 else ("runs", "results")
    os.makedirs(out, exist_ok=True)
    runs = [load(p) for p in sorted(glob.glob(os.path.join(rundir, "*.jsonl")))]
    fig_rates(runs, out); fig_budget(runs, out); fig_selfreports(out)
    print("figures written to", out)
