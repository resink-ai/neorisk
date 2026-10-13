# neorisk

Python monorepo managed with [uv](https://docs.astral.sh/uv/) workspaces.

```
libs/   shared libraries   (each has its own pyproject.toml)
apps/   applications       (depend on libs via `workspace = true`)
```

Apps consume libs from the local workspace — no PyPI involved.

## Common tasks

```sh
uv sync                              # install everything into the root .venv
uv run --package hello hello         # run an app
uv run pytest                        # run all tests
uv run ruff check . && uv run ruff format .

uv init --lib libs/<name> --name neorisk-<name>   # new shared library
uv init --app apps/<name> --name <name>           # new application
cd apps/<app> && uv add --workspace neorisk-<name> # app depends on a lib
```
