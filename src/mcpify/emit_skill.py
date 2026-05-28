from pathlib import Path

from mcpify.openapi import Spec
from mcpify.utils import to_kebab


def emit(spec: Spec, out_dir: Path, name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = to_kebab(name)
    skill_dir = out_dir / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_render(spec, name, slug), encoding="utf-8")


def _render(spec: Spec, name: str, slug: str) -> str:
    title = spec.title
    operations = spec.operations
    summary = ", ".join({op.tags[0] for op in operations if op.tags}) or "API operations"
    head = (
        "---\n"
        f"name: {slug}\n"
        f'description: "Use {title} via the {name} MCP server. Covers: {summary}."\n'
        "---\n\n"
        f"# {title} — Operation Guide\n\n"
        f"このスキルを有効化すると、Claude は {name} MCP サーバー経由で {title} を操作できます。\n\n"
        "## セットアップ\n\n"
        f"1. `{name}` MCP サーバーを Claude Desktop / Claude Code に登録（生成された `mcp_server/claude_desktop_config.example.json` を参照）\n"
        "2. 環境変数 `MCPIFY_BASE_URL` と `MCPIFY_AUTH_TOKEN` を設定\n"
        "3. クライアントを再起動\n\n"
        "## 使えるツール\n\n"
    )
    rows: list = []
    for op in operations:
        line = f"### `{op.py_name}` — {op.summary or op.method + ' ' + op.path}\n\n"
        if op.description:
            line += op.description.strip() + "\n\n"
        line += f"- HTTP: `{op.method} {op.path}`\n"
        if op.params:
            line += "- パラメータ:\n"
            for p in op.params:
                req = "必須" if p.required else "任意"
                line += f"  - `{p.py_name}` ({p.py_type}, {req}, {p.location}) — {p.description or '—'}\n"
        if op.has_body:
            line += f"- ボディ: `body` (dict, {'必須' if op.body_required else '任意'})\n"
        rows.append(line)
    return head + "\n".join(rows) + "\n## 使い方の例\n\n" \
        "ユーザー: 「すべての項目を一覧して」\n" \
        f"→ Claude が `{operations[0].py_name if operations else 'list_items'}` ツールを呼び出して結果を返す。\n"
