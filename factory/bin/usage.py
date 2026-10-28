#!/usr/bin/env python3
"""Factory usage collector: tokens, cost and work counters per job.

Reads Claude Code transcripts (one JSON object per line). Every API request is
an `assistant` line with `requestId`, `message.model`, `message.usage` and
`effort`; a request spans several lines (one per content block), so lines are
deduplicated by requestId, keeping the most complete usage.

  usage.py hook                      SubagentStop hook: reads the hook JSON on stdin
  usage.py checkpoint <job-id> <cp>  cp: pr-opened | reviewed | closed
  usage.py ledger [--readme]         rebuild factory/LEDGER.md, and with --readme the README section

See factory/usage.md. Standard library only; the hook never fails the session.
"""
import fcntl
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACTORY = ROOT / "factory"
JOBS = FACTORY / "jobs"
PRICING = json.loads((FACTORY / "pricing.json").read_text())
LEDGER = FACTORY / "ledger.jsonl"
LEDGER_MD = FACTORY / "LEDGER.md"
README = ROOT / "README.md"
MARK_START, MARK_END = "<!-- factory-ledger:start -->", "<!-- factory-ledger:end -->"

PHASES = {
    "bug-reporter": "intake",
    "spec-writer": "spec", "bug-triager": "spec",
    "builder": "build",
    "reviewer-security": "review", "reviewer-ux": "review",
    "reviewer-ui": "review", "reviewer-code": "review",
    "approver": "approve",
}
TOKEN_TYPES = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
REJECTED = re.compile(r"doesn't want to proceed|was rejected|denied|not allowed|permission", re.I)
JOB_RE = re.compile(r"factory/jobs/(\d{3}-[a-z0-9-]+)/")
CHECKPOINTS = ("pr-opened", "reviewed", "closed")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


@contextmanager
def locked(folder):
    with open(folder / ".usage.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


# ---- pricing -----------------------------------------------------------------

def price_for(model):
    base = model.split("[")[0]
    keys = [k for k in PRICING["models"] if base == k or base.startswith(k + "-")]
    return PRICING["models"][max(keys, key=len)] if keys else None


def request_cost(model, t, speed):
    p = price_for(model)
    if p is None:
        return None
    prompt = t["input"] + t["cache_read"] + t["cache_write_5m"] + t["cache_write_1h"]
    long = p.get("long_context")
    if long and prompt > long["threshold"]:
        p = {**p, **long}
    mult = PRICING["cache_write_multipliers"]
    cost = (t["input"] * p["input"] + t["output"] * p["output"]
            + t["cache_read"] * p["cache_read"]
            + t["cache_write_5m"] * p["input"] * mult["5m"]
            + t["cache_write_1h"] * p["input"] * mult["1h"]) / 1_000_000
    if speed == "fast":
        cost *= p.get("fast_multiplier", 1)
    return cost


def tokens_of(usage):
    write = usage.get("cache_creation") or {}
    w5, w1 = write.get("ephemeral_5m_input_tokens"), write.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:
        w5, w1 = usage.get("cache_creation_input_tokens", 0), 0
    return {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0),
            "cache_read": usage.get("cache_read_input_tokens", 0),
            "cache_write_5m": w5 or 0, "cache_write_1h": w1 or 0}


# ---- transcripts -------------------------------------------------------------

def read_transcript(path, after=None, until=None, main_only=False):
    """Usage of the requests in a transcript, optionally within (after, until]."""
    requests, tools, results, stamps, efforts = {}, {}, [], [], Counter()
    try:
        lines = Path(path).expanduser().read_text().splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        when = ts(d.get("timestamp"))
        if when is None or (after and when <= after) or (until and when > until):
            continue
        if main_only and d.get("isSidechain"):
            continue
        msg = d.get("message") or {}
        if d.get("type") == "assistant" and msg.get("usage") and msg.get("model") != "<synthetic>":
            key = d.get("requestId") or msg.get("id") or d.get("uuid")
            t = tokens_of(msg["usage"])
            old = requests.get(key)
            if old is None or t["output"] >= old["tokens"]["output"]:
                requests[key] = {"model": msg["model"], "tokens": t,
                                 "speed": msg["usage"].get("speed"), "at": when}
            if d.get("effort"):
                efforts[d["effort"]] += 1
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tools[block.get("id")] = block.get("name")
        if d.get("type") == "user" and isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    text = json.dumps(block.get("content"))
                    results.append((block.get("tool_use_id"), bool(block.get("is_error")), text))
        stamps.append(when)
    return summarize(requests, tools, results, stamps, efforts)


def summarize(requests, tools, results, stamps, efforts):
    models = defaultdict(lambda: {**{k: 0 for k in TOKEN_TYPES}, "requests": 0, "cost_usd": 0.0})
    unpriced, peak = set(), 0
    for r in requests.values():
        m = models[r["model"].split("[")[0]]
        for k in TOKEN_TYPES:
            m[k] += r["tokens"][k]
        m["requests"] += 1
        cost = request_cost(r["model"], r["tokens"], r["speed"])
        if cost is None:
            unpriced.add(r["model"])
        else:
            m["cost_usd"] += cost
        t = r["tokens"]
        peak = max(peak, t["input"] + t["cache_read"] + t["cache_write_5m"] + t["cache_write_1h"])
    edits = {"accept": 0, "reject": 0}
    errors = 0
    for tool_id, is_error, text in results:
        errors += is_error
        if tools.get(tool_id) in EDIT_TOOLS:
            edits["reject" if is_error and REJECTED.search(text) else "accept"] += 1
    return {
        "started_at": min(stamps).isoformat().replace("+00:00", "Z") if stamps else None,
        "ended_at": max(stamps).isoformat().replace("+00:00", "Z") if stamps else None,
        "duration_s": round((max(stamps) - min(stamps)).total_seconds()) if stamps else 0,
        "requests": len(requests),
        "models": {k: {**v, "cost_usd": round(v["cost_usd"], 6)} for k, v in models.items()},
        "effort": efforts.most_common(1)[0][0] if efforts else None,
        "peak_context": peak,
        "tool_calls": len(tools),
        "tool_errors": errors,
        "edits": edits,
        "unpriced_models": sorted(unpriced),
    }


def first_prompt(path):
    try:
        for line in Path(path).expanduser().read_text().splitlines():
            d = json.loads(line)
            if d.get("type") == "user":
                content = (d.get("message") or {}).get("content")
                return content if isinstance(content, str) else json.dumps(content)
    except (OSError, ValueError):
        pass
    return ""


def is_empty(rec):
    return rec["requests"] == 0 and rec["tool_calls"] == 0


# ---- recording ---------------------------------------------------------------

def append(folder, record):
    with open(folder / "usage.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")


def record_orchestrator(job_dir, state, transcript, session_id, until=None):
    """Attribute the orchestrator session's own requests since its last mark to the job.

    A session first seen on this job counts from when the job started or was
    reopened (/factory rework or approve set resumedAt), never from before.
    """
    if not transcript:
        return
    marks = state.setdefault("orchestrators", {})
    job = read_json(job_dir / "job.json", {})
    opened = max(filter(None, [job.get("startedAt"), job.get("resumedAt")]), key=ts, default=None)
    after = max(filter(None, [ts(marks.get(transcript)), ts(opened)]), default=None)
    rec = read_transcript(transcript, after=after, until=until, main_only=True)
    marks[transcript] = rec["ended_at"] or marks.get(transcript) or opened
    if not is_empty(rec):
        append(job_dir, {"at": now(), "agent": "orchestrator", "phase": "orchestrate",
                         "session_id": session_id, "stage": job.get("stage"),
                         "round": job.get("round"), **rec})


def hook():
    data = json.load(sys.stdin)
    agent = data.get("agent_type") or ""
    path = data.get("agent_transcript_path")
    if agent not in PHASES or not path:
        return
    prompt = first_prompt(path)
    m = JOB_RE.search(prompt)
    if m and (JOBS / m.group(1)).is_dir():
        targets = [JOBS / m.group(1)]
    elif agent == "bug-reporter":
        targets = [Path(p.strip()) for p in (data.get("last_assistant_message") or "").splitlines()
                   if p.strip().startswith("/") and Path(p.strip()).is_dir()]
    else:
        return
    if not targets:
        return
    job_dir = targets[0] if JOBS in targets[0].parents else None
    with locked(targets[0]):
        state = read_json(targets[0] / ".usage-state.json", {})
        agents = state.setdefault("agents", {})
        agent_id = data.get("agent_id") or path
        rec = read_transcript(path, after=ts(agents.get(agent_id)))
        agents[agent_id] = rec["ended_at"] or agents.get(agent_id)
        job = read_json(targets[0] / "job.json", {})
        base = {"at": now(), "agent": agent, "phase": PHASES[agent], "agent_id": agent_id,
                "session_id": data.get("session_id"), "stage": job.get("stage"),
                "round": job.get("round")}
        if not is_empty(rec):
            share = 1 / len(targets)
            for target in targets:
                part = rec if share == 1 else scale(rec, share)
                append(target, {**base, **part})
        if job_dir:
            record_orchestrator(job_dir, state, data.get("transcript_path"), data.get("session_id"))
            state["sessions"] = sorted(set(state.get("sessions", [])) | {data.get("session_id")} - {None})
        write_json(targets[0] / ".usage-state.json", state)


def scale(rec, share):
    """One reporter run that opened several reports: split its usage evenly."""
    out = json.loads(json.dumps(rec))
    for m in out["models"].values():
        for k in (*TOKEN_TYPES, "cost_usd"):
            m[k] = round(m[k] * share, 6)
    out["split"] = round(share, 4)
    return out


# ---- aggregation ---------------------------------------------------------------

def records(job_dir):
    out = []
    for f in (job_dir / "report" / "usage.jsonl", job_dir / "usage.jsonl"):
        if f.exists():
            out += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    return out


def aggregate(recs):
    total = {**{k: 0 for k in TOKEN_TYPES}, "cost_usd": 0.0, "requests": 0}
    by_model, by_phase, by_agent = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    edits, efforts = Counter(), Counter()
    tool_calls = errors = peak = active = 0
    unpriced = set()
    for r in recs:
        for model, m in r["models"].items():
            for k in (*TOKEN_TYPES, "cost_usd", "requests"):
                total[k] += m[k]
                by_model[model][k] += m[k]
                by_phase[r["phase"]][k] += m[k]
                by_agent[r["agent"]][k] += m[k]
            efforts[f"{model}:{r.get('effort') or 'default'}"] += m["requests"]
        by_agent[r["agent"]]["runs"] += 1
        edits.update(r["edits"])
        tool_calls += r["tool_calls"]
        errors += r["tool_errors"]
        peak = max(peak, r["peak_context"])
        active += r["duration_s"]
        unpriced.update(r.get("unpriced_models", []))
    fix = lambda d: {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in d.items()}
    return {
        "cost_usd": round(total["cost_usd"], 4),
        "tokens": {k: total[k] for k in TOKEN_TYPES},
        "requests": total["requests"],
        "by_model": fix(by_model), "by_phase": fix(by_phase), "by_agent": fix(by_agent),
        "efforts": dict(efforts),
        "peak_context": peak, "tool_calls": tool_calls, "tool_errors": errors,
        "edits": {"accept": edits["accept"], "reject": edits["reject"]},
        "agent_active_s": active,
        "unpriced_models": sorted(unpriced),
    }


def git(*args):
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def git_stats(job, previous):
    branch = job.get("branch")
    if not branch or git("rev-parse", "--verify", "--quiet", branch) is None:
        return previous or {}
    added = removed = files = 0
    for line in (git("diff", "--numstat", f"main...{branch}") or "").splitlines():
        a, r, _ = line.split("\t", 2)
        if a != "-":
            added, removed = added + int(a), removed + int(r)
        files += 1
    return {"lines_added": added, "lines_removed": removed, "files_changed": files,
            "commits": int(git("rev-list", "--count", f"main..{branch}") or 0)}


def checkpoint(job_id, name):
    if name not in CHECKPOINTS:
        sys.exit(f"checkpoint must be one of {', '.join(CHECKPOINTS)}")
    job_dir = JOBS / job_id
    job = read_json(job_dir / "job.json", None)
    if job is None:
        sys.exit(f"no job.json in {job_dir}")
    with locked(job_dir):
        state = read_json(job_dir / ".usage-state.json", {})
        # A closed job stops at endedAt, so a session that moved on to another job
        # doesn't charge that work here.
        until = ts(job.get("endedAt")) if job.get("stage") in ("merged", "needs-human") else None
        for transcript in list(state.get("orchestrators", {})):
            record_orchestrator(job_dir, state, transcript, None, until=until)
        write_json(job_dir / ".usage-state.json", state)
        usage = read_json(job_dir / "usage.json", {})
        totals = aggregate(records(job_dir))
        work = git_stats(job, usage.get("work"))
        usage.update({
            "job": job_id, "kind": job.get("kind", "feature"), "feature": job.get("feature"),
            "stage": job.get("stage"), "round": job.get("round"),
            "startedAt": job.get("startedAt"), "endedAt": job.get("endedAt"),
            "sessions": state.get("sessions", []),
            "agent_ids": sorted(state.get("agents", {})),
            "work": {**work, "merged": job.get("stage") == "merged",
                     "fixed_in": job.get("fixed_in")},
            "totals": totals,
        })
        usage.setdefault("checkpoints", {})[name] = {
            "at": now(), "cost_usd": totals["cost_usd"], "tokens": totals["tokens"],
            "by_model": {m: v["cost_usd"] for m, v in totals["by_model"].items()}}
        write_json(job_dir / "usage.json", usage)
        (job_dir / "usage.md").write_text(job_markdown(usage))
    if name == "closed":
        upsert_ledger(usage)
        ledger()
    print(f"{job_id}: {name} ${totals['cost_usd']:.2f}, {sum(totals['tokens'].values()):,} tokens")


# ---- markdown ------------------------------------------------------------------

def money(x):
    return f"${x:,.2f}"


def num(x):
    return f"{int(round(x)):,}"


def duration(start, end):
    if not start or not end:
        return "-"
    s = int((ts(end) - ts(start)).total_seconds())
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


def model_table(by_model):
    rows = ["| Model | Input | Output | Cache read | Cache write | Requests | Cost |",
            "| ----- | ----: | -----: | ---------: | ----------: | -------: | ---: |"]
    for model, m in sorted(by_model.items(), key=lambda kv: -kv[1]["cost_usd"]):
        rows.append(f"| {model} | {num(m['input'])} | {num(m['output'])} | {num(m['cache_read'])} "
                    f"| {num(m['cache_write_5m'] + m['cache_write_1h'])} | {num(m['requests'])} "
                    f"| {money(m['cost_usd'])} |")
    return "\n".join(rows)


def job_markdown(u):
    t, w, cps = u["totals"], u["work"], u["checkpoints"]
    opened = cps.get("pr-opened", {}).get("cost_usd")
    reviewed = cps.get("reviewed", {}).get("cost_usd")
    closed = cps.get("closed", {}).get("cost_usd")
    lines = [
        f"# Usage: {u['job']}", "",
        f"> {u.get('feature') or ''}", "",
        "| | |", "| --- | --- |",
        f"| Stage | {u['stage']}, round {u['round']} |",
        f"| Started / ended | {u.get('startedAt') or '-'} / {u.get('endedAt') or '-'} |",
        f"| Wall time | {duration(u.get('startedAt'), u.get('endedAt') or now())} |",
        f"| Cost | **{money(t['cost_usd'])}** |",
        f"| Until ready for review | {money(opened) if opened is not None else '-'} |",
        f"| Review rounds and approval | {money(reviewed - opened) if None not in (opened, reviewed) else '-'} |",
        f"| Closing | {money(closed - reviewed) if None not in (closed, reviewed) else '-'} |",
        f"| Peak context | {num(t['peak_context'])} tokens |",
        f"| Effort (model:effort → requests) | {', '.join(f'{k} → {v}' for k, v in t['efforts'].items()) or '-'} |",
        f"| Lines | +{w.get('lines_added', 0)} / -{w.get('lines_removed', 0)} in {w.get('files_changed', 0)} files |",
        f"| Commits | {w.get('commits', 0)} |",
        f"| Tool calls | {t['tool_calls']} ({t['tool_errors']} errors) |",
        f"| Edits accepted / rejected | {t['edits']['accept']} / {t['edits']['reject']} |",
        f"| Agent active time | {t['agent_active_s'] // 60} min |",
        "", "## By model", "", model_table(t["by_model"]), "",
        "## By agent", "",
        "| Agent | Runs | Requests | Output tokens | Cost |",
        "| ----- | ---: | -------: | ------------: | ---: |",
    ]
    for agent, a in sorted(t["by_agent"].items(), key=lambda kv: -kv[1]["cost_usd"]):
        lines.append(f"| {agent} | {a['runs']} | {num(a['requests'])} | {num(a['output'])} | {money(a['cost_usd'])} |")
    if t["unpriced_models"]:
        lines += ["", f"Not priced (add them to factory/pricing.json): {', '.join(t['unpriced_models'])}."]
    return "\n".join(lines) + "\n"


def upsert_ledger(u):
    t, w = u["totals"], u["work"]
    entry = {
        "job": u["job"], "kind": u["kind"], "feature": u.get("feature"), "stage": u["stage"],
        "startedAt": u.get("startedAt"), "endedAt": u.get("endedAt"),
        "cost_usd": t["cost_usd"], "tokens": t["tokens"],
        "by_model": {m: {k: v[k] for k in (*TOKEN_TYPES, "requests", "cost_usd")}
                     for m, v in t["by_model"].items()},
        "checkpoints": {k: v["cost_usd"] for k, v in u["checkpoints"].items()},
        "lines_added": w.get("lines_added", 0), "lines_removed": w.get("lines_removed", 0),
        "commits": w.get("commits", 0), "merged": w.get("merged", False),
        "tool_calls": t["tool_calls"], "edits": t["edits"],
        "agent_active_s": t["agent_active_s"], "peak_context": t["peak_context"],
    }
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()] if LEDGER.exists() else []
    rows = [r for r in rows if r["job"] != u["job"]] + [entry]
    rows.sort(key=lambda r: r["job"])
    LEDGER.write_text("".join(json.dumps(r) + "\n" for r in rows))


def ledger(readme=False):
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()] if LEDGER.exists() else []
    by_model = defaultdict(Counter)
    for r in rows:
        for model, m in r["by_model"].items():
            by_model[model].update(m)
    total = sum(r["cost_usd"] for r in rows)
    merged = [r for r in rows if r["merged"]]
    summary = [
        f"**{len(rows)} jobs** ({len(merged)} merged) · **{money(total)}** total · "
        f"{num(sum(sum(r['tokens'].values()) for r in rows))} tokens · "
        f"+{sum(r['lines_added'] for r in rows)} / -{sum(r['lines_removed'] for r in rows)} lines · "
        f"{sum(r['commits'] for r in rows)} commits",
        "", model_table(by_model) if rows else "No jobs closed yet.",
    ]
    jobs = ["| Job | Kind | Result | Started | Wall time | Until review | Review | Total | Lines | Commits |",
            "| --- | ---- | ------ | ------- | --------- | -----------: | -----: | ----: | ----: | ------: |"]
    for r in rows:
        cp = r["checkpoints"]
        review = cp["reviewed"] - cp["pr-opened"] if "reviewed" in cp and "pr-opened" in cp else None
        jobs.append(f"| {r['job']} | {r['kind']} | {r['stage']} | {(r.get('startedAt') or '-')[:10]} "
                    f"| {duration(r.get('startedAt'), r.get('endedAt'))} "
                    f"| {money(cp['pr-opened']) if 'pr-opened' in cp else '-'} "
                    f"| {money(review) if review is not None else '-'} | **{money(r['cost_usd'])}** "
                    f"| +{r['lines_added']}/-{r['lines_removed']} | {r['commits']} |")
    body = ("\n".join(summary) + "\n\n" + "\n".join(jobs) + "\n") if rows else "No jobs closed yet.\n"
    LEDGER_MD.write_text("# Factory ledger\n\nGenerated by `factory/bin/usage.py` from "
                         "`factory/ledger.jsonl`. Costs are estimates from `factory/pricing.json`.\n\n" + body)
    if readme and README.exists():
        text = README.read_text()
        if MARK_START in text and MARK_END in text:
            head, rest = text.split(MARK_START, 1)
            _, tail = rest.split(MARK_END, 1)
            README.write_text(f"{head}{MARK_START}\n{body}{MARK_END}{tail}")


def main():
    cmd = sys.argv[1:] or ["help"]
    if cmd[0] == "hook":
        try:
            hook()
        except Exception as e:  # a usage bug must never block an agent
            print(f"factory usage hook: {e}", file=sys.stderr)
    elif cmd[0] == "checkpoint" and len(cmd) == 3:
        checkpoint(cmd[1], cmd[2])
    elif cmd[0] == "ledger":
        ledger(readme="--readme" in cmd)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
