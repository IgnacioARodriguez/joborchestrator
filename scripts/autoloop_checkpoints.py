from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an auditable git checkpoint for an autoloop iteration.")
    parser.add_argument("--iteration", type=int, required=True)
    parser.add_argument("--prefix", default="autoloop-checkpoint")
    parser.add_argument("--allow-dirty", action="store_true")
    return parser.parse_args(argv)


def create_checkpoint(
    iteration: int,
    *,
    prefix: str = "autoloop-checkpoint",
    allow_dirty: bool = False,
    cwd: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    tag_name = checkpoint_name(iteration, prefix=prefix)
    head = run_git(["rev-parse", "HEAD"], cwd=cwd)
    dirty_status = run_git(["status", "--porcelain"], cwd=cwd)
    if dirty_status and not allow_dirty:
        raise CheckpointError("worktree is dirty; commit or stash changes before creating an autoloop checkpoint")

    if run_git(["tag", "--list", tag_name], cwd=cwd):
        target = run_git(["rev-list", "-n", "1", tag_name], cwd=cwd)
        if target != head:
            raise CheckpointError(f"checkpoint {tag_name} already exists at {target[:12]}, not current HEAD {head[:12]}")
        return {
            "checkpoint": tag_name,
            "commit_sha": head,
            "created": False,
            "dirty": bool(dirty_status),
        }

    message = f"autoloop checkpoint {iteration} at {head[:12]}"
    run_git(["tag", "-a", tag_name, head, "-m", message], cwd=cwd)
    return {
        "checkpoint": tag_name,
        "commit_sha": head,
        "created": True,
        "dirty": bool(dirty_status),
    }


def checkpoint_name(iteration: int, *, prefix: str = "autoloop-checkpoint") -> str:
    if iteration < 1:
        raise CheckpointError("iteration must be >= 1")
    clean_prefix = prefix.strip()
    if not clean_prefix:
        raise CheckpointError("prefix must not be empty")
    return f"{clean_prefix}-{iteration}"


def run_git(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise CheckpointError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


class CheckpointError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        checkpoint = create_checkpoint(args.iteration, prefix=args.prefix, allow_dirty=args.allow_dirty)
    except CheckpointError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(checkpoint, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
