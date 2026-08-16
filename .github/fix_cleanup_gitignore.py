from pathlib import Path


path = Path(".gitignore")
text = path.read_text(encoding="utf-8")
text = text.replace(
    "# Public documentation such as docs/roadmap.md and docs/design/ remains tracked.\n",
    "# Public documentation such as docs/roadmap.md remains tracked.\n",
)

lines = text.splitlines()
plans_index = lines.index("docs/plans/")
for pattern in ("docs/design/", "docs/specs/"):
    if pattern not in lines:
        plans_index += 1
        lines.insert(plans_index, pattern)

path.write_text("\n".join(lines) + "\n", encoding="utf-8")
