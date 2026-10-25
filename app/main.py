
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="GHDL Execution Service")


class SimulationRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=100)
    vhdl_source: str = Field(min_length=1)


@app.get("/")
def home():
    return {"message": "GHDL Execution Service is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/simulate")
def simulate(request: SimulationRequest):
    if not request.filename.lower().endswith((".vhd", ".vhdl")):
        raise HTTPException(
            status_code=400,
            detail="Filename must end in .vhd or .vhdl",
        )

    if not request.vhdl_source.strip():
        raise HTTPException(
            status_code=400,
            detail="VHDL source cannot be empty",
        )

    return {
        "status": "accepted",
        "stage": "request_received",
        "filename": request.filename,
        "message": "Request accepted. GHDL simulation is not implemented yet.",
    }
