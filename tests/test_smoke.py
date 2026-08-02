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


def test_generated_clients_send_user_agent(tmp_path):
    """Hosts reject the urllib default UA as bot traffic, so always identify."""
    out = run_mcpify(tmp_path)
    for f in [out / "mcp_server" / "server.py", out / "cli" / "smoke.py"]:
        body = f.read_text(encoding="utf-8")
        assert 'MCPIFY_USER_AGENT' in body
        assert 'User-Agent' in body


def test_generated_clients_support_query_api_key(tmp_path):
    """Many APIs (YouTube, Maps) take the key as a query param, not a Bearer header."""
    out = run_mcpify(tmp_path)
    for f in [out / "mcp_server" / "server.py", out / "cli" / "smoke.py"]:
        body = f.read_text(encoding="utf-8")
        assert 'MCPIFY_API_KEY' in body
        assert 'API_KEY_PARAM' in body


HOSTILE = {
    "openapi": "3.0.0",
    "info": {"title": "Hostile", "version": "1.0.0"},
    "servers": [{"url": "https://example.com\"); __import__('os').system('id'); (\""}],
    "paths": {
        "/x": {
            "get": {
                "operationId": "x",
                "summary": 'quote " and triple """ and newline\nand backslash \\',
                "parameters": [
                    {
                        # A parameter name crafted to break out of the generated
                        # dict literal and execute code. See tests below.
                        "name": "a\": __import__('os').system('echo pwned'), \"b",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string"},
                        "description": 'desc with """ and \\ and\nnewline',
                    }
                ],
            }
        }
    },
}


def _emit_hostile(tmp_path: Path) -> Path:
    spec_path = tmp_path / "hostile.json"
    spec_path.write_text(json.dumps(HOSTILE), encoding="utf-8")
    out = tmp_path / "out"
    subprocess.run(
        [sys.executable, "-m", "mcpify", str(spec_path),
         "--out", str(out), "--name", "hostile"],
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    )
    return out


def test_hostile_spec_still_compiles(tmp_path):
    """A spec full of quotes and newlines must not produce broken source."""
    out = _emit_hostile(tmp_path)
    for f in [out / "mcp_server" / "server.py", out / "cli" / "hostile.py"]:
        subprocess.run([sys.executable, "-m", "py_compile", str(f)], check=True)


YAML_WITH_DATE = """\
openapi: "3.0.0"
info:
  title: Dated API
  version: "1.0.0"
servers:
  - url: https://example.com
paths:
  /items:
    get:
      operationId: listItems
      summary: List items.
components:
  schemas:
    Meta:
      example:
        added: 2015-02-22T20:00:45.000Z
        count: 3
        active: true
"""


def test_yaml_spec_with_timestamps(tmp_path):
    """YAML 1.1 turns bare dates into datetime, which is not JSON-serializable.

    A single date anywhere in the document used to abort generation while
    writing openapi.json. Timestamps must survive as strings; other scalars
    must keep their native types.
    """
    try:
        import yaml  # noqa: F401
    except ImportError:
        return  # PyYAML is optional; nothing to check without it

    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(YAML_WITH_DATE, encoding="utf-8")
    out = tmp_path / "out"
    subprocess.run(
        [sys.executable, "-m", "mcpify", str(spec_path),
         "--out", str(out), "--name", "dated"],
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    )
    written = json.loads((out / "openapi.json").read_text(encoding="utf-8"))
    example = written["components"]["schemas"]["Meta"]["example"]
    assert example["added"] == "2015-02-22T20:00:45.000Z"
    assert example["count"] == 3
    assert example["active"] is True


def test_cli_reports_http_errors_readably(tmp_path):
    """A failed call should explain itself, not dump a urllib traceback."""
    out = run_mcpify(tmp_path)
    body = (out / "cli" / "smoke.py").read_text(encoding="utf-8")
    assert "urllib.error.HTTPError" in body
    assert "MCPIFY_API_KEY" in body  # the 401/403 hint names the way in


def test_local_spec_urls_are_refused_by_default(tmp_path):
    """A spec URL aimed at the local network should not be fetched silently."""
    sys.path.insert(0, str(SRC))
    from mcpify import openapi

    for url in ["http://127.0.0.1:1/spec.json",
                "http://169.254.169.254/latest/meta-data/",
                "http://10.0.0.5/internal.json"]:
        try:
            openapi.load(url)
        except openapi.LocalAddressBlocked:
            continue
        raise AssertionError(f"not blocked: {url}")


def test_allow_local_opts_back_in(tmp_path):
    """Serving a spec from localhost is a normal thing to do while developing."""
    sys.path.insert(0, str(SRC))
    from mcpify import openapi

    # allow_local skips the check, so the call gets far enough to fail on the
    # connection instead of on the guard.
    try:
        openapi.load("http://127.0.0.1:1/spec.json", allow_local=True)
    except openapi.LocalAddressBlocked:
        raise AssertionError("--allow-local did not bypass the guard")
    except Exception:
        pass  # connection refused is the expected outcome here


def test_redirect_into_local_network_is_refused(tmp_path):
    """A public URL that redirects inward must be caught at the redirect."""
    sys.path.insert(0, str(SRC))
    from mcpify import openapi

    handler = openapi._GuardedRedirectHandler()

    class Req:
        def get_full_url(self): return "https://example.com/spec.json"
        def has_header(self, name): return False
        def get_method(self): return "GET"
        timeout = 30
        headers: dict = {}
        unredirected_hdrs: dict = {}
        origin_req_host = "example.com"
        unverifiable = False

    try:
        handler.redirect_request(Req(), None, 302, "Found", {},
                                 "http://169.254.169.254/latest/meta-data/")
    except openapi.LocalAddressBlocked:
        pass
    else:
        raise AssertionError("redirect into link-local was allowed")


def test_hostile_spec_cannot_inject_code(tmp_path):
    """Spec values must land as inert string literals, never as expressions.

    A crafted parameter name once escaped its dict literal and ran arbitrary
    code in the generated client. Every spec-derived value now goes through
    utils.py_literal, so the payload must survive only as quoted data.
    """
    out = _emit_hostile(tmp_path)
    for f in [out / "mcp_server" / "server.py", out / "cli" / "hostile.py"]:
        body = f.read_text(encoding="utf-8")
        # The payload text may appear, but never as a live call: an unescaped
        # __import__ would mean the quotes around it were broken out of.
        for line in body.splitlines():
            if "__import__" in line:
                assert '\\"' in line, f"unescaped payload in {f.name}: {line}"
