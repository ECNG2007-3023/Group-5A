"""Write the API's OpenAPI description to docs/openapi.json.

P5B and P6B can load that file into Postman, Swagger UI or a code generator
without running our service. Re-run after changing app/models.py or the
endpoints in app/main.py (a test fails if you forget):

    python docker/export_openapi.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402

OUT = ROOT / "docs" / "openapi.json"

if __name__ == "__main__":
    OUT.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")
