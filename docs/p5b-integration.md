# P5A ↔ P5B integration: hand-off notes

Status: **P5A side ready, P5B not built yet.** This page tells the P5B team
what P5A offers and lists the integration tests still to add once P5B exists.

## How the two fit together

From the course contract (J. Nancoo, 22 Sept 2026): the VHDL is sent to a
language server for syntax checking (P5B), and compiled and simulated by the
GHDL service (P5A), with a `.vcd` the user opens in Surfer.

```
 P6B front end ──(1) VHDL files──▶ P5B language server ──▶ diagnostics
       │
       └──────(2) same files, top, stop_time──▶ P5A /simulate ──▶ Result + VCD
```

Both services should use the **same file model**, so the front end can send
one list to either:

```json
{"files": [{"name": "and_gate.vhd", "content": "..."}], "top": "and_gate_tb"}
```

## What P5A gives P5B

| Need | Where |
| --- | --- |
| Endpoints, request and Result format | [hdl-service-contract-v1.md](hdl-service-contract-v1.md) |
| Machine-readable schema | [openapi.json](openapi.json) |
| Ready-made Python client | [`clients/p5a_client.py`](../clients/p5a_client.py) |
| Is P5A up? | `GET /health` → `{"status":"ok","docker":"ok","image":"present"}` |
| Browser access from another port | CORS on, set `P5A_CORS_ORIGINS` |

GHDL's own messages are in `stages[i].output` in the form
`file.vhd:line:col:error: message`, so P5B (or the front end) can turn a P5A
analysis error into the same kind of diagnostic P5B produces.

## Questions to agree with P5B

1. Does P5B call P5A (e.g. syntax check with P5B, then forward to P5A), or
   does the front end call each one directly? P5A works either way.
2. P5B's diagnostic format (file, line, column, severity, message), so both
   can be shown the same way in the editor.
3. Which VHDL standard P5B checks against. P5A uses GHDL's default (VHDL-93c)
   unless `P5A_GHDL_STD` is set, e.g. `08`. Both should match, or P5B may
   accept code that P5A rejects.
4. Ports and addresses when both run on one machine (P5A uses 8000).

## Integration tests to add once P5B exists

| Test | Expected |
| --- | --- |
| Same files sent to P5B and P5A | Both accept the request format |
| File with a syntax error | P5B reports it; P5A returns `analysis_error` at the same file and line |
| Clean file | P5B has no errors; P5A returns `success` with a VCD |
| P5A down | P5B/front end shows "simulation unavailable", not a crash (client raises `P5AUnavailable`) |
| VHDL standard | A VHDL-2008-only construct gets the same verdict from both |
