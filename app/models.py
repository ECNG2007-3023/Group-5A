"""Request and response shapes for the P5A GHDL Execution Service API."""
from typing import List, Optional

from pydantic import BaseModel, Field


class VhdlFile(BaseModel):
    """One VHDL source file sent by the client."""
    name: str = Field(min_length=1, max_length=100, examples=["and_gate.vhd"])
    content: str = Field(min_length=1)


class SimulationRequest(BaseModel):
    """A job: the VHDL files, the testbench to run, and how long to simulate."""
    files: List[VhdlFile] = Field(min_length=1)
    top: str = Field(min_length=1, max_length=100, examples=["and_gate_tb"])
    stop_time: Optional[str] = Field(default=None, examples=["100ns"])


class StageResult(BaseModel):
    """What happened in one GHDL stage (analysis, elaboration or simulation)."""
    stage: str
    command: str
    exit_code: Optional[int]
    output: str
    duration_s: float
    timed_out: bool
    oom_killed: bool


class SimulationResult(BaseModel):
    """The result of a job, as returned by POST /simulate."""
    job_id: str
    status: str            # "success" or "failed"
    stage: str             # last stage reached, or "done"
    error: Optional[str]   # e.g. "analysis_error", "timeout"; None on success
    message: str
    stages: List[StageResult]
    vcd: Optional[str]     # VCD waveform text, viewable in Surfer/GTKWave
