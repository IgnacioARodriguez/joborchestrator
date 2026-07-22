from pathlib import Path

import pytest

from scripts import autoloop_checkpoints as checkpoints


def test_checkpoint_name_validates_iteration_and_prefix():
    assert checkpoints.checkpoint_name(3) == "autoloop-checkpoint-3"
    assert checkpoints.checkpoint_name(3, prefix="probe") == "probe-3"

    with pytest.raises(checkpoints.CheckpointError, match="iteration"):
        checkpoints.checkpoint_name(0)

    with pytest.raises(checkpoints.CheckpointError, match="prefix"):
        checkpoints.checkpoint_name(1, prefix=" ")


def test_create_checkpoint_tags_current_clean_head(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    head = "1234567890abcdef"

    def fake_git(args: list[str], *, cwd: Path) -> str:
        calls.append(args)
        if args == ["rev-parse", "HEAD"]:
            return head
        if args == ["status", "--porcelain"]:
            return ""
        if args == ["tag", "--list", "autoloop-checkpoint-2"]:
            return ""
        if args == ["tag", "-a", "autoloop-checkpoint-2", head, "-m", "autoloop checkpoint 2 at 1234567890ab"]:
            return ""
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(checkpoints, "run_git", fake_git)

    result = checkpoints.create_checkpoint(2, cwd=tmp_path)

    assert result == {
        "checkpoint": "autoloop-checkpoint-2",
        "commit_sha": head,
        "created": True,
        "dirty": False,
    }
    assert calls[-1][0:3] == ["tag", "-a", "autoloop-checkpoint-2"]


def test_create_checkpoint_is_idempotent_for_existing_tag_at_head(monkeypatch, tmp_path):
    head = "abcdef1234567890"

    def fake_git(args: list[str], *, cwd: Path) -> str:
        if args == ["rev-parse", "HEAD"]:
            return head
        if args == ["status", "--porcelain"]:
            return ""
        if args == ["tag", "--list", "autoloop-checkpoint-4"]:
            return "autoloop-checkpoint-4"
        if args == ["rev-list", "-n", "1", "autoloop-checkpoint-4"]:
            return head
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(checkpoints, "run_git", fake_git)

    result = checkpoints.create_checkpoint(4, cwd=tmp_path)

    assert result["created"] is False
    assert result["commit_sha"] == head


def test_create_checkpoint_rejects_dirty_worktree(monkeypatch, tmp_path):
    def fake_git(args: list[str], *, cwd: Path) -> str:
        if args == ["rev-parse", "HEAD"]:
            return "1234567890abcdef"
        if args == ["status", "--porcelain"]:
            return " M prompt.md"
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(checkpoints, "run_git", fake_git)

    with pytest.raises(checkpoints.CheckpointError, match="worktree is dirty"):
        checkpoints.create_checkpoint(1, cwd=tmp_path)


def test_create_checkpoint_rejects_existing_tag_at_different_head(monkeypatch, tmp_path):
    def fake_git(args: list[str], *, cwd: Path) -> str:
        if args == ["rev-parse", "HEAD"]:
            return "aaaaaaaaaaaa"
        if args == ["status", "--porcelain"]:
            return ""
        if args == ["tag", "--list", "autoloop-checkpoint-5"]:
            return "autoloop-checkpoint-5"
        if args == ["rev-list", "-n", "1", "autoloop-checkpoint-5"]:
            return "bbbbbbbbbbbb"
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr(checkpoints, "run_git", fake_git)

    with pytest.raises(checkpoints.CheckpointError, match="already exists"):
        checkpoints.create_checkpoint(5, cwd=tmp_path)
