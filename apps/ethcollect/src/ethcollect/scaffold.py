"""`eth-collect new-source`: a connector folder and a reference stub from a template."""

from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).parent
SKILL = Path(__file__).parents[4] / ".claude" / "skills" / "eth-collect" / "references"

CONNECTOR = '''"""{name}: TODO one paragraph on what this source is and how it is read."""

from ethcollect import tables

KIND = "{kind}"
SUMMARY = "TODO one line: what it gives, access, trust"
DEFAULT_RATE = 1.0


def add_arguments(p) -> None:
    pass


def parse(body: bytes) -> list[dict]:
    """Pure: raw bytes in, table rows out. Unit-test this on a saved sample."""
    raise NotImplementedError


def run(ctx, args) -> None:
    body = ctx.get("TODO url")  # cached under data/eth/raw/{name}/
    df = tables.frame("{table}", parse(body))
    tables.write(ctx.out, "{table}", ctx.source, df)
    ctx.note("{table}", df.height)
'''

REFERENCE = """# {name}

- **What it is:** TODO
- **Access:** TODO (URL, key or none, rate limit, terms of use checked on YYYY-MM-DD)
- **Format:** TODO (file type, fields, an example record)
- **Field mapping:** TODO (source field -> table column, label_kind and trust)
- **Quirks:** TODO (pagination, delays, known false positives)
- **Changes seen:** none yet
"""


def new_source(name: str, kind: str) -> list[Path]:
    folder = PACKAGE / "connectors" / name.replace("-", "_")
    if folder.exists():
        raise SystemExit(f"{folder} already exists")
    folder.mkdir(parents=True)
    table = "labels" if kind == "label" else "transfers"
    made = [folder / "connector.py", folder / "README.md"]
    made[0].write_text(CONNECTOR.format(name=name, kind=kind, table=table))
    made[1].write_text(f"# {name}\n\nTODO: what it reads, how to run it, what it writes.\n")
    ref = SKILL / ("labels" if kind == "label" else "") / f"{name}.md"
    if SKILL.exists() and not ref.exists():
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(REFERENCE.format(name=name))
        made.append(ref)
    return made
