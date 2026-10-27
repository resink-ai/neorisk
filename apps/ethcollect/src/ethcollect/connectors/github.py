"""Fetching a file from a public GitHub repository through the raw cache."""

from __future__ import annotations

from ethcollect.context import Context


def raw_file(ctx: Context, repo: str, ref: str, path: str) -> bytes:
    url = f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"
    ctx.note("url", url)
    return ctx.get(url, suffix="." + path.rsplit(".", 1)[-1])
