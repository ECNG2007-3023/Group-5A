"""Python client for the P5A GHDL Execution Service (contract v1).

For P5B, P6B or any script that wants to run VHDL without writing HTTP code.
It needs only `httpx` (already in requirements.txt). Copy this one file into
another project if you like; it does not import anything else from this repo.

    from clients.p5a_client import P5AClient, files_from_paths

    p5a = P5AClient("http://127.0.0.1:8000")
    result = p5a.simulate(files_from_paths("and_gate.vhd", "and_gate_tb.vhd"),
                          top="and_gate_tb", stop_time="100ns")
    if result["status"] == "success":
        open("and_gate_tb.vcd", "w").write(result["vcd"])     # open in Surfer
    else:
        print(result["error"], result["message"])
        for stage in result["stages"]:
            print(stage["stage"], stage["output"])             # GHDL's messages

Every call returns the contract's Result dict, for VHDL errors AND for
service errors (400/422/500/503), so callers only read one format. Only a
service that cannot be reached at all raises P5AUnavailable.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple, Optional

import httpx

# A job can run three stages of up to 10 s each, and may queue behind other
# jobs, so allow much longer than that before giving up.
DEFAULT_TIMEOUT_S = 120


class P5AUnavailable(Exception):
    """The service could not be reached (not started, wrong address, ...)."""


class VcdDownload(NamedTuple):
    """Reply of /simulate/vcd: the waveform on success, else the Result."""
    vcd: Optional[bytes]      # the .vcd file, or None if the job failed
    job_id: Optional[str]
    result: Optional[dict]    # the failure Result, or None on success


def files_from_paths(*paths):
    """Build the request's "files" list from .vhd files on disk."""
    return [{"name": Path(p).name,
             "content": Path(p).read_text(encoding="utf-8")} for p in paths]


class P5AClient:
    def __init__(self, base_url="http://127.0.0.1:8000",
                 timeout=DEFAULT_TIMEOUT_S, http: httpx.Client | None = None):
        # `http` lets tests pass FastAPI's TestClient instead of a real server.
        self._http = http or httpx.Client(base_url=base_url.rstrip("/"),
                                          timeout=timeout)

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    # ------------------------------------------------------------- calls

    def health(self) -> dict:
        """{"status": "ok", "docker": "ok", "image": "present"} when ready."""
        return self._send("GET", "/health").json()

    def is_ready(self) -> bool:
        try:
            h = self.health()
        except P5AUnavailable:
            return False
        return h.get("docker") == "ok" and h.get("image") == "present"

    def simulate(self, files, top, stop_time=None) -> dict:
        """Run a job. Returns the Result dict (VCD as text when it worked)."""
        return self._send("POST", "/simulate",
                          json=self._body(files, top, stop_time)).json()

    def simulate_vcd(self, files, top, stop_time=None) -> VcdDownload:
        """Run a job and get the waveform as a .vcd file."""
        r = self._send("POST", "/simulate/vcd",
                       json=self._body(files, top, stop_time))
        if r.status_code == 200:
            return VcdDownload(r.content, r.headers.get("x-job-id"), None)
        result = r.json()
        return VcdDownload(None, result.get("job_id"), result)

    # ----------------------------------------------------------- helpers

    @staticmethod
    def _body(files, top, stop_time):
        if isinstance(files, dict):                    # {name: content}
            files = [{"name": n, "content": c} for n, c in files.items()]
        body = {"files": list(files), "top": top}
        if stop_time:
            body["stop_time"] = stop_time
        return body

    def _send(self, method, path, **kwargs):
        try:
            return self._http.request(method, path, **kwargs)
        except httpx.TransportError as e:
            raise P5AUnavailable(
                f"P5A service not reachable ({e}). Is it running?") from e
