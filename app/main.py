from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from . import docker_runner
from .models import SimulationRequest, SimulationResult


@asynccontextmanager
async def lifespan(_app):
    # Remove containers and job folders left over from a previous run.
    docker_runner.cleanup_stale_jobs()
    yield


app = FastAPI(
    title="GHDL Execution Service",
    description="P5A: runs VHDL through GHDL analysis, elaboration and "
                "simulation, each stage in its own locked-down Docker "
                "container, and returns the result of every stage plus the "
                "VCD waveform.",
    lifespan=lifespan,
)


# Every failure, whatever caused it, comes back in the SAME shape as a
# normal result, so a client only has to read one format.
def failure(status_code, error, message, stage="validation", job_id=None,
            stages=None):
    return JSONResponse(status_code=status_code, content={
        "job_id": job_id, "status": "failed", "stage": stage,
        "error": error, "message": message, "stages": stages or [],
        "vcd": None,
    })


@app.exception_handler(RequestValidationError)
async def bad_request_body(_request: Request, exc: RequestValidationError):
    # Missing fields, wrong types, empty file list... (checked by FastAPI).
    problems = "; ".join(
        f"{'.'.join(str(p) for p in e['loc'][1:]) or 'body'}: {e['msg']}"
        for e in exc.errors())
    return failure(400, "validation_error", f"Invalid request: {problems}")


@app.exception_handler(Exception)
async def unexpected_error(_request: Request, exc: Exception):
    # A bug in our code: never crash with an HTML page, always JSON.
    return failure(500, "internal_error",
                   f"Unexpected server error: {type(exc).__name__}",
                   stage="service")


@app.get("/")
def home():
    return {"message": "GHDL Execution Service is running"}


@app.get("/health")
def health_check():
    return {"status": "ok", **docker_runner.docker_status()}


# A plain "def" (not "async def") so FastAPI runs each job in a worker
# thread and one slow simulation doesn't block other requests.
@app.post("/simulate", response_model=SimulationResult, responses={
    400: {"model": SimulationResult, "description": "validation_error"},
    500: {"model": SimulationResult, "description": "internal_error (bug)"},
    503: {"model": SimulationResult,
          "description": "internal_error: Docker down or image missing"},
})
def simulate(request: SimulationRequest):
    result = run(request)
    if isinstance(result, JSONResponse):
        return result

    # The VCD is plain text, so send it as a string inside the JSON.
    vcd = result["vcd"]
    result["vcd"] = vcd.decode("utf-8", errors="replace") if vcd else None

    # VHDL errors, timeouts and successes all come back as 200 with
    # "status" and "error" saying what happened.
    return result


@app.post("/simulate/vcd", response_class=Response, responses={
    200: {"content": {"text/plain": {}},
          "description": "The waveform as a .vcd file, ready to open in Surfer"},
    400: {"model": SimulationResult}, 422: {"model": SimulationResult},
    503: {"model": SimulationResult},
})
def simulate_vcd(request: SimulationRequest):
    """Same job as /simulate, but a success returns the waveform as a .vcd
    file download instead of JSON. Any failure returns the usual JSON result
    (HTTP 422 for VHDL errors and timeouts, since there is no file)."""
    result = run(request)
    if isinstance(result, JSONResponse):
        return result
    if result["status"] != "success" or not result["vcd"]:
        result["vcd"] = None
        return JSONResponse(status_code=422, content=result)
    return Response(
        content=result["vcd"], media_type="text/plain",
        headers={"Content-Disposition":
                 f'attachment; filename="{request.top}.vcd"',
                 "X-Job-Id": result["job_id"]})


def run(request):
    """Run the job; turn request and service problems into failure replies."""
    result = docker_runner.run_job(
        files=request.files,
        top=request.top,
        stop_time=request.stop_time,
    )

    # The request itself was wrong (bad file name, bad stop time...).
    if result["error"] == "validation_error":
        return failure(400, "validation_error", result["message"],
                       job_id=result["job_id"])

    # Docker isn't running or the GHDL image isn't built: our fault, not theirs.
    if result["error"] == "internal_error":
        return failure(503, "internal_error", result["message"],
                       stage=result["stage"], job_id=result["job_id"],
                       stages=result["stages"])
    return result
