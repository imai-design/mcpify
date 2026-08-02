import json
import re

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]+")


def py_literal(s) -> str:
    """Render a spec-derived value as a safe Python string literal.

    Anything taken from an OpenAPI document — parameter names, paths, URLs,
    descriptions — is untrusted input that ends up inside generated source.
    Interpolating it raw allows a crafted spec to execute arbitrary code in
    the generated client, so every such value must go through here.
    """
    return json.dumps("" if s is None else str(s))


def to_snake(name: str) -> str:
    name = _NON_ALNUM.sub("_", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.strip("_").lower() or "op"


def to_kebab(name: str) -> str:
    return to_snake(name).replace("_", "-")


def py_identifier(name: str) -> str:
    ident = to_snake(name)
    if ident[:1].isdigit():
        ident = f"op_{ident}"
    return ident


OPENAPI_TO_PY_TYPE = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


def schema_to_py_type(schema: dict) -> str:
    if not isinstance(schema, dict):
        return "str"
    t = schema.get("type")
    if t in OPENAPI_TO_PY_TYPE:
        return OPENAPI_TO_PY_TYPE[t]
    if "$ref" in schema or "oneOf" in schema or "anyOf" in schema:
        return "dict"
    return "str"
