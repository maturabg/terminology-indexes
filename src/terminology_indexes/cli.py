"""``idx`` command line: build shards, combine, query, write the manifest."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from terminology_indexes.build import BuildError, combine, fetch_and_build, manifest
from terminology_indexes.model import load_registry
from terminology_indexes.search import search


def cmd_build(args: argparse.Namespace) -> int:
    registry = load_registry(args.sources_dir)
    for source_id in args.source:
        source = registry.get(source_id)
        if source is None:
            raise BuildError(f"unknown source {source_id!r}")
        if source.mode != "index" or source.status == "blocked":
            raise BuildError(f"{source_id}: mode={source.mode}, status={source.status}; not buildable")
        rows = fetch_and_build(source, args.raw_dir, args.shards_dir)
        print(f"{source_id}: {rows} entries", file=sys.stderr)
    if not args.no_combine:
        return cmd_combine(args)
    return 0


def cmd_combine(args: argparse.Namespace) -> int:
    counts = combine(args.shards_dir.glob("shard-*.sqlite"), args.out, args.release_tag)
    print(f"{args.out}: {sum(counts.values())} entries from {len(counts)} source(s)", file=sys.stderr)
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    if not args.index.exists():
        raise BuildError(f"{args.index} not found; run `idx build` first")
    conn = sqlite3.connect(f"file:{args.index}?mode=ro", uri=True)
    try:
        hits = search(conn, args.text, lang=args.lang, limit=args.limit)
    finally:
        conn.close()
    if args.json:
        print(json.dumps([h.__dict__ for h in hits], ensure_ascii=False, indent=2))
    else:
        for h in hits:
            print(f"{h.match:5}  {h.source}  {h.title}  {h.url}")
    return 0 if hits else 1


def cmd_manifest(args: argparse.Namespace) -> int:
    text = json.dumps(manifest(args.index), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="idx", description=__doc__)
    sub = p.add_subparsers(required=True)

    def paths(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--shards-dir", type=Path, default=Path("shards"))
        sp.add_argument("--out", type=Path, default=Path("index.sqlite"))
        sp.add_argument("--release-tag", default="")

    b = sub.add_parser("build", help="fetch + parse sources into shards, then combine")
    b.add_argument("--source", action="append", required=True, help="source id (repeatable)")
    b.add_argument("--sources-dir", type=Path, default=Path("sources"))
    b.add_argument("--raw-dir", type=Path, default=Path("raw"))
    b.add_argument("--no-combine", action="store_true")
    paths(b)
    b.set_defaults(func=cmd_build)

    c = sub.add_parser("combine", help="merge shards-dir/shard-*.sqlite into one index")
    paths(c)
    c.set_defaults(func=cmd_combine)

    q = sub.add_parser("query", help="search the index")
    q.add_argument("text")
    q.add_argument("--index", type=Path, default=Path("index.sqlite"))
    q.add_argument("--lang")
    q.add_argument("--limit", type=int, default=5)
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_query)

    m = sub.add_parser("manifest", help="print the manifest of a built index")
    m.add_argument("--index", type=Path, default=Path("index.sqlite"))
    m.add_argument("-o", "--output", type=Path)
    m.set_defaults(func=cmd_manifest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except BuildError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
