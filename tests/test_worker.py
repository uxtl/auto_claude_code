"""测试 worker.py — mock manager + queue."""

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from vibe.approval import ApprovalStore
from vibe.config import Config
from vibe.manager import TaskResult
from vibe.task import Task, TaskQueue
from vibe.worker import PROMPT_PREFIX, PROMPT_SUFFIX, build_prompt, worker_loop


class TestBuildPrompt:
    def test_contains_parts(self):
        result = build_prompt("do X")
        assert result.startswith(PROMPT_PREFIX)
        assert result.endswith(PROMPT_SUFFIX)
        assert "do X" in result


class TestWorkerLoop:
    def test_empty_queue(self, config: Config, queue: TaskQueue):
        """claim_next 返回 None → 立即退出."""
        worker_loop("w0", config, queue)
        # 没有任务，正常退出即可（无异常）

    def test_processes_all(self, config: Config, workspace: Path, queue: TaskQueue):
        """两个任务 → 都被处理."""
        (workspace / "tasks" / "001_a.md").write_text("task a", encoding="utf-8")
        (workspace / "tasks" / "002_b.md").write_text("task b", encoding="utf-8")

        mock_result = TaskResult(success=True, output="ok", files_changed=[], duration_seconds=1.0)
        with patch("vibe.worker.manager.run_task", return_value=mock_result):
            worker_loop("w0", config, queue)

        # 两个任务都应完成
        done_files = list((workspace / "tasks" / "done").glob("*.md"))
        assert len(done_files) == 2


class TestExecuteTask:
    def test_success(self, config: Config, workspace: Path, queue: TaskQueue):
        """run_task 返回 success → queue.complete."""
        (workspace / "tasks" / "001_test.md").write_text("content", encoding="utf-8")

        mock_result = TaskResult(success=True, output="done", files_changed=[], duration_seconds=0.5)
        with patch("vibe.worker.manager.run_task", return_value=mock_result):
            worker_loop("w0", config, queue)

        done_files = list((workspace / "tasks" / "done").glob("*.md"))
        assert len(done_files) == 1

    def test_failure(self, workspace: Path):
        """run_task 返回 failure → queue.fail → 重试直到耗尽."""
        # max_retries=3 so: fail(0→1), re-claim, fail(1→2), re-claim, fail(2→3≥3) → exhausted
        cfg = Config(workspace=str(workspace), max_retries=3)
        q = TaskQueue(cfg, workspace)
        (workspace / "tasks" / "001_test.md").write_text("content", encoding="utf-8")

        mock_result = TaskResult(success=False, error="broke", files_changed=[], duration_seconds=0.5)
        with patch("vibe.worker.manager.run_task", return_value=mock_result) as mock_run:
            worker_loop("w0", cfg, q)

        # worker loops: claim→fail→requeue (x3), then exhausted → failed/
        assert mock_run.call_count == 3
        failed_files = list((workspace / "tasks" / "failed").glob("*.md"))
        assert len(failed_files) == 1

    def test_plan_mode(self, workspace: Path, queue: TaskQueue):
        """plan_mode=True → 调用 run_plan."""
        cfg = Config(workspace=str(workspace), plan_mode=True)
        q = TaskQueue(cfg, workspace)
        (workspace / "tasks" / "001_test.md").write_text("plan task", encoding="utf-8")

        mock_result = TaskResult(success=True, output="planned", files_changed=[], duration_seconds=1.0)
        with patch("vibe.worker.manager.run_plan", return_value=mock_result) as mock_plan:
            worker_loop("w0", cfg, q)

        mock_plan.assert_called_once()


class TestApprovalFlow:
    def test_approval_approved(self, workspace: Path):
        """store.approve → execute_plan 被调用 → 任务完成."""
        cfg = Config(workspace=str(workspace), plan_mode=True, plan_auto_approve=False)
        q = TaskQueue(cfg, workspace)
        store = ApprovalStore()
        (workspace / "tasks" / "001_test.md").write_text("task content", encoding="utf-8")

        plan_result = TaskResult(success=True, output="the plan", duration_seconds=0.5)
        exec_result = TaskResult(success=True, output="[计划]\nthe plan\n\n[执行结果]\nexecuted", duration_seconds=1.0)

        with (
            patch("vibe.worker.manager.generate_plan", return_value=plan_result),
            patch("vibe.worker.manager.execute_plan", return_value=exec_result) as mock_exec,
        ):
            # 在另一线程中运行 worker，因为它会阻塞
            def run_worker():
                worker_loop("w0", cfg, q, approval_store=store)

            t = threading.Thread(target=run_worker)
            t.start()

            # 等待审批出现
            import time
            for _ in range(50):
                if store.list_pending():
                    break
                time.sleep(0.05)

            pending = store.list_pending()
            assert len(pending) == 1
            store.approve(pending[0].approval_id)

            t.join(timeout=5)
            assert not t.is_alive()

        mock_exec.assert_called_once()
        done_files = list((workspace / "tasks" / "done").glob("*.md"))
        assert len(done_files) == 1

    def test_approval_rejected(self, workspace: Path):
        """store.reject → 任务失败."""
        cfg = Config(workspace=str(workspace), plan_mode=True, plan_auto_approve=False, max_retries=1)
        q = TaskQueue(cfg, workspace)
        store = ApprovalStore()
        (workspace / "tasks" / "001_test.md").write_text("task content", encoding="utf-8")

        plan_result = TaskResult(success=True, output="the plan", duration_seconds=0.5)

        with patch("vibe.worker.manager.generate_plan", return_value=plan_result):
            def run_worker():
                worker_loop("w0", cfg, q, approval_store=store)

            t = threading.Thread(target=run_worker)
            t.start()

            # 每次循环都会 re-claim 并 re-generate plan，需要 reject 每次
            import time
            for _ in range(50):
                pending = store.list_pending()
                if pending:
                    store.reject(pending[0].approval_id)
                if not t.is_alive():
                    break
                time.sleep(0.05)

            t.join(timeout=5)
            assert not t.is_alive()

        failed_files = list((workspace / "tasks" / "failed").glob("*.md"))
        assert len(failed_files) == 1

    def test_plan_mode_auto_approve(self, workspace: Path):
        """plan_auto_approve=True → 走 run_plan 不经过 store."""
        cfg = Config(workspace=str(workspace), plan_mode=True, plan_auto_approve=True)
        q = TaskQueue(cfg, workspace)
        store = ApprovalStore()
        (workspace / "tasks" / "001_test.md").write_text("task content", encoding="utf-8")

        mock_result = TaskResult(success=True, output="planned", files_changed=[], duration_seconds=1.0)
        with patch("vibe.worker.manager.run_plan", return_value=mock_result) as mock_plan:
            worker_loop("w0", cfg, q, approval_store=store)

        mock_plan.assert_called_once()
        # store 中不应有任何审批记录
        assert store.list_pending() == []
