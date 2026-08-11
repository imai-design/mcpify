import hashlib
import json
import keyword
import os
import re
from pathlib import Path

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]+")
_MD_CONTROL = re.compile(r"[\r\x00-\x08\x0b\x0c\x1b\u200b-\u200f\u2028\u2029]")


def py_literal(s) -> str:
    """Render a spec-derived value as a safe Python string literal.

    Anything taken from an OpenAPI document — parameter names, paths, URLs,
    descriptions — is untrusted input that ends up inside generated source.
    Interpolating it raw allows a crafted spec to execute arbitrary code in
    the generated client, so every such value must go through here.
    """
    return json.dumps("" if s is None else str(s))


def one_line(s, max_len: int = 400) -> str:
    """仕様書由来のテキストを1行の無害な文字列に潰す。

    仕様書は untrusted input で、その値はエージェントが従う文書に入る。
    見出し・水平線・コードフェンスを開けないよう改行と制御文字を落とす。
    """
    s = _MD_CONTROL.sub("", "" if s is None else str(s))
    s = " ".join(s.split()).replace("`", "'")
    return (s[:max_len] + "…") if len(s) > max_len else s


def yaml_scalar(s) -> str:
    """仕様書由来の値を YAML の二重引用符スカラーとして安全に出す。

    YAML 1.2 の二重引用符スカラーは JSON 文字列の上位互換なので、
    json.dumps のエスケープがそのまま使える（PyYAML 非依存を維持）。
    """
    return json.dumps(one_line(s), ensure_ascii=False)


def to_snake(name: str) -> str:
    name = _NON_ALNUM.sub("_", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.strip("_").lower() or "op"


def to_kebab(name: str) -> str:
    return to_snake(name).replace("_", "-")


def py_identifier(name: str) -> str:
    """Turn a spec-derived name into a safe Python identifier.

    to_snake() already falls back to "op" when nothing alnum survives, but
    that means every such name collapses onto the same identifier ("---" and
    "" and "!!!" all become "op"); hash the original so they stay distinct.
    Reserved words (`from`, `import`, `match`, ...) are also not valid
    parameter/function names, so those get a trailing underscore.
    """
    ident = to_snake(name)
    if not ident or ident == "op":
        ident = "p_" + hashlib.sha1(str(name).encode("utf-8")).hexdigest()[:8]
    if ident[:1].isdigit():
        ident = f"op_{ident}"
    if keyword.iskeyword(ident) or keyword.issoftkeyword(ident):
        ident = ident + "_"
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
    if isinstance(t, list):
        # OpenAPI 3.1 allows {"type": ["string", "null"]}; a bare list is not
        # a valid dict key for OPENAPI_TO_PY_TYPE, so pick the non-null entry.
        t = next((x for x in t if x != "null"), None)
    if isinstance(t, str) and t in OPENAPI_TO_PY_TYPE:
        return OPENAPI_TO_PY_TYPE[t]
    if "$ref" in schema or "oneOf" in schema or "anyOf" in schema:
        return "dict"
    return "str"


def compile_check(source: str, path) -> None:
    """Refuse to write generated Python that would not even parse.

    A reserved keyword slipping through as an identifier, a duplicate
    argument, or any other malformed name must fail generation loudly here
    instead of leaving a broken file on disk that only breaks once someone
    tries to run it.
    """
    try:
        compile(source, str(path), "exec")
    except SyntaxError as e:
        raise RuntimeError(
            f"refusing to write {path}: generated code is not valid Python ({e})"
        ) from e


def write_generated(path: Path, text: str, root: Path, mode: int = 0o644) -> None:
    """生成物を書き出す。既存のシンボリックリンクは絶対に追跡しない。

    --out の外にあるファイルを書き換えられないよう、書き込み先の親ディレクトリが
    root 配下に収まっているかも検証する（root 自体が既にシンボリックリンクの場合、
    その先へ書いてしまわないよう root 側は呼び出し側で is_symlink() を確認すること）。
    """
    root = Path(root).resolve()
    resolved_parent = path.parent.resolve()
    if resolved_parent != root and root not in resolved_parent.parents:
        raise RuntimeError(f"refusing to write outside --out: {path}")
    if path.is_symlink():
        raise RuntimeError(
            f"{path} is a symlink; refusing to write through it and "
            f"overwrite whatever it points at."
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
