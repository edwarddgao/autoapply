"""Automated job application orchestrator.

Usage:
    python -m autoapply.pipeline                  # 8 concurrent (default)
    python -m autoapply.pipeline --concurrency 4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .db import init_local_db
from .filter import rebuild_candidates
from .search import find_candidates, mark_applied, mark_excluded
from .update import download_db


LOGS_DIR = Path(__file__).parent.parent / "logs"
PIPELINE_LOG = LOGS_DIR / "pipeline.log"


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PIPELINE_LOG, "a") as f:
        f.write(line + "\n")


CHILD_ENV = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
CHILD_ENV["ENABLE_TOOL_SEARCH"] = "false"
CHILD_ENV["MAX_THINKING_TOKENS"] = "0"
JOB_TIMEOUT = 600


APPLICATION_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "submitted": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["submitted"],
})


def parse_stream_log(log_path: Path) -> tuple[str, str, float]:
    """Parse a stream-json log file. Returns (status, reason, cost)."""
    cost = 0.0
    structured_output = None

    for line in log_path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if event.get("type") == "result":
            cost = event.get("total_cost_usd", 0)
            structured_output = event.get("structured_output")

    if structured_output and structured_output.get("submitted"):
        return "submitted", "", cost

    reason = (structured_output or {}).get("reason", "unknown")
    return "error", reason, cost


def close_extra_tabs() -> None:
    """Close all Chrome tabs except one blank tab."""
    subprocess.run(
        ["osascript", "-e",
         'tell application "Google Chrome" to tell window 1 to close (tabs whose URL is not "chrome://newtab/")'],
        capture_output=True,
    )


TAB_SCHEMA = json.dumps({
    "type": "object",
    "properties": {"tab_ids": {"type": "array", "items": {"type": "integer"}}},
    "required": ["tab_ids"],
})


def restart_chrome(timeout: int = 60) -> None:
    """Kill and relaunch Chrome, poll until extension responds."""
    log("Restarting Chrome...")
    subprocess.run(
        ["osascript", "-e", 'quit app "Google Chrome"'],
        capture_output=True,
    )
    time.sleep(3)
    subprocess.run(["open", "-a", "Google Chrome"], capture_output=True)

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(5)
        try:
            result = subprocess.run(
                ["claude", "-p", "Call tabs_context_mcp with createIfEmpty=true.",
                 "--chrome", "--max-turns", "3", "--dangerously-skip-permissions"],
                capture_output=True, text=True, env=CHILD_ENV, timeout=30,
            )
            if result.returncode == 0:
                log("Chrome extension reconnected")
                return
        except subprocess.TimeoutExpired:
            continue
    log("Chrome extension did not reconnect within timeout")


def create_tabs(n: int, retries: int = 3) -> list[int]:
    """One-shot claude -p to create browser tabs, with retries and Chrome restart."""
    prompt = (
        f"Call tabs_context_mcp with createIfEmpty=true. "
        f"Then call tabs_create_mcp {n - 1} more times (one at a time). "
        f"Return all {n} tab IDs."
    )
    result = None
    for attempt in range(retries):
        if attempt > 0:
            log(f"create_tabs attempt {attempt + 1}/{retries} after Chrome restart...")
            restart_chrome()
        try:
            result = subprocess.run(
                ["claude", "-p", prompt,
                 "--chrome", "--output-format", "json",
                 "--json-schema", TAB_SCHEMA,
                 "--max-turns", "15", "--dangerously-skip-permissions"],
                capture_output=True, text=True, env=CHILD_ENV, timeout=120,
            )
            data = json.loads(result.stdout)
            tab_ids = data.get("structured_output", {}).get("tab_ids", [])
            unique_ids = list(dict.fromkeys(tab_ids))
            if unique_ids:
                log(f"create_tabs: {unique_ids}")
                return unique_ids
        except (json.JSONDecodeError, TypeError, subprocess.TimeoutExpired):
            pass
    stdout = result.stdout[:500] if result else "N/A"
    stderr = result.stderr[:500] if result else "N/A"
    log(f"FATAL: Failed to create tabs after {retries} attempts.\nstdout: {stdout}\nstderr: {stderr}")
    sys.exit(1)


async def apply_to_job(job: dict, tab_id: int) -> tuple[str, str, float]:
    """Spawn claude -p to apply. Returns (status, reason, cost)."""
    log_path = LOGS_DIR / f"{job['job_id']}.jsonl"
    prompt = (
        f"Navigate tab {tab_id} to {job['apply_url']}. "
        f"Company: {job['company_name']} | Role: {job['title']}"
    )

    cmd = [
        "claude", "-p", prompt,
        "--chrome",
        "--system-prompt-file", str(Path(__file__).parent.parent / "agent_prompt.txt"),
        "--tools", "Bash,Read",
        "--output-format", "stream-json",
        "--verbose",
        "--json-schema", APPLICATION_SCHEMA,
        "--max-turns", "200",
        "--dangerously-skip-permissions",
        "--model", "haiku",
        "--no-session-persistence",
    ]

    with open(log_path, "w") as log_file:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=log_file,
                stderr=asyncio.subprocess.PIPE,
                env=CHILD_ENV,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=JOB_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "timeout", f"Timeout ({JOB_TIMEOUT}s)", 0.0

    if proc.returncode != 0 and not log_path.stat().st_size:
        err = stderr.decode("utf-8", errors="replace")[:200] if stderr else "unknown"
        return "error", f"Process failed: {err}", 0.0

    return parse_stream_log(log_path)


async def worker(
    worker_id: int,
    tab_id: int,
    job_queue: asyncio.Queue,
    results: dict,
    recent_errors: list[float],
    stop_event: asyncio.Event,
):
    """Pull jobs from queue, apply, mark result, repeat."""

    while not stop_event.is_set():
        try:
            job = job_queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        log(f"  [{worker_id}] -> {job['company_name']} - {job['title']}")

        try:
            status, reason, job_cost = await apply_to_job(job, tab_id)
        except Exception as e:
            status, reason, job_cost = "error", str(e), 0.0

        results["cost"] += job_cost

        if status == "submitted":
            mark_applied(job["job_id"])
            results["submitted"] += 1
        else:
            mark_excluded(job["job_id"], reason)
            results["excluded"] += 1
            now = time.time()
            recent_errors.append(now)
            recent_errors[:] = [t for t in recent_errors if t > now - 60]
            if len(recent_errors) >= 24:
                log(f"\n  !!! {len(recent_errors)} errors in last 60s — Chrome likely crashed.")
                stop_event.set()

        sym = "+" if status == "submitted" else "!"
        log(
            f"  [{worker_id}] {sym} {status.upper()}: {job['company_name']} - {job['title']} "
            f"(${job_cost:.2f}) [{results['submitted']} submitted]"
        )
        if status != "submitted":
            log(f"         Reason: {reason}")

        job_queue.task_done()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    LOGS_DIR.mkdir(exist_ok=True)
    init_local_db()

    log("Updating jobs.db from GitHub Releases...")
    try:
        if download_db():
            rebuild_candidates()
        else:
            log("Update failed, using existing jobs.db")
    except Exception as e:
        log(f"Update failed ({e}), using existing jobs.db")

    log(f"Creating {args.concurrency} browser tabs...")
    close_extra_tabs()
    tab_ids = create_tabs(args.concurrency)
    log(f"Tabs: {tab_ids}")

    results: dict = {"submitted": 0, "excluded": 0, "cost": 0.0}
    recent_errors: list[float] = []
    stop_event = asyncio.Event()

    def on_sigint(sig, frame):
        log(f"\n\nInterrupted. {json.dumps(results)}")
        sys.exit(0)
    signal.signal(signal.SIGINT, on_sigint)

    candidates = find_candidates()
    if not candidates:
        log("No candidates in database.")
        return

    job_queue: asyncio.Queue = asyncio.Queue()
    for c in candidates:
        job_queue.put_nowait(c)

    log(f"\nProcessing {job_queue.qsize()} jobs (concurrency={args.concurrency})")

    while not job_queue.empty() and not stop_event.is_set():
        workers = [
            asyncio.create_task(
                worker(i, tab_ids[i], job_queue, results,
                       recent_errors, stop_event)
            )
            for i in range(min(args.concurrency, len(tab_ids)))
        ]
        await asyncio.gather(*workers)

        log(f"\n--- Progress: {json.dumps(results)} ---")

        if stop_event.is_set():
            restart_chrome()
            stop_event.clear()
            recent_errors.clear()
            close_extra_tabs()
            tab_ids = create_tabs(args.concurrency)
            log(f"Fresh tabs: {tab_ids}")

    log(f"\nFINAL: {json.dumps(results)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        log(f"FATAL: {e}")
        import traceback
        log(traceback.format_exc())
        sys.exit(1)
