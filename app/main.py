from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from . import docker_runner
from .models import SimulationRequest, SimulationResult


@asynccontextmanager
async def lifespan(_app):
    # Remove containers and job folders left over from a previous run.
    docker_runner.cleanup_stale_jobs()
    yield


app = FastAPI(title="GHDL Execution Service", lifespan=lifespan)


@app.get("/")
def home():
    return {"message": "GHDL Execution Service is running"}


@app.get("/health")
def health_check():
    return {"status": "ok", **docker_runner.docker_status()}


# A plain "def" (not "async def") so FastAPI runs each job in a worker
# thread and one slow simulation doesn't block other requests.
@app.post("/simulate", response_model=SimulationResult)
def simulate(request: SimulationRequest):
    result = docker_runner.run_job(
        files=request.files,
        top=request.top,
        stop_time=request.stop_time,
    )

    # The request itself was wrong (bad file name, bad stop time...).
    if result["error"] == "validation_error":
        raise HTTPException(status_code=400, detail=result["message"])

    # Docker isn't running or the GHDL image isn't built: our fault, not theirs.
    if result["error"] == "internal_error":
        raise HTTPException(status_code=503, detail=result["message"])

    # The VCD is plain text, so send it as a string inside the JSON.
    vcd = result["vcd"]
    result["vcd"] = vcd.decode("utf-8", errors="replace") if vcd else None

    # VHDL errors, timeouts and successes all come back as 200 with
    # "status" and "error" saying what happened.
    return result
