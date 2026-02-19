"""测试 task.py — 全部用 tmp_path 做真实文件操作."""

from pathlib import Path
from unittest.mock import patch

from vibe.config import Config
from vibe.task import TaskQueue, _extract_retry_count, _set_retry_count, _MAX_TASK_FILE_SIZE


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


class TestFailAtomicWrite:
    """测试 fail() 的原子写入: os.replace 失败时 .running 文件不丢失."""

    def test_retry_atomic_preserves_running_on_replace_failure(
        self, queue: TaskQueue, workspace: Path,
    ):
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")
        task = queue.claim_next("w0")
        assert task is not None

        with patch("vibe.task.os.replace", side_effect=OSError("disk full")):
            try:
                queue.fail(task, "some error")
            except OSError:
                pass

        # .running 文件应当仍然存在（未被删除）
        assert task.path.exists()

    def test_exhausted_atomic_preserves_running_on_replace_failure(
        self, workspace: Path,
    ):
        cfg = Config(workspace=str(workspace), max_retries=1)
        q = TaskQueue(cfg, workspace)

        task_file = workspace / "tasks" / "001_test.md"
        task_file.write_text("<!-- RETRY: 0 -->\ntask", encoding="utf-8")
        task = q.claim_next("w0")
        assert task is not None

        with patch("vibe.task.os.replace", side_effect=OSError("disk full")):
            try:
                q.fail(task, "final error")
            except OSError:
                pass

        # .running 文件应当仍然存在
        assert task.path.exists()


class TestFileSizeLimit:
    def test_oversized_file_skipped(self, queue: TaskQueue, workspace: Path):
        task_file = workspace / "tasks" / "001_big.md"
        # 写入超过 1MB 的内容
        task_file.write_text("x" * (_MAX_TASK_FILE_SIZE + 1), encoding="utf-8")
        task = queue.claim_next("w0")
        assert task is None


class TestRetryFailed:
    def test_retry_single(self, workspace: Path):
        task_dir = workspace / "tasks"
        fail_dir = workspace / "tasks" / "failed"
        # 模拟一个带时间戳前缀和错误注释的失败任务
        failed_file = fail_dir / "20240101_120000_000000_001_hello.md"
        failed_file.write_text(
            "<!-- FINAL FAILURE at 2024-01-01T12:00:00 -->\n"
            "<!-- Error: timeout -->\n"
            "<!-- Retries exhausted: 2/2 -->\n"
            "<!-- RETRY: 2 -->\n"
            "do something\n",
            encoding="utf-8",
        )

        retried = TaskQueue.retry_failed(task_dir, fail_dir, name="001_hello")
        assert retried == ["001_hello.md"]
        # 源文件已删除
        assert not failed_file.exists()
        # 目标文件存在且内容已清理
        dest = task_dir / "001_hello.md"
        assert dest.exists()
        content = dest.read_text(encoding="utf-8")
        assert "RETRY" not in content
        assert "FAILED" not in content
        assert "Error:" not in content
        assert "do something" in content

    def test_retry_all(self, workspace: Path):
        task_dir = workspace / "tasks"
        fail_dir = workspace / "tasks" / "failed"
        (fail_dir / "20240101_120000_000000_001_a.md").write_text(
            "<!-- FINAL FAILURE at 2024-01-01 -->\ntask a\n", encoding="utf-8",
        )
        (fail_dir / "20240101_120001_000000_002_b.md").write_text(
            "<!-- RETRY: 1 -->\ntask b\n", encoding="utf-8",
        )

        retried = TaskQueue.retry_failed(task_dir, fail_dir)
        assert len(retried) == 2
        assert (task_dir / "001_a.md").exists()
        assert (task_dir / "002_b.md").exists()

    def test_retry_empty(self, workspace: Path):
        task_dir = workspace / "tasks"
        fail_dir = workspace / "tasks" / "failed"
        retried = TaskQueue.retry_failed(task_dir, fail_dir)
        assert retried == []

    def test_retry_not_found(self, workspace: Path):
        task_dir = workspace / "tasks"
        fail_dir = workspace / "tasks" / "failed"
        (fail_dir / "20240101_120000_000000_001_hello.md").write_text(
            "task\n", encoding="utf-8",
        )
        retried = TaskQueue.retry_failed(task_dir, fail_dir, name="nonexistent")
        assert retried == []


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
