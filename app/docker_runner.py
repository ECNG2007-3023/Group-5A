"""Milestone 3: Docker job isolation for the P5A GHDL Execution Service.

Each job gets:
  * its own folder under config.JOBS_DIR, holding only that job's VHDL files
  * fresh, short-lived containers from the GHDL image for each stage
    (analysis -> elaboration -> simulation), with that folder mounted at /work
  * hard limits: no network, memory cap (no swap), CPU cap, process cap,
    read-only root filesystem, all Linux capabilities dropped, non-root user
  * a wall-clock timeout per stage. On timeout the WHOLE container is killed,
    so a runaway simulation cannot survive (the old subprocess version only
    killed the ghdl process)
  * cleanup: containers are always removed, and the job folder is deleted once
    the VCD has been read out

Main entry point:
    result = run_job(files=[{"name": "and_gate.vhd", "content": "..."}],
                     top="and_gate_tb", stop_time="100ns")

The result is a plain dict (easy to return from FastAPI):
    {
      "job_id": "3f2a...",
      "status": "success" | "failed",
      "stage":  "validation" | "analysis" | "elaboration" | "simulation" | "done",
      "error":  None | "validation_error" | "analysis_error" | "elaboration_error"
                | "runtime_error" | "timeout" | "memory_limit" | "internal_error",
      "message": "human readable summary",
      "stages": [ {"stage", "command", "exit_code", "output",
                   "duration_s", "timed_out", "oom_killed"}, ... ],
      "vcd": bytes | None,
    }
"""
from __future__ import annotations

import re
import shutil
import stat
import time
import uuid
from pathlib import Path

import docker
import requests
from docker.errors import DockerException, ImageNotFound, NotFound

from . import config

# ---------------------------------------------------------------- validation

FILE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,99}\.(vhd|vhdl)$", re.I)
VHDL_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,99}$")
STOP_TIME_RE = re.compile(r"^(\d+(?:\.\d+)?)\s?(fs|ps|ns|us|ms|sec)$")

VCD_NAME = "wave.vcd"


class JobValidationError(ValueError):
    """The request itself is wrong (bad name, too big, etc.). No container runs."""


def validate_request(files, top, stop_time=None):
    """Check a job request. Returns (files_list, top, stop_time) normalised.

    `files` may be a list of {"name": ..., "content": ...} dicts (or objects
    with .name/.content, e.g. Pydantic models) or a {name: content} dict.
    Raises JobValidationError with a readable message if anything is wrong.
    """
    if isinstance(files, dict):
        files = [{"name": n, "content": c} for n, c in files.items()]

    normalised = []
    for f in files or []:
        name = f["name"] if isinstance(f, dict) else getattr(f, "name", None)
        content = f["content"] if isinstance(f, dict) else getattr(f, "content", None)
        normalised.append((name, content))

    if not normalised:
        raise JobValidationError("At least one VHDL file is required.")
    if len(normalised) > config.MAX_FILES:
        raise JobValidationError(f"Too many files (max {config.MAX_FILES}).")

    seen = set()
    for name, content in normalised:
        if not isinstance(name, str) or not FILE_NAME_RE.match(name):
            raise JobValidationError(
                f"Invalid file name {name!r}. Use letters, digits, _ . - "
                "and end in .vhd or .vhdl (no folders).")
        if name.lower() in seen:
            raise JobValidationError(f"Duplicate file name {name!r}.")
        seen.add(name.lower())
        if not isinstance(content, str) or not content.strip():
            raise JobValidationError(f"File {name!r} is empty.")
        if len(content.encode("utf-8")) > config.MAX_FILE_BYTES:
            raise JobValidationError(
                f"File {name!r} is larger than {config.MAX_FILE_BYTES} bytes.")

    if not isinstance(top, str) or not VHDL_IDENT_RE.match(top):
        raise JobValidationError(
            f"Invalid top-level/testbench name {top!r}. It must be a VHDL "
            "identifier (start with a letter; letters, digits, _).")

    stop_time = (stop_time or config.DEFAULT_STOP_TIME).strip()
    m = STOP_TIME_RE.match(stop_time)
    if not m:
        raise JobValidationError(
            f"Invalid stop_time {stop_time!r}. Examples: 100ns, 1us, 2 ms.")
    stop_time = m.group(1) + m.group(2)       # GHDL wants no space: "100ns"

    return normalised, top, stop_time


# ------------------------------------------------------------- docker helpers

_client = None


def get_client():
    """Shared Docker client (created on first use)."""
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def docker_status(client=None):
    """For /health: is Docker reachable and is the GHDL image built?"""
    try:
        client = client or get_client()
        client.ping()
    except DockerException as e:
        return {"docker": "unreachable", "image": "unknown", "detail": str(e)}
    try:
        client.images.get(config.GHDL_IMAGE)
        image = "present"
    except ImageNotFound:
        image = "missing"
    return {"docker": "ok", "image": image}


def _truncate(text, limit=None):
    limit = limit or config.MAX_LOG_CHARS
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [output truncated, {len(text) - limit} more characters]"


def _std_flag():
    return [f"--std={config.GHDL_STD}"] if config.GHDL_STD else []


def _run_stage(client, job_id, job_dir, stage, command, timeout_s):
    """Run one command in a fresh, locked-down container. Always removes it."""
    started = time.monotonic()
    timed_out = False
    oom_killed = False
    exit_code = None
    output = ""

    container = client.containers.run(
        config.GHDL_IMAGE,
        command,
        detach=True,
        working_dir="/work",
        volumes={str(job_dir): {"bind": "/work", "mode": "rw"}},
        network_disabled=True,                      # no network at all
        mem_limit=config.MEM_LIMIT,
        memswap_limit=config.MEM_LIMIT,             # same as mem_limit = no swap
        nano_cpus=int(config.CPU_LIMIT * 1e9),
        pids_limit=config.PIDS_LIMIT,
        read_only=True,                             # only /work and /tmp writable
        tmpfs={"/tmp": f"size={config.TMPFS_SIZE}"},
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        labels={config.CONTAINER_LABEL: job_id, "p5a.stage": stage},
    )
    try:
        try:
            exit_code = container.wait(timeout=timeout_s)["StatusCode"]
        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError):
            # Still running after the limit: kill the whole container, which
            # kills ghdl AND any simulation process it started.
            timed_out = True
            try:
                container.kill()
            except (NotFound, DockerException):
                pass
            try:
                exit_code = container.wait(timeout=10)["StatusCode"]
            except Exception:
                exit_code = None

        try:
            container.reload()
            oom_killed = bool(container.attrs.get("State", {}).get("OOMKilled"))
        except DockerException:
            pass

        try:
            raw = container.logs(stdout=True, stderr=True)
            output = raw.decode("utf-8", errors="replace")
        except DockerException:
            output = ""
    finally:
        try:
            container.remove(force=True)
        except (NotFound, DockerException):
            pass

    return {
        "stage": stage,
        "command": " ".join(command),
        "exit_code": exit_code,
        "output": _truncate(output),
        "duration_s": round(time.monotonic() - started, 3),
        "timed_out": timed_out,
        "oom_killed": oom_killed,
    }


def _make_job_dir(job_id, files):
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_dir = config.JOBS_DIR / job_id
    job_dir.mkdir()
    # The container runs as user p5a. On Linux hosts the folder is owned by
    # whoever runs the API, so open it up so the container can write
    # GHDL's work library and the VCD. (Docker Desktop on Windows ignores this.)
    job_dir.chmod(0o777)
    for name, content in files:
        (job_dir / name).write_text(content, encoding="utf-8", newline="\n")
    return job_dir


def _remove_dir(path):
    def _onerror(func, p, _exc):
        try:
            Path(p).chmod(stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=_onerror)


# ------------------------------------------------------------------ main API

STAGE_ERRORS = {
    "analysis": "analysis_error",
    "elaboration": "elaboration_error",
    "simulation": "runtime_error",
}


def run_job(files, top, stop_time=None, job_id=None, client=None,
            timeout_s=None, keep_job_dir=False):
    """Validate, then run analysis, elaboration and simulation in isolated
    containers. Returns the result dict described at the top of this file."""
    job_id = job_id or uuid.uuid4().hex
    result = {"job_id": job_id, "status": "failed", "stage": "validation",
              "error": None, "message": "", "stages": [], "vcd": None}

    try:
        files, top, stop_time = validate_request(files, top, stop_time)
    except JobValidationError as e:
        result.update(error="validation_error", message=str(e))
        return result

    timeout_s = timeout_s or config.JOB_TIMEOUT_S
    job_dir = None
    try:
        client = client or get_client()
        job_dir = _make_job_dir(job_id, files)
        std = _std_flag()

        plan = [
            ("analysis", ["ghdl", "-a", *std, *[name for name, _ in files]]),
            ("elaboration", ["ghdl", "-e", *std, top]),
            ("simulation", ["ghdl", "-r", *std, top,
                            f"--vcd={VCD_NAME}", f"--stop-time={stop_time}"]),
        ]

        for stage, command in plan:
            result["stage"] = stage
            info = _run_stage(client, job_id, job_dir, stage, command, timeout_s)
            result["stages"].append(info)

            if info["timed_out"]:
                result.update(error="timeout", message=(
                    f"{stage.capitalize()} did not finish within {timeout_s} s; "
                    "the container was killed."))
                return result
            if info["oom_killed"]:
                result.update(error="memory_limit", message=(
                    f"{stage.capitalize()} went over the {config.MEM_LIMIT} "
                    "memory limit; the container was killed."))
                return result
            if info["exit_code"] != 0:
                result.update(error=STAGE_ERRORS[stage], message=(
                    f"{stage.capitalize()} failed (exit code "
                    f"{info['exit_code']}). See the stage output."))
                return result

        vcd_path = job_dir / VCD_NAME
        if vcd_path.is_file():
            size = vcd_path.stat().st_size
            if size > config.MAX_VCD_BYTES:
                result["message"] = (f"Simulation finished, but the VCD "
                                     f"({size} bytes) is over the limit and "
                                     "was not kept.")
            else:
                result["vcd"] = vcd_path.read_bytes()
                result["message"] = "Simulation finished."
        else:
            result["message"] = "Simulation finished, but no VCD was produced."

        result.update(status="success", stage="done")
        return result

    except ImageNotFound:
        result.update(error="internal_error", message=(
            f"GHDL image '{config.GHDL_IMAGE}' not found. Build it with: "
            f"docker build -t {config.GHDL_IMAGE} ./docker"))
        return result
    except DockerException as e:
        result.update(error="internal_error",
                      message=f"Docker error: {e}. Is Docker running?")
        return result
    finally:
        if job_dir is not None and not keep_job_dir:
            _remove_dir(job_dir)


def cleanup_stale_jobs(client=None, max_age_s=None):
    """Remove leftover job containers and job folders older than the TTL.
    Call this once at API startup, before any jobs run: it force-removes
    EVERY container with the p5a.job label, including ones still running.
    Returns (containers_removed, folders_removed)."""
    max_age_s = config.JOB_TTL_S if max_age_s is None else max_age_s
    containers_removed = 0
    try:
        client = client or get_client()
        for c in client.containers.list(
                all=True, filters={"label": config.CONTAINER_LABEL}):
            try:
                c.remove(force=True)
                containers_removed += 1
            except DockerException:
                pass
    except DockerException:
        pass

    folders_removed = 0
    if config.JOBS_DIR.is_dir():
        now = time.time()
        for d in config.JOBS_DIR.iterdir():
            if d.is_dir() and now - d.stat().st_mtime > max_age_s:
                _remove_dir(d)
                folders_removed += 1
    return containers_removed, folders_removed
