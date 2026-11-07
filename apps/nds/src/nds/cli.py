"""nds command line."""

import argparse
import sys
from pathlib import Path

from nds import ops
from nds.config import CONFIG_NAME, Config, NdsError
from nds.remote import open_remote


def _policy(args) -> ops.ConflictPolicy:
    if args.force:
        return lambda *_: ops.OVERWRITE
    if args.no_clobber:
        return lambda *_: ops.SKIP
    if not sys.stdin.isatty():
        return lambda *_: ops.ABORT

    def ask(rel: str, local_fp: str, remote_fp: str) -> str:
        print(f"conflict: {rel}\n  local  {local_fp}\n  remote {remote_fp}")
        while True:
            choice = input("[o]verwrite / [s]kip / [a]bort? ").strip().lower()
            if choice in ("o", "s", "a"):
                return {"o": ops.OVERWRITE, "s": ops.SKIP, "a": ops.ABORT}[choice]

    return ask


def _print(res: ops.Result, quiet_states: tuple[str, ...] = ()) -> None:
    counts: dict[str, int] = {}
    for rel, state in res.files.items():
        counts[state] = counts.get(state, 0) + 1
        if state not in quiet_states:
            print(f"{state:>9}  {rel}")
    print(
        "\n" + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
        if counts
        else "nothing to do"
    )


def _cmd_init(args, root: Path) -> None:
    if (root / CONFIG_NAME).exists():
        raise NdsError(f"{CONFIG_NAME} already exists")
    remote_path = Path(args.path).expanduser()
    remote_path.mkdir(parents=True, exist_ok=True)
    cfg = Config(
        root=root,
        dataset=args.dataset or root.name,
        default_remote="home",
        remotes={"home": {"type": "local", "path": args.path}},
    )
    cfg.save()
    print(f"wrote {root / CONFIG_NAME}; remote 'home' -> {remote_path}")


def _cmd_remote(args, root: Path) -> None:
    cfg = Config.load(root)
    if args.action == "add":
        spec = {"type": args.type}
        if args.path:
            spec["path"] = args.path
        cfg.remotes[args.name] = spec
        cfg.default_remote = cfg.default_remote or args.name
    elif args.action == "rm":
        if cfg.remotes.pop(args.name, None) is None:
            raise NdsError(f"unknown remote {args.name!r}")
        if cfg.default_remote == args.name:
            cfg.default_remote = next(iter(cfg.remotes), None)
    cfg.save()
    for name, spec in cfg.remotes.items():
        star = "*" if name == cfg.default_remote else " "
        print(f"{star} {name}  {spec.get('type')}  {spec.get('path', '')}")


def _cmd_ls_remote(args, root: Path) -> None:
    cfg = Config.load(root)
    for view in cfg.resolve(args.datasets, args.all):
        _, spec = cfg.remote(args.remote)
        entries = open_remote(spec, view.dataset).list()
        if cfg.datasets:
            print(f"[{view.dataset}]")
        for rel, e in sorted(entries.items()):
            print(f"{e.size:>14}  {e.fp}  {rel}")
        print(f"\n{len(entries)} files")


def _cmd_dataset(args, root: Path) -> None:
    cfg = Config.load(root)
    if args.action == "add":
        spec = {"path": args.path or args.name}
        if not (root / spec["path"]).is_dir():
            raise NdsError(f"{root / spec['path']} is not a folder")
        cfg.datasets[args.name] = spec
        cfg.check_datasets()
    elif args.action == "rm":
        if cfg.datasets.pop(args.name, None) is None:
            raise NdsError(f"unknown dataset {args.name!r}")
    cfg.save()
    for name, spec in cfg.datasets.items():
        print(f"{name}  {spec.get('path', name)}")


def _transfer(args, root: Path) -> None:
    top = Config.load(root)
    _, spec = top.remote(args.remote)
    kw = {"include": args.include, "exclude": args.exclude, "full": args.full}
    for cfg in top.resolve(args.datasets, args.all):
        remote = open_remote(spec, cfg.dataset)
        if top.datasets:
            print(f"[{cfg.dataset}]")
        if args.cmd == "status":
            _print(ops.status(cfg, remote, **kw), quiet_states=("stored",))
        elif args.cmd == "push":
            _print(ops.push(cfg, remote, _policy(args), **kw))
        else:
            _print(ops.pull(cfg, remote, _policy(args), **kw))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nds", description="NeoRisk data storage")
    p.add_argument("-C", dest="root", default=".", help="dataset folder (default: cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create nds.yaml with a local remote")
    s.add_argument("--dataset")
    s.add_argument("--path", default="~/data", help="local remote folder (default ~/data)")

    s = sub.add_parser("remote", help="add / rm / ls remotes")
    s.add_argument("action", choices=["add", "rm", "ls"])
    s.add_argument("name", nargs="?")
    s.add_argument("--type", default="local")
    s.add_argument("--path")

    s = sub.add_parser("dataset", help="add / rm / ls datasets in a multi-dataset nds.yaml")
    s.add_argument("action", choices=["add", "rm", "ls"])
    s.add_argument("name", nargs="?")
    s.add_argument("--path", help="folder of the dataset (default: its name)")

    s = sub.add_parser("ls-remote", help="list what the remote holds")
    s.add_argument("datasets", nargs="*", help="dataset names (multi-dataset nds.yaml)")
    s.add_argument("--all", action="store_true", help="every dataset")
    s.add_argument("-r", "--remote", help="remote name (default: default_remote)")

    for name, h in (
        ("status", "show what push would do"),
        ("push", "move files to the remote"),
        ("pull", "link / fetch files from the remote"),
    ):
        s = sub.add_parser(name, help=h)
        s.add_argument("datasets", nargs="*", help="dataset names (multi-dataset nds.yaml)")
        s.add_argument("--all", action="store_true", help="every dataset")
        s.add_argument("-r", "--remote", help="remote name (default: default_remote)")
        s.add_argument("--include", action="append", default=[])
        s.add_argument("--exclude", action="append", default=[])
        s.add_argument("--full", action="store_true", help="hash whole files, not samples")
        if name != "status":
            s.add_argument("--force", action="store_true", help="overwrite on conflict")
            s.add_argument("--no-clobber", action="store_true", help="skip on conflict")

    args = p.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.cmd == "init":
            _cmd_init(args, root)
        elif args.cmd == "remote":
            if args.action != "ls" and not args.name:
                p.error("remote add/rm needs a name")
            _cmd_remote(args, root)
        elif args.cmd == "dataset":
            if args.action != "ls" and not args.name:
                p.error("dataset add/rm needs a name")
            _cmd_dataset(args, root)
        elif args.cmd == "ls-remote":
            _cmd_ls_remote(args, root)
        else:
            _transfer(args, root)
    except NdsError as e:
        print(f"nds: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
