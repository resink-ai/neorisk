"""DeFiHackLabs (SunWeb3Sec/DeFiHackLabs, Apache-2.0): one Foundry reproduction per DeFi
exploit under `src/test/<YYYY-MM>/`. Each file opens with a `@KeyInfo` comment block whose
`Attacker :` and `Attack Contract :` lines link the exploiter on a block explorer. Only
etherscan.io links are Ethereum mainnet; other explorers (bscscan, arbiscan, ...) are skipped,
and so are `Vulnerable Contract` lines, which name the victim.
"""

import json
import re
from datetime import date

from ethcollect import tables
from ethcollect.connectors.github import raw_file

KIND = "label"
SUMMARY = "DeFiHackLabs exploit reproductions, attacker and attack-contract addresses; hack"
DEFAULT_RATE = 5.0
REPO, REF = "SunWeb3Sec/DeFiHackLabs", "main"
INCIDENT = re.compile(r"^src/test/(\d{4})-(\d{2})/[^/]+\.sol$")
ATTACKER = re.compile(
    r"^\s*//.*?\b(attacker(?:'s)?(?:\s+(?:address|eoa|contract))?|attack\s+contract|exploit\s+contract|exploiter"
    r"(?:\s+contract)?)\s*\d*\s*:?\s*https?://(?:www\.)?etherscan\.io/address/(0x[0-9a-fA-F]{40})",
    re.IGNORECASE | re.MULTILINE,
)


def add_arguments(p) -> None:
    pass


def incidents(tree: bytes) -> list[tuple[str, date]]:
    """The GitHub tree listing -> (path, first day of its month) for every incident file."""
    out = []
    for item in json.loads(tree)["tree"]:
        m = INCIDENT.match(item["path"])
        if m:
            out.append((item["path"], date(int(m[1]), int(m[2]), 1)))
    return out


def parse(body: bytes, *, path: str, month: date) -> list[dict]:
    """One incident file -> hack labels for its Ethereum attacker lines."""
    rows = []
    for m in ATTACKER.finditer(body.decode(errors="replace")):
        rows += tables.label_rows([m[2]], kind="hack", source="defihacklabs", trust="medium",
                                  ref=f"{path} ({m[1].lower()})", observed_at=month)
    return rows


def run(ctx, args) -> None:
    url = f"https://api.github.com/repos/{REPO}/git/trees/{REF}"
    files = incidents(ctx.get(url, params={"recursive": "1"}, suffix=".json"))
    if args.limit:
        files = files[-args.limit:]
    ctx.note("incident_files", len(files))
    rows, hit = [], 0
    for path, month in files:
        got = parse(raw_file(ctx, REPO, REF, path), path=path, month=month)
        hit += bool(got)
        rows += got
    ctx.note("ethereum_incidents", hit)
    df = tables.frame("labels", rows)
    tables.write(ctx.out, "labels", ctx.source, df)
    ctx.note("labels", df.height)
