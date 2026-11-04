"""Settings for the P5A GHDL Execution Service.

Every value can be overridden with an environment variable of the same name,
e.g. in PowerShell:  $env:P5A_JOB_TIMEOUT_S = "20"
"""
import os
from pathlib import Path


def _env(name, default, cast=str):
    value = os.environ.get(name)
    return cast(value) if value not in (None, "") else default


# Docker image that contains GHDL (built from docker/Dockerfile).
GHDL_IMAGE = _env("P5A_GHDL_IMAGE", "p5a-ghdl")

# Where per-job folders are created. It must be a folder the Docker daemon can
# see. On Windows + Docker Desktop, anything under C:\Users works, so the
# default is a "jobs" folder in the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = Path(_env("P5A_JOBS_DIR", str(REPO_ROOT / "jobs"))).resolve()

# Resource limits applied to every job container.
JOB_TIMEOUT_S = _env("P5A_JOB_TIMEOUT_S", 10, int)      # per stage, wall clock
MEM_LIMIT = _env("P5A_MEM_LIMIT", "256m")                # RAM cap (no swap)
CPU_LIMIT = _env("P5A_CPU_LIMIT", 1.0, float)            # number of CPUs
PIDS_LIMIT = _env("P5A_PIDS_LIMIT", 64, int)             # stops fork bombs
TMPFS_SIZE = _env("P5A_TMPFS_SIZE", "16m")               # writable /tmp size

# How many jobs may run at once; extra requests wait for a free slot.
MAX_CONCURRENT_JOBS = _env("P5A_MAX_CONCURRENT_JOBS", 4, int)

# Request limits.
MAX_FILES = _env("P5A_MAX_FILES", 20, int)
MAX_FILE_BYTES = _env("P5A_MAX_FILE_BYTES", 200_000, int)
MAX_LOG_CHARS = _env("P5A_MAX_LOG_CHARS", 20_000, int)   # output kept per stage
MAX_VCD_BYTES = _env("P5A_MAX_VCD_BYTES", 5_000_000, int)
DEFAULT_STOP_TIME = _env("P5A_DEFAULT_STOP_TIME", "1us")

# Optional VHDL standard passed to GHDL, e.g. "08" or "93c". Empty = GHDL default.
GHDL_STD = _env("P5A_GHDL_STD", "")

# Job folders older than this are deleted by cleanup_stale_jobs().
JOB_TTL_S = _env("P5A_JOB_TTL_S", 3600, int)

# Label put on every job container so leftovers can be found and removed.
CONTAINER_LABEL = "p5a.job"

# Browser origins allowed to call the API (for the P6B front end), comma
# separated, e.g. "http://localhost:5173,http://127.0.0.1:5173". "*" = any.
CORS_ORIGINS = [o.strip() for o in _env("P5A_CORS_ORIGINS", "*").split(",")
                if o.strip()]
