"""White-box path coverage of one function, worked like the lecture's
discount() example: _whole_stop_time(value, unit) in app/docker_runner.py.

    number = Decimal(value); i = index of unit
    D1: while number is not whole  AND  i < last unit:   (2 conditions: C1, C2)
            number *= 1000; i += 1
    D2: if number is not whole:  raise JobValidationError
    return f"{number}{unit}"

    Decisions: 2 (D1, D2)  ->  cyclomatic complexity 3
    Conditions in D1: C1 (not whole), C2 (a smaller unit exists)

    Coverage    | tests needed            | test IDs
    statement   | P1 + P4 (every line)    | TC-A-P1, TC-A-P4
    branch      | D1 and D2 both T and F  | TC-A-P1, TC-A-P2, TC-A-P4
    condition   | C1 T/F and C2 T/F       | TC-A-P1 (C1 F), TC-A-P2 (C1 T, C2 T), TC-A-P4 (C2 F)
    path        | every route             | TC-A-P1 .. TC-A-P4
"""
import pytest

from app.docker_runner import JobValidationError, _whole_stop_time


@pytest.mark.parametrize("value, unit, expected", [
    ("100", "ns", "100ns"),        # P1: loop runs 0 times, D2 false
    ("1.5", "ns", "1500ps"),       # P2: loop runs once, D2 false
    ("0.0001", "ns", "100fs"),     # P3: loop runs twice (ns -> ps -> fs), D2 false
], ids=["TC-A-P1_whole", "TC-A-P2_one_step", "TC-A-P3_two_steps"])
def test_paths_that_return(value, unit, expected):
    assert _whole_stop_time(value, unit) == expected


def test_path_that_raises():
    """TC-A-P4: already at fs, still not whole: C2 false ends the loop, D2 true."""
    with pytest.raises(JobValidationError, match="finer than 1 fs"):
        _whole_stop_time("0.5", "fs")
