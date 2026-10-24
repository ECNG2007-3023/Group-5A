
from fastapi import FastAPI

app = FastAPI(title="GHDL Execution Service")


@app.get("/")
def home():
    return {"message": "GHDL Execution Service is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}
