"""Runs one P5A job through GHDL: analysis -> elaboration -> simulation.

Covers FR-P5A-01..06 for the Week 7 slice. Each job gets its own temporary
folder inside the service container; a GHDL step that runs past the time
limit is killed and reported as a service/runtime failure (P5-StR1.2).
"""
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

STAGE_TIMEOUT_S = int(os.environ.get("P5A_STAGE_TIMEOUT_S", "10"))
MAX_FILE_BYTES = int(os.environ.get("P5A_MAX_FILE_BYTES", str(200_000)))
JOBS_ROOT = Path(os.environ.get("P5A_JOBS_ROOT", tempfile.gettempdir())) / "p5a-jobs"
ALLOWED_EXT = (".vhd", ".vhdl")
NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(vhd|vhdl)$")
TOP_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
# GHDL message, e.g. "and_gate.vhd:12:5:error: ';' is expected instead of 'end'"
MSG_RE = re.compile(r"^(?P<file>[^:\s]+\.vhdl?):(?P<line>\d+):(?P<col>\d+):\s*(?P<msg>.*)$")


class RequestError(Exception):
    """FR-P5A-02: the request itself is invalid, so no job is created."""


def validate(files: dict[str, bytes], top: str) -> None:
    """FR-P5A-01: check the request shape only. VHDL code errors are found
    later by the analysis stage, not here."""
    if not files:
        raise RequestError("No VHDL files were submitted.")
    for name, data in files.items():
        if not NAME_RE.match(name):
            raise RequestError(f"'{name}' must be a plain file name ending in .vhd or .vhdl.")
        if not data.strip():
            raise RequestError(f"'{name}' is empty.")
        if len(data) > MAX_FILE_BYTES:
            raise RequestError(f"'{name}' is larger than {MAX_FILE_BYTES} bytes.")
    if not top or not TOP_RE.match(top):
        raise RequestError("A valid top-level testbench name ('top') is required.")


def parse_errors(output: str) -> list[dict]:
    errors = []
    for line in output.splitlines():
        m = MSG_RE.match(line.strip())
        if m:
            errors.append({"file": m["file"], "line": int(m["line"]),
                           "column": int(m["col"]), "message": m["msg"]})
    return errors


def _run(cmd: list[str], cwd: Path) -> tuple[str, str]:
    """Returns (outcome, output). outcome is 'pass', 'fail' or 'timeout'."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=STAGE_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "") if isinstance(e.stdout, str) else ""
        return "timeout", out
    out = p.stdout + p.stderr
    return ("pass" if p.returncode == 0 else "fail"), out


def run_job(files: dict[str, bytes], top: str, stop_time: str | None = None) -> dict:
    """FR-P5A-03..06: stage the job and return the result dict."""
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True)
    for name, data in files.items():
        (job_dir / name).write_bytes(data)

    stages = {"analysis": "not_run", "elaboration": "not_run", "simulation": "not_run"}
    result = {"job_id": job_id, "status": "success", "failed_stage": None,
              "category": None, "stages": stages, "errors": [], "log": "",
              "vcd_available": False}

    sim_cmd = ["ghdl", "-r", top, "--vcd=wave.vcd"]
    if stop_time:
        sim_cmd.append(f"--stop-time={stop_time}")
    plan = [
        ("analysis", ["ghdl", "-a", *files.keys()]),
        ("elaboration", ["ghdl", "-e", top]),
        ("simulation", sim_cmd),
    ]
    for stage, cmd in plan:
        try:
            outcome, out = _run(cmd, job_dir)
        except FileNotFoundError:
            outcome, out = "error", "GHDL is not installed or not on PATH."
        result["log"] += out
        if outcome == "pass":
            stages[stage] = "pass"
            continue
        stages[stage] = "fail"
        result["status"] = "fail"
        result["failed_stage"] = stage
        if outcome == "fail":
            result["category"] = f"{stage}_error"
            result["errors"] = parse_errors(out) or [{"file": None, "line": None,
                                                      "column": None, "message": out.strip()}]
        else:
            result["category"] = "service_runtime_error"
            msg = (f"Stopped after {STAGE_TIMEOUT_S}s time limit (runaway job)."
                   if outcome == "timeout" else out)
            result["errors"] = [{"file": None, "line": None, "column": None, "message": msg}]
        break

    vcd = job_dir / "wave.vcd"
    result["vcd_available"] = result["status"] == "success" and vcd.exists() and vcd.stat().st_size > 0
    if not result["vcd_available"]:
        shutil.rmtree(job_dir, ignore_errors=True)
    return result


def vcd_path(job_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{12}", job_id):
        return None
    p = JOBS_ROOT / job_id / "wave.vcd"
    return p if p.exists() else None
