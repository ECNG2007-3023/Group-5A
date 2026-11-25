"""STD test cases for P5A (Software Testing Description v1.0.0, Group 5).

Every test is named after its STD ID (UT-01, IT-02, ...) so the pytest output
lines up with the test log in Section 3.4 of the STD. Each test also saves
what it saw to tests/evidence/<ID>.json -- that file is the test's evidence.

    python -m pytest tests/test_std.py -v -rA

* Tests without @needs_docker use a fake Docker client and run anywhere.
* Tests with @needs_docker need Docker Desktop running and the image built
  (docker build -t p5a-ghdl ./docker). Without it they are SKIPPED, not failed.

The P5B / joint cases (UT-08..UT-14, IT-03..IT-06, VT-03, VT-05) are in the
Group-5B repository's tests/test_std.py.
"""
import json
import platform
import statistics
import threading
import time
from pathlib import Path

import pytest
from docker.errors import DockerException
from fastapi.testclient import TestClient

from app import config, docker_runner as dr, main
from conftest import assert_cleaned_up, leftover_containers, needs_docker, vhdl
from test_docker_runner import OK, FakeClient
from test_integration import check_contract

EVIDENCE = Path(__file__).resolve().parent / "evidence"
AND_GATE = [vhdl("and_gate.vhd"), vhdl("and_gate_tb.vhd")]


def save(test_id, data):
    """Write the evidence for one STD test case (bytes are shortened to text)."""
    def clean(x):
        if isinstance(x, bytes):
            text = x.decode("utf-8", errors="replace")
            return text if len(text) < 1500 else text[:1500] + "\n... [cut]"
        if isinstance(x, str) and len(x) > 1500:
            return x[:1500] + "\n... [cut]"
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        return x
    EVIDENCE.mkdir(exist_ok=True)
    record = {"test_id": test_id, "platform": platform.platform(),
              "time": time.strftime("%Y-%m-%d %H:%M:%S"), "observed": clean(data)}
    (EVIDENCE / f"{test_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


@pytest.fixture
def http(jobs_dir, monkeypatch):
    monkeypatch.setattr(dr, "cleanup_stale_jobs", lambda *a, **k: (0, 0))
    with TestClient(main.app) as c:
        yield c


def fake_docker(monkeypatch, behaviours):
    """Make the API use a FakeClient that plays back one behaviour per stage."""
    client = FakeClient(behaviours)
    monkeypatch.setattr(dr, "get_client", lambda: client)
    return client


def no_docker_allowed(monkeypatch):
    """Fail the test if anything tries to start a container."""
    def refuse():
        raise AssertionError("a container was requested for an invalid request")
    monkeypatch.setattr(dr, "get_client", refuse)


def body(files, top, stop_time=None):
    b = {"files": files, "top": top}
    if stop_time:
        b["stop_time"] = stop_time
    return b


# =========================================================== 3.2.1 Unit tests

def test_UT01_valid_request_accepted(http, monkeypatch, jobs_dir):
    """FR-P5A-01: a well-formed request passes validation and creates a job."""
    files, top, stop = dr.validate_request(AND_GATE, "and_gate_tb", "100 ns")
    client = fake_docker(monkeypatch, [OK, OK, OK])
    r = http.post("/simulate", json=body(AND_GATE, "and_gate_tb", "100ns"))
    save("UT-01", {"normalised": {"files": [n for n, _ in files], "top": top, "stop_time": stop},
                   "http_status": r.status_code, "result": r.json(),
                   "containers_started": len(client.started)})
    assert r.status_code == 200 and r.json()["status"] == "success"
    assert r.json()["job_id"]
    assert len(client.started) == 3


UT02_CASES = {
    "no_files": body([], "and_gate_tb"),
    "empty_file": body([{"name": "e.vhd", "content": ""}], "e"),
    "blank_file": body([{"name": "e.vhd", "content": "   \n"}], "e"),
    "not_vhdl_name": body([{"name": "notes.txt", "content": "hello"}], "notes"),
    "path_traversal": body([{"name": "../x.vhd", "content": "entity x is end;"}], "x"),
    "bad_top": body(AND_GATE, "1abc"),
    "missing_top": {"files": AND_GATE},
    "oversized_file": body([{"name": "big.vhd", "content": "-" * (config.MAX_FILE_BYTES + 1)}], "big"),
}


@pytest.mark.parametrize("case", UT02_CASES)
def test_UT02_invalid_requests_rejected(http, monkeypatch, case):
    """FR-P5A-02: bad requests are rejected before any container is created."""
    no_docker_allowed(monkeypatch)
    r = http.post("/simulate", json=UT02_CASES[case])
    res = r.json()
    save(f"UT-02_{case}", {"request_case": case, "http_status": r.status_code, "result": res})
    assert r.status_code == 400
    assert res["status"] == "failed" and res["error"] == "validation_error"
    assert res["stage"] == "validation" and res["vcd"] is None and res["message"]


def test_UT03_stages_run_in_order(monkeypatch, jobs_dir):
    """FR-P5A-03: analysis -> elaboration -> simulation, in that order."""
    client = FakeClient([OK, OK, OK])
    r = dr.run_job(AND_GATE, "and_gate_tb", "100ns", client=client)
    commands = [c.command for c in client.started]
    save("UT-03", {"commands_in_order": commands, "stages": [s["stage"] for s in r["stages"]]})
    assert [c[1] for c in commands] == ["-a", "-e", "-r"]
    assert [s["stage"] for s in r["stages"]] == ["analysis", "elaboration", "simulation"]
    assert r["status"] == "success"


@pytest.mark.parametrize("failing, behaviours, ran", [
    ("analysis", [(1, "invalid_syntax.vhd:13:11: ';' expected", False, False)], 1),
    ("elaboration", [OK, (1, "unit no_such_tb not found", False, False)], 2),
])
def test_UT04_stops_at_first_failing_stage(jobs_dir, failing, behaviours, ran):
    """FR-P5A-03: no stage runs after the one that failed."""
    client = FakeClient(behaviours)
    r = dr.run_job(AND_GATE, "and_gate_tb", client=client)
    save(f"UT-04_{failing}", {"containers_started": len(client.started),
                              "stages_run": [s["stage"] for s in r["stages"]], "result": r})
    assert len(client.started) == ran
    assert r["stage"] == failing and r["status"] == "failed"
    assert "simulation" not in [s["stage"] for s in r["stages"]]
    assert list(jobs_dir.iterdir()) == []


def test_UT05_fresh_bounded_container_per_stage(jobs_dir):
    """FR-P5A-04: a new, locked-down container for every stage, always removed."""
    client = FakeClient([OK, OK, OK])
    dr.run_job(AND_GATE, "and_gate_tb", client=client)
    keys = ["network_disabled", "read_only", "mem_limit", "memswap_limit", "nano_cpus",
            "pids_limit", "cap_drop", "security_opt", "tmpfs"]
    seen = [{k: c.kwargs.get(k) for k in keys} for c in client.started]
    save("UT-05", {"containers": len(client.started), "settings_per_stage": seen,
                   "removed": [c.removed for c in client.started],
                   "documented_limits": {"timeout_s": config.JOB_TIMEOUT_S,
                                         "memory": config.MEM_LIMIT, "cpus": config.CPU_LIMIT,
                                         "pids": config.PIDS_LIMIT, "tmpfs": config.TMPFS_SIZE}})
    assert len({id(c) for c in client.started}) == 3
    for c in client.started:
        kw = c.kwargs
        assert kw["network_disabled"] is True and kw["read_only"] is True
        assert kw["mem_limit"] == kw["memswap_limit"] == config.MEM_LIMIT
        assert kw["nano_cpus"] == int(config.CPU_LIMIT * 1e9)
        assert kw["pids_limit"] == config.PIDS_LIMIT
        assert kw["cap_drop"] == ["ALL"] and "no-new-privileges" in kw["security_opt"]
        assert c.removed
    assert list(jobs_dir.iterdir()) == []


class DockerDownClient:
    containers = property(lambda self: self)

    def run(self, *a, **k):
        raise DockerException("Docker daemon is not running")


@pytest.mark.parametrize("label, client, stage, error", [
    ("analysis", FakeClient([(1, "';' expected", False, False)]), "analysis", "analysis_error"),
    ("elaboration", FakeClient([OK, (1, "unit not found", False, False)]),
     "elaboration", "elaboration_error"),
    ("simulation_assertion", FakeClient([OK, OK, (1, "assertion failure", False, False)]),
     "simulation", "runtime_error"),
    ("simulation_timeout", FakeClient([OK, OK, (0, "", True, False)]), "simulation", "timeout"),
    ("simulation_memory", FakeClient([OK, OK, (137, "", False, True)]),
     "simulation", "memory_limit"),
    # Docker fails while starting the first container: reported at the stage
    # that was about to run, as a service error (HTTP 503 from the API).
    ("service_docker_down", DockerDownClient(), "analysis", "internal_error"),
])
def test_UT06_failures_classified_by_stage(jobs_dir, label, client, stage, error):
    """FR-P5A-05: analysis, elaboration, simulation and service/runtime failures
    are told apart."""
    r = dr.run_job(AND_GATE, "and_gate_tb", client=client)
    save(f"UT-06_{label}", {"stage": r["stage"], "error": r["error"], "message": r["message"]})
    assert r["status"] == "failed"
    assert (r["stage"], r["error"]) == (stage, error)
    assert r["message"] and r["vcd"] is None


def test_UT07_result_fields_and_vcd_rule(http, monkeypatch):
    """FR-P5A-06: six contract fields (+ job_id); VCD on success, null on failure."""
    fake_docker(monkeypatch, [OK, OK, OK])
    ok = http.post("/simulate", json=body(AND_GATE, "and_gate_tb")).json()
    fake_docker(monkeypatch, [(1, "';' expected", False, False)])
    bad = http.post("/simulate", json=body(AND_GATE, "and_gate_tb")).json()
    save("UT-07", {"success": ok, "failure": bad})
    for res in (ok, bad):
        check_contract(res)
    assert ok["vcd"] and ok["vcd"].startswith("$timescale")
    assert bad["vcd"] is None


# ==================================================== 3.2.2 Integration tests

@needs_docker
def test_IT01_api_validation_runner(http, jobs_dir):
    """Valid requests reach GHDL containers; invalid ones stop at the API."""
    good = http.post("/simulate", json=body(AND_GATE, "and_gate_tb", "100ns"))
    bad = [http.post("/simulate", json=UT02_CASES[c]) for c in ("empty_file", "not_vhdl_name")]
    save("IT-01", {"valid": {"http": good.status_code, "status": good.json()["status"],
                             "stages": [s["stage"] for s in good.json()["stages"]]},
                   "invalid": [{"http": b.status_code, "result": b.json()} for b in bad]})
    assert good.status_code == 200 and good.json()["status"] == "success"
    assert len(good.json()["stages"]) == 3
    for b in bad:
        assert b.status_code == 400 and b.json()["stages"] == []
    assert_cleaned_up(jobs_dir)


IT02_CASES = [
    ("valid", ["and_gate.vhd", "and_gate_tb.vhd"], "and_gate_tb", "success", "done", None),
    ("syntax_error", ["invalid_syntax.vhd"], "invalid_syntax", "failed", "analysis",
     "analysis_error"),
    ("elaboration_error", ["and_gate.vhd"], "no_such_tb", "failed", "elaboration",
     "elaboration_error"),
    ("assertion_failure", ["simulation_failure_tb.vhd"], "simulation_failure_tb", "failed",
     "simulation", "runtime_error"),
]


@needs_docker
@pytest.mark.parametrize("label, files, top, status, stage, error", IT02_CASES,
                         ids=[c[0] for c in IT02_CASES])
def test_IT02_runner_docker_result_builder(http, jobs_dir, label, files, top, status, stage,
                                           error):
    """Real GHDL output (exit code, messages, VCD) reaches the Result intact."""
    res = http.post("/simulate", json=body([vhdl(f) for f in files], top, "100ns")).json()
    save(f"IT-02_{label}", res)
    check_contract(res)
    assert (res["status"], res["stage"], res["error"]) == (status, stage, error), res["message"]
    if status == "failed":
        assert res["stages"][-1]["output"].strip()     # GHDL's own message is passed on
    assert_cleaned_up(jobs_dir)


@needs_docker
def test_IT02_vcd_download(http, jobs_dir):
    r = http.post("/simulate/vcd", json=body(AND_GATE, "and_gate_tb", "100ns"))
    out = EVIDENCE / "IT-02_and_gate_tb.vcd"
    EVIDENCE.mkdir(exist_ok=True)
    out.write_bytes(r.content)
    save("IT-02_vcd_download", {"http": r.status_code, "headers": dict(r.headers),
                                "saved_vcd": out.name})
    assert r.status_code == 200
    assert 'filename="and_gate_tb.vcd"' in r.headers["content-disposition"]
    assert b"$enddefinitions" in r.content


# ===================================================== 3.2.3 Validation tests

def _vars(vcd_text):
    return sorted({line.split()[4] for line in vcd_text.splitlines() if line.startswith("$var")})


@needs_docker
@pytest.mark.parametrize("files, top", [(["and_gate.vhd", "and_gate_tb.vhd"], "and_gate_tb"),
                                        (["valid_test.vhd", "valid_test_tb.vhd"], "valid_test_tb")],
                         ids=["and_gate", "valid_test"])
def test_VT01_end_to_end_valid_simulation(http, jobs_dir, files, top):
    """UC-A01: a valid design gives success and a usable VCD."""
    res = http.post("/simulate", json=body([vhdl(f) for f in files], top, "100ns")).json()
    reference = Path(__file__).resolve().parent.parent / "demo_output" / "and_gate_tb.vcd"
    data = {"status": res["status"], "stages": [(s["stage"], s["exit_code"]) for s in res["stages"]],
            "signals_in_vcd": _vars(res["vcd"] or "")}
    if top == "and_gate_tb" and reference.is_file():
        data["signals_in_reference"] = _vars(reference.read_text())
    save(f"VT-01_{top}", data)
    assert res["status"] == "success" and res["vcd"]
    assert all(code == 0 for _, code in data["stages"])
    if "signals_in_reference" in data:
        assert data["signals_in_vcd"] == data["signals_in_reference"]


@needs_docker
def test_VT02_p5a_reports_stage_and_line(http, jobs_dir):
    """UC-A02 / FR-P5-Joint-02 (P5A half): file name and line of a syntax error.
    The P5B half (same line from VHDL-LS) is VT-02 in the Group-5B repo."""
    res = http.post("/simulate", json=body([vhdl("invalid_syntax.vhd")], "invalid_syntax")).json()
    out = res["stages"][0]["output"]
    save("VT-02_p5a", {"stage": res["stage"], "error": res["error"], "ghdl_output": out})
    assert res["error"] == "analysis_error"
    assert "invalid_syntax.vhd:13:" in out or "invalid_syntax.vhd:14:" in out


# ===================================================== 3.2.4 High-order tests

@needs_docker
def test_HT01_performance(http, jobs_dir):
    """Response time is consistent and well inside the per-stage timeout."""
    http.post("/simulate", json=body(AND_GATE, "and_gate_tb", "100ns"))   # warm-up
    times = []
    for _ in range(10):
        t = time.perf_counter()
        r = http.post("/simulate", json=body(AND_GATE, "and_gate_tb", "100ns"))
        times.append(round(time.perf_counter() - t, 3))
        assert r.json()["status"] == "success"
    median = statistics.median(times)
    save("HT-01", {"runs_s": times, "median_s": median, "max_s": max(times),
                   "timeout_per_stage_s": config.JOB_TIMEOUT_S})
    assert max(times) < 3 * config.JOB_TIMEOUT_S
    assert max(times) <= 2 * median


@needs_docker
def test_HT02_concurrent_jobs(http, jobs_dir):
    """10 jobs at once: all correct, none mixed up, nothing left behind."""
    results = [None] * 10

    def one(i):
        files = AND_GATE if i % 2 == 0 else [vhdl("invalid_syntax.vhd")]
        top = "and_gate_tb" if i % 2 == 0 else "invalid_syntax"
        results[i] = http.post("/simulate", json=body(files, top, "100ns")).json()

    threads = [threading.Thread(target=one, args=(i,)) for i in range(10)]
    t = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    save("HT-02", {"wall_time_s": round(time.perf_counter() - t, 2),
                   "max_concurrent_jobs": config.MAX_CONCURRENT_JOBS,
                   "outcomes": [(r["status"], r["error"]) for r in results],
                   "job_ids_unique": len({r["job_id"] for r in results}) == 10})
    for i, r in enumerate(results):
        assert r["status"] == ("success" if i % 2 == 0 else "failed")
    assert len({r["job_id"] for r in results}) == 10
    assert_cleaned_up(jobs_dir)


def test_HT02_oversized_input_rejected(http, monkeypatch):
    no_docker_allowed(monkeypatch)
    too_many = [{"name": f"f{i}.vhd", "content": "entity x is end;"}
                for i in range(config.MAX_FILES + 1)]
    r1 = http.post("/simulate", json=UT02_CASES["oversized_file"])
    r2 = http.post("/simulate", json=body(too_many, "x"))
    save("HT-02_oversized", {"oversized_file": r1.json(), "too_many_files": r2.json()})
    assert r1.status_code == r2.status_code == 400


@needs_docker
def test_HT03_recovery_after_timeout(http, jobs_dir, monkeypatch):
    """SA-P5A-01: a runaway job is killed and the next job still works."""
    monkeypatch.setattr(config, "JOB_TIMEOUT_S", 3)
    runaway = http.post("/simulate", json=body([vhdl("runaway_tb.vhd")], "runaway_tb", "1sec")).json()
    after = http.post("/simulate", json=body(AND_GATE, "and_gate_tb", "100ns")).json()
    save("HT-03_timeout", {"runaway": {"error": runaway["error"], "message": runaway["message"]},
                           "next_job": after["status"], "leftover_containers": len(leftover_containers())})
    assert runaway["error"] == "timeout"
    assert after["status"] == "success"
    assert_cleaned_up(jobs_dir)


@needs_docker
def test_HT03_recovery_after_memory_kill(http, jobs_dir):
    hog = http.post("/simulate", json=body([vhdl("mem_hog_tb.vhd")], "mem_hog_tb", "1sec")).json()
    after = http.post("/simulate", json=body(AND_GATE, "and_gate_tb", "100ns")).json()
    save("HT-03_memory", {"mem_hog": {"error": hog["error"], "message": hog["message"]},
                          "next_job": after["status"]})
    assert hog["error"] == "memory_limit"
    assert after["status"] == "success"


ESCAPE_TB = """\
use std.textio.all;
entity escape_tb is end entity;
architecture sim of escape_tb is
begin
  process
    file f : text;
    variable st : file_open_status;
    variable l : line;
  begin
    file_open(st, f, "{path}", write_mode);
    if st = open_ok then
      write(l, string'("escaped"));
      writeline(f, l);
      report "WROTE_OUTSIDE_WORK" severity note;
    else
      report "BLOCKED" severity note;
    end if;
    wait;
  end process;
end architecture;
"""


@needs_docker
@pytest.mark.parametrize("path", ["/etc/escaped.txt", "/escaped.txt"])
def test_HT04_cannot_write_outside_job_folder(http, jobs_dir, path):
    """FR-P5A-04: the read-only root filesystem stops writes outside /work."""
    src = ESCAPE_TB.replace("{path}", path)
    res = http.post("/simulate", json=body([{"name": "escape_tb.vhd", "content": src}],
                                           "escape_tb", "10ns")).json()
    out = res["stages"][-1]["output"] if res["stages"] else ""
    save(f"HT-04_write_{path.strip('/').replace('/', '_')}", {"status": res["status"], "output": out})
    assert "WROTE_OUTSIDE_WORK" not in out
    assert "BLOCKED" in out or res["status"] == "failed"


@needs_docker
def test_HT04_no_network_and_not_root(jobs_dir):
    from test_limits import probe
    net = probe(jobs_dir, ["ls", "/sys/class/net"])
    uid = probe(jobs_dir, ["id", "-u"])
    save("HT-04_sandbox", {"network_interfaces": net["output"].split(), "uid": uid["output"].strip()})
    assert net["output"].split() == ["lo"]
    assert uid["output"].strip() != "0"


@needs_docker
def test_HT05_cross_platform_record(http, jobs_dir):
    """Run on each OS; compare the saved HT-05 evidence files between machines."""
    res = http.post("/simulate", json=body(AND_GATE, "and_gate_tb", "100ns")).json()
    save(f"HT-05_{platform.system()}", {"os": platform.platform(), "python": platform.python_version(),
                                        "status": res["status"],
                                        "stages": [(s["stage"], s["exit_code"]) for s in res["stages"]],
                                        "signals_in_vcd": _vars(res["vcd"] or "")})
    assert res["status"] == "success"
