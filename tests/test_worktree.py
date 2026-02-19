"""测试 worktree.py — mock _run_git."""

import subprocess
from pathlib import Path
from unittest.mock import patch, call

from vibe.worktree import (
    cleanup_stale_worktrees,
    commit_and_merge,
    create_worktree,
    is_git_repo,
    remove_worktree,
)


def _cp(stdout="", stderr="", returncode=0):
    """创建 CompletedProcess 快捷方法."""
    return subprocess.CompletedProcess(
        args=["git"], stdout=stdout, stderr=stderr, returncode=returncode
    )


class TestIsGitRepo:
    def test_true(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", return_value=_cp(stdout="true")):
            assert is_git_repo(tmp_path) is True

    def test_false(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", return_value=_cp(returncode=1)):
            assert is_git_repo(tmp_path) is False

    def test_no_git(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", side_effect=FileNotFoundError):
            assert is_git_repo(tmp_path) is False


class TestCreateWorktree:
    def test_success(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", return_value=_cp()):
            path = create_worktree(tmp_path, "w0")
        assert "vibe-w0-" in str(path)

    def test_failure(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", return_value=_cp(returncode=1, stderr="error")):
            try:
                create_worktree(tmp_path, "w0")
                assert False, "Should raise RuntimeError"
            except RuntimeError as e:
                assert "失败" in str(e)


class TestRemoveWorktree:
    def test_calls_correct_command(self, tmp_path: Path):
        wt = Path("/tmp/vibe-w0-12345")
        with patch("vibe.worktree._run_git", return_value=_cp()) as mock_git:
            remove_worktree(tmp_path, wt)
        mock_git.assert_called_once()
        args = mock_git.call_args[0][0]
        assert "worktree" in args
        assert "remove" in args


class TestCommitAndMerge:
    def test_no_changes(self, tmp_path: Path):
        """status 为空 → 返回 True，不 commit."""
        with patch("vibe.worktree._run_git", return_value=_cp(stdout="")):
            result = commit_and_merge(tmp_path, Path("/tmp/wt"), "msg")
        assert result is True

    def test_success(self, tmp_path: Path):
        """status→add→commit→branch→merge→branch -d 全链路."""
        responses = [
            _cp(stdout="M file.py"),     # status --porcelain
            _cp(),                        # add -A
            _cp(),                        # commit
            _cp(stdout="vibe/w0-123"),   # rev-parse branch
            _cp(),                        # merge
            _cp(),                        # branch -d
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = commit_and_merge(tmp_path, Path("/tmp/wt"), "msg")
        assert result is True

    def test_merge_conflict(self, tmp_path: Path):
        """merge 失败 → abort + 返回 False."""
        responses = [
            _cp(stdout="M file.py"),     # status
            _cp(),                        # add
            _cp(),                        # commit
            _cp(stdout="vibe/w0-123"),   # branch
            _cp(returncode=1, stderr="conflict"),  # merge fails
            _cp(),                        # merge --abort
        ]
        with patch("vibe.worktree._run_git", side_effect=responses):
            result = commit_and_merge(tmp_path, Path("/tmp/wt"), "msg")
        assert result is False


class TestCleanupStale:
    def test_calls_prune(self, tmp_path: Path):
        with patch("vibe.worktree._run_git", return_value=_cp()) as mock_git:
            cleanup_stale_worktrees(tmp_path)
        args = mock_git.call_args[0][0]
        assert args == ["worktree", "prune"]
