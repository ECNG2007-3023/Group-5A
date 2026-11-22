"""Invariants: rules that must ALWAYS be true about the service's results.

The checks run inside the service (not only in the tests):

    every result, before run_job() returns it   check_result()    docker_runner.py
    before a job folder is deleted              check_inside()    docker_runner.py
    after files are put in dependency order     check_same_files() docker_runner.py

A broken rule raises InvariantError. That is a bug in the service, never the
client's fault, so main.py's catch-all handler turns it into HTTP 500
"internal_error" instead of sending a wrong result, and the job folder is
still cleaned up (run_job's `finally`).

A real exception is used instead of Python's `assert`, because `assert`
statements are removed when Python runs with -O, and these checks must stay.
"""
from pathlib import Path

RESULT_KEYS = {"job_id", "status", "stage", "error", "message", "stages", "vcd"}
STAGE_ORDER = ["analysis", "elaboration", "simulation"]
ERROR_CODES = {"validation_error", "analysis_error", "elaboration_error",
               "runtime_error", "timeout", "memory_limit", "internal_error"}
# The stage each "the VHDL failed" error must come from.
STAGE_OF_ERROR = {"analysis_error": "analysis",
                  "elaboration_error": "elaboration",
                  "runtime_error": "simulation"}
TRUNCATION_ALLOWANCE = 100   # room for the "[output truncated ...]" marker


class InvariantError(RuntimeError):
    """A rule that must always hold was broken: a bug in the service."""


def require(condition, rule):
    """Raise InvariantError naming the rule if the condition is false."""
    if not condition:
        raise InvariantError(rule)


def _clean(stage):
    return (stage["exit_code"] == 0 and not stage["timed_out"]
            and not stage["oom_killed"])


def check_result(result, max_log_chars):
    """The contract v1 rules for one result dict from run_job()."""
    require(isinstance(result, dict) and set(result) == RESULT_KEYS,
            "a result has exactly the contract v1 fields")
    require(isinstance(result["job_id"], str) and result["job_id"],
            "a result has a job id")
    status, error, stages = result["status"], result["error"], result["stages"]
    require(status in ("success", "failed"), 'status is "success" or "failed"')
    require((status == "success") == (error is None),
            "error is empty exactly when the job succeeded")

    # Stages run in order, and stop at the first one that fails.
    names = [s["stage"] for s in stages]
    require(names == STAGE_ORDER[:len(names)],
            "stages run in order: analysis, elaboration, simulation")
    require(all(_clean(s) for s in stages[:-1]),
            "only the last stage that ran can have failed")
    for s in stages:
        require(len(s["output"]) <= max_log_chars + TRUNCATION_ALLOWANCE,
                "stage output is within the size limit")

    if status == "success":
        require(result["stage"] == "done", 'a success has stage "done"')
        require(names == STAGE_ORDER and _clean(stages[-1]),
                "a success ran all three stages without an error")
        require(result["vcd"] is None or isinstance(result["vcd"], bytes),
                "the VCD is bytes or empty")
        return

    require(error in ERROR_CODES, "error is one of the contract's codes")
    require(result["vcd"] is None, "a failed job has no VCD")
    require(isinstance(result["message"], str) and result["message"],
            "a failed job explains why")
    if error == "validation_error":
        require(result["stage"] == "validation" and stages == [],
                "a rejected request starts no container")
    elif error in STAGE_OF_ERROR:
        require(stages and names[-1] == STAGE_OF_ERROR[error]
                and result["stage"] == names[-1] and stages[-1]["exit_code"] != 0,
                f"{error} comes from a failed {STAGE_OF_ERROR[error]} stage")
    elif error == "timeout":
        require(stages and stages[-1]["timed_out"], "a timeout comes from a killed stage")
    elif error == "memory_limit":
        require(stages and stages[-1]["oom_killed"],
                "memory_limit comes from a stage killed for memory")


# ------------------------------------------------------------- loop invariants
#
# Each loop invariant is checked three times, as in the lecture's proof
# pattern: ESTABLISHMENT (true before the first iteration), PRESERVATION
# (still true after every iteration) and EXIT (true when the loop ends, which
# gives the result we want). TERMINATION is checked separately with a measure
# that must get smaller on every iteration and can never go below zero.

def check_order_invariant(placed, needs):
    """Loop invariant of analysis_order():
    every file placed so far comes AFTER every file it depends on.
    (Same shape as the lecture's "max is the largest of the elements
    processed so far": a property of the part of the list built so far.)"""
    seen = set()
    for i in placed:
        require(needs[i] <= seen,
                "loop invariant: each file is placed after the files it needs")
        require(i not in seen, "loop invariant: no file is placed twice")
        seen.add(i)


def check_progress(before, after):
    """Termination: the measure (files still to place / stages still to run)
    must get strictly smaller every iteration and never go below zero."""
    require(0 <= after < before, "termination: the loop makes progress")


def check_stage_loop(stages, plan_names):
    """Loop invariant of the stage loop in run_job(): at the start of every
    iteration, the stages run so far are the first ones of the plan, in order,
    and every one of them finished cleanly (a failed stage ends the loop)."""
    names = [s["stage"] for s in stages]
    require(names == plan_names[:len(names)],
            "loop invariant: the stages run so far are the plan's first stages")
    require(all(_clean(s) for s in stages),
            "loop invariant: every stage run so far finished cleanly")


def check_inside(path, root):
    """Only a job folder directly inside JOBS_DIR may be deleted, so a bug
    elsewhere can never make the service delete anything else."""
    path, root = Path(path).resolve(), Path(root).resolve()
    require(path.parent == root and path != root,
            "a deleted job folder is directly inside the jobs folder")


def check_same_files(before, after):
    """Sorting files into dependency order never adds, loses or changes one."""
    require(sorted(before) == sorted(after),
            "dependency ordering keeps exactly the files that were sent")
