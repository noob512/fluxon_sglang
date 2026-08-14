#!/usr/bin/env python3
"""Keep an experiment host free of explicitly identified external GPU jobs.

The guard is deliberately host-local and run-scoped.  It does not block
ordinary SSH sessions or system services.  A process is stopped only when its
argv proves that it is an external Fluxon/SGLang/benchmark launcher/runtime,
or an inference-like GPU worker.  External cleanup of its own tmux socket and
Fluxon shm is allowed because every protected CPU process runs under setsid and
Mooncake does not use the stale Fluxon mapping.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shlex
import signal
import sys
import time
from pathlib import Path
from typing import Iterable, Optional


READ_ONLY_PROGRAMS = {
    "cat",
    "find",
    "grep",
    "head",
    "iostat",
    "lsof",
    "nvidia-smi",
    "pgrep",
    "ps",
    "rg",
    "sed",
    "sha256sum",
    "sort",
    "ss",
    "stat",
    "tail",
    "test",
    "wc",
}
READ_ONLY_SHELL_PROGRAMS = READ_ONLY_PROGRAMS | {
    "date",
    "df",
    "du",
    "free",
    "hostname",
    "id",
    "ls",
    "pwd",
    "readlink",
    "realpath",
    "true",
    "uptime",
    "whoami",
}
EXTERNAL_PATH_MARKERS = (
    "/tmp/fluxload_20260729",
    "/storage/mjq/sglang_fluxon/fluxon_f2",
    "/storage/zth/sglang_l13_fluxon_v2",
    "/public/mjq/sglang_fluxon/fluxon_f2",
    "/public/zth/sglang_l13_fluxon_v2",
    "start_gpu_stack_owner_",
    "start_tp2_",
    "hca_observer_e44_",
)
EXTERNAL_SCRIPT_SUFFIXES = (
    "scripts/gvc_aft_realtime_stream.py",
    "encoder_app.py",
)
EXTERNAL_RUNTIME_MARKERS = (
    "fluxon_py.runtime.start_",
    "fluxon_py.runtime.remote",
    "-m sglang.launch_server",
    "sglang.launch_server",
    "gpu_idle_guard.py",
    "inference_like_compute.py",
)
PROTECTED_RUN_ENV_KEYS = {
    "BASE_DIR",
    "FLUXON_F_RUN_ID",
    "FLUXON_RUN_ID",
    "FLUXON_RUNTIME_ROOT",
    "MOONCAKE_EXPERIMENT_RUN_ID",
    "RUN_ID",
    "SESSION_PREFIX",
}


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")


def argv_text(argv: Iterable[str]) -> str:
    return " ".join(argv)


def python_script_target(argv: list[str]) -> Optional[str]:
    """Return the executed Python script, excluding -c/-m invocations."""
    if not argv or not Path(argv[0]).name.startswith("python"):
        return None
    index = 1
    while index < len(argv):
        item = argv[index]
        if item in {"-c", "-m"}:
            return None
        if item in {"-W", "-X"}:
            index += 2
            continue
        if item.startswith("-"):
            index += 1
            continue
        return item
    return None


def is_read_only_shell_probe(argv: list[str]) -> bool:
    """Recognize a conservative shell pipeline made only of inspection tools."""
    if not argv or Path(argv[0]).name not in {"bash", "dash", "sh", "zsh"}:
        return False
    try:
        index = argv.index("-c")
        code = argv[index + 1]
    except (ValueError, IndexError):
        return False
    if "$(" in code or "`" in code or "\n" in code:
        return False
    try:
        lexer = shlex.shlex(code, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return False
    commands: list[list[str]] = [[]]
    for token in tokens:
        if token and set(token) <= {";", "&", "|"}:
            if commands[-1]:
                commands.append([])
            continue
        commands[-1].append(token)
    commands = [command for command in commands if command]
    if not commands:
        return False
    for command in commands:
        while command and command[0] in {"!", "command"}:
            command = command[1:]
        if not command:
            return False
        program = Path(command[0]).name
        if program not in READ_ONLY_SHELL_PROGRAMS:
            return False
        for token in command[1:]:
            if ">" in token and not token.endswith(">/dev/null"):
                return False
        if program == "find" and any(
            token in {"-delete", "-exec", "-execdir", "-ok", "-okdir"}
            for token in command[1:]
        ):
            return False
    return True


def classify(argv: list[str], protected_run_id: str) -> Optional[str]:
    if not argv:
        return None
    program = Path(argv[0]).name
    text = argv_text(argv)

    # Run-scoped commands are issued by this experiment.  The long-lived
    # Mooncake client itself has no forbidden marker and does not need this
    # exception, but observers and lifecycle commands include the run id.
    if protected_run_id in text:
        return None
    if program in READ_ONLY_PROGRAMS:
        return None
    if is_read_only_shell_probe(argv):
        return None

    lowered = text.lower()
    if program == "ffmpeg" and any("nvenc" in item.lower() for item in argv[1:]):
        return "external_gpu_encoder"
    python_target = python_script_target(argv)
    if argv[0].endswith(EXTERNAL_SCRIPT_SUFFIXES) or (
        python_target is not None
        and python_target.endswith(EXTERNAL_SCRIPT_SUFFIXES)
    ):
        return "external_gpu_workload"
    if any(marker in text for marker in EXTERNAL_PATH_MARKERS):
        return "external_fluxon_path"
    if any(marker in text for marker in EXTERNAL_RUNTIME_MARKERS):
        return "external_inference_runtime"
    if "benchmark" in lowered and any(
        marker in lowered for marker in ("fluxon", "sglang", "mooncake", "kv_cache", "kv-cache")
    ):
        return "external_kv_benchmark"
    if "keeper" in lowered and any(marker in lowered for marker in ("fluxon", "sglang", "e44_")):
        return "external_experiment_keeper"

    return None


def read_proc_argv(pid: int) -> list[str]:
    raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def read_proc_environ(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return []
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def belongs_to_protected_run(environ: Iterable[str], protected_run_id: str) -> bool:
    """Allow only processes carrying this exact run identity in known keys."""
    for entry in environ:
        key, separator, value = entry.partition("=")
        if separator and key in PROTECTED_RUN_ENV_KEYS and protected_run_id in value:
            return True
    return False


def read_proc_stat(pid: int) -> tuple[int, int, int, int]:
    # comm may contain spaces and parentheses, so parse fields after the last
    # right parenthesis.  Fields 4/5/6/22 are ppid/pgrp/session/starttime.
    text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    tail = text[text.rfind(")") + 2 :].split()
    return int(tail[1]), int(tail[2]), int(tail[3]), int(tail[19])


def snapshot_processes() -> dict[int, dict[str, object]]:
    result: dict[int, dict[str, object]] = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            ppid, pgrp, session, starttime = read_proc_stat(pid)
            result[pid] = {
                "argv": read_proc_argv(pid),
                "ppid": ppid,
                "pgrp": pgrp,
                "session": session,
                "starttime": starttime,
            }
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
            continue
    return result


def descendants(root: int, table: dict[int, dict[str, object]]) -> list[int]:
    children: dict[int, list[int]] = {}
    for pid, info in table.items():
        children.setdefault(int(info["ppid"]), []).append(pid)
    found: list[int] = []
    pending = [root]
    seen = set()
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        if pid in table:
            found.append(pid)
            pending.extend(children.get(pid, ()))
    # Children first for TERM/KILL; the root is stopped before this ordering is
    # used, so it cannot create an unbounded new subtree.
    return list(reversed(found))


class JsonlLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: dict[str, object]) -> None:
        event = dict(event)
        event.setdefault("timestamp_utc", utc_now())
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def send_signal(pids: Iterable[int], sig: signal.Signals) -> list[int]:
    sent: list[int] = []
    for pid in pids:
        try:
            os.kill(pid, sig)
            sent.append(pid)
        except (ProcessLookupError, PermissionError):
            continue
    return sent


def source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def run_guard(args: argparse.Namespace) -> int:
    log_path = Path(args.log)
    pid_path = Path(args.pid_file)
    if log_path.exists() or pid_path.exists():
        raise SystemExit(f"guard evidence already exists: log={log_path} pid_file={pid_path}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.parent.mkdir(parents=True, exist_ok=True)

    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, request_stop)

    logger = JsonlLog(log_path)
    pid_record = {
        "pid": os.getpid(),
        "protected_run_id": args.protected_run_id,
        "source_sha256": source_sha256(),
        "start_timestamp_utc": utc_now(),
    }
    fd = os.open(pid_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(pid_record, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())

    logger.append({"event": "start", **pid_record})
    handled: set[tuple[int, int]] = set()
    scans = 0
    blocked = 0
    last_heartbeat = time.monotonic()

    while not stopping:
        table = snapshot_processes()
        scans += 1
        scoped_pids: Optional[set[int]] = None
        if args.scope_root_pid is not None:
            scoped_pids = set(descendants(args.scope_root_pid, table))
        for pid, info in table.items():
            if pid in (1, os.getpid(), os.getppid()):
                continue
            if scoped_pids is not None and pid not in scoped_pids:
                continue
            identity = (pid, int(info["starttime"]))
            if identity in handled:
                continue
            argv = list(info["argv"])
            reason = classify(argv, args.protected_run_id)
            if reason is None:
                continue
            if belongs_to_protected_run(read_proc_environ(pid), args.protected_run_id):
                continue

            # Freeze the proven offender before collecting its descendants and
            # evidence.  Never signal an entire pgrp/session: an SSH command
            # may share those with a harmless parent.
            try:
                os.kill(pid, signal.SIGSTOP)
            except (ProcessLookupError, PermissionError):
                continue
            table = snapshot_processes()
            victims = descendants(pid, table)
            send_signal(victims, signal.SIGSTOP)
            handled.update((victim, int(table[victim]["starttime"])) for victim in victims if victim in table)
            blocked += 1
            logger.append(
                {
                    "argv": argv,
                    "event": "blocked",
                    "pgrp": info["pgrp"],
                    "pid": pid,
                    "ppid": info["ppid"],
                    "reason": reason,
                    "session": info["session"],
                    "victims": victims,
                }
            )
            term_sent = send_signal(victims, signal.SIGTERM)
            send_signal(victims, signal.SIGCONT)
            time.sleep(args.kill_grace_s)
            kill_sent = send_signal(victims, signal.SIGKILL)
            logger.append(
                {
                    "event": "terminated",
                    "kill_sent": kill_sent,
                    "root_pid": pid,
                    "term_sent": term_sent,
                }
            )

        now = time.monotonic()
        if now - last_heartbeat >= args.heartbeat_s:
            logger.append({"blocked": blocked, "event": "heartbeat", "scans": scans})
            last_heartbeat = now
        time.sleep(args.scan_interval_s)

    logger.append({"blocked": blocked, "event": "stop", "pid": os.getpid(), "scans": scans})
    return 0


def self_test() -> int:
    run_id = "c_tp2x2_formal_exclusive_test"
    cases = [
        (["/tmp/fluxload_20260729/venv/bin/python", "benchmark_gpu_load.py"], "external_fluxon_path"),
        (
            [
                "/public/wyb/aiflow/gvc/.venv/bin/python",
                "scripts/gvc_aft_realtime_stream.py",
                "--gpu-ids",
                "4,5,6,7",
            ],
            "external_gpu_workload",
        ),
        (
            [
                "/bin/bash",
                "-lc",
                "dpkg-query -s libevent-dev; "
                "find /public/wyb/aiflow/gvc /usr -name libevent.so -print",
            ],
            None,
        ),
        (
            [
                "/public/wyb/aiflow/gvc/.venv/bin/python",
                "-m",
                "pytest",
                "-q",
                "scripts/tests/test_realtime_streaming_contract.py",
            ],
            None,
        ),
        (
            [
                "git",
                "diff",
                "--",
                "encoder_app.py",
                "scripts/gvc_aft_realtime_stream.py",
            ],
            None,
        ),
        (
            [
                "/public/wyb/aiflow/gvc/.venv/bin/python",
                "-c",
                "from network.aft import common; print(common.AFT_BUILD_PATH)",
            ],
            None,
        ),
        (["bash", "/storage/mjq/sglang_fluxon/fluxon_f2/fluxon_release/start_gpu_stack_owner_numa1_ssd.sh"], "external_fluxon_path"),
        (["python", "-m", "fluxon_py.runtime.start_owner"], "external_inference_runtime"),
        (["python", "-m", "sglang.launch_server", "--port", "30000"], "external_inference_runtime"),
        (["python", "/storage/x/fluxon_s3_benchmark.py"], "external_kv_benchmark"),
        (["tmux", "kill-server"], None),
        (["bash", "-c", "rm -rf /dev/shm/sglang_fluxon_current_cpu_remote/fluxon_f2"], None),
        (["python", "inference_like_compute.py", "--gpus", "0"], "external_inference_runtime"),
        (
            [
                "ffmpeg",
                "-hide_banner",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=128x128:rate=10",
                "-frames:v",
                "1",
                "-an",
                "-c:v",
                "h264_nvenc",
                "-f",
                "h264",
                "-",
            ],
            "external_gpu_encoder",
        ),
        (["ffmpeg", "-i", "input.mp4", "-c:v", "libx264", "output.mp4"], None),
        (["grep", "sglang.launch_server", "/tmp/process.txt"], None),
        (
            [
                "bash",
                "-c",
                "nvidia-smi --query-gpu=index,memory.used --format=csv,noheader; "
                "find /tmp/fluxload_20260729 -maxdepth 3 -type d -print | sort",
            ],
            None,
        ),
        (
            [
                "bash",
                "-c",
                "nvidia-smi pmon -c 1; cat /proc/loadavg; "
                "iostat -dx 1 2 2>/dev/null | tail -n 40 || true; "
                "test -d /tmp/fluxload_20260729/results && "
                "find /tmp/fluxload_20260729/results -maxdepth 1 -type f "
                "-printf \"%f\\n\" | sort || true",
            ],
            None,
        ),
        (
            [
                "zsh",
                "-c",
                'hostname; date; ls -ld /pvcteam/mjq/vlm_fluxon; grep -n "replica_writeback_hot_capacity_ratio" /pvcteam/mjq/vlm_fluxon/start_fluxon_cluster.py 2>/dev/null; nvidia-smi --query-gpu=index,name,memory.used --format=csv,noheader; ps -eo pid,etime,cmd | grep -E "start_fluxon|launch_server|benchmark_visionarena|sglang" | grep -v grep',
            ],
            None,
        ),
        (["bash", "-c", f"tmux kill-server # {run_id}"], None),
        (["/storage/mjq/.venv_sglang_fluxon/lib/python3.10/site-packages/mooncake/mooncake_client", "--port=50052"], None),
        (["bash", "/storage/zgf/gpu_burner.sh", "start", "0,1"], None),
    ]
    for argv, expected in cases:
        actual = classify(argv, run_id)
        if actual != expected:
            raise AssertionError(f"classification mismatch: argv={argv!r} expected={expected!r} actual={actual!r}")
    protected_env_cases = [
        ([f"MOONCAKE_EXPERIMENT_RUN_ID={run_id}"], True),
        ([f"BASE_DIR=/tmp/mooncake/{run_id}"], True),
        ([f"UNRELATED={run_id}"], False),
        (["MOONCAKE_EXPERIMENT_RUN_ID=some_other_run"], False),
    ]
    for environ, expected in protected_env_cases:
        actual = belongs_to_protected_run(environ, run_id)
        if actual != expected:
            raise AssertionError(
                f"protected environment mismatch: environ={environ!r} "
                f"expected={expected!r} actual={actual!r}"
            )
    print(
        f"SELF_TEST_PASS classification_cases={len(cases)} "
        f"protected_env_cases={len(protected_env_cases)} source_sha256={source_sha256()}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protected-run-id")
    parser.add_argument("--log")
    parser.add_argument("--pid-file")
    parser.add_argument("--scan-interval-s", type=float, default=0.02)
    parser.add_argument("--kill-grace-s", type=float, default=0.20)
    parser.add_argument("--heartbeat-s", type=float, default=30.0)
    parser.add_argument(
        "--scope-root-pid",
        type=int,
        help="test-only: inspect only this process and its descendants",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return args
    for name in ("protected_run_id", "log", "pid_file"):
        if not getattr(args, name):
            parser.error(f"--{name.replace('_', '-')} is required")
    if not args.protected_run_id.replace("_", "").isalnum():
        parser.error("--protected-run-id must contain only letters, digits, and underscores")
    if not (0.005 <= args.scan_interval_s <= 1.0):
        parser.error("--scan-interval-s must be between 0.005 and 1.0")
    if not (0.0 <= args.kill_grace_s <= 5.0):
        parser.error("--kill-grace-s must be between 0 and 5")
    if not (1.0 <= args.heartbeat_s <= 300.0):
        parser.error("--heartbeat-s must be between 1 and 300")
    if args.scope_root_pid is not None and args.scope_root_pid <= 1:
        parser.error("--scope-root-pid must be greater than 1")
    return args


if __name__ == "__main__":
    parsed = parse_args()
    raise SystemExit(self_test() if parsed.self_test else run_guard(parsed))
