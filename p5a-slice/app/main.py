"""P5A GHDL Execution Service - FastAPI entry point (Week 7 slice)."""
import subprocess

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .runner import RequestError, run_job, validate, vcd_path

app = FastAPI(title="P5A GHDL Execution Service")
RESULTS: dict[str, dict] = {}


@app.get("/health")
def health():
    try:
        v = subprocess.run(["ghdl", "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    except (FileNotFoundError, IndexError):
        v = "GHDL not found"
    return {"status": "ok", "ghdl": v}


@app.post("/jobs")
async def submit_job(top: str = Form(...), files: list[UploadFile] = File(...),
                     stop_time: str | None = Form(None)):
    data = {f.filename: await f.read() for f in files}
    try:
        validate(data, top)
    except RequestError as e:
        # FR-P5A-02: rejected before any job exists.
        return JSONResponse(status_code=400, content={
            "job_id": None, "status": "fail", "failed_stage": None,
            "category": "service_runtime_error",
            "errors": [{"file": None, "line": None, "column": None, "message": str(e)}]})
    result = run_job(data, top, stop_time)
    RESULTS[result["job_id"]] = result
    return result


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in RESULTS:
        raise HTTPException(404, "Unknown job")
    return RESULTS[job_id]


@app.get("/jobs/{job_id}/waveform")
def get_waveform(job_id: str):
    p = vcd_path(job_id)
    if p is None:
        raise HTTPException(404, "No waveform for this job")
    return FileResponse(p, media_type="text/plain", filename="wave.vcd")
