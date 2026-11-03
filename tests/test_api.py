"""Tests for the HTTP API in app/main.py.

run_job is replaced with a fake, so these tests don't need Docker.
"""
import pytest
from fastapi.testclient import TestClient

from app import docker_runner, main

AND_GATE = {"name": "and_gate.vhd", "content": "entity and_gate is end;"}


def fake_result(**changes):
    result = {"job_id": "abc123", "status": "success", "stage": "done",
              "error": None, "message": "Simulation finished.",
              "stages": [], "vcd": b"$date today $end"}
    result.update(changes)
    return result


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(docker_runner, "cleanup_stale_jobs", lambda: (0, 0))
    with TestClient(main.app) as c:
        yield c


def use_fake_run_job(monkeypatch, result):
    calls = []

    def fake_run_job(files, top, stop_time=None):
        calls.append({"files": files, "top": top, "stop_time": stop_time})
        return result

    monkeypatch.setattr(docker_runner, "run_job", fake_run_job)
    return calls


def test_home(client):
    assert client.get("/").status_code == 200


def test_health_reports_docker(client, monkeypatch):
    monkeypatch.setattr(docker_runner, "docker_status",
                        lambda: {"docker": "ok", "image": "present"})
    body = client.get("/health").json()
    assert body == {"status": "ok", "docker": "ok", "image": "present"}


def test_success_returns_vcd_as_text(client, monkeypatch):
    calls = use_fake_run_job(monkeypatch, fake_result())
    r = client.post("/simulate", json={"files": [AND_GATE],
                                       "top": "and_gate_tb",
                                       "stop_time": "100ns"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["vcd"] == "$date today $end"
    assert calls[0]["top"] == "and_gate_tb"
    assert calls[0]["stop_time"] == "100ns"
    assert calls[0]["files"][0].name == "and_gate.vhd"


def test_vhdl_error_is_200_with_error(client, monkeypatch):
    use_fake_run_job(monkeypatch, fake_result(
        status="failed", stage="analysis", error="analysis_error",
        message="Analysis failed", vcd=None))
    r = client.post("/simulate", json={"files": [AND_GATE], "top": "and_gate"})
    assert r.status_code == 200
    assert r.json()["error"] == "analysis_error"
    assert r.json()["vcd"] is None


def test_validation_error_is_400(client, monkeypatch):
    use_fake_run_job(monkeypatch, fake_result(
        status="failed", stage="validation", error="validation_error",
        message="Invalid file name", vcd=None))
    r = client.post("/simulate", json={"files": [AND_GATE], "top": "x"})
    assert r.status_code == 400
    assert "Invalid file name" in r.json()["detail"]


def test_docker_problem_is_503(client, monkeypatch):
    use_fake_run_job(monkeypatch, fake_result(
        status="failed", stage="analysis", error="internal_error",
        message="Docker error", vcd=None))
    r = client.post("/simulate", json={"files": [AND_GATE], "top": "x"})
    assert r.status_code == 503


def test_missing_fields_rejected(client):
    assert client.post("/simulate", json={"top": "x"}).status_code == 422
    assert client.post("/simulate", json={"files": [], "top": "x"}).status_code == 422


def test_milestone2_single_file_form_still_works(client, monkeypatch):
    calls = use_fake_run_job(monkeypatch, fake_result())
    r = client.post("/simulate", json={"filename": "valid_test.vhd",
                                       "vhdl_source": "entity valid_test is end;",
                                       "top_entity": "valid_test"})
    assert r.status_code == 200
    assert calls[0]["top"] == "valid_test"
    assert calls[0]["files"][0].name == "valid_test.vhd"
    assert calls[0]["files"][0].content == "entity valid_test is end;"


def test_neither_form_rejected(client):
    r = client.post("/simulate", json={"filename": "a.vhd"})
    assert r.status_code == 422
