"""Black-box tests, designed with the techniques from the ECNG 2007 lecture
"White Box and Black Box Testing": equivalence partitioning (EP), boundary
value analysis (BVA), decision tables, state transitions and error guessing.

Only the service's inputs and outputs are used (HTTP requests and replies, or
run_job()'s result), never its internals. Test IDs (TC-A-xx) match the test
case tables in docs/test-plan.md.

Rejected inputs never reach Docker, so those run anywhere. Accepted inputs
start real GHDL containers and are skipped without Docker.
"""
import pytest
from fastapi.testclient import TestClient

from app import config, docker_runner, main
from conftest import needs_docker, vhdl
from test_docker_runner import OK, FakeClient

LIMIT_FILES = config.MAX_FILES            # 20
LIMIT_BYTES = config.MAX_FILE_BYTES       # 200,000
GOOD = [vhdl("and_gate.vhd"), vhdl("and_gate_tb.vhd")]


def entity(name):
    return f"entity {name} is\nend entity;\narchitecture a of {name} is\nbegin\nend architecture;\n"


def padded(name, size):
    """A valid VHDL file of exactly `size` bytes (padded with a comment)."""
    body = entity(name)
    pad = size - len(body.encode()) - 3                 # "--" + "\n"
    assert pad >= 0
    return "--" + "x" * pad + "\n" + body


@pytest.fixture
def http(jobs_dir, monkeypatch):
    monkeypatch.setattr(docker_runner, "cleanup_stale_jobs", lambda *a, **k: (0, 0))
    with TestClient(main.app) as c:
        yield c


def post(http, files, top, stop_time=None, path="/simulate"):
    body = {"files": files, "top": top}
    if stop_time is not None:
        body["stop_time"] = stop_time
    return http.post(path, json=body)


def rejected(r):
    return r.status_code == 400 and r.json()["error"] == "validation_error"


def accepted(r):
    """The request passed validation: a job ran (whatever GHDL then said)."""
    return r.status_code == 200 and r.json()["error"] != "validation_error"


# =========================================================================
# Equivalence partitioning + boundary value analysis
# =========================================================================

# ---- Number of files. Partitions: 0 (invalid) | 1..20 (valid) | >20 (invalid)
#      Boundaries tested just below, on and just above: 0 1 2 | 19 20 21

def files_n(n):
    return [{"name": f"e{i}.vhd", "content": entity(f"e{i}")} for i in range(n)]


@pytest.mark.parametrize("n", [0, LIMIT_FILES + 1, 50],
                         ids=["TC-A-01_0_files", "TC-A-02_21_files", "TC-A-03_50_files"])
def test_ep_bva_file_count_rejected(http, n):
    assert rejected(post(http, files_n(n), "e0"))


@needs_docker
@pytest.mark.parametrize("n", [1, 2, LIMIT_FILES - 1, LIMIT_FILES],
                         ids=["TC-A-04_1_file", "TC-A-05_2_files", "TC-A-06_19_files",
                              "TC-A-07_20_files"])
def test_ep_bva_file_count_accepted(http, n):
    r = post(http, files_n(n), "e0")
    assert accepted(r) and r.json()["status"] == "success", r.json()["message"]


# ---- File size. Partitions: empty/blank (invalid) | 1..200,000 bytes (valid)
#      | >200,000 bytes (invalid). Boundaries: 199,999  200,000  200,001

@pytest.mark.parametrize("content", ["", "   \n\t "], ids=["TC-A-08_empty", "TC-A-09_blank"])
def test_ep_empty_file_rejected(http, content):
    assert rejected(post(http, [{"name": "e.vhd", "content": content}], "e"))


def test_bva_file_one_byte_over_limit_rejected(http):
    """TC-A-10: 200,001 bytes."""
    big = padded("e", LIMIT_BYTES + 1)
    assert len(big.encode()) == LIMIT_BYTES + 1
    assert rejected(post(http, [{"name": "e.vhd", "content": big}], "e"))


@needs_docker
@pytest.mark.parametrize("size", [LIMIT_BYTES - 1, LIMIT_BYTES],
                         ids=["TC-A-11_199999_bytes", "TC-A-12_200000_bytes"])
def test_bva_file_size_on_and_below_limit_accepted(http, size):
    content = padded("e", size)
    assert len(content.encode()) == size
    r = post(http, [{"name": "e.vhd", "content": content}], "e")
    assert accepted(r) and r.json()["status"] == "success", r.json()["message"]


def test_bva_size_counts_bytes_not_characters(http):
    """TC-A-13: 'é' is 2 bytes in UTF-8, so 100,001 of them are over the limit."""
    content = "-- " + "é" * 100_001 + "\n" + entity("e")
    assert len(content) < LIMIT_BYTES < len(content.encode())
    assert rejected(post(http, [{"name": "e.vhd", "content": content}], "e"))


# ---- File name. Partitions: valid (.vhd/.vhdl, safe characters, <=100 + ext)
#      | wrong extension | unsafe characters/folders | too long.
#      Boundary on length: 100 characters in total (ok) vs 101.

@pytest.mark.parametrize("name", [
    "a" * 97 + ".vhd",          # TC-A-14: 101 characters, 1 over the limit
    "design.v",                 # TC-A-15: wrong extension (Verilog)
    "design.vhd.txt",           # TC-A-16: extension not last
    "../design.vhd",            # TC-A-17: path traversal
    "sub/design.vhd",           # TC-A-18: folder
    "my design.vhd",            # TC-A-19: space
    ".vhd",                     # TC-A-20: no name at all
], ids=["TC-A-14", "TC-A-15", "TC-A-16", "TC-A-17", "TC-A-18", "TC-A-19", "TC-A-20"])
def test_ep_bva_bad_file_names_rejected(http, name):
    assert rejected(post(http, [{"name": name, "content": entity("e")}], "e"))


@needs_docker
@pytest.mark.parametrize("name", ["a" * 96 + ".vhd", "E.VHDL", "x_1-2.v.vhd"],
                         ids=["TC-A-21_length_100", "TC-A-22_upper_case", "TC-A-23_dots_dash"])
def test_ep_bva_good_file_names_accepted(http, name):
    assert accepted(post(http, [{"name": name, "content": entity("e")}], "e"))


# ---- Top (testbench) name. Partitions: VHDL identifier of 1..100 characters
#      (valid) | starts with a digit/underscore | other characters | too long.

@pytest.mark.parametrize("top", ["1abc", "_abc", "a-b", "a b", "a" * 101, ""],
                         ids=["TC-A-24_digit_first", "TC-A-25_underscore_first",
                              "TC-A-26_dash", "TC-A-27_space", "TC-A-28_101_chars",
                              "TC-A-29_empty"])
def test_ep_bva_bad_top_rejected(http, top):
    assert rejected(post(http, [{"name": "e.vhd", "content": entity("e")}], top))


@needs_docker
@pytest.mark.parametrize("top", ["e", "a" * 100], ids=["TC-A-30_1_char", "TC-A-31_100_chars"])
def test_ep_bva_good_top_accepted(http, top):
    r = post(http, [{"name": "t.vhd", "content": entity(top)}], top)
    assert accepted(r) and r.json()["status"] == "success", r.json()["message"]


# ---- stop_time. Partitions: number + unit fs/ps/ns/us/ms/sec (valid)
#      | no unit | unknown unit | negative | not a number. Boundary: 0.

@pytest.mark.parametrize("stop", ["100", "100 s", "100 min", "-5ns", "abc", "1e3ns", "ns"],
                         ids=["TC-A-32_no_unit", "TC-A-33_unit_s", "TC-A-34_unit_min",
                              "TC-A-35_negative", "TC-A-36_text", "TC-A-37_exponent",
                              "TC-A-38_unit_only"])
def test_ep_bad_stop_time_rejected(http, stop):
    assert rejected(post(http, GOOD, "and_gate_tb", stop))


@needs_docker
@pytest.mark.parametrize("stop", ["0ns", "1fs", "100ps", "100ns", "2 us", "1.5ns", "1ms", "1sec"],
                         ids=["TC-A-39_zero", "TC-A-40_fs", "TC-A-41_ps", "TC-A-42_ns",
                              "TC-A-43_us_space", "TC-A-44_decimal", "TC-A-45_ms",
                              "TC-A-46_sec"])
def test_ep_bva_good_stop_time_accepted(http, stop):
    """TC-A-44 FAILED before the fix: 1.5ns passed validation, then GHDL said
    "bad unit for '1.5ns'". The service now sends 1500ps."""
    r = post(http, GOOD, "and_gate_tb", stop)
    assert accepted(r) and r.json()["status"] == "success", r.json()["message"]


@pytest.mark.parametrize("given, sent", [("1.5ns", "1500ps"), ("0.25us", "250ns"),
                                         ("2.0ms", "2ms"), ("100 ns", "100ns")],
                         ids=["TC-A-44b", "TC-A-44c", "TC-A-44d", "TC-A-44e"])
def test_ep_decimal_stop_time_is_sent_as_whole_number(jobs_dir, given, sent):
    client = FakeClient([OK, OK, OK])
    docker_runner.run_job(GOOD, "and_gate_tb", given, client=client)
    assert client.started[-1].command[-1] == f"--stop-time={sent}"


def test_bva_stop_time_finer_than_1fs_rejected(http):
    """TC-A-44f: 0.5fs cannot be made whole: there is no unit below fs."""
    assert rejected(post(http, GOOD, "and_gate_tb", "0.5fs"))


# =========================================================================
# Decision tables
# =========================================================================

# ---- How a stage's outcome is classified (contract v1, "Error codes").
#   Conditions: timed out? | killed for memory? | exit code 0?
#   A timeout wins over memory, and memory over the exit code.
#
#   Rule | timed out | OOM | exit 0 | Action (error)
#   R1   |    Y      |  Y  |   Y    | timeout
#   R2   |    Y      |  Y  |   N    | timeout
#   R3   |    Y      |  N  |   Y    | timeout
#   R4   |    Y      |  N  |   N    | timeout
#   R5   |    N      |  Y  |   Y    | memory_limit
#   R6   |    N      |  Y  |   N    | memory_limit
#   R7   |    N      |  N  |   N    | analysis_error
#   R8   |    N      |  N  |   Y    | continue (job succeeds)

DECISION_TABLE = [
    ("R1", True, True, 0, "timeout"),
    ("R2", True, True, 1, "timeout"),
    ("R3", True, False, 0, "timeout"),
    ("R4", True, False, 1, "timeout"),
    ("R5", False, True, 0, "memory_limit"),
    ("R6", False, True, 1, "memory_limit"),
    ("R7", False, False, 1, "analysis_error"),
    ("R8", False, False, 0, None),
]


@pytest.mark.parametrize("rule, timed_out, oom, exit_code, expected", DECISION_TABLE,
                         ids=[f"TC-A-47_{r[0]}" for r in DECISION_TABLE])
def test_decision_table_stage_outcome(jobs_dir, rule, timed_out, oom, exit_code, expected):
    first = (exit_code, "output", timed_out, oom)
    r = docker_runner.run_job(GOOD, "and_gate_tb", client=FakeClient([first, OK, OK]))
    assert r["error"] == expected, rule
    assert (r["status"] == "success") == (expected is None)


# ---- Which HTTP reply each endpoint gives (contract v1, "Endpoints").
#   Conditions: request valid? | Docker available? | VHDL correct?
#
#   Rule | valid | Docker | VHDL ok | /simulate         | /simulate/vcd
#   R1   |   N   |   -    |    -    | 400 validation    | 400 validation
#   R2   |   Y   |   N    |    -    | 503 internal      | 503 internal
#   R3   |   Y   |   Y    |    N    | 200 failed        | 422 JSON result
#   R4   |   Y   |   Y    |    Y    | 200 success + VCD | 200 .vcd file

def docker_down(monkeypatch):
    def down(*_a, **_k):
        raise docker_runner.DockerException("connection refused")
    monkeypatch.setattr(docker_runner, "get_client", down)


@pytest.mark.parametrize("path", ["/simulate", "/simulate/vcd"])
def test_decision_table_r1_invalid_request(http, monkeypatch, path):
    """TC-A-48 R1: invalid is rejected before Docker matters (Docker down too)."""
    docker_down(monkeypatch)
    r = post(http, [{"name": "../x.vhd", "content": "x"}], "x", path=path)
    assert r.status_code == 400 and r.json()["error"] == "validation_error"


@pytest.mark.parametrize("path", ["/simulate", "/simulate/vcd"])
def test_decision_table_r2_docker_down(http, monkeypatch, path):
    """TC-A-49 R2."""
    docker_down(monkeypatch)
    r = post(http, GOOD, "and_gate_tb", path=path)
    assert r.status_code == 503 and r.json()["error"] == "internal_error"


@needs_docker
def test_decision_table_r3_vhdl_error(http):
    """TC-A-50 R3."""
    bad = [vhdl("invalid_syntax.vhd")]
    r = post(http, bad, "invalid_syntax")
    assert r.status_code == 200 and r.json()["status"] == "failed"
    r = post(http, bad, "invalid_syntax", path="/simulate/vcd")
    assert r.status_code == 422 and r.json()["error"] == "analysis_error"


@needs_docker
def test_decision_table_r4_success(http):
    """TC-A-51 R4."""
    r = post(http, GOOD, "and_gate_tb", "100ns")
    assert r.status_code == 200 and r.json()["status"] == "success" and r.json()["vcd"]
    r = post(http, GOOD, "and_gate_tb", "100ns", path="/simulate/vcd")
    assert r.status_code == 200 and b"$enddefinitions" in r.content


# =========================================================================
# State transitions: a job moves validation -> analysis -> elaboration ->
# simulation -> done, and leaves at the first state that fails.
#
#   From         | event          | to
#   validation   | request OK     | analysis      | request bad -> stop (validation)
#   analysis     | stage OK       | elaboration   | stage fails -> stop (analysis)
#   elaboration  | stage OK       | simulation    | stage fails -> stop (elaboration)
#   simulation   | stage OK       | done          | stage fails -> stop (simulation)
# =========================================================================

FAIL = (1, "error", False, False)


@pytest.mark.parametrize("outcomes, final_stage, stages_run", [
    ([OK, OK, OK], "done", 3),
    ([FAIL], "analysis", 1),
    ([OK, FAIL], "elaboration", 2),
    ([OK, OK, FAIL], "simulation", 3),
], ids=["TC-A-52_all_ok", "TC-A-53_stop_analysis", "TC-A-54_stop_elaboration",
        "TC-A-55_stop_simulation"])
def test_state_transitions_of_a_job(jobs_dir, outcomes, final_stage, stages_run):
    client = FakeClient(outcomes)
    r = docker_runner.run_job(GOOD, "and_gate_tb", client=client)
    assert r["stage"] == final_stage
    assert len(r["stages"]) == stages_run == len(client.started)   # never goes further


def test_state_transition_bad_request_never_leaves_validation(jobs_dir):
    """TC-A-56: the job stays in 'validation' and no container starts."""
    client = FakeClient([])
    r = docker_runner.run_job([{"name": "x.v", "content": "x"}], "x", client=client)
    assert r["stage"] == "validation" and client.started == []


# =========================================================================
# Error guessing: inputs a careless client (or a Windows user) might send.
# =========================================================================

@pytest.mark.parametrize("body", [
    {},                                                         # TC-A-57 empty body
    [],                                                         # TC-A-58 JSON array
    {"files": "and_gate.vhd", "top": "x"},                      # TC-A-59 files as text
    {"files": [{"name": "a.vhd", "content": 42}], "top": "a"},  # TC-A-60 content a number
    {"files": [{"name": "a.vhd", "content": "x"}], "top": None},  # TC-A-61 top null
    {"files": [{"name": "a.vhd"}], "top": "a"},                 # TC-A-62 no content
], ids=["TC-A-57", "TC-A-58", "TC-A-59", "TC-A-60", "TC-A-61", "TC-A-62"])
def test_error_guessing_malformed_bodies(http, body):
    r = http.post("/simulate", json=body)
    assert r.status_code == 400 and r.json()["error"] == "validation_error"
    assert "Traceback" not in r.text


def test_error_guessing_not_json_at_all(http):
    """TC-A-63."""
    r = http.post("/simulate", content=b"hello", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"] == "validation_error"


def test_error_guessing_duplicate_names_differing_in_case(http):
    """TC-A-64: Windows treats A.vhd and a.vhd as the same file."""
    files = [{"name": "A.vhd", "content": entity("a")}, {"name": "a.vhd", "content": entity("b")}]
    assert rejected(post(http, files, "a"))


def test_error_guessing_shell_injection_in_top(http):
    """TC-A-65: a command hidden in the top name is refused, not run."""
    assert rejected(post(http, GOOD, "x; rm -rf /"))
    assert rejected(post(http, GOOD, "x$(whoami)"))


@needs_docker
@pytest.mark.parametrize("change", [
    lambda t: "﻿" + t,                     # TC-A-66 UTF-8 BOM (Windows Notepad)
    lambda t: t.replace("\n", "\r\n"),          # TC-A-67 Windows line endings
    lambda t: "-- café ✓\n" + t,                # TC-A-68 non-English characters
    lambda t: t.replace("  ", "\t"),            # TC-A-69 tabs
], ids=["TC-A-66_bom", "TC-A-67_crlf", "TC-A-68_unicode", "TC-A-69_tabs"])
def test_error_guessing_windows_style_files_work(http, change):
    """A design saved by a Windows editor must still simulate. TC-A-66 FAILED
    before the fix (GHDL: "UTF-8 BOM detected"); the service now drops the BOM."""
    files = [{"name": "and_gate.vhd", "content": change(GOOD[0]["content"])}, GOOD[1]]
    r = post(http, files, "and_gate_tb", "100ns")
    assert r.json()["status"] == "success", r.json()["stages"][0]["output"][:300]
