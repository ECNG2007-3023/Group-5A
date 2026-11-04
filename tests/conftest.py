# Lets "from app import ..." work when pytest is run from the repo root.
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "ghdl"


def vhdl(name):
    """One request file built from tests/ghdl/<name>."""
    return {"name": name, "content": (FIXTURES / name).read_text(encoding="utf-8")}


def _real_client():
    """A Docker client if Docker is running and the GHDL image is built."""
    try:
        import docker
        client = docker.from_env()
        client.ping()
        client.images.get(config.GHDL_IMAGE)
        return client
    except Exception:
        return None


REAL_DOCKER = _real_client()

# Tests marked with this are SKIPPED (not failed) when Docker is not running
# or the image is not built.
needs_docker = pytest.mark.skipif(
    REAL_DOCKER is None,
    reason=f"Docker not running or image '{config.GHDL_IMAGE}' not built")


def leftover_containers():
    return REAL_DOCKER.containers.list(
        all=True, filters={"label": config.CONTAINER_LABEL})


@pytest.fixture
def jobs_dir(tmp_path, monkeypatch):
    """A private jobs folder for one test, so cleanup can be checked."""
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(config, "JOBS_DIR", jobs)
    return jobs


def assert_cleaned_up(jobs_dir):
    """No job folder and no job container may be left behind."""
    assert not jobs_dir.exists() or list(jobs_dir.iterdir()) == []
    assert leftover_containers() == []
