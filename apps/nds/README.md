# nds

Park large datasets outside Git and keep them reachable by symlink. Design:
`docs/superpowers/specs/2026-11-06-nds-cli-design.html`.

```
cd data/spider2
nds init                 # writes nds.yaml, creates ~/data
nds status               # what push would do
nds push                 # move files to ~/data/spider2, symlink them back
nds ls-remote            # what the remote holds
nds pull                 # on a fresh checkout: restore the symlinks
```

Conflicts (same path, different content): prompt, or `--force` / `--no-clobber`. Fingerprints are
sampled by default (size + head/middle/tail 1 MiB); `--full` hashes whole files.

## One config for many datasets

Put a `datasets:` section in a single `nds.yaml` (e.g. `data/nds.yaml`):

```yaml
default_remote: home
remotes:
  home: {type: local, path: ~/data}
exclude: ["**/*.tmp", "cache/**"]        # shared by every dataset
datasets:
  spider2: {path: spider2}
  eth: {path: eth, exclude: ["raw/**"]}  # adds to the shared excludes
```

```
nds push spider2         # one dataset
nds push --all           # every dataset; safe to run after pushing some earlier
nds dataset add ref      # register data/ref
nds push -r lake ...     # pick a remote with -r
```

Each dataset gets its own folder and manifest on the remote (`~/data/spider2/...`). Dataset paths
must be relative, inside the config's folder, and must not overlap. A folder with its own
`nds.yaml` is left alone. Without `datasets:` the file describes just its own folder.

## Remotes

```yaml
remotes:
  home:    {type: local, path: ~/data}    # moves files, leaves a symlink in their place
  desktop: {type: ssh, host: my-desktop, path: /data/neorisk}   # rsync copy, local files stay
```

Push to `desktop` first if you want a second copy before any file is moved. Bring a dataset back with
`nds pull <name> -r <remote>`. Conflicts abort a non-interactive run unless `--force` / `--no-clobber`.

Each remote keeps `.nds-manifest.jsonl` (one JSON line per file, later lines win) in the dataset folder.
Writing through a symlink edits the stored copy; `nds status` shows such files as `modified`.
