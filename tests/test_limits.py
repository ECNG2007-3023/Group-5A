"""Milestone 5: resource-limit, sandbox, stress and cleanup tests.

These run real VHDL (and a few shell probes) in the real p5a-ghdl image to
prove the limits in app/config.py are actually enforced, not just requested.
They are skipped when Docker is not running or the image is not built.

    python -m pytest tests/test_limits.py -v
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import config, docker_runner as dr
from conftest import (REAL_DOCKER, assert_cleaned_up, leftover_containers,
                      needs_docker, vhdl)

GOOD = [vhdl("and_gate.vhd"), vhdl("and_gate_tb.vhd")]


# --------------------------------------------- the container sandbox itself

def probe(jobs_dir, command):
    """Run a shell command in a job container with the exact same limits as
    a GHDL stage. Returns the stage dict (exit_code, output, ...)."""
    job_dir = jobs_dir / "probe"
    job_dir.mkdir(parents=True)
    job_dir.chmod(0o777)
    try:
        return dr._run_stage(REAL_DOCKER, "probe", job_dir, "probe",
                             command, timeout_s=20)
    finally:
        dr._remove_dir(job_dir)


@needs_docker
class TestSandbox:
    def test_runs_as_non_root(self, jobs_dir):
        r = probe(jobs_dir, ["id", "-u"])
        assert r["exit_code"] == 0
        assert r["output"].strip() != "0"

    def test_has_no_network(self, jobs_dir):
        # Only the loopback interface exists: no route to the outside at all.
        r = probe(jobs_dir, ["ls", "/sys/class/net"])
        assert r["output"].split() == ["lo"]

    def test_root_filesystem_is_read_only(self, jobs_dir):
        r = probe(jobs_dir, ["sh", "-c", "touch /etc/hacked"])
        assert r["exit_code"] != 0
        assert "Read-only file system" in r["output"]

    def test_only_work_and_tmp_are_writable(self, jobs_dir):
        r = probe(jobs_dir, ["sh", "-c", "touch /work/a /tmp/b && echo ok"])
        assert r["exit_code"] == 0 and "ok" in r["output"]

    def test_all_capabilities_dropped(self, jobs_dir):
        r = probe(jobs_dir, ["grep", "CapEff", "/proc/self/status"])
        assert r["output"].split()[-1] == "0000000000000000"

    def test_process_limit_stops_fork_bomb(self, jobs_dir):
        r = probe(jobs_dir, ["sh", "-c",
                             "for i in $(seq 200); do sleep 2 & done; wait"])
        assert r["exit_code"] != 0
        assert "fork" in r["output"].lower()

    def test_tmp_is_size_limited(self, jobs_dir):
        r = probe(jobs_dir, ["sh", "-c",
                             "dd if=/dev/zero of=/tmp/big bs=1M count=64"])
        assert r["exit_code"] != 0
        assert "No space left" in r["output"]


# --------------------------------------------------- limits on real VHDL

@needs_docker
class TestVhdlLimits:
    def test_memory_hog_is_killed_as_memory_limit(self, jobs_dir):
        start = time.monotonic()
        r = dr.run_job([vhdl("mem_hog_tb.vhd")], "mem_hog_tb", "1sec",
                       client=REAL_DOCKER, timeout_s=30)
        assert r["error"] == "memory_limit", r["message"]
        assert r["stage"] == "simulation"
        assert r["stages"][-1]["oom_killed"] is True
        assert time.monotonic() - start < 30          # killed, not timed out
        assert_cleaned_up(jobs_dir)

    def test_runaway_is_killed_as_timeout(self, jobs_dir):
        start = time.monotonic()
        r = dr.run_job([vhdl("runaway_tb.vhd")], "runaway_tb", "1sec",
                       client=REAL_DOCKER, timeout_s=3)
        assert r["error"] == "timeout"
        assert r["stages"][-1]["timed_out"] is True
        assert time.monotonic() - start < 20
        assert_cleaned_up(jobs_dir)

    def test_huge_output_keeps_the_final_error(self, jobs_dir):
        r = dr.run_job([vhdl("chatty_fail_tb.vhd")], "chatty_fail_tb", "1us",
                       client=REAL_DOCKER)
        out = r["stages"][-1]["output"]
        assert r["error"] == "runtime_error"
        assert "output truncated" in out
        assert len(out) < config.MAX_LOG_CHARS + 200
        assert "step 1" in out                        # the start is kept
        assert "FINAL CHECK FAILED" in out            # and so is the end

    def test_vcd_over_limit_is_dropped(self, jobs_dir, monkeypatch):
        monkeypatch.setattr(config, "MAX_VCD_BYTES", 50)
        r = dr.run_job(GOOD, "and_gate_tb", "100ns", client=REAL_DOCKER)
        assert r["status"] == "success"
        assert r["vcd"] is None
        assert "over the limit" in r["message"]
        assert_cleaned_up(jobs_dir)

    @pytest.mark.parametrize("files, top, error", [
        ([vhdl("invalid_syntax.vhd")], "invalid_syntax", "analysis_error"),
        ([vhdl("and_gate.vhd")], "no_such_entity", "elaboration_error"),
        ([vhdl("simulation_failure_tb.vhd")], "simulation_failure_tb",
         "runtime_error"),
    ])
    def test_every_failure_cleans_up(self, jobs_dir, files, top, error):
        r = dr.run_job(files, top, "100ns", client=REAL_DOCKER)
        assert r["error"] == error
        assert_cleaned_up(jobs_dir)


# -------------------------------------------------------------- stress

@needs_docker
class TestStress:
    def test_parallel_jobs_are_correct_and_isolated(self, jobs_dir):
        """8 jobs at once, mixing good and bad VHDL with the SAME file name.
        Each must get its own answer, and nothing may be left behind."""
        jobs = []
        for i in range(8):
            if i % 2:
                bad = {"name": "and_gate.vhd",
                       "content": vhdl("invalid_syntax.vhd")["content"]}
                jobs.append(([bad], "invalid_syntax", "analysis_error"))
            else:
                jobs.append((GOOD, "and_gate_tb", None))

        def run(job):
            files, top, _ = job
            return dr.run_job(files, top, "100ns", client=REAL_DOCKER)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(run, jobs))

        for (_, _, expected), r in zip(jobs, results):
            assert r["error"] == expected, r["message"]
            if expected is None:
                assert b"$enddefinitions" in r["vcd"]
        assert len({r["job_id"] for r in results}) == 8
        assert_cleaned_up(jobs_dir)

    def test_cleanup_removes_leftover_container(self, jobs_dir):
        """A container left by a crashed API is removed at the next start."""
        REAL_DOCKER.containers.run(
            config.GHDL_IMAGE, ["sleep", "60"], detach=True,
            labels={config.CONTAINER_LABEL: "crashed-job"})
        assert len(leftover_containers()) == 1
        removed, _ = dr.cleanup_stale_jobs(REAL_DOCKER)
        assert removed == 1
        assert leftover_containers() == []


# -------------------------------------- concurrency cap (no Docker needed)

class SlowFakeClient:
    """Fake Docker whose containers take 0.2 s; records peak concurrency."""

    def __init__(self):
        self.containers = self
        self.running = 0
        self.peak = 0
        self.lock = threading.Lock()

    def run(self, image, command, **kwargs):
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        client = self

        class C:
            attrs = {"State": {"OOMKilled": False}}

            def wait(self, timeout=None):
                time.sleep(0.2)
                with client.lock:
                    client.running -= 1
                return {"StatusCode": 1}       # analysis fails: one stage

            def reload(self): pass
            def kill(self): pass
            def logs(self, **_): return b""
            def remove(self, force=False): pass
        return C()


def test_concurrent_jobs_are_capped(jobs_dir, monkeypatch):
    monkeypatch.setattr(dr, "_job_slots", threading.BoundedSemaphore(2))
    client = SlowFakeClient()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(
            lambda _: dr.run_job(GOOD, "and_gate_tb", client=client), range(6)))
    assert client.peak == 2                    # never more than the cap
    assert all(r["error"] == "analysis_error" for r in results)


def test_truncate_keeps_start_and_end():
    text = "START" + "x" * 1000 + "END"
    out = dr._truncate(text, limit=100)
    assert out.startswith("START") and out.endswith("END")
    assert "908 characters removed" in out     # 1008 long, 100 kept
