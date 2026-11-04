# Group-5A: P5A GHDL Execution Service

A FastAPI service that runs VHDL through GHDL (analysis, elaboration,
simulation). Each stage runs in its own short-lived, locked-down Docker
container. The service returns the result of every stage and the VCD
waveform, which you can open in Surfer.

API format: [docs/hdl-service-contract-v1.md](docs/hdl-service-contract-v1.md)

## Run it (Windows, PowerShell, from the repo root)

1. Start **Docker Desktop**.
2. Build the GHDL image (once): `docker build -t p5a-ghdl ./docker`
3. Set up Python (once):
   ```
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
4. Start the API: `uvicorn app.main:app --reload`
5. Open http://127.0.0.1:8000/docs to try `POST /simulate` in the browser.

## Test it

| Command | What it checks |
| --- | --- |
| `python -m pytest` | All tests. Real-Docker tests are skipped (not failed) if Docker is not running or the image is not built; `-rs` shows why |
| `python -m pytest tests/test_limits.py -v` | Milestone 5: memory, process, network, file-system and time limits on real containers, huge output, 8 jobs in parallel, cleanup |
| `python -m pytest tests/test_integration.py -v` | Milestone 5: whole service end to end over HTTP, every reply checked against contract v1 |
| `python docker/m4_api_check.py` | With the API running: sends 13 real requests (success, every error type, runaway job, memory hog, bad requests, VCD download) and prints PASS/FAIL |
| `python docker/m3_demo.py` | Runs jobs through the runner directly, without the API |

GitHub runs all of this on every push and pull request
(`.github/workflows/tests.yml`), so a red X on a PR means something broke.
What each test proves: [docs/test-plan.md](docs/test-plan.md).

## Use it from another project (P5B, P6B)

```python
from clients.p5a_client import P5AClient, files_from_paths

result = P5AClient("http://127.0.0.1:8000").simulate(
    files_from_paths("and_gate.vhd", "and_gate_tb.vhd"), top="and_gate_tb")
```

Schema for other tools: [docs/openapi.json](docs/openapi.json).
P5B notes: [docs/p5b-integration.md](docs/p5b-integration.md).

## Layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | API endpoints (`/health`, `/simulate`, `/simulate/vcd`) |
| `app/models.py` | Request and result shapes |
| `app/docker_runner.py` | Runs each stage in an isolated container, classifies failures |
| `app/config.py` | Limits (10 s per stage, 256 MB, 1 CPU, 4 jobs at once...), CORS origins; all overridable by environment variable |
| `clients/p5a_client.py` | Python client for other teams |
| `docker/Dockerfile` | The `p5a-ghdl` image (GHDL only, non-root user) |
| `tests/` | Unit, limit and integration tests; `tests/ghdl/` holds the VHDL test files |
| `docs/` | Contract v1, OpenAPI schema, test plan, P5B notes |
