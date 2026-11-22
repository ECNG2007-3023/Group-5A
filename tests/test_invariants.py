"""Invariants, assertions and exceptions (app/invariants.py).

White-box tests: check_result() accepts every result the runner really
produces and rejects each way a contract rule can be broken. Then a broken
rule is forced inside the running service to prove the client gets HTTP 500
"internal_error" (never a wrong result) and the job folder is still removed.
No Docker needed: Docker is replaced by the fake from test_docker_runner.py.
"""
import copy

import pytest
from fastapi.testclient import TestClient

from app import config, docker_runner as dr, main
from app import invariants as inv
from app.invariants import InvariantError
from conftest import vhdl
from test_docker_runner import OK, FakeClient

GOOD = [vhdl("and_gate.vhd"), vhdl("and_gate_tb.vhd")]
LIMIT = config.MAX_LOG_CHARS


def stage(name, exit_code=0, timed_out=False, oom=False, output=""):
    return {"stage": name, "command": "ghdl", "exit_code": exit_code, "output": output,
            "duration_s": 0.1, "timed_out": timed_out, "oom_killed": oom}


SUCCESS = {"job_id": "abc", "status": "success", "stage": "done", "error": None,
           "message": "Simulation finished.", "vcd": b"$end",
           "stages": [stage("analysis"), stage("elaboration"), stage("simulation")]}
ANALYSIS_FAIL = {**SUCCESS, "status": "failed", "stage": "analysis", "vcd": None,
                 "error": "analysis_error", "message": "Analysis failed.",
                 "stages": [stage("analysis", 1)]}


def broken(result):
    """check_result must refuse this result; returns the rule it names."""
    with pytest.raises(InvariantError) as exc:
        inv.check_result(result, LIMIT)
    return str(exc.value)


def changed(result, **fields):
    r = copy.deepcopy(result)
    r.update(fields)
    return r


# ------------------------------------------- everything the runner produces passes

FAIL = (1, "error", False, False)
TIMEOUT = (None, "", True, False)
OOM = (137, "", False, True)


# Success, and each kind of failure at each of the three stages (10 cases).
@pytest.mark.parametrize("behaviours", [
    *[[b] for b in (FAIL, TIMEOUT, OOM)],
    *[[OK, b] for b in (FAIL, TIMEOUT, OOM)],
    *[[OK, OK, b] for b in (OK, FAIL, TIMEOUT, OOM)],
])
def test_every_runner_outcome_obeys_the_rules(jobs_dir, behaviours):
    """Success and every failure at every stage: run_job checks its own result
    before returning, so getting a result back at all means the rules held."""
    r = dr.run_job(GOOD, "and_gate_tb", client=FakeClient(behaviours))
    inv.check_result(r, LIMIT)
    assert list(jobs_dir.iterdir()) == []


def test_validation_failure_obeys_the_rules():
    r = dr.run_job([{"name": "../x.vhd", "content": "x"}], "x")
    inv.check_result(r, LIMIT)
    assert r["error"] == "validation_error"


# ------------------------------------------- each broken rule is caught

@pytest.mark.parametrize("result, rule", [
    (changed(SUCCESS, extra=1), "exactly the contract v1 fields"),
    (changed(SUCCESS, job_id=""), "job id"),
    (changed(SUCCESS, status="ok"), '"success" or "failed"'),
    (changed(SUCCESS, error="timeout"), "error is empty exactly when"),
    (changed(ANALYSIS_FAIL, error=None), "error is empty exactly when"),
    (changed(SUCCESS, stage="simulation"), 'stage "done"'),
    (changed(SUCCESS, stages=[stage("analysis"), stage("elaboration")]),
     "all three stages"),
    (changed(SUCCESS, stages=[stage("elaboration"), stage("analysis"), stage("simulation")]),
     "in order"),
    (changed(SUCCESS, stages=[stage("analysis", 1), stage("elaboration"),
                              stage("simulation")]), "only the last stage"),
    (changed(SUCCESS, vcd="text"), "VCD is bytes"),
    (changed(ANALYSIS_FAIL, vcd=b"$end"), "no VCD"),
    (changed(ANALYSIS_FAIL, error="oops"), "contract's codes"),
    (changed(ANALYSIS_FAIL, message=""), "explains why"),
    (changed(ANALYSIS_FAIL, error="elaboration_error"),
     "elaboration_error comes from a failed elaboration stage"),
    (changed(ANALYSIS_FAIL, stages=[stage("analysis", 0)]), "failed analysis stage"),
    (changed(ANALYSIS_FAIL, error="validation_error"), "starts no container"),
    (changed(ANALYSIS_FAIL, error="timeout"), "killed stage"),
    (changed(ANALYSIS_FAIL, error="memory_limit"), "killed for memory"),
    (changed(ANALYSIS_FAIL, stages=[stage("analysis", 1, output="x" * (LIMIT + 500))]),
     "size limit"),
])
def test_broken_results_are_caught(result, rule):
    assert rule in broken(result)


def test_only_job_folders_may_be_deleted(tmp_path):
    jobs = tmp_path / "jobs"
    inv.check_inside(jobs / "abc", jobs)
    for bad in (jobs, tmp_path, jobs / "abc" / "deeper", jobs / ".." / "x"):
        with pytest.raises(InvariantError):
            inv.check_inside(bad, jobs)


def test_dependency_order_keeps_the_same_files():
    inv.check_same_files([("a", "1"), ("b", "2")], [("b", "2"), ("a", "1")])
    with pytest.raises(InvariantError):
        inv.check_same_files([("a", "1"), ("b", "2")], [("a", "1")])


# ------------------------------------------- broken rule inside the running service

def test_broken_result_becomes_500_and_job_folder_is_still_removed(
        jobs_dir, monkeypatch):
    """Force a bug: the runner labels a failed ANALYSIS stage "runtime_error"
    (a simulation error). The client must get HTTP 500, not the contradictory result,
    and no job folder may be left behind."""
    monkeypatch.setattr(dr, "STAGE_ERRORS", {**dr.STAGE_ERRORS,
                                             "analysis": "runtime_error"})
    client = FakeClient([FAIL])
    monkeypatch.setattr(dr, "get_client", lambda: client)
    monkeypatch.setattr(dr, "cleanup_stale_jobs", lambda *a, **k: (0, 0))
    with TestClient(main.app, raise_server_exceptions=False) as c:
        r = c.post("/simulate", json={"files": GOOD, "top": "and_gate_tb"})
    assert r.status_code == 500
    assert r.json()["error"] == "internal_error" and r.json()["vcd"] is None
    assert list(jobs_dir.iterdir()) == []


def test_delete_refuses_a_folder_outside_jobs(jobs_dir, monkeypatch, tmp_path):
    """Force a bug: the job folder points outside JOBS_DIR. Nothing is deleted."""
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "keep.txt").write_text("x")
    monkeypatch.setattr(dr, "_make_job_dir", lambda job_id, files: precious)
    with pytest.raises(InvariantError):
        dr.run_job(GOOD, "and_gate_tb", client=FakeClient([OK, OK, OK]))
    assert (precious / "keep.txt").exists()


# =========================================== loop invariants (lecture pattern)

def test_order_loop_invariant_trace(monkeypatch):
    """The analysis_order() loop on [testbench, design], traced the same way as
    the lecture's maximum example: the invariant is checked at ESTABLISHMENT
    (nothing placed), after each iteration (PRESERVATION) and at EXIT.

        iteration | placed so far      | invariant
        start     | []                 | true (nothing placed)
        1         | [design]           | design needs nothing      -> true
        2         | [design, tb]       | tb needs design, placed   -> true
        exit      | all files placed   | so the whole list is in dependency order
    """
    snapshots = []
    real = dr.check_order_invariant

    def record(placed, needs):
        snapshots.append(list(placed))
        real(placed, needs)
    monkeypatch.setattr(dr, "check_order_invariant", record)
    tb, design = vhdl("and_gate_tb.vhd"), vhdl("and_gate.vhd")
    files = [(tb["name"], tb["content"]), (design["name"], design["content"])]
    result = dr.analysis_order(files)
    assert [n for n, _ in result] == ["and_gate.vhd", "and_gate_tb.vhd"]
    assert snapshots == [[], [1], [1, 0], [1, 0]]   # establish, 2 x preserve, exit


def test_order_loop_invariant_catches_a_bad_order():
    needs = [{1}, set()]                       # file 0 needs file 1
    inv.check_order_invariant([1, 0], needs)   # correct
    with pytest.raises(InvariantError, match="placed after the files it needs"):
        inv.check_order_invariant([0, 1], needs)
    with pytest.raises(InvariantError, match="placed twice"):
        inv.check_order_invariant([1, 1], [set(), set()])


def test_termination_measure_must_decrease():
    inv.check_progress(3, 2)
    for before, after in ((2, 2), (2, 3), (1, -1)):
        with pytest.raises(InvariantError, match="termination"):
            inv.check_progress(before, after)


def test_stage_loop_invariant_catches_each_break():
    plan = ["analysis", "elaboration", "simulation"]
    inv.check_stage_loop([stage("analysis"), stage("elaboration")], plan)
    with pytest.raises(InvariantError, match="first stages"):
        inv.check_stage_loop([stage("elaboration")], plan)
    with pytest.raises(InvariantError, match="finished cleanly"):
        inv.check_stage_loop([stage("analysis", 1)], plan)


def test_broken_stage_loop_is_stopped(jobs_dir, monkeypatch):
    """Force a bug: a stage reports the wrong name. The loop invariant stops
    the job (InvariantError) instead of running on, and still cleans up."""
    real = dr._run_stage

    def wrong_name(*args, **kwargs):
        info = real(*args, **kwargs)
        info["stage"] = "simulation"
        return info
    monkeypatch.setattr(dr, "_run_stage", wrong_name)
    with pytest.raises(InvariantError, match="loop invariant"):
        dr.run_job(GOOD, "and_gate_tb", client=FakeClient([OK, OK, OK]))
    assert list(jobs_dir.iterdir()) == []


# ======================================================= assertions (assert)

def test_assertions_guard_programmer_assumptions(tmp_path):
    """assert statements check assumptions made by the programmer. They are
    switched on in normal runs and in testing (and off with python -O, which
    is why the must-always-hold rules use InvariantError instead)."""
    with pytest.raises(AssertionError):
        dr._truncate("text", limit=-1)                          # limit must be > 0
    with pytest.raises(AssertionError):
        dr._make_job_dir("j", [("a.vhd", "x"), ("A.vhd", "y")])  # names unique
    with pytest.raises(AssertionError):
        dr._run_stage(None, "j", tmp_path, "analysis", ["ghdl", "-a"], timeout_s=0)
