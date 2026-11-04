# HDL Service Contract v1: P5A GHDL Execution Service

Course staff (J. Nancoo, forum, 22 Sept 2026) defined the contract as: compile
a VHDL file with a GHDL service, produce a `.vcd` file that can be viewed in
Surfer, send the VHDL to a language server for syntax checking (P5B), and use
FastAPI for the interface. This page fixes the exact P5A part of that
contract. P5B and P6B (front end) should use the same file model.

Interactive docs while the service runs: `http://127.0.0.1:8000/docs`

## Endpoints

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/health` | `{"status": "ok", "docker": "ok", "image": "present"}` |
| POST | `/simulate` | A **Result** (JSON), VCD inside as text |
| POST | `/simulate/vcd` | On success the VCD as a file `<top>.vcd` for Surfer; otherwise a **Result** |

## Request (both POST endpoints)

```json
{
  "files": [
    {"name": "and_gate.vhd",    "content": "library IEEE; ..."},
    {"name": "and_gate_tb.vhd", "content": "library IEEE; ..."}
  ],
  "top": "and_gate_tb",
  "stop_time": "100ns"
}
```

| Field | Rule |
| --- | --- |
| `files` | 1 to 20 files. `name`: letters, digits, `_ . -`, ends in `.vhd` or `.vhdl`, no folders, no duplicates. `content`: not empty, at most 200,000 bytes |
| `top` | The entity to elaborate and run (normally the testbench). A VHDL identifier |
| `stop_time` | Optional, default `1us`. A number and unit: `fs ps ns us ms sec` |

The Milestone 2 single-file form `{"filename", "vhdl_source", "top_entity"}`
is also accepted and treated as one file.

## Result

Every reply from `/simulate`, and every failure from any endpoint, has exactly
these fields:

```json
{
  "job_id": "3f2a9c...",
  "status": "failed",
  "stage": "analysis",
  "error": "analysis_error",
  "message": "Analysis failed (exit code 1). See the stage output.",
  "stages": [
    {"stage": "analysis", "command": "ghdl -a invalid_syntax.vhd",
     "exit_code": 1, "output": "invalid_syntax.vhd:13:11:error: ';' expected at end of signal assignment ...",
     "duration_s": 0.4, "timed_out": false, "oom_killed": false}
  ],
  "vcd": null
}
```

| Field | Values |
| --- | --- |
| `status` | `success` or `failed` |
| `stage` | Where the job stopped: `validation`, `analysis`, `elaboration`, `simulation`, `service`, or `done` on success |
| `error` | `null` on success, otherwise one of the error codes below |
| `stages` | One entry per stage that ran, in order, with GHDL's own output (file and line of the error) |
| `vcd` | On success the VCD waveform as text, otherwise `null`. At most 5,000,000 bytes |

## Error codes and HTTP status

| `error` | Meaning | `/simulate` | `/simulate/vcd` |
| --- | --- | --- | --- |
| `null` | Success | 200 | 200 + `.vcd` file |
| `validation_error` | The request itself is invalid; no container started | 400 | 400 |
| `analysis_error` | `ghdl -a` failed (syntax or type error) | 200 | 422 |
| `elaboration_error` | `ghdl -e` failed (e.g. unknown top entity) | 200 | 422 |
| `runtime_error` | `ghdl -r` failed (e.g. assertion of severity failure) | 200 | 422 |
| `timeout` | A stage ran over 10 s; its container was killed | 200 | 422 |
| `memory_limit` | A stage went over 256 MB; its container was killed | 200 | 422 |
| `internal_error` | Docker not running or image missing (503), or a bug (500) | 503 / 500 | 503 / 500 |

## Limits for every job

Each stage runs in a new container from image `p5a-ghdl`: no network,
read-only root file system, non-root user, 256 MB memory (no swap), 1 CPU,
64 processes, 10 s per stage. Limits are set in `app/config.py`.
