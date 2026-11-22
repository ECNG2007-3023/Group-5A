# P5A ↔ P5B integration: hand-off notes

Status: **done.** P5B (the Group-5B repository) is built and runs together
with P5A as one backend (`parent_main.py` in Group-5B, which uses P5A's code
unchanged). The answers to the questions below are in Group-5B's
`docs/p5a-integration.md`; the integration tests are in Group-5B's
`tests/test_combined.py` and all pass.

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

## Questions agreed with P5B (answered in Group-5B's docs/p5a-integration.md)

1. Does P5B call P5A (e.g. syntax check with P5B, then forward to P5A), or
   does the front end call each one directly? P5A works either way.
2. P5B's diagnostic format (file, line, column, severity, message), so both
   can be shown the same way in the editor.
3. Which VHDL standard P5B checks against. P5A uses GHDL's default (VHDL-93c)
   unless `P5A_GHDL_STD` is set, e.g. `08`. Both should match, or P5B may
   accept code that P5A rejects.
4. Ports and addresses when both run on one machine (P5A uses 8000).

## Integration tests (in Group-5B, all passing)

| Test planned here | Group-5B test |
| --- | --- |
| Same files sent to P5B and P5A | `test_session_files_pass_p5as_own_validator`, `test_session_files_run_through_p5a_simulate` |
| File with a syntax error: P5B reports it, P5A `analysis_error` on the same line | `test_syntax_error_is_found_by_both_services_on_the_same_line`, `test_fr_p5_01_syntax_error_end_to_end` |
| Clean file: no diagnostics, P5A `success` with a VCD | `test_fr_p5_02_valid_design_end_to_end`, `test_real_ghdl_job_on_the_session_files` |
| P5A/Docker down does not break P5B | `test_p5b_keeps_working_when_p5a_has_no_docker` |
| VHDL standard: same verdict from both | `test_vhdl_2008_code_gets_the_same_verdict_from_both` (the combined backend runs GHDL with VHDL-2008) |
| P5A unchanged inside the combined backend | `test_p5a_behaves_the_same_in_the_combined_app`, P5A's `m4_api_check.py` 13/13 against it |
