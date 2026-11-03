"""Request and response shapes for the P5A GHDL Execution Service API."""
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class VhdlFile(BaseModel):
    """One VHDL source file sent by the client."""
    name: str = Field(min_length=1, max_length=100, examples=["and_gate.vhd"])
    content: str = Field(min_length=1)


class SimulationRequest(BaseModel):
    """A job: the VHDL files, the testbench to run, and how long to simulate.

    Preferred form:  {"files": [{"name", "content"}, ...], "top", "stop_time"}
    The single-file form from Milestone 2 is still accepted:
                     {"filename", "vhdl_source", "top_entity"}
    """
    files: Optional[List[VhdlFile]] = Field(default=None, min_length=1)
    top: Optional[str] = Field(default=None, min_length=1, max_length=100,
                               examples=["and_gate_tb"])
    stop_time: Optional[str] = Field(default=None, examples=["100ns"])

    # Milestone 2 single-file form.
    filename: Optional[str] = Field(default=None, min_length=1, max_length=100)
    vhdl_source: Optional[str] = Field(default=None, min_length=1)
    top_entity: Optional[str] = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _use_one_form(self):
        if self.files is None and self.filename and self.vhdl_source:
            self.files = [VhdlFile(name=self.filename, content=self.vhdl_source)]
        if self.top is None and self.top_entity:
            self.top = self.top_entity
        if not self.files or not self.top:
            raise ValueError("Send 'files' and 'top' (or the older "
                             "'filename', 'vhdl_source' and 'top_entity').")
        return self


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
    job_id: Optional[str]  # None only when the request body itself was invalid
    status: str            # "success" or "failed"
    stage: str             # last stage reached, or "done"
    error: Optional[str]   # e.g. "analysis_error", "timeout"; None on success
    message: str
    stages: List[StageResult]
    vcd: Optional[str]     # VCD waveform text, viewable in Surfer/GTKWave
