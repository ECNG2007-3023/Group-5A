"""Milestone 4/5 check: verify the running API with real HTTP requests.

Sends the course-style scenarios (success, VHDL errors, runaway job, bad
requests) to POST /simulate and checks the status code, "status", "stage"
and "error" fields of every reply. Uses the VHDL files in tests/ghdl.

1. Build the GHDL image (once):      docker build -t p5a-ghdl ./docker
2. Start the API (repo root, venv):  uvicorn app.main:app
3. In a second terminal:             python docker/m4_api_check.py
   (another address:                 python docker/m4_api_check.py http://host:8000)

Prints one PASS/FAIL line per scenario and exits with code 1 if any failed.
"""
import sys
from pathlib import Path

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "ghdl"
RESULT_KEYS = {"job_id", "status", "stage", "error", "message", "stages", "vcd"}

RUNAWAY_TB = """\
entity runaway_tb is
end entity;
architecture sim of runaway_tb is
begin
  process
  begin
    loop
    end loop;  -- never waits, so simulation time never advances
  end process;
end architecture;
"""


def file(name):
    return {"name": name, "content": (FIXTURES / name).read_text(encoding="utf-8")}


# name, request body, expected HTTP code, expected status, stage, error,
# whether a VCD must come back
SCENARIOS = [
    ("success: AND gate + testbench",
     {"files": [file("and_gate.vhd"), file("and_gate_tb.vhd")],
      "top": "and_gate_tb", "stop_time": "100ns"},
     200, "success", "done", None, True),
    ("success: Milestone 2 one-file form",
     {"filename": "valid_test.vhd", "top_entity": "valid_test",
      "vhdl_source": (FIXTURES / "valid_test.vhd").read_text(encoding="utf-8")},
     200, "success", "done", None, False),
    ("analysis error: missing semicolon",
     {"files": [file("invalid_syntax.vhd")], "top": "invalid_syntax"},
     200, "failed", "analysis", "analysis_error", False),
    ("elaboration error: unknown top entity",
     {"files": [file("and_gate.vhd")], "top": "no_such_entity"},
     200, "failed", "elaboration", "elaboration_error", False),
    ("runtime error: failing assertion",
     {"files": [file("simulation_failure_tb.vhd")], "top": "simulation_failure_tb"},
     200, "failed", "simulation", "runtime_error", False),
    ("runaway job is killed",
     {"files": [{"name": "runaway_tb.vhd", "content": RUNAWAY_TB}],
      "top": "runaway_tb", "stop_time": "1ms"},
     200, "failed", "simulation", "timeout", False),
    ("M5: files sent testbench first",
     {"files": [file("and_gate_tb.vhd"), file("and_gate.vhd")],
      "top": "and_gate_tb", "stop_time": "100ns"},
     200, "success", "done", None, True),
    ("M5: memory hog is killed",
     {"files": [file("mem_hog_tb.vhd")], "top": "mem_hog_tb",
      "stop_time": "1sec"},
     200, "failed", "simulation", "memory_limit", False),
    ("service still works after the runaway",
     {"files": [file("and_gate.vhd"), file("and_gate_tb.vhd")],
      "top": "and_gate_tb"},
     200, "success", "done", None, True),
    ("bad request: file name with a folder",
     {"files": [{"name": "../evil.vhd", "content": "x"}], "top": "evil"},
     400, "failed", "validation", "validation_error", False),
    ("bad request: bad stop_time",
     {"files": [file("and_gate.vhd")], "top": "and_gate", "stop_time": "soon"},
     400, "failed", "validation", "validation_error", False),
    ("bad request: no files",
     {"files": [], "top": "and_gate"},
     400, "failed", "validation", "validation_error", False),
]


def check(name, body, code, status, stage, error, want_vcd):
    r = requests.post(f"{BASE}/simulate", json=body, timeout=120)
    got = r.json()
    problems = []
    if r.status_code != code:
        problems.append(f"HTTP {r.status_code}, expected {code}")
    if set(got) != RESULT_KEYS:
        problems.append(f"fields {sorted(got)}")
    for key, want in (("status", status), ("stage", stage), ("error", error)):
        if got.get(key) != want:
            problems.append(f"{key}={got.get(key)!r}, expected {want!r}")
    if want_vcd and not (got.get("vcd") or "").startswith("$"):
        problems.append("no VCD returned")
    if not want_vcd and status == "failed" and got.get("vcd") is not None:
        problems.append("VCD returned for a failed job")
    print(f"{'PASS' if not problems else 'FAIL'}  {name}"
          + ("" if not problems else "  <- " + "; ".join(problems)))
    return not problems


def check_vcd_download():
    body = {"files": [file("and_gate.vhd"), file("and_gate_tb.vhd")],
            "top": "and_gate_tb", "stop_time": "100ns"}
    r = requests.post(f"{BASE}/simulate/vcd", json=body, timeout=120)
    ok = (r.status_code == 200 and r.text.startswith("$")
          and "and_gate_tb.vcd" in r.headers.get("content-disposition", ""))
    if ok:
        out = Path("demo_output")
        out.mkdir(exist_ok=True)
        (out / "and_gate_tb.vcd").write_text(r.text, encoding="utf-8")
    print(f"{'PASS' if ok else 'FAIL'}  VCD download from /simulate/vcd"
          + ("  (saved demo_output/and_gate_tb.vcd, open it in Surfer)" if ok
             else f"  <- HTTP {r.status_code}"))
    return ok


def main():
    try:
        health = requests.get(f"{BASE}/health", timeout=10).json()
    except requests.RequestException as e:
        sys.exit(f"Cannot reach {BASE}: {e}\nIs `uvicorn app.main:app` running?")
    print(f"/health: {health}")
    if health.get("docker") != "ok" or health.get("image") != "present":
        sys.exit("Docker is not ready. Start Docker Desktop and build the image.")

    results = [check(*s) for s in SCENARIOS] + [check_vcd_download()]
    print(f"\n{sum(results)}/{len(results)} scenarios passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
