# P5A test plan and results (Milestone 5)

What each automated test proves, and the latest result. Run everything with
`python -m pytest -v -rs` (Docker Desktop running, image built). GitHub runs
the same on every push and pull request.

**Latest full run: 101 passed, 0 failed, 0 skipped** (real Docker, GHDL 4.1.0
on Ubuntu 24.04, 4 Nov 2026). Live HTTP check `docker/m4_api_check.py`: 13/13.

The "Requirement" column refers to contract v1
([hdl-service-contract-v1.md](hdl-service-contract-v1.md)). Add the matching
SRS IDs (FR-P5A-xx) from the team's SRS where the report needs them.

## Test files

| File | Tests | Needs Docker | Level |
| --- | --- | --- | --- |
| `tests/test_docker_runner.py` | 43 | 7 of them | Unit (runner, with a fake Docker) + real-Docker checks |
| `tests/test_api.py` | 12 | No | Unit (API, with a fake runner) |
| `tests/test_analysis_order.py` | 7 | No | Unit (file dependency order) |
| `tests/test_limits.py` | 18 | 16 of them | Resource limits, sandbox, stress, cleanup |
| `tests/test_integration.py` | 21 | 12 of them | End to end over HTTP, contract conformance, client |
| `docker/m4_api_check.py` | 13 scenarios | Yes, API running | Live system check over real HTTP |

## What is proven

### Request validation (no container starts)

| Requirement | Tests | Result |
| --- | --- | --- |
| Bad file names (folders, `..`, wrong extension) rejected with `validation_error` / 400 | `TestValidation::test_bad_file_names_rejected` (8 cases), `test_bad_requests_get_400_in_result_shape` | Pass |
| Empty, duplicate, too large, too many files rejected | `TestValidation` (4 tests) | Pass |
| Bad `top` and `stop_time` rejected (no command injection) | `test_bad_top_rejected` (5), `test_bad_stop_time_rejected` (5) | Pass |
| Every failure, including bad JSON, has the Result shape | `test_missing_fields_rejected_in_result_shape`, `check_contract()` in every integration test | Pass |

### GHDL stages and error classification

| Requirement | Tests | Result |
| --- | --- | --- |
| Working design simulates and returns a real VCD | `test_simulate_end_to_end[and_gate]`, `test_success_vcd_is_a_real_waveform`, `test_vcd_download_end_to_end` | Pass |
| Syntax error → `analysis_error`, with GHDL's file and line | `[syntax_error]`, `test_vhdl_errors_point_to_file_and_line` | Pass |
| Unknown top entity → `elaboration_error` | `[unknown_top]` | Pass |
| Failing assertion → `runtime_error` | `[failing_assertion]` | Pass |
| Files accepted in any order | `[testbench_sent_first]`, `test_analysis_order.py` (7) | Pass |
| `/simulate/vcd` gives a `.vcd` file on success, JSON 422 on failure | `test_vcd_download_*` | Pass |

### Resource limits and sandbox (real containers)

| Requirement | Tests | Result |
| --- | --- | --- |
| Runaway simulation killed at the time limit → `timeout` | `test_runaway_is_killed_as_timeout`, `test_runaway_job_times_out`, `test_runaway_simulation_is_killed` | Pass (killed in ~3 s) |
| Memory hog killed at 256 MB → `memory_limit` | `test_memory_hog_is_killed_as_memory_limit`, `[memory_hog]` | Pass (killed in < 1 s) |
| Fork bomb stopped by the 64-process limit | `test_process_limit_stops_fork_bomb` | Pass |
| No network inside a job | `test_has_no_network` (only `lo` exists) | Pass |
| Read-only root file system; only `/work` and `/tmp` writable | `test_root_filesystem_is_read_only`, `test_only_work_and_tmp_are_writable` | Pass |
| `/tmp` capped at 16 MB | `test_tmp_is_size_limited` | Pass |
| Runs as non-root with no Linux capabilities | `test_runs_as_non_root`, `test_all_capabilities_dropped` | Pass |
| Limits requested on every container | `test_every_container_is_locked_down` | Pass |
| Huge output is cut but keeps the final error | `test_huge_output_keeps_the_final_error`, `test_truncate_keeps_start_and_end` | Pass |
| VCD over 5 MB is not returned | `test_vcd_over_limit_is_dropped` | Pass |

### Isolation, concurrency and cleanup

| Requirement | Tests | Result |
| --- | --- | --- |
| Jobs cannot see each other's files | `test_jobs_do_not_see_each_other`, `test_parallel_jobs_are_correct_and_isolated` (8 jobs at once, same file names) | Pass |
| At most 4 jobs use Docker at once; the rest queue | `test_concurrent_jobs_are_capped` | Pass |
| No container or job folder left after success, every failure type, timeout or OOM | `assert_cleaned_up()` in 15 test runs | Pass |
| Leftovers from a crashed API removed at start-up | `test_cleanup_removes_leftover_container`, `test_cleanup_stale_jobs` | Pass |
| Docker down / image missing → 503 `internal_error` | `test_docker_down_is_503`, `test_docker_problem_is_503` | Pass |

### Integration with other teams

| Requirement | Tests | Result |
| --- | --- | --- |
| Browser front end (P6B) may call the API (CORS) | `test_browser_front_end_allowed_by_cors` | Pass |
| Published OpenAPI schema matches the real API | `test_published_openapi_file_is_up_to_date`, `test_openapi_lists_contract_endpoints` | Pass |
| Python client works and reports a down service clearly | `test_client_*` (3) | Pass |
| P5B language server integration | See [p5b-integration.md](p5b-integration.md) | **Pending: P5B not built yet** |

## Bugs found by Milestone 5 testing (fixed)

1. **Files had to be sent in dependency order.** Sending the testbench before
   the design gave `analysis_error: unit "and_gate" not found`. The service
   now sorts files by dependency before `ghdl -a` (`analysis_order()` in
   `app/docker_runner.py`).
2. **Long output lost the real error.** Output over 20,000 characters kept
   only the start, so a testbench printing many notes before failing lost the
   failure message. Truncation now keeps the start and the end.
3. **No cap on parallel jobs.** 40 simultaneous requests could start 40
   containers of 256 MB each. Now at most `P5A_MAX_CONCURRENT_JOBS` (4) run;
   the rest wait.
