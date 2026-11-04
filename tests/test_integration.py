"""Milestone 5: end-to-end tests of the whole service.

HTTP request -> FastAPI -> docker_runner -> real GHDL containers -> reply,
driven through clients/p5a_client.py, the same client P5B/P6B can use.
Every reply is checked against contract v1 (docs/hdl-service-contract-v1.md).

The real-Docker tests are skipped when Docker or the image is missing; the
contract and client tests at the bottom always run.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from app import docker_runner, main
from app.models import SimulationResult
from clients.p5a_client import P5AClient, P5AUnavailable
from conftest import assert_cleaned_up, needs_docker, vhdl

RESULT_KEYS = {"job_id", "status", "stage", "error", "message", "stages", "vcd"}
STAGE_KEYS = {"stage", "command", "exit_code", "output", "duration_s",
              "timed_out", "oom_killed"}


def check_contract(result):
    """Fail if a reply does not have exactly the contract v1 Result shape."""
    assert set(result) == RESULT_KEYS
    SimulationResult.model_validate(result)
    assert result["status"] in ("success", "failed")
    assert result["stage"] in ("validation", "analysis", "elaboration",
                               "simulation", "service", "done")
    for s in result["stages"]:
        assert set(s) == STAGE_KEYS
    if result["status"] == "success":
        assert result["error"] is None and result["stage"] == "done"
    else:
        assert result["error"] and result["vcd"] is None


@pytest.fixture
def http(jobs_dir):
    """The real app, in-process, with a private jobs folder."""
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def p5a(http):
    return P5AClient(http=http)


# ----------------------------------------------- end to end (real Docker)

SCENARIOS = [
    # id, files, top, stop_time, status, stage, error
    ("and_gate", ["and_gate.vhd", "and_gate_tb.vhd"], "and_gate_tb", "100ns",
     "success", "done", None),
    ("testbench_sent_first", ["and_gate_tb.vhd", "and_gate.vhd"],
     "and_gate_tb", "100ns", "success", "done", None),
    ("single_file", ["valid_test.vhd"], "valid_test", None,
     "success", "done", None),
    ("syntax_error", ["invalid_syntax.vhd"], "invalid_syntax", None,
     "failed", "analysis", "analysis_error"),
    ("unknown_top", ["and_gate.vhd"], "no_such_entity", None,
     "failed", "elaboration", "elaboration_error"),
    ("failing_assertion", ["simulation_failure_tb.vhd"],
     "simulation_failure_tb", "100ns", "failed", "simulation", "runtime_error"),
    ("memory_hog", ["mem_hog_tb.vhd"], "mem_hog_tb", "1sec",
     "failed", "simulation", "memory_limit"),
]


@needs_docker
@pytest.mark.parametrize("files, top, stop, status, stage, error",
                         [s[1:] for s in SCENARIOS], ids=[s[0] for s in SCENARIOS])
def test_simulate_end_to_end(p5a, jobs_dir, files, top, stop, status, stage,
                             error):
    result = p5a.simulate([vhdl(f) for f in files], top, stop)
    check_contract(result)
    assert (result["status"], result["stage"], result["error"]) == \
           (status, stage, error), result["message"]
    assert_cleaned_up(jobs_dir)


@needs_docker
def test_success_vcd_is_a_real_waveform(p5a):
    result = p5a.simulate([vhdl("and_gate.vhd"), vhdl("and_gate_tb.vhd")],
                          "and_gate_tb", "100ns")
    vcd = result["vcd"]
    for marker in ("$timescale", "$var", "$enddefinitions"):
        assert marker in vcd
    assert " a " in vcd and " b " in vcd     # testbench signals are recorded


@needs_docker
def test_vhdl_errors_point_to_file_and_line(p5a):
    result = p5a.simulate([vhdl("invalid_syntax.vhd")], "invalid_syntax")
    assert "invalid_syntax.vhd:" in result["stages"][0]["output"]


@needs_docker
def test_runaway_job_times_out(p5a, monkeypatch, jobs_dir):
    monkeypatch.setattr(main.docker_runner.config, "JOB_TIMEOUT_S", 3)
    result = p5a.simulate([vhdl("runaway_tb.vhd")], "runaway_tb", "1sec")
    check_contract(result)
    assert result["error"] == "timeout"
    assert_cleaned_up(jobs_dir)


@needs_docker
def test_vcd_download_end_to_end(p5a):
    dl = p5a.simulate_vcd([vhdl("and_gate.vhd"), vhdl("and_gate_tb.vhd")],
                          "and_gate_tb", "100ns")
    assert dl.result is None and dl.job_id
    assert dl.vcd.startswith(b"$date") or b"$timescale" in dl.vcd


@needs_docker
def test_vcd_download_failure_is_result(p5a):
    dl = p5a.simulate_vcd([vhdl("invalid_syntax.vhd")], "invalid_syntax")
    assert dl.vcd is None
    check_contract(dl.result)
    assert dl.result["error"] == "analysis_error"


@needs_docker
def test_health_end_to_end(p5a):
    assert p5a.health() == {"status": "ok", "docker": "ok", "image": "present"}
    assert p5a.is_ready()


# --------------------------------------- contract and client (no Docker)

def test_bad_requests_get_400_in_result_shape(http):
    bodies = [
        {"files": [{"name": "../x.vhd", "content": "x"}], "top": "x"},
        {"files": [{"name": "a.vhd", "content": "x"}], "top": "1bad"},
        {"files": [{"name": "a.vhd", "content": "x"}], "top": "a",
         "stop_time": "forever"},
        {"files": [], "top": "a"},
        {"top": "a"},
    ]
    for body in bodies:
        r = http.post("/simulate", json=body)
        assert r.status_code == 400, body
        check_contract(r.json())
        assert r.json()["error"] == "validation_error"


def test_docker_down_is_503(http, monkeypatch):
    def down(*_a, **_k):
        raise docker_runner.DockerException("connection refused")
    monkeypatch.setattr(docker_runner, "get_client", down)
    r = http.post("/simulate", json={"files": [vhdl("and_gate.vhd")],
                                     "top": "and_gate"})
    assert r.status_code == 503
    check_contract(r.json())
    assert r.json()["error"] == "internal_error"


def test_browser_front_end_allowed_by_cors(http):
    r = http.options("/simulate", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] in ("*", "http://localhost:5173")
    r = http.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "x-job-id" in r.headers.get("access-control-expose-headers", "").lower()


def test_openapi_lists_contract_endpoints(http):
    spec = http.get("/openapi.json").json()
    assert {"/health", "/simulate", "/simulate/vcd"} <= set(spec["paths"])
    props = spec["components"]["schemas"]["SimulationResult"]["properties"]
    assert set(props) == RESULT_KEYS


def test_client_reports_unreachable_service():
    p5a = P5AClient("http://127.0.0.1:9", timeout=2)   # nothing listens there
    with pytest.raises(P5AUnavailable):
        p5a.health()
    assert p5a.is_ready() is False


def test_client_accepts_dict_of_files(http, monkeypatch):
    seen = {}

    def fake_run_job(files, top, stop_time=None):
        seen["names"] = [f.name for f in files]
        return {"job_id": "j", "status": "success", "stage": "done",
                "error": None, "message": "ok", "stages": [], "vcd": b"$end"}
    monkeypatch.setattr(docker_runner, "run_job", fake_run_job)
    result = P5AClient(http=http).simulate({"a.vhd": "entity a is end;"}, "a")
    assert seen["names"] == ["a.vhd"] and result["vcd"] == "$end"


def test_client_uses_real_http():
    """The client really speaks HTTP (checked against a mock transport)."""
    def handler(request):
        assert request.url.path == "/simulate"
        assert request.read().startswith(b'{"files"')
        return httpx.Response(200, json={"job_id": "j", "status": "success",
                                         "stage": "done", "error": None,
                                         "message": "", "stages": [],
                                         "vcd": "$end"})
    http = httpx.Client(base_url="http://p5a", transport=httpx.MockTransport(handler))
    assert P5AClient(http=http).simulate([{"name": "a.vhd", "content": "x"}],
                                         "a")["status"] == "success"


def test_published_openapi_file_is_up_to_date():
    """docs/openapi.json (given to P5B/P6B) must match the running API.
    If this fails, run:  python docker/export_openapi.py"""
    import json
    from pathlib import Path
    published = json.loads((Path(__file__).resolve().parent.parent
                            / "docs" / "openapi.json").read_text())
    live = main.app.openapi()
    assert published["paths"].keys() == live["paths"].keys()
    assert published["components"]["schemas"] == live["components"]["schemas"]
