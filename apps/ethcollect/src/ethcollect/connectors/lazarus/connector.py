"""DPRK / Lazarus theft addresses from tayvano/lazarus-bluenoroff-research (CC0), one markdown
file per incident under `hacks-and-thefts/` and `more-hacks-and-thefts/`.

The files are free-form notes, not a schema, and they also list victims (cold wallets, Safe
signers), exchange deposit addresses and other chains. A line's address is kept only when the
line and its section heading name no victim or service and no other chain. Lines that say what
the address did (exploiter, theft, laundering...) get medium trust, the rest low.
"""

import json
import re
from datetime import date

from ethcollect import tables
from ethcollect.connectors.github import raw_file

KIND = "label"
SUMMARY = "Lazarus/DPRK theft notes (tayvano, CC0), attacker and laundering addresses; hack"
DEFAULT_RATE = 5.0
REPO, REF = "tayvano/lazarus-bluenoroff-research", "main"
# notes that are not a theft: where PulseX sacrifice funds went
SKIP = {"more-hacks-and-thefts/pulsex-provex-richard-heart.md"}
INCIDENT = re.compile(r"^(?:more-)?hacks-and-thefts/[^/]+\.md$")
DATED = re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})")
ADDRESS = re.compile(r"(?<![0-9a-fA-Fx])0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
NOT_ATTACKER = re.compile(
    r"victim|cold wallet|hot wallet|warm wallet|signer|\bsafe\b|multisig|treasury|"
    r"team wallet|\btokens?\b|router|exchange|deposit|\bdepo\b|amt stolen|amount stolen|binance|okx|kucoin|huobi|\bhtx\b|"
    r"coinbase|kraken|tether|\bweth\b|proxy|implementation|returned|recovered|white ?hat|"
    r"bounty|seized|refund|reimburse|further reading|reports|podcast|dune|news",
    re.IGNORECASE,
)
OTHER_CHAIN = re.compile(
    r"\b(?:matic|polygon|bnb|bsc|ftm|fantom|arb|arbitrum|avax|avalanche|optimism|on base|trx|"
    r"tron|sol|solana|heco|klay|cronos|celo|gnosis|linea|zksync|blast|mantle|ronin chain|"
    r"harmony)\b|bscscan|polygonscan|arbiscan|ftmscan|snowtrace|basescan|"
    r"optimistic\.etherscan",
    re.IGNORECASE,
)
ATTACKER_WORDS = re.compile(
    r"exploit|attacker|hacker|theft|thief|stolen|launder|lazarus|dprk|drainer|scam|"
    r"phish|consolidat|mixer|tornado|swap|bridg",
    re.IGNORECASE,
)


def add_arguments(p) -> None:
    pass


def incidents(tree: bytes) -> list[tuple[str, date | None]]:
    """The GitHub tree listing -> (path, date in the file name or None)."""
    out = []
    for item in json.loads(tree)["tree"]:
        if INCIDENT.match(item["path"]) and item["path"] not in SKIP:
            m = DATED.search(item["path"])
            out.append((item["path"], date(int(m[1]), int(m[2]), int(m[3])) if m else None))
    return out


def parse(body: bytes, *, path: str, when: date | None) -> list[dict]:
    """One incident file -> hack labels for the attacker-side Ethereum addresses it lists."""
    rows, heading, seen = [], "", set()
    for line in body.decode(errors="replace").splitlines():
        if line.lstrip().startswith("#"):
            heading = line
            continue
        if NOT_ATTACKER.search(heading) or OTHER_CHAIN.search(heading):
            continue
        found = ADDRESS.findall(line)
        if not found or NOT_ATTACKER.search(line) or OTHER_CHAIN.search(line):
            continue
        trust = "medium" if ATTACKER_WORDS.search(line) or ATTACKER_WORDS.search(heading) else "low"
        for a in found:
            if a.lower() not in seen:
                seen.add(a.lower())
                rows += tables.label_rows([a], kind="hack", source="lazarus", trust=trust,
                                          ref=f"{path}: {line.strip()[:120]}", observed_at=when)
    return rows


def run(ctx, args) -> None:
    url = f"https://api.github.com/repos/{REPO}/git/trees/{REF}"
    files = incidents(ctx.get(url, params={"recursive": "1"}, suffix=".json"))
    if args.limit:
        files = files[: args.limit]
    ctx.note("incident_files", len(files))
    rows, hit = [], 0
    for path, when in files:
        got = parse(raw_file(ctx, REPO, REF, path), path=path, when=when)
        hit += bool(got)
        rows += got
    ctx.note("files_with_addresses", hit)
    # an address named in several incidents keeps its best-trust row
    rows.sort(key=lambda r: -r["trust"])
    df = tables.frame("labels", rows).unique("address", keep="first", maintain_order=True)
    tables.write(ctx.out, "labels", ctx.source, df)
    ctx.note("labels", df.height)
