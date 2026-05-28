import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from mcpify.utils import py_identifier, schema_to_py_type

HTTP_METHODS = ("get", "post", "put", "patch", "delete")


@dataclass
class Param:
    name: str
    py_name: str
    location: str  # path | query | header | body
    py_type: str
    required: bool
    description: str = ""


@dataclass
class Operation:
    op_id: str
    py_name: str
    method: str
    path: str
    summary: str = ""
    description: str = ""
    tags: list = field(default_factory=list)
    params: list = field(default_factory=list)
    has_body: bool = False
    body_required: bool = False


@dataclass
class Spec:
    title: str
    version: str
    base_url: str
    operations: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def load(target: str) -> dict:
    """Fetch and parse an OpenAPI document from URL or filesystem path."""
    if target.startswith(("http://", "https://")):
        with urllib.request.urlopen(target, timeout=30) as resp:
            data = resp.read()
    else:
        data = Path(target).expanduser().read_bytes()
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return _parse_yaml(data.decode("utf-8"))


def _parse_yaml(text: str) -> dict:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError as e:
        raise RuntimeError(
            "YAML OpenAPI detected but PyYAML is not installed. "
            "Install with: pip install pyyaml"
        ) from e


def normalize(raw: dict) -> Spec:
    info = raw.get("info") or {}
    title = info.get("title") or "Untitled API"
    version = info.get("version") or "0.0.0"
    servers = raw.get("servers") or []
    base_url = servers[0]["url"] if servers and isinstance(servers[0], dict) else ""

    operations: list = []
    paths = raw.get("paths") or {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_level_params = path_item.get("parameters") or []
        for method in HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            operations.append(_build_op(method, path, op, path_level_params))
    return Spec(title=title, version=version, base_url=base_url,
                operations=operations, raw=raw)


def _build_op(method: str, path: str, op: dict, path_params: list) -> Operation:
    op_id = op.get("operationId") or f"{method}_{path}"
    py_name = py_identifier(op_id)

    merged_params: list = []
    seen: set = set()
    for p in list(path_params) + list(op.get("parameters") or []):
        if not isinstance(p, dict):
            continue
        key = (p.get("name"), p.get("in"))
        if key in seen:
            continue
        seen.add(key)
        schema = p.get("schema") or {}
        merged_params.append(Param(
            name=p.get("name", "param"),
            py_name=py_identifier(p.get("name", "param")),
            location=p.get("in", "query"),
            py_type=schema_to_py_type(schema),
            required=bool(p.get("required") or p.get("in") == "path"),
            description=p.get("description") or "",
        ))

    request_body = op.get("requestBody")
    has_body = isinstance(request_body, dict) and bool(request_body.get("content"))
    body_required = has_body and bool(request_body.get("required"))

    return Operation(
        op_id=op_id,
        py_name=py_name,
        method=method.upper(),
        path=path,
        summary=op.get("summary") or "",
        description=op.get("description") or "",
        tags=list(op.get("tags") or []),
        params=merged_params,
        has_body=has_body,
        body_required=body_required,
    )
