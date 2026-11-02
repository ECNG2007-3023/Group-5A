"""Unit tests for app/runner.py (Week 9 unit-test design, examples).

Run with:  pytest -q
UT IDs trace to the detailed design (SDD) and to FR-P5A requirements.
"""
import pytest

from app.runner import RequestError, parse_errors, validate

GOOD = b"entity x is end;"


# UT-VAL-01 (FR-P5A-01): a normal request passes validation.
def test_valid_request_passes():
    validate({"and_gate.vhd": GOOD}, "and_gate_tb")


# UT-VAL-02 (FR-P5A-02): no files -> rejected.
def test_no_files_rejected():
    with pytest.raises(RequestError, match="No VHDL files"):
        validate({}, "and_gate_tb")


# UT-VAL-03 (FR-P5A-02): empty file -> rejected.
def test_empty_file_rejected():
    with pytest.raises(RequestError, match="empty"):
        validate({"and_gate.vhd": b"   "}, "and_gate_tb")


# UT-VAL-04 (FR-P5A-02, security): wrong extension or a folder path -> rejected.
@pytest.mark.parametrize("name", ["notes.txt", "../evil.vhd", "dir/and_gate.vhd"])
def test_bad_file_names_rejected(name):
    with pytest.raises(RequestError):
        validate({name: GOOD}, "and_gate_tb")


# UT-VAL-05 (FR-P5A-02): missing or malformed top-level name -> rejected.
@pytest.mark.parametrize("top", ["", "1tb", "tb; rm -rf /"])
def test_bad_top_rejected(top):
    with pytest.raises(RequestError, match="top-level"):
        validate({"and_gate.vhd": GOOD}, top)


# UT-PAR-01 (FR-P5A-06, UR-P5-02): a GHDL error line becomes file/line/column/message.
def test_parse_single_error():
    out = "bad_semicolon.vhd:10:15:error: ';' expected at end of signal assignment"
    assert parse_errors(out) == [{
        "file": "bad_semicolon.vhd", "line": 10, "column": 15,
        "message": "error: ';' expected at end of signal assignment"}]


# UT-PAR-02: lines that are not GHDL messages are ignored.
def test_parse_ignores_other_lines():
    assert parse_errors("ghdl: compilation error\n\n") == []
