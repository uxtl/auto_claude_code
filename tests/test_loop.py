"""测试 loop.py — mock worker + worktree 函数."""

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from vibe.config import Config
from vibe.loop import run_loop
from vibe.worker import shutdown_event


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


class TestDockerPreCheck:
    def test_docker_unavailable_raises(self, workspace: Path):
        """use_docker=True + Docker 不可用 → RuntimeError."""
        cfg = Config(workspace=str(workspace), use_docker=True)
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")

        with (
            patch("vibe.loop.check_docker_available", return_value=(False, "not installed")),
            pytest.raises(RuntimeError, match="Docker 不可用"),
        ):
            run_loop(cfg)

    def test_docker_image_missing_raises(self, workspace: Path):
        """use_docker=True + 镜像不存在且构建失败 → RuntimeError."""
        cfg = Config(workspace=str(workspace), use_docker=True)
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")

        with (
            patch("vibe.loop.check_docker_available", return_value=(True, "ok")),
            patch("vibe.loop.ensure_docker_image", return_value=(False, "no Dockerfile")),
            pytest.raises(RuntimeError, match="镜像准备失败"),
        ):
            run_loop(cfg)

    def test_docker_ok_continues(self, workspace: Path):
        """use_docker=True + Docker 正常 → 正常执行."""
        cfg = Config(workspace=str(workspace), use_docker=True)
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")

        with (
            patch("vibe.loop.check_docker_available", return_value=(True, "ok")),
            patch("vibe.loop.ensure_docker_image", return_value=(True, "exists")),
            patch("vibe.loop.worker_loop") as mock_wl,
        ):
            run_loop(cfg)
        mock_wl.assert_called_once()

    def test_no_docker_skips_checks(self, config: Config, workspace: Path):
        """use_docker=False → 不调用 Docker 检查."""
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")

        with (
            patch("vibe.loop.check_docker_available") as mock_check,
            patch("vibe.loop.worker_loop"),
        ):
            run_loop(config)
        mock_check.assert_not_called()


class TestContinuousMode:
    """测试 continuous=True 持续轮询模式."""

    def setup_method(self):
        shutdown_event.clear()

    def teardown_method(self):
        shutdown_event.clear()

    def test_continuous_false_no_tasks_exits(self, config: Config, workspace: Path):
        """continuous=False + 无任务 → 立即退出（现有行为不变）."""
        with patch("vibe.loop.worker_loop") as mock_wl:
            run_loop(config, continuous=False)
        mock_wl.assert_not_called()

    def test_continuous_true_no_tasks_waits_then_exits(self, workspace: Path):
        """continuous=True + 无任务 → 等待轮询，shutdown_event 后退出."""
        cfg = Config(workspace=str(workspace), poll_interval=1)

        # 在短延迟后触发 shutdown_event
        def _set_shutdown():
            shutdown_event.set()

        timer = threading.Timer(0.3, _set_shutdown)
        timer.start()

        with patch("vibe.loop.worker_loop") as mock_wl:
            run_loop(cfg, continuous=True)

        mock_wl.assert_not_called()

    def test_continuous_true_processes_then_polls(self, workspace: Path):
        """continuous=True + 有任务 → 处理完后继续轮询，直到 shutdown."""
        cfg = Config(workspace=str(workspace), poll_interval=1)
        task_file = workspace / "tasks" / "001_test.md"
        task_file.write_text("task", encoding="utf-8")

        call_count = 0

        def mock_worker(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # worker 处理完任务后，删除文件模拟任务完成
            if task_file.exists():
                task_file.unlink()

        # 在 worker 执行后短延迟触发 shutdown
        def _set_shutdown():
            shutdown_event.set()

        timer = threading.Timer(0.5, _set_shutdown)
        timer.start()

        with patch("vibe.loop.worker_loop", side_effect=mock_worker):
            run_loop(cfg, continuous=True)

        assert call_count == 1

    def test_continuous_true_picks_up_new_tasks(self, workspace: Path):
        """continuous=True → 第一轮无任务，第二轮有新任务 → 执行新任务."""
        cfg = Config(workspace=str(workspace), poll_interval=1)
        task_dir = workspace / "tasks"

        worker_called = threading.Event()

        def mock_worker(*args, **kwargs):
            # 删除任务文件模拟完成
            for f in task_dir.glob("*.md"):
                f.unlink()
            worker_called.set()

        # 延迟添加任务
        def _add_task():
            (task_dir / "001_new.md").write_text("new task", encoding="utf-8")

        def _set_shutdown():
            shutdown_event.set()

        # 0.3s 后添加新任务，1.5s 后关闭
        timer_add = threading.Timer(0.3, _add_task)
        timer_shutdown = threading.Timer(2.5, _set_shutdown)
        timer_add.start()
        timer_shutdown.start()

        with patch("vibe.loop.worker_loop", side_effect=mock_worker):
            run_loop(cfg, continuous=True)

        assert worker_called.is_set()
