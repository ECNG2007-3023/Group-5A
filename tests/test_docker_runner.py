"""Milestone 3 tests for app/docker_runner.py.

Run from the repo root (venv active):
    python -m pytest tests -v

* Validation and fake-Docker tests run anywhere, no Docker needed.
* The "real Docker" tests need Docker Desktop running and the image built
  (docker build -t p5a-ghdl ./docker). If either is missing they are SKIPPED,
  not failed.
"""
import time
from pathlib import Path

import pytest
import requests

from app import config, docker_runner as dr

# ----------------------------------------------------------------- fixtures

AND_GATE = """\
library ieee;
use ieee.std_logic_1164.all;

entity and_gate is
  port (a, b : in std_logic; y : out std_logic);
end entity;

architecture rtl of and_gate is
begin
  y <= a and b;
end architecture;
"""

AND_GATE_TB = """\
library ieee;
use ieee.std_logic_1164.all;

entity and_gate_tb is
end entity;

architecture sim of and_gate_tb is
  signal a, b, y : std_logic := '0';
begin
  dut: entity work.and_gate port map (a => a, b => b, y => y);

  stim: process
  begin
    a <= '0'; b <= '0'; wait for 10 ns;
    assert y = '0' report "0 and 0 should be 0" severity error;
    a <= '1'; b <= '1'; wait for 10 ns;
    assert y = '1' report "1 and 1 should be 1" severity error;
    wait;
  end process;
end architecture;
"""

SYNTAX_ERROR = AND_GATE.replace("y <= a and b;", "y <= a and b")   # missing ;

FAILING_TB = """\
entity fail_tb is
end entity;

architecture sim of fail_tb is
begin
  process
  begin
    wait for 5 ns;
    assert false report "deliberate failure" severity failure;
    wait;
  end process;
end architecture;
"""

RUNAWAY_TB = """\
entity runaway_tb is
end entity;

architecture sim of runaway_tb is
  signal clk : bit := '0';
begin
  process
  begin
    loop
      clk <= not clk;
      wait for 1 ns;
    end loop;
  end process;
end architecture;
"""

GOOD_FILES = [{"name": "and_gate.vhd", "content": AND_GATE},
              {"name": "and_gate_tb.vhd", "content": AND_GATE_TB}]


@pytest.fixture(autouse=True)
def temp_jobs_dir(tmp_path, monkeypatch):
    """Every test gets its own jobs folder, so we can check it is cleaned up."""
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(config, "JOBS_DIR", jobs)
    return jobs


# ------------------------------------------------- validation (no Docker)

class TestValidation:
    def test_good_request_is_normalised(self):
        files, top, stop = dr.validate_request(GOOD_FILES, "and_gate_tb", "100 ns")
        assert [n for n, _ in files] == ["and_gate.vhd", "and_gate_tb.vhd"]
        assert top == "and_gate_tb"
        assert stop == "100ns"

    def test_dict_of_files_accepted(self):
        files, _, _ = dr.validate_request({"a.vhd": AND_GATE}, "and_gate")
        assert files == [("a.vhd", AND_GATE)]

    def test_default_stop_time(self):
        _, _, stop = dr.validate_request(GOOD_FILES, "and_gate_tb", None)
        assert stop == config.DEFAULT_STOP_TIME

    @pytest.mark.parametrize("name", [
        "../evil.vhd", "dir/a.vhd", "a.txt", "a", "", ".hidden.vhd", "a b.vhd",
        "C:\\x.vhd",
    ])
    def test_bad_file_names_rejected(self, name):
        with pytest.raises(dr.JobValidationError):
            dr.validate_request([{"name": name, "content": AND_GATE}], "and_gate")

    def test_no_files_rejected(self):
        with pytest.raises(dr.JobValidationError):
            dr.validate_request([], "x")

    def test_empty_file_rejected(self):
        with pytest.raises(dr.JobValidationError):
            dr.validate_request([{"name": "a.vhd", "content": "   "}], "x")

    def test_duplicate_names_rejected(self):
        with pytest.raises(dr.JobValidationError):
            dr.validate_request([{"name": "a.vhd", "content": AND_GATE},
                                 {"name": "A.vhd", "content": AND_GATE}], "x")

    def test_too_large_rejected(self, monkeypatch):
        monkeypatch.setattr(config, "MAX_FILE_BYTES", 10)
        with pytest.raises(dr.JobValidationError):
            dr.validate_request([{"name": "a.vhd", "content": AND_GATE}], "x")

    def test_too_many_files_rejected(self, monkeypatch):
        monkeypatch.setattr(config, "MAX_FILES", 1)
        with pytest.raises(dr.JobValidationError):
            dr.validate_request(GOOD_FILES, "and_gate_tb")

    @pytest.mark.parametrize("top", ["", "1tb", "tb;rm", "tb tb", "--help"])
    def test_bad_top_rejected(self, top):
        with pytest.raises(dr.JobValidationError):
            dr.validate_request(GOOD_FILES, top)

    @pytest.mark.parametrize("stop", ["100", "ns", "-5ns", "1 hour", "1ns; ls"])
    def test_bad_stop_time_rejected(self, stop):
        with pytest.raises(dr.JobValidationError):
            dr.validate_request(GOOD_FILES, "and_gate_tb", stop)

    def test_run_job_returns_validation_error_without_docker(self):
        r = dr.run_job([], "x", client=object())   # client is never touched
        assert r["status"] == "failed"
        assert r["error"] == "validation_error"
        assert r["stages"] == []


# ------------------------------------------- fake Docker (no Docker needed)

class FakeContainer:
    def __init__(self, behaviour, command, kwargs):
        self.behaviour = behaviour      # (exit_code, output, hang, oom)
        self.command = command
        self.kwargs = kwargs
        self.killed = False
        self.removed = False
        self.attrs = {"State": {"OOMKilled": behaviour[3]}}

    def wait(self, timeout=None):
        if self.behaviour[2] and not self.killed:
            raise requests.exceptions.ReadTimeout()
        return {"StatusCode": 137 if self.killed else self.behaviour[0]}

    def kill(self):
        self.killed = True

    def reload(self):
        pass

    def logs(self, stdout=True, stderr=True):
        return self.behaviour[1].encode()

    def remove(self, force=False):
        self.removed = True


class FakeClient:
    """Plays back one behaviour per stage and writes a VCD on simulation."""

    def __init__(self, behaviours):
        self.behaviours = list(behaviours)
        self.started = []
        self.containers = self

    def run(self, image, command, **kwargs):
        c = FakeContainer(self.behaviours.pop(0), command, kwargs)
        self.started.append(c)
        if command[1] == "-r" and c.behaviour[0] == 0 and not c.behaviour[2]:
            host_dir = Path(next(iter(kwargs["volumes"])))
            (host_dir / dr.VCD_NAME).write_text("$timescale 1fs $end\n")
        return c


OK = (0, "", False, False)


class TestWithFakeDocker:
    def test_success_returns_vcd_and_cleans_up(self, temp_jobs_dir):
        client = FakeClient([OK, OK, OK])
        r = dr.run_job(GOOD_FILES, "and_gate_tb", "100ns", client=client)
        assert r["status"] == "success" and r["stage"] == "done"
        assert r["vcd"].startswith(b"$timescale")
        assert [s["stage"] for s in r["stages"]] == ["analysis", "elaboration", "simulation"]
        assert all(c.removed for c in client.started)
        assert list(temp_jobs_dir.iterdir()) == []         # job folder deleted

    def test_every_container_is_locked_down(self):
        client = FakeClient([OK, OK, OK])
        dr.run_job(GOOD_FILES, "and_gate_tb", client=client)
        for c in client.started:
            kw = c.kwargs
            assert kw["network_disabled"] is True
            assert kw["read_only"] is True
            assert kw["mem_limit"] == config.MEM_LIMIT
            assert kw["memswap_limit"] == config.MEM_LIMIT
            assert kw["pids_limit"] == config.PIDS_LIMIT
            assert kw["nano_cpus"] == int(config.CPU_LIMIT * 1e9)
            assert kw["cap_drop"] == ["ALL"]
            assert "no-new-privileges" in kw["security_opt"]
            assert config.CONTAINER_LABEL in kw["labels"]

    def test_commands(self):
        client = FakeClient([OK, OK, OK])
        dr.run_job(GOOD_FILES, "and_gate_tb", "2 us", client=client)
        a, e, s = (c.command for c in client.started)
        assert a == ["ghdl", "-a", "and_gate.vhd", "and_gate_tb.vhd"]
        assert e == ["ghdl", "-e", "and_gate_tb"]
        assert s == ["ghdl", "-r", "and_gate_tb", "--vcd=wave.vcd", "--stop-time=2us"]

    def test_analysis_error_stops_early(self, temp_jobs_dir):
        client = FakeClient([(1, "and_gate.vhd:11:16: ';' expected", False, False)])
        r = dr.run_job(GOOD_FILES, "and_gate_tb", client=client)
        assert r["error"] == "analysis_error" and r["stage"] == "analysis"
        assert "';' expected" in r["stages"][0]["output"]
        assert len(client.started) == 1
        assert list(temp_jobs_dir.iterdir()) == []

    def test_elaboration_error(self):
        r = dr.run_job(GOOD_FILES, "and_gate_tb",
                       client=FakeClient([OK, (1, "unit not found", False, False)]))
        assert r["error"] == "elaboration_error"

    def test_runtime_error(self):
        r = dr.run_job(GOOD_FILES, "and_gate_tb",
                       client=FakeClient([OK, OK, (1, "assertion failure", False, False)]))
        assert r["error"] == "runtime_error" and r["stage"] == "simulation"

    def test_timeout_kills_and_removes_container(self, temp_jobs_dir):
        client = FakeClient([OK, OK, (0, "", True, False)])
        r = dr.run_job(GOOD_FILES, "and_gate_tb", client=client)
        sim = client.started[-1]
        assert r["error"] == "timeout"
        assert sim.killed and sim.removed
        assert r["stages"][-1]["timed_out"] is True
        assert list(temp_jobs_dir.iterdir()) == []

    def test_oom_reported(self):
        r = dr.run_job(GOOD_FILES, "and_gate_tb",
                       client=FakeClient([OK, OK, (137, "", False, True)]))
        assert r["error"] == "memory_limit"

    def test_long_output_truncated(self, monkeypatch):
        monkeypatch.setattr(config, "MAX_LOG_CHARS", 50)
        r = dr.run_job(GOOD_FILES, "and_gate_tb",
                       client=FakeClient([(1, "x" * 500, False, False)]))
        assert "truncated" in r["stages"][0]["output"]
        assert len(r["stages"][0]["output"]) < 200


# ------------------------------------------- real Docker (skipped if absent)

def _real_client():
    try:
        import docker
        client = docker.from_env()
        client.ping()
        client.images.get(config.GHDL_IMAGE)
        return client
    except Exception:
        return None


REAL = _real_client()
needs_docker = pytest.mark.skipif(
    REAL is None,
    reason=f"Docker not running or image '{config.GHDL_IMAGE}' not built")


def _leftover_containers():
    return REAL.containers.list(all=True, filters={"label": config.CONTAINER_LABEL})


@needs_docker
class TestRealDocker:
    def test_and_gate_simulates_and_makes_vcd(self, temp_jobs_dir):
        r = dr.run_job(GOOD_FILES, "and_gate_tb", "100ns", client=REAL)
        assert r["status"] == "success", r
        assert r["vcd"] and b"$enddefinitions" in r["vcd"]
        assert list(temp_jobs_dir.iterdir()) == []
        assert _leftover_containers() == []

    def test_syntax_error_is_analysis_error(self):
        r = dr.run_job([{"name": "and_gate.vhd", "content": SYNTAX_ERROR}],
                       "and_gate", client=REAL)
        assert r["error"] == "analysis_error", r
        assert r["stages"][0]["output"].strip()     # GHDL's message is passed back

    def test_unknown_top_is_elaboration_error(self):
        r = dr.run_job(GOOD_FILES, "no_such_tb", client=REAL)
        assert r["error"] == "elaboration_error", r

    def test_failing_assertion_is_runtime_error(self):
        r = dr.run_job([{"name": "fail_tb.vhd", "content": FAILING_TB}],
                       "fail_tb", "100ns", client=REAL)
        assert r["error"] == "runtime_error", r
        assert "deliberate failure" in r["stages"][-1]["output"]

    def test_runaway_simulation_is_killed(self, temp_jobs_dir):
        start = time.monotonic()
        r = dr.run_job([{"name": "runaway_tb.vhd", "content": RUNAWAY_TB}],
                       "runaway_tb", "1000sec", client=REAL, timeout_s=3)
        elapsed = time.monotonic() - start
        assert r["error"] == "timeout", r
        assert elapsed < 30
        assert _leftover_containers() == []        # nothing left running
        assert list(temp_jobs_dir.iterdir()) == []

    def test_jobs_do_not_see_each_other(self, temp_jobs_dir):
        """Two jobs with the same file name but different code both work,
        which only happens if each has its own folder/work library."""
        r1 = dr.run_job(GOOD_FILES, "and_gate_tb", "50ns", client=REAL)
        r2 = dr.run_job([{"name": "and_gate.vhd", "content": SYNTAX_ERROR}],
                        "and_gate", client=REAL)
        r3 = dr.run_job(GOOD_FILES, "and_gate_tb", "50ns", client=REAL)
        assert (r1["status"], r2["error"], r3["status"]) == \
               ("success", "analysis_error", "success")

    def test_cleanup_stale_jobs(self, temp_jobs_dir):
        old = temp_jobs_dir / "old_job"
        old.mkdir(parents=True)
        removed_containers, removed_dirs = dr.cleanup_stale_jobs(REAL, max_age_s=-1)
        assert removed_dirs == 1 and not old.exists()
