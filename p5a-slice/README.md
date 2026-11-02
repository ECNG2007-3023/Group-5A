# P5A GHDL Execution Service: Week 7 slice

A small working version of P5A: a FastAPI service that takes VHDL files, runs
GHDL analysis -> elaboration -> simulation, stops at the first failing stage,
and returns a JSON result plus the VCD waveform on success.

## Files

| File | What it is | SRS requirement |
| --- | --- | --- |
| `app/main.py` | FastAPI endpoints | FR-P5A-01, 02, 06 |
| `app/runner.py` | Validation, the three GHDL stages, time limit, error parsing | FR-P5A-01..06, SA-P5A-01 |
| `Dockerfile` | Packages Python + FastAPI + GHDL into one image | Design constraint (Docker) |
| `tests/test_runner.py` | Unit tests for `validate` and `parse_errors` (`pytest -q`) | Week 9 unit-test design |
| `test_client.py` | Runs every fixture and checks the result, without P5B or P6 | P5-StR3.1 |
| `fixtures/` | Test VHDL: good design, syntax error, failing assertion, runaway | System tests |

## API

| Request | What it does |
| --- | --- |
| `POST /jobs` (form fields: `top`, one or more `files`, optional `stop_time`) | Runs the job, returns the result |
| `GET /jobs/{job_id}` | Returns the stored result |
| `GET /jobs/{job_id}/waveform` | Downloads `wave.vcd` (success only) |
| `GET /health` | Service is up + GHDL version |

Result example (syntax error):

```json
{"job_id": "525e8814402f", "status": "fail", "failed_stage": "analysis",
 "category": "analysis_error",
 "stages": {"analysis": "fail", "elaboration": "not_run", "simulation": "not_run"},
 "errors": [{"file": "bad_semicolon.vhd", "line": 10, "column": 15,
             "message": "error: ';' expected at end of signal assignment"}],
 "vcd_available": false}
```

Categories: `analysis_error`, `elaboration_error`, `simulation_error`,
`service_runtime_error` (runaway job or service fault). An invalid request
(no files, empty file, wrong extension, no `top`) returns HTTP 400 and no job.

## Run it with Docker (Windows: install Docker Desktop first)

```
docker build -t p5a .
docker run --rm -p 8000:8000 p5a
```

Then, in another terminal:

```
pip install httpx
python test_client.py
```

## Run it without Docker (for quick development)

Needs GHDL on your PATH.

```
pip install -r requirements.txt
uvicorn app.main:app --reload
python test_client.py
```

## Next steps

1. **Per-job containers.** Right now each job runs in its own temp folder
   inside the one service container. To match "ephemeral isolation" fully,
   change `runner._run` to start a fresh `docker run --rm --network none
   --memory 512m` container per job.
2. **Agree the JSON with P5B and group 6**, then freeze it.
3. **Shared file/session model with P5B**: accept a P5B session's file set
   as a job without restructuring (FR-P5-Joint-01).
4. **More unit tests**: extend `tests/test_runner.py` as the runner grows.
