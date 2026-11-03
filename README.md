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
| `pytest` | Unit tests. Real-Docker tests are skipped if Docker is not running |
| `python docker/m4_api_check.py` | With the API running: sends 11 real requests (success, analysis/elaboration/runtime errors, runaway job, bad requests, VCD download) and prints PASS/FAIL |
| `python docker/m3_demo.py` | Runs jobs through the runner directly, without the API |

## Layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | API endpoints (`/health`, `/simulate`, `/simulate/vcd`) |
| `app/models.py` | Request and result shapes |
| `app/docker_runner.py` | Runs each stage in an isolated container, classifies failures |
| `app/config.py` | Limits (10 s per stage, 256 MB, 1 CPU...), overridable by environment variable |
| `docker/Dockerfile` | The `p5a-ghdl` image (GHDL only, non-root user) |
| `tests/` | Unit tests; `tests/ghdl/` holds the VHDL test files |
