# P5A: testing techniques applied (Milestone 5)

How each technique from the ECNG 2007 sessions is used in this repository:
**Assertions and Exceptions**, **Using Invariants**, and **White Box and Black
Box Testing**. Every item points to the code that does it and the test that
proves it.

**Latest run: 244 passed, 0 failed, 0 skipped** (real Docker, GHDL 4.1.0,
19 Nov 2026). **Coverage: 99%** statement + branch (coverage.py).

| Technique (lecture) | Where in the code | Tests |
| --- | --- | --- |
| Assertions | `assert` statements in `app/docker_runner.py` | `test_invariants.py::test_assertions_guard_programmer_assumptions` |
| Exceptions (try / throw / catch) | `JobValidationError`, Docker errors, `InvariantError`; handlers in `app/main.py` | `test_api.py`, `test_docker_failures.py`, `test_blackbox.py` (decision table) |
| Loop invariants | `analysis_order()` loop, the stage loop in `run_job()` | `test_invariants.py` (trace tests) |
| Data-structure invariant | every result checked by `check_result()` | `test_invariants.py::test_broken_results_are_caught` |
| White box: statement, branch, condition, path | whole code base; worked example on `_whole_stop_time()` | coverage.py, `test_paths.py`, `test_docker_failures.py` |
| Black box: equivalence partitions, boundary values | request validation | `test_blackbox.py` TC-A-01 … TC-A-46 |
| Black box: decision tables | stage outcome, HTTP reply | `test_blackbox.py` TC-A-47 … TC-A-51 |
| Black box: state transitions | job stages | `test_blackbox.py` TC-A-52 … TC-A-56 |
| Black box: error guessing | malformed requests, Windows files, Docker failures | `test_blackbox.py` TC-A-57 … TC-A-69, `test_docker_failures.py` |
| Writing test cases | the tables in this document | – |

---

## 1. Assertions

An assertion checks an assumption the programmer made; if it is false the
program stops at once (lecture slide 2). We use them for **preconditions**:
things the calling code has already guaranteed, so a failure can only mean a
bug in our own code.

| `assert` (in `app/docker_runner.py`) | Assumption it checks |
| --- | --- |
| `assert 1 <= len(files) <= config.MAX_FILES` (in `run_job`) | `validate_request()` really did enforce the file limits |
| `assert isinstance(text, str) and limit > 0` (in `_truncate`) | only text, with a positive limit, is ever truncated |
| `assert command and all(isinstance(part, str) ...)`, `assert timeout_s > 0` (in `_run_stage`) | a container is always started with a real command and a time limit |
| `assert files and len({n.lower() ...}) == len(files)` (in `_make_job_dir`) | file names reaching the disk are unique (Windows ignores case) |
| `assert done == set(ordered)` (in `analysis_order`) | the loop's bookkeeping set matches the list |
| `assert len(result["stages"]) == len(plan_names)` (after the stage loop) | leaving the loop normally means all three stages ran |

**Assert in production or not?** The lecture (slide 4) gives both sides:
assertions add overhead, can take a service offline and may reveal internal
details, but they also verify behaviour and detect faults. We split the job:

* plain `assert` for cheap internal assumptions. They run in normal use and in
  testing, and are removed if Python is started with `-O`;
* `InvariantError` (section 3) for rules that **must never be switched off**.
  It is a real exception, so it cannot be removed by `-O`, and `main.py` turns
  it into a plain HTTP 500 so no internal details reach the user.

## 2. Exceptions

An exception is a runtime error or abnormal condition that breaks the normal
flow (slide 5). C++ uses `try` / `throw` / `catch`; Python's words are
`try` / `raise` / `except`. The lecture's example and ours side by side:

| Lecturer's C++ example (`Search`) | P5A (`validate_request` and `run`) |
| --- | --- |
| `throw runtime_error("Student ID not found!");` | `raise JobValidationError("Too many files (max 20).")` |
| `try { ... }` | `try: files, top, stop_time = validate_request(...)` |
| `catch (const exception& e) { cout << e.what(); }` | `except JobValidationError as e: result.update(error="validation_error", message=str(e))` |

When we use them, following slide 7:

| Slide 7 reason | Exception in P5A | What the client gets |
| --- | --- | --- |
| Possible invalid operations | `JobValidationError` (bad name, size, top, stop_time); FastAPI's `RequestValidationError` (bad JSON) | 400 `validation_error` |
| Code relies on external systems | `DockerException`, `ImageNotFound`, `requests.ReadTimeout` (a hung container) | 503 `internal_error`, or `timeout` |
| Debugging and testing | `InvariantError`, `AssertionError` | 500 `internal_error` (never a wrong result) |
| Anything else | any other `Exception` (catch-all handler in `main.py`) | 500 in the normal Result shape, no traceback |

Every one of these is tested; `test_docker_failures.py` makes each Docker
call fail in turn (kill, wait, reload, logs, remove, image missing, daemon
stopped).

## 3. Invariants

An invariant is a property that stays true at specified points while the
program changes state (Using Invariants, slide 4). All of ours are checked
**while the service runs** (`app/invariants.py`), not only in the tests.

### 3.1 Loop invariant: putting files in dependency order

**Goal** (method step 1): `analysis_order(files)` must return the files so
that every file comes after the files it uses (GHDL analyses in order).

**Invariant** (step 2): *at the start of every iteration, every file placed
so far comes after every file it needs.* Like the lecture's "max is the
largest of the elements processed so far", it is a statement about the part
of the list built so far, and it is strong enough: once every file is placed
it says the whole list is in dependency order.

**Proof pattern** (step 3), each step checked in the code:

| Step | Why it holds | Checked by |
| --- | --- | --- |
| Establishment | before the loop nothing is placed, so it is trivially true | `check_order_invariant(ordered, needs)` before the loop |
| Preservation | each iteration only places a file whose needs are **all** already placed (`needs[i] <= done`), so the property still holds | the same check after every iteration |
| Exit | the loop ends when every file is placed; by the invariant the whole list is in order | the same check in the loop's `else:` |
| Termination | measure = files still to place. It starts at n ≥ 0 and drops by exactly 1 each iteration, so the loop must stop | `check_progress(before, after)` |

If the files depend on each other in a circle, no file is ever ready; the
loop then stops early on purpose and GHDL reports the real problem.

**Trace table** for `[tb.vhd, adder.vhd, consts.vhd]` sent testbench first
(tb needs adder, adder needs consts):

| Iteration | Ready files | Placed after the iteration | Files left (measure) | Invariant |
| --- | --- | --- | --- | --- |
| start | – | `[]` | 3 | true (nothing placed) |
| 1 | consts | `[consts]` | 2 | consts needs nothing: true |
| 2 | adder | `[consts, adder]` | 1 | adder's need (consts) is placed: true |
| 3 | tb | `[consts, adder, tb]` | 0 | tb's need (adder) is placed: true |
| exit | – | all placed | 0 | so the list is in dependency order |

Tested by `test_testbench_first_is_reordered` and, recording the invariant at
each check, `test_order_loop_invariant_trace`. Before this loop existed,
sending the testbench first gave `analysis_error: unit "and_gate" not found`.

### 3.2 Loop invariant: the three GHDL stages

*At the start of every iteration, the stages run so far are the first ones of
the plan (analysis, elaboration, simulation), in order, and every one of them
finished cleanly.* Establishment: no stage has run. Preservation: a stage that
fails returns from the loop, so only clean stages are kept. Exit: all three
ran cleanly, so the job is a success. Termination: stages left drops from 3 to
0. Checked by `check_stage_loop()` and `check_progress()`; tests
`test_stage_loop_invariant_catches_each_break` and
`test_broken_stage_loop_is_stopped`.

### 3.3 Data-structure invariant: the Result

Every result, before `run_job()` returns it, must obey contract v1
(`check_result()`):

* exactly the contract's fields, and a job id;
* `error` is empty exactly when `status` is `success`; a success has stage `done` and three clean stages;
* stages appear in order and stop at the first failure;
* a failed job has no VCD and explains why, and its error code matches the stage that failed;
* a rejected request starts no container;
* stage output stays within the size limit.

Also: only a folder directly inside `jobs/` is ever deleted (`check_inside()`),
and dependency ordering never adds or loses a file (`check_same_files()`).
`test_broken_results_are_caught` breaks each rule (19 cases);
`test_every_runner_outcome_obeys_the_rules` runs every real outcome (10 cases).

## 4. White-box testing

### 4.1 Coverage, measured with coverage.py

```
python -m coverage run -m pytest      # statement + branch (see .coveragerc)
python -m coverage report -m
```

| File | Statement + branch coverage |
| --- | --- |
| `app/docker_runner.py` | 99% |
| `app/invariants.py` | 100% |
| `app/main.py` | 100% |
| `app/models.py` | 100% |
| `app/config.py` | 100% |
| `clients/p5a_client.py` | 98% |
| **Total** | **99%** |

`app/ghdl_runner.py` (the Milestone 2 runner, replaced by `docker_runner.py`
and imported by nothing) is left out of the figure; see `.coveragerc`.

**Review of uncovered code** (the lecture's "run, review uncovered, add
tests" loop). The first run gave 90%. The lines no test reached were all the
runner's handling of Docker itself failing part-way through a job, so
`tests/test_docker_failures.py` was added: a fake Docker whose calls fail one
at a time. That raised `docker_runner.py` from 92% to 99%. As the lecture
warns, coverage only shows the code ran; the black-box tests below check the
answers are right.

### 4.2 Worked example: `_whole_stop_time(value, unit)`

```
number = Decimal(value); i = index of unit
D1: while number is not whole  AND  a smaller unit exists:   (conditions C1, C2)
        number *= 1000; move to the next smaller unit
D2: if number is not whole: raise JobValidationError
return number + unit
```

2 decisions, so cyclomatic complexity 3.

| Coverage | Goal | Tests (`tests/test_paths.py`) | Inputs |
| --- | --- | --- | --- |
| Statement | every line runs | 2 | P1 `100 ns`, P4 `0.5 fs` |
| Branch | D1 and D2 each true and false | 3 | P1, P2 `1.5 ns`, P4 |
| Condition | C1 and C2 each true and false | 3 | P1 (C1 false), P2 (C1, C2 true), P4 (C2 false) |
| Path | every route | 4 | P1 `100ns`, P2 `1.5ns → 1500ps`, P3 `0.0001ns → 100fs`, P4 `0.5fs → rejected` |

## 5. Black-box testing

Designed from contract v1 only (`tests/test_blackbox.py`). Rejected inputs
need no Docker; accepted ones run real GHDL jobs.

### 5.1 Equivalence partitions and boundary values

| Input | Partitions (one test from each) | Boundary values (below / on / above) | Test IDs |
| --- | --- | --- | --- |
| Number of files | 0 invalid · 1–20 valid · >20 invalid (tested with 50) | 0 · 1 · 2 and 19 · 20 · 21 | TC-A-01 … 07 |
| File size | empty or blank invalid · 1–200,000 bytes valid · >200,000 invalid | 199,999 · 200,000 · 200,001; 2-byte characters counted as bytes | TC-A-08 … 13 |
| File name | valid · wrong extension · not last extension · `..` · folder · space · no name | 100 characters · 101 characters | TC-A-14 … 23 |
| Top name | valid identifier · digit first · underscore first · dash · space · empty | 1 · 100 · 101 characters | TC-A-24 … 31 |
| stop_time | number + fs/ps/ns/us/ms/sec · no unit · unknown unit · negative · text · exponent · unit only | 0ns, 1fs, decimal, 0.5fs (finer than 1 fs) | TC-A-32 … 46 |

### 5.2 Decision tables

**Stage outcome** (contract v1 "Error codes"):

| Rule | Timed out | Killed for memory | Exit code 0 | Error |
| --- | --- | --- | --- | --- |
| R1 | Y | Y | Y | `timeout` |
| R2 | Y | Y | N | `timeout` |
| R3 | Y | N | Y | `timeout` |
| R4 | Y | N | N | `timeout` |
| R5 | N | Y | Y | `memory_limit` |
| R6 | N | Y | N | `memory_limit` |
| R7 | N | N | N | `analysis_error` (stage error) |
| R8 | N | N | Y | none, the job continues |

Tested as TC-A-47 R1 … R8.

**HTTP reply** (contract v1 "Endpoints"):

| Rule | Request valid | Docker available | VHDL correct | `/simulate` | `/simulate/vcd` | Test |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | N | – | – | 400 `validation_error` | 400 `validation_error` | TC-A-48 |
| R2 | Y | N | – | 503 `internal_error` | 503 `internal_error` | TC-A-49 |
| R3 | Y | Y | N | 200, status `failed` | 422, JSON result | TC-A-50 |
| R4 | Y | Y | Y | 200, `success` + VCD | 200, `.vcd` file | TC-A-51 |

### 5.3 State transitions: a job's stages

| From | Event | To | Test |
| --- | --- | --- | --- |
| validation | request bad | stop at `validation` (no container) | TC-A-56 |
| validation | request OK | analysis | all below |
| analysis | stage fails | stop at `analysis` | TC-A-53 |
| analysis | stage OK | elaboration | TC-A-54, 55, 52 |
| elaboration | stage fails | stop at `elaboration` | TC-A-54 |
| elaboration | stage OK | simulation | TC-A-55, 52 |
| simulation | stage fails | stop at `simulation` | TC-A-55 |
| simulation | stage OK | done | TC-A-52 |

### 5.4 Error guessing

Following the lecture's list (empty inputs, boundary overshoots, data types,
buffer limits, environmental disruptions):

* **Empty inputs / data types:** empty body, a JSON array, `files` as text, `content` a number, `top` null, missing content, not JSON at all (TC-A-57 … 63).
* **Windows behaviour:** `A.vhd` and `a.vhd` together (TC-A-64); files with a UTF-8 BOM, CRLF line endings, accented characters and tabs (TC-A-66 … 69).
* **Security:** a shell command hidden in the top name (TC-A-65).
* **Buffer limits:** 50 files, 200,001 bytes, 101-character names (in 5.1); a 20,000-line output and a 5 MB VCD (`test_limits.py`).
* **Environmental disruptions:** Docker stopped, image missing, container hangs, cannot be killed, logs unreadable (`test_docker_failures.py`, TC-A-49); memory hog, fork bomb, runaway simulation (`test_limits.py`).

## 6. Test cases

Written in the lecture's format. "Actual" is from the latest run.

| ID | Objective | Preconditions | Steps | Test data | Expected | Actual | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-A-07 | Upper boundary of file count is accepted | Docker running, image built | POST /simulate | 20 one-entity files, top `e0` | 200, `success` | 200, `success` | Pass |
| TC-A-02 | Just above the file-count boundary is rejected | API running | POST /simulate | 21 files | 400 `validation_error` | 400 `validation_error` | Pass |
| TC-A-12 | Largest allowed file is accepted | Docker running | POST /simulate | one file of exactly 200,000 bytes | 200, `success` | 200, `success` | Pass |
| TC-A-10 | One byte over the size limit is rejected | API running | POST /simulate | one file of 200,001 bytes | 400 `validation_error` | 400 `validation_error` | Pass |
| TC-A-14 | Name one character over the limit is rejected | API running | POST /simulate | 101-character name | 400 `validation_error` | 400 `validation_error` | Pass |
| TC-A-21 | Name exactly at the limit is accepted | Docker running | POST /simulate | 100-character name | job runs | job runs | Pass (Fail before fix 1) |
| TC-A-17 | Path traversal in a name is refused | API running | POST /simulate | name `../design.vhd` | 400, nothing written | 400, nothing written | Pass |
| TC-A-44 | A decimal stop time works | Docker running | POST /simulate | `and_gate` design, stop_time `1.5ns` | 200, `success` | 200, `success` | Pass (Fail before fix 2) |
| TC-A-47 R5 | A memory kill is reported as `memory_limit` | – | run_job with a stage killed for memory | fake Docker: OOM, exit 0 | `memory_limit` | `memory_limit` | Pass |
| TC-A-49 | Docker down gives 503 on both endpoints | Docker unreachable | POST /simulate, /simulate/vcd | valid design | 503 `internal_error` | 503 `internal_error` | Pass |
| TC-A-50 | A VHDL error gives 422 on the VCD endpoint | Docker running | POST /simulate/vcd | `invalid_syntax.vhd` | 422, `analysis_error` | 422, `analysis_error` | Pass |
| TC-A-53 | A job stops at the first failing stage | – | run_job | fake Docker: analysis fails | stage `analysis`, 1 container | stage `analysis`, 1 container | Pass |
| TC-A-65 | A shell command in `top` is refused | API running | POST /simulate | top `x; rm -rf /` | 400 `validation_error` | 400 `validation_error` | Pass |
| TC-A-66 | A file saved by Notepad (UTF-8 BOM) simulates | Docker running | POST /simulate | `and_gate.vhd` starting with a BOM | 200, `success` | 200, `success` | Pass (Fail before fix 3) |
| Limits | A memory hog is killed | Docker running | POST /simulate | `mem_hog_tb.vhd` | `memory_limit` in < 30 s | `memory_limit` in < 1 s | Pass |
| Limits | A runaway simulation is killed | Docker running | run_job, 3 s limit | `runaway_tb.vhd` | `timeout` | `timeout` in ~3 s | Pass |

### Defects found by these tests (all fixed)

| # | Found by | Test | Actual before the fix | Fix |
| --- | --- | --- | --- | --- |
| 1 | Boundary value analysis | TC-A-21 | A 100-character name passed `run_job()` but was refused by the API (the runner allowed 100 + extension) | One rule everywhere: at most 100 characters in total, as in P5B |
| 2 | Equivalence partitioning | TC-A-44 | `1.5ns` passed validation, then GHDL failed: `bad unit for '1.5ns'` | Decimals are moved to a smaller unit: `1500ps` |
| 3 | Error guessing | TC-A-66 | A file saved with a BOM failed: `UTF-8 BOM detected` | A leading BOM is removed |
| 4 | Error guessing (earlier, Milestone 5) | `testbench_sent_first` | Testbench first: `unit "and_gate" not found` | Files put in dependency order (section 3.1) |
| 5 | Stress testing (earlier) | `test_huge_output_keeps_the_final_error` | Long output lost the final error message | Truncation keeps the start and the end |
