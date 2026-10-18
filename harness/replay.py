"""Replay the Qwen "silence" sessions against Ollama's HTTP API and log every turn.

Standard library only, so it runs on a bare Windows Python.

    python replay.py --num-ctx 4096 --think on --seed 1 --session 1
    python replay.py --grid            # full condition grid, resumable

Modes
  live      the model's own new replies go into history (matches the original CLI behaviour)
  verbatim  the ORIGINAL assistant output from the transcript goes into history, so every
            condition sees the same prompt sequence; the new reply is logged and discarded

Each turn is logged as one JSON line. Use the Ollama server log (server.log) next to it
for the server-side view: task.n_tokens (the full prompt) and truncated=0/1.
"""
import argparse, json, os, platform, sys, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The model's own Modelfile parameters (blob sha256:9371364b...), set explicitly so the
# run doesn't depend on server defaults. Only seed and num_ctx vary between conditions.
MODEL_PARAMS = {"temperature": 1.0, "top_k": 20, "top_p": 0.95, "presence_penalty": 1.5}


def http(host, path, body=None, timeout=900):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(host + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def environment(host, model):
    env = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "host": host, "model": model,
           "os": platform.platform(), "python": sys.version.split()[0],
           "machine": platform.node()}
    try:
        env["ollama_version"] = http(host, "/api/version")["version"]
    except Exception as e:
        env["ollama_version_error"] = repr(e)
    try:
        tags = http(host, "/api/tags")["models"]
        env["model_digest"] = next((m["digest"] for m in tags if m["name"] in (model, model + ":latest")), None)
    except Exception as e:
        env["tags_error"] = repr(e)
    try:
        show = http(host, "/api/show", {"model": model})
        env["model_details"] = show.get("details")
        env["model_parameters"] = show.get("parameters")
        env["capabilities"] = show.get("capabilities")
        mi = show.get("model_info") or {}
        env["context_length_trained"] = next((v for k, v in mi.items() if k.endswith("context_length")), None)
    except Exception as e:
        env["show_error"] = repr(e)
    return env


def run(args, session_ids, out_path):
    turns_doc = json.load(open(os.path.join(ROOT, "data", "turns.json"), encoding="utf-8"))
    cond = {"num_ctx": args.num_ctx, "think": args.think, "seed": args.seed, "mode": args.mode,
            "num_predict": args.num_predict, "model": args.model}
    done = set()
    if os.path.exists(out_path):                       # resume
        for l in open(out_path, encoding="utf-8"):
            r = json.loads(l)
            if r.get("type") == "turn":
                done.add((r["session"], r["turn"]))
    if done and args.mode == "live":
        # live history can't be rebuilt from the log exactly, so redo the incomplete session
        complete = {s["session"] for s in turns_doc
                    if all((s["session"], j) in done for j in range(len(s["turns"])))}
        session_ids = [s for s in session_ids if s not in complete]
        if not session_ids:
            print("already complete:", out_path); return
        lines = [l for l in open(out_path, encoding="utf-8")
                 if json.loads(l).get("type") != "turn" or json.loads(l)["session"] in complete]
        open(out_path, "w", encoding="utf-8").writelines(lines)
    f = open(out_path, "a", encoding="utf-8")
    if not done:
        f.write(json.dumps({"type": "env", **environment(args.host, args.model), "condition": cond}) + "\n")
        f.flush()

    for sess in turns_doc:
        if sess["session"] not in session_ids:
            continue
        history = []            # fresh `ollama run` = empty history
        for j, t in enumerate(sess["turns"]):
            if args.mode == "verbatim" and (sess["session"], j) in done:
                history += [{"role": "user", "content": t["user"]},
                            {"role": "assistant", "content": t["answer"], "thinking": t["thinking"]}]
                continue
            msgs = history + [{"role": "user", "content": t["user"]}]
            opts = dict(MODEL_PARAMS, num_ctx=args.num_ctx, seed=args.seed + 1000 * sess["session"] + j)
            if args.num_predict:
                opts["num_predict"] = args.num_predict
            body = {"model": args.model, "messages": msgs, "stream": False,
                    "think": args.think == "on", "options": opts, "keep_alive": "30m"}
            t0 = time.time(); err = None
            try:
                r = http(args.host, "/api/chat", body)
            except urllib.error.HTTPError as e:
                r, err = {}, f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
            except Exception as e:
                r, err = {}, repr(e)
            wall = time.time() - t0
            m = r.get("message", {}) or {}
            content, thinking = m.get("content", "") or "", m.get("thinking", "") or ""
            rec = {"type": "turn", "session": sess["session"], "turn": j, **cond,
                   "user": t["user"], "user_source": t["source"],
                   "orig_answered": t["answered"],
                   "history_messages": len(history),
                   "prompt_eval_count": r.get("prompt_eval_count"),
                   "eval_count": r.get("eval_count"),
                   "done_reason": r.get("done_reason"),
                   "thinking_chars": len(thinking), "answer_chars": len(content),
                   "answer_empty": content.strip() == "",
                   "wall_s": round(wall, 3),
                   "total_duration_ns": r.get("total_duration"),
                   "prompt_eval_duration_ns": r.get("prompt_eval_duration"),
                   "eval_duration_ns": r.get("eval_duration"),
                   "answer": content, "thinking": thinking, "error": err}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
            print(f"s{sess['session']} t{j:02d} ctx={args.num_ctx} think={args.think} seed={args.seed} "
                  f"prompt={rec['prompt_eval_count']} out={rec['eval_count']} {rec['done_reason']} "
                  f"think={len(thinking)}c ans={len(content)}c{'  EMPTY' if rec['answer_empty'] else ''}"
                  f"{'  ERR ' + err if err else ''} {wall:.1f}s", flush=True)
            history.append({"role": "user", "content": t["user"]})
            if args.mode == "verbatim" and t["answered"] is not None:
                history.append({"role": "assistant", "content": t["answer"], "thinking": t["thinking"]})
            else:
                # what the CLI stores after each turn (empty content included)
                history.append({"role": "assistant", "content": content, "thinking": thinking})
    f.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="http://localhost:11434")
    p.add_argument("--model", default="qwen3.5")
    p.add_argument("--num-ctx", type=int, default=4096)
    p.add_argument("--think", choices=["on", "off"], default="on")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--mode", choices=["live", "verbatim"], default="live")
    p.add_argument("--session", default="all", help="1, 2 or all")
    p.add_argument("--num-predict", type=int, default=0, help="output cap, 0 = none")
    p.add_argument("--grid", action="store_true", help="run the full condition grid")
    p.add_argument("--ctx-list", default="4096,8192,32768")
    p.add_argument("--seeds", default="1,2,3")
    p.add_argument("--outdir", default=os.path.join(ROOT, "runs"))
    a = p.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    sessions = [1, 2] if a.session == "all" else [int(a.session)]

    def out_name(x):
        return os.path.join(a.outdir, f"{x.mode}_ctx{x.num_ctx}_think{x.think}_seed{x.seed}.jsonl")

    if not a.grid:
        run(a, sessions, out_name(a)); return
    ctxs = [int(c) for c in a.ctx_list.split(",")]
    seeds = [int(s) for s in a.seeds.split(",")]
    # seed-major order: one full pass over every condition first, then more seeds
    for seed in seeds:
        for ctx in ctxs:
            for think in ("on", "off"):
                x = argparse.Namespace(**vars(a)); x.num_ctx, x.seed, x.think = ctx, seed, think
                print(f"=== {out_name(x)}", flush=True)
                run(x, sessions, out_name(x))


if __name__ == "__main__":
    main()
