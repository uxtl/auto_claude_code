"""测试 loop.py — mock worker + worktree 函数."""

from pathlib import Path
from unittest.mock import MagicMock, patch, call

from vibe.config import Config
from vibe.loop import run_loop


class TestRunLoop:
    def test_no_tasks(self, config: Config, workspace: Path):
        """无 .md 文件 → 不启动 worker."""
        with patch("vibe.loop.worker_loop") as mock_wl:
            run_loop(config)
        mock_wl.assert_not_called()

    def test_single_worker(self, config: Config, workspace: Path):
        """max_workers=1 → 直接调用 worker_loop."""
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")

        with patch("vibe.loop.worker_loop") as mock_wl:
            run_loop(config)
        mock_wl.assert_called_once()
        args = mock_wl.call_args[0]
        assert args[0] == "w0"  # worker_id

    def test_multi_worker_no_git(self, workspace: Path):
        """多 worker + 非 git → 走共享模式."""
        cfg = Config(workspace=str(workspace), max_workers=2, use_worktree=True)
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")

        with (
            patch("vibe.loop.is_git_repo", return_value=False),
            patch("vibe.loop.worker_loop") as mock_wl,
        ):
            run_loop(cfg)
        # 应该被调用两次（2 个 worker）
        assert mock_wl.call_count == 2

    def test_multi_worker_with_worktree(self, workspace: Path):
        """多 worker + git → 创建/合并/清理 worktree."""
        cfg = Config(workspace=str(workspace), max_workers=2, use_worktree=True)
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")

        with (
            patch("vibe.loop.is_git_repo", return_value=True),
            patch("vibe.loop.cleanup_stale_worktrees"),
            patch("vibe.loop.create_worktree", side_effect=[Path("/tmp/wt0"), Path("/tmp/wt1")]) as mock_create,
            patch("vibe.loop.worker_loop") as mock_wl,
            patch("vibe.loop.commit_and_merge") as mock_merge,
            patch("vibe.loop.remove_worktree") as mock_remove,
        ):
            run_loop(cfg)

        assert mock_create.call_count == 2
        assert mock_wl.call_count == 2
        assert mock_merge.call_count == 2
        assert mock_remove.call_count == 2

    def test_worktree_creation_failure_fallback(self, workspace: Path):
        """创建失败 → 清理 + 降级共享模式."""
        cfg = Config(workspace=str(workspace), max_workers=2, use_worktree=True)
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")

        def create_side_effect(workspace, wid):
            if wid == "w1":
                raise RuntimeError("fail")
            return Path("/tmp/wt0")

        with (
            patch("vibe.loop.is_git_repo", return_value=True),
            patch("vibe.loop.cleanup_stale_worktrees"),
            patch("vibe.loop.create_worktree", side_effect=create_side_effect),
            patch("vibe.loop.worker_loop") as mock_wl,
            patch("vibe.loop.remove_worktree") as mock_remove,
        ):
            run_loop(cfg)

        # 应该已清理第一个 worktree 并降级到共享模式
        mock_remove.assert_called_once()
        # 共享模式仍然运行 worker
        assert mock_wl.call_count == 2
