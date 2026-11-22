"""White-box tests added after reviewing the coverage report (coverage.py,
statement + branch). The lines no test reached were all the same kind: what
the runner does when DOCKER ITSELF misbehaves part-way through a job. Each
test below makes one Docker call fail and checks the service still gives a
proper result and cleans up. No real Docker needed.
"""
import os
import stat

import pytest
import requests
from docker.errors import DockerException, ImageNotFound, NotFound

from app import config, docker_runner as dr
from conftest import vhdl

GOOD = [vhdl("and_gate.vhd"), vhdl("and_gate_tb.vhd")]


class BrokenContainer:
    """A container whose calls can be made to fail one at a time."""

    def __init__(self, broken, hang=False):
        self.broken = set(broken)
        self.hang = hang
        self.killed = False
        self.removed = False
        self.attrs = {"State": {"OOMKilled": False}}

    def _maybe_fail(self, call, exc=DockerException):
        if call in self.broken:
            raise exc(f"{call} failed")

    def wait(self, timeout=None):
        if self.hang and not self.killed:
            raise requests.exceptions.ReadTimeout()
        self._maybe_fail("wait_after_kill", RuntimeError)
        return {"StatusCode": 0}

    def kill(self):
        self.killed = True
        self._maybe_fail("kill", NotFound)

    def reload(self):
        self._maybe_fail("reload")

    def logs(self, stdout=True, stderr=True):
        self._maybe_fail("logs")
        return b"output"

    def remove(self, force=False):
        self.removed = True
        self._maybe_fail("remove", NotFound)


class BrokenClient:
    def __init__(self, broken=(), hang=False, run_error=None):
        self.containers = self
        self.started = []
        self.broken, self.hang, self.run_error = broken, hang, run_error

    def run(self, image, command, **kwargs):
        if self.run_error:
            raise self.run_error
        c = BrokenContainer(self.broken, self.hang)
        self.started.append(c)
        return c


@pytest.mark.parametrize("broken", [["reload"], ["logs"], ["remove"]],
                         ids=["reload_fails", "logs_fail", "remove_fails"])
def test_a_failing_docker_call_still_gives_a_result(jobs_dir, broken):
    r = dr.run_job(GOOD, "and_gate_tb", client=BrokenClient(broken))
    assert r["status"] == "success"            # the job itself was fine
    assert list(jobs_dir.iterdir()) == []


def test_timeout_when_kill_and_wait_also_fail(jobs_dir):
    """The hung container cannot be killed (already gone) and waiting for it
    fails too: still reported as a timeout, never a crash."""
    client = BrokenClient(["kill", "wait_after_kill"], hang=True)
    r = dr.run_job(GOOD, "and_gate_tb", client=client, timeout_s=1)
    assert r["error"] == "timeout" and r["stages"][0]["exit_code"] is None
    assert all(c.removed for c in client.started)


@pytest.mark.parametrize("error, text", [
    (ImageNotFound("no image"), "not found. Build it with"),
    (DockerException("daemon gone"), "Is Docker running?"),
], ids=["image_missing", "docker_stopped"])
def test_docker_problem_mid_job_is_internal_error(jobs_dir, error, text):
    r = dr.run_job(GOOD, "and_gate_tb", client=BrokenClient(run_error=error))
    assert r["error"] == "internal_error" and text in r["message"]
    assert list(jobs_dir.iterdir()) == []


def test_success_without_a_vcd_file(jobs_dir):
    """GHDL ran but wrote no wave.vcd (e.g. an empty testbench)."""
    r = dr.run_job(GOOD, "and_gate_tb", client=BrokenClient())
    assert r["status"] == "success" and r["vcd"] is None
    assert "no VCD was produced" in r["message"]


# ----------------------------------------------------- /health: docker_status

class StatusClient:
    def __init__(self, ping_error=None, image_error=None):
        self.ping_error, self.image_error = ping_error, image_error
        self.images = self

    def ping(self):
        if self.ping_error:
            raise self.ping_error

    def get(self, name):
        if self.image_error:
            raise self.image_error


@pytest.mark.parametrize("client, expected", [
    (StatusClient(), {"docker": "ok", "image": "present"}),
    (StatusClient(image_error=ImageNotFound("x")), {"docker": "ok", "image": "missing"}),
], ids=["all_ok", "image_missing"])
def test_docker_status(client, expected):
    assert dr.docker_status(client) == expected


def test_docker_status_unreachable():
    status = dr.docker_status(StatusClient(ping_error=DockerException("refused")))
    assert status["docker"] == "unreachable" and "refused" in status["detail"]


# ----------------------------------------------------- clean-up edge cases

def test_remove_dir_retries_after_making_writable(tmp_path, monkeypatch):
    """The onerror handler: the first delete fails, it makes the file
    writable and tries again."""
    calls = []
    real_unlink = os.unlink

    def flaky_unlink(path, *a, **k):
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError("read-only")
        return real_unlink(path, *a, **k)
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "a.txt").write_text("x")
    monkeypatch.setattr(os, "unlink", flaky_unlink)
    dr._remove_dir(folder)
    assert not folder.exists() and len(calls) >= 2


class ListClient:
    def __init__(self, list_error=None, remove_error=None):
        self.containers = self
        self.list_error, self.remove_error = list_error, remove_error

    def list(self, all=False, filters=None):
        if self.list_error:
            raise self.list_error
        outer = self

        class C:
            def remove(self, force=False):
                if outer.remove_error:
                    raise outer.remove_error
        return [C()]


@pytest.mark.parametrize("client, removed", [
    (ListClient(list_error=DockerException("down")), 0),
    (ListClient(remove_error=DockerException("busy")), 0),
    (ListClient(), 1),
], ids=["docker_down", "container_busy", "removed"])
def test_cleanup_stale_jobs_survives_docker_errors(jobs_dir, client, removed):
    containers, folders = dr.cleanup_stale_jobs(client)
    assert (containers, folders) == (removed, 0)


def test_cleanup_stale_jobs_removes_only_old_folders(jobs_dir):
    jobs_dir.mkdir()
    old, new = jobs_dir / "old", jobs_dir / "new"
    old.mkdir()
    new.mkdir()
    os.utime(old, (0, 0))                                # 1970: very old
    _, folders = dr.cleanup_stale_jobs(ListClient(), max_age_s=3600)
    assert folders == 1 and not old.exists() and new.exists()
