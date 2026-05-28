import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
FIXTURE = {
    "openapi": "3.0.0",
    "info": {"title": "Smoke API", "version": "1.0.0"},
    "servers": [{"url": "https://example.com"}],
    "paths": {
        "/items/{id}": {
            "get": {
                "operationId": "getItem",
                "summary": "Get an item by id.",
                "parameters": [
                    {"name": "id", "in": "path", "required": True,
                     "schema": {"type": "string"}}
                ],
            },
        },
        "/items": {
            "post": {
                "operationId": "createItem",
                "summary": "Create a new item.",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
            },
        },
    },
}


def run_mcpify(tmp_path: Path) -> Path:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(FIXTURE), encoding="utf-8")
    out = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "mcpify", str(spec_path),
         "--out", str(out), "--name", "smoke"],
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    )
    assert "operations" in result.stdout
    return out


def test_emits_four_channels(tmp_path):
    out = run_mcpify(tmp_path)
    assert (out / "openapi.json").is_file()
    assert (out / "mcp_server" / "server.py").is_file()
    assert (out / "skills" / "smoke" / "SKILL.md").is_file()
    assert (out / "cli" / "smoke.py").is_file()


def test_generated_code_compiles(tmp_path):
    out = run_mcpify(tmp_path)
    for f in [out / "mcp_server" / "server.py", out / "cli" / "smoke.py"]:
        subprocess.run([sys.executable, "-m", "py_compile", str(f)], check=True)


def test_skill_describes_operations(tmp_path):
    out = run_mcpify(tmp_path)
    body = (out / "skills" / "smoke" / "SKILL.md").read_text(encoding="utf-8")
    assert "get_item" in body
    assert "create_item" in body
    assert "POST /items" in body
