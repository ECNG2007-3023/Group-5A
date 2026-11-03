
import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.ghdl_runner import (
    analyze_vhdl,
    elaborate_vhdl,
    simulate_vhdl,
)

app = FastAPI(title="GHDL Execution Service")


class SimulationRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=100)
    vhdl_source: str = Field(min_length=1)
    top_entity: str = Field(min_length=1, max_length=100)


@app.get("/")
def home():
    return {"message": "GHDL Execution Service is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/simulate")
def simulate(request: SimulationRequest):

    # Validate the filename and entity name.
    if not re.fullmatch(
        r"[A-Za-z0-9_-]+\.vhdl?", request.filename,
        re.IGNORECASE,
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid VHDL filename",
        )

    if not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*", request.top_entity
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid top entity name",
        )

    if not request.vhdl_source.strip():
        raise HTTPException(
            status_code=400,
            detail="VHDL source cannot be empty",
        )

    # Create a temporary workspace for this request.
    with tempfile.TemporaryDirectory(
        prefix="ghdl_job_"
    ) as temporary_directory:

        working_directory = Path(temporary_directory)

        source_file = working_directory / request.filename
        source_file.write_text(
            request.vhdl_source,
            encoding="utf-8",
        )

        # Stage 1: Analyze
        analysis = analyze_vhdl(
            working_directory,
            [request.filename],
        )

        if not analysis["success"]:
            return {
                "status": "failed",
                "stage": "analysis",
                "result": analysis,
            }

        # Stage 2: Elaborate
        elaboration = elaborate_vhdl(
            working_directory,
            request.top_entity,
        )

        if not elaboration["success"]:
            return {
                "status": "failed",
                "stage": "elaboration",
                "result": elaboration,
            }

        # Stage 3: Simulate
        simulation = simulate_vhdl(
            working_directory,
            request.top_entity,
        )

        if not simulation["success"]:
            return {
                "status": "failed",
                "stage": "simulation",
                "result": simulation,
            }

        # Read the waveform before deleting the workspace.
        waveform_file = working_directory / "wave.vcd"

        waveform = None

        if waveform_file.exists():
            waveform = waveform_file.read_text(
                encoding="utf-8",
            )

        return {
            "status": "completed",
            "stage": "simulation",
            "filename": request.filename,
            "top_entity": request.top_entity,
            "analysis": analysis,
            "elaboration": elaboration,
            "simulation": simulation,
            "waveform": waveform,
        }
