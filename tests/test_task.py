"""测试 task.py — 全部用 tmp_path 做真实文件操作."""

from pathlib import Path

from vibe.config import Config
from vibe.task import TaskQueue, _extract_retry_count, _set_retry_count


# ── retry count 辅助函数 ─────────────────────────────────────

class TestRetryCount:
    def test_extract_none(self):
        assert _extract_retry_count("normal content") == 0

    def test_extract(self):
        assert _extract_retry_count("<!-- RETRY: 3 -->\ncontent") == 3

    def test_set_new(self):
        result = _set_retry_count("content", 1)
        assert result.startswith("<!-- RETRY: 1 -->")
        assert "content" in result

    def test_set_replace(self):
        original = "<!-- RETRY: 1 -->\ncontent"
        result = _set_retry_count(original, 2)
        assert "<!-- RETRY: 2 -->" in result
        assert "<!-- RETRY: 1 -->" not in result


# ── TaskQueue ────────────────────────────────────────────────

class TestClaimNext:
    def test_empty(self, queue: TaskQueue):
        assert queue.claim_next("w0") is None

    def test_renames(self, queue: TaskQueue, workspace: Path):
        task_file = workspace / "tasks" / "001_test.md"
        task_file.write_text("do something", encoding="utf-8")

        task = queue.claim_next("w0")
        assert task is not None
        assert task.name == "001_test"
        assert task.content == "do something"
        # 原文件已被改名
        assert not task_file.exists()
        assert task.path.name == "001_test.md.running.w0"

    def test_order(self, queue: TaskQueue, workspace: Path):
        (workspace / "tasks" / "002_second.md").write_text("b", encoding="utf-8")
        (workspace / "tasks" / "001_first.md").write_text("a", encoding="utf-8")

        task = queue.claim_next("w0")
        assert task is not None
        assert task.name == "001_first"


class TestComplete:
    def test_moves_to_done(self, queue: TaskQueue, workspace: Path):
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")
        task = queue.claim_next("w0")
        queue.complete(task)

        # running 文件已消失
        assert not task.path.exists()
        # done/ 中有归档文件
        done_files = list((workspace / "tasks" / "done").glob("*.md"))
        assert len(done_files) == 1
        assert "001_test" in done_files[0].name


class TestFail:
    def test_retry(self, queue: TaskQueue, workspace: Path):
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")
        task = queue.claim_next("w0")
        queue.fail(task, "some error")

        # running 文件已删除
        assert not task.path.exists()
        # 重新排队为 .md
        restored = workspace / "tasks" / "001_test.md"
        assert restored.exists()
        content = restored.read_text(encoding="utf-8")
        assert "<!-- RETRY: 1 -->" in content

    def test_exhausted(self, workspace: Path):
        cfg = Config(workspace=str(workspace), max_retries=1)
        q = TaskQueue(cfg, workspace)

        task_file = workspace / "tasks" / "001_test.md"
        task_file.write_text("<!-- RETRY: 0 -->\ntask", encoding="utf-8")
        task = q.claim_next("w0")
        q.fail(task, "final error")

        # 不会重新排队
        assert not (workspace / "tasks" / "001_test.md").exists()
        # 移到 failed/
        failed_files = list((workspace / "tasks" / "failed").glob("*.md"))
        assert len(failed_files) == 1


class TestRecover:
    def test_recover_running(self, workspace: Path):
        task_dir = workspace / "tasks"
        running = task_dir / "001_test.md.running.w0"
        running.write_text("task", encoding="utf-8")

        count = TaskQueue.recover_running(task_dir)
        assert count == 1
        assert (task_dir / "001_test.md").exists()
        assert not running.exists()

    def test_recover_conflict(self, workspace: Path):
        task_dir = workspace / "tasks"
        (task_dir / "001_test.md").write_text("original", encoding="utf-8")
        (task_dir / "001_test.md.running.w0").write_text("dup", encoding="utf-8")

        count = TaskQueue.recover_running(task_dir)
        assert count == 1
        # running 文件被删除（因为 .md 已存在）
        assert not (task_dir / "001_test.md.running.w0").exists()
        # 原始 .md 文件保留
        assert (task_dir / "001_test.md").read_text(encoding="utf-8") == "original"
