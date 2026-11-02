"""P5A system-test client: sends each fixture to the service and checks the answer.

Usage: python test_client.py [base_url]   (default http://localhost:8000)
Runs without P5B or Project 6 (P5-StR3.1).
"""
import sys
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
FX = Path(__file__).parent / "fixtures"

CASES = [
    # id, files, top, expected status, expected failed_stage, expected category
    ("SYS-A-01 valid design", ["and_gate.vhd", "and_gate_tb.vhd"], "and_gate_tb", "success", None, None),
    ("SYS-A-02 syntax error", ["bad_semicolon.vhd", "and_gate_tb.vhd"], "and_gate_tb", "fail", "analysis", "analysis_error"),
    ("SYS-A-03 unknown top", ["and_gate.vhd", "and_gate_tb.vhd"], "no_such_tb", "fail", "elaboration", "elaboration_error"),
    ("SYS-A-04 failing assertion", ["and_gate.vhd", "assert_fail_tb.vhd"], "assert_fail_tb", "fail", "simulation", "simulation_error"),
    ("SYS-A-05 runaway job", ["runaway_tb.vhd"], "runaway_tb", "fail", "simulation", "service_runtime_error"),
    ("SYS-A-06 valid after runaway", ["and_gate.vhd", "and_gate_tb.vhd"], "and_gate_tb", "success", None, None),
]


def submit(files, top):
    parts = [("files", (f, (FX / f).read_bytes(), "text/plain")) for f in files]
    return httpx.post(f"{BASE}/jobs", data={"top": top}, files=parts, timeout=60)


def main():
    passed = 0
    for name, files, top, status, stage, cat in CASES:
        r = submit(files, top).json()
        ok = (r["status"], r["failed_stage"], r["category"]) == (status, stage, cat)
        if ok and status == "success":
            w = httpx.get(f"{BASE}/jobs/{r['job_id']}/waveform", timeout=30)
            ok = w.status_code == 200 and len(w.content) > 0
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}  -> {r['status']}, {r['failed_stage']}, {r['category']}")
    # SYS-A-07: invalid request (empty file) is rejected with no job created.
    r = httpx.post(f"{BASE}/jobs", data={"top": "x_tb"},
                   files=[("files", ("empty.vhd", b"", "text/plain"))], timeout=30)
    ok = r.status_code == 400 and r.json()["job_id"] is None
    passed += ok
    print(f"{'PASS' if ok else 'FAIL'}  SYS-A-07 invalid request  -> HTTP {r.status_code}")
    total = len(CASES) + 1
    print(f"\n{passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
