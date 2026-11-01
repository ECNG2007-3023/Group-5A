"""Milestone 1 check: launch the GHDL image as a container from Python.

Build the image first (run from the repo root):
    docker build -t p5a-ghdl ./docker

Then run this script (venv active, Docker Desktop open):
    python docker/launch_test.py

Check 1 runs `ghdl --version` in a throwaway container.
Check 2 mounts a temp folder, writes a tiny VHDL file into it and runs
`ghdl -a` on it, which proves files can be passed into a container.
"""
import sys
import tempfile
from pathlib import Path

import docker
from docker.errors import APIError, DockerException, ImageNotFound

IMAGE = "p5a-ghdl"

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


def run(client, command, volumes=None):
    """Run one command in a fresh container. Returns (exit_code, output)."""
    container = client.containers.run(
        IMAGE,
        command,
        detach=True,
        network_disabled=True,   # jobs never need the network
        mem_limit="256m",
        pids_limit=64,
        volumes=volumes,
    )
    try:
        exit_code = container.wait(timeout=30)["StatusCode"]
        output = container.logs(stdout=True, stderr=True).decode(errors="replace")
    finally:
        container.remove(force=True)
    return exit_code, output


def main():
    try:
        client = docker.from_env()
        client.ping()
    except DockerException:
        print("FAIL: cannot reach Docker. Is Docker Desktop open and running?")
        return 1

    try:
        client.images.get(IMAGE)
    except ImageNotFound:
        print(f"FAIL: image '{IMAGE}' not found. Build it first:\n"
              f"      docker build -t {IMAGE} ./docker")
        return 1

    ok = True

    # Check 1: container starts and GHDL is present.
    try:
        code, out = run(client, ["ghdl", "--version"])
    except (APIError, DockerException) as e:
        print(f"FAIL check 1 (ghdl --version): {e}")
        return 1
    first = out.splitlines()[0] if out.strip() else "(no output)"
    check1 = code == 0 and "GHDL" in out
    print(f"{'PASS' if check1 else 'FAIL'} check 1: ghdl --version -> {first}")
    ok &= check1

    # Check 2: a mounted folder is visible and writable inside the container.
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "and_gate.vhd").write_text(AND_GATE)
        try:
            code, out = run(
                client,
                ["ghdl", "-a", "and_gate.vhd"],
                volumes={tmp: {"bind": "/work", "mode": "rw"}},
            )
        except (APIError, DockerException) as e:
            print(f"FAIL check 2 (mounted analysis): {e}")
            return 1
        check2 = code == 0
        print(f"{'PASS' if check2 else 'FAIL'} check 2: ghdl -a on mounted file "
              f"-> exit code {code}")
        if not check2:
            print(out)
        ok &= check2

    print("\nAll checks passed." if ok else "\nSome checks failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
