"""测试 task.py — 全部用 tmp_path 做真实文件操作."""

from pathlib import Path
from unittest.mock import patch

from vibe.config import Config
from vibe.task import (
    TaskQueue,
    _MAX_TASK_FILE_SIZE,
    _make_slug,
    _set_retry_count,
    extract_dependencies,
    extract_error_context,
    extract_retry_count,
    first_content_line,
    next_task_number,
)


# ── retry count 辅助函数 ─────────────────────────────────────

class TestRetryCount:
    def test_extract_none(self):
        assert extract_retry_count("normal content") == 0

    def test_extract(self):
        assert extract_retry_count("<!-- RETRY: 3 -->\ncontent") == 3

    def test_set_new(self):
        result = _set_retry_count("content", 1)
        assert result.startswith("<!-- RETRY: 1 -->")
        assert "content" in result

    def test_set_replace(self):
        original = "<!-- RETRY: 1 -->\ncontent"
        result = _set_retry_count(original, 2)
        assert "<!-- RETRY: 2 -->" in result
        assert "<!-- RETRY: 1 -->" not in result


# ── extract_error_context ────────────────────────────────────

class TestExtractErrorContext:
    def test_no_errors(self):
        errors, diagnostics, clean = extract_error_context("do something\n")
        assert errors == []
        assert diagnostics == []
        assert "do something" in clean

    def test_with_errors(self):
        content = (
            "<!-- FAILED at 2024-01-01T12:00:00 -->\n"
            "<!-- Error: timeout -->\n"
            "<!-- RETRY: 1 -->\n"
            "do something\n"
        )
        errors, diagnostics, clean = extract_error_context(content)
        assert errors == ["timeout"]
        assert diagnostics == []
        assert "do something" in clean

    def test_multiple_errors(self):
        content = (
            "<!-- FAILED at 2024-01-02T12:00:00 -->\n"
            "<!-- Error: permission denied -->\n"
            "<!-- FAILED at 2024-01-01T12:00:00 -->\n"
            "<!-- Error: timeout -->\n"
            "<!-- RETRY: 2 -->\n"
            "do something\n"
        )
        errors, diagnostics, clean = extract_error_context(content)
        assert len(errors) == 2
        assert "permission denied" in errors
        assert "timeout" in errors

    def test_clean_content(self):
        content = (
            "<!-- FINAL FAILURE at 2024-01-01T12:00:00 -->\n"
            "<!-- Error: some error -->\n"
            "<!-- Retries exhausted: 2/2 -->\n"
            "<!-- RETRY: 2 -->\n"
            "do something\n"
        )
        errors, diagnostics, clean = extract_error_context(content)
        assert "FAILED" not in clean
        assert "Error:" not in clean
        assert "RETRY" not in clean
        assert "Retries exhausted" not in clean
        assert "do something" in clean

    def test_multiline_diagnostics(self):
        """多行诊断块被正确解析."""
        content = (
            "<!-- FAILED at 2024-01-01T12:00:00 -->\n"
            "<!-- Error: some error -->\n"
            "<!-- Diagnostics:\n"
            "执行诊断（耗时 45.2s，退出码 1）:\n"
            "执行摘要: 共 10 次工具调用，3 次失败\n"
            "-->\n"
            "<!-- RETRY: 1 -->\n"
            "do something\n"
        )
        errors, diagnostics, clean = extract_error_context(content)
        assert len(diagnostics) == 1
        assert "执行诊断" in diagnostics[0]
        assert "45.2s" in diagnostics[0]
        assert "Diagnostics" not in clean
        assert "do something" in clean

    def test_single_line_diagnostics(self):
        """单行诊断也能解析."""
        content = (
            "<!-- Diagnostics: short diagnostic -->\n"
            "do something\n"
        )
        errors, diagnostics, clean = extract_error_context(content)
        assert diagnostics == ["short diagnostic"]
        assert "do something" in clean

    def test_clean_content_removes_diagnostics(self):
        """诊断块不出现在清理后的内容中."""
        content = (
            "<!-- FAILED at 2024-01-01 -->\n"
            "<!-- Error: broke -->\n"
            "<!-- Diagnostics:\n"
            "line1\n"
            "line2\n"
            "-->\n"
            "do something\n"
        )
        errors, diagnostics, clean = extract_error_context(content)
        assert "line1" not in clean
        assert "line2" not in clean
        assert "-->" not in clean
        assert "do something" in clean


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


class TestRelease:
    def test_release_back_to_queue(self, queue: TaskQueue, workspace: Path):
        """release 后 .running 文件重命名回 .md."""
        (workspace / "tasks" / "001_test.md").write_text("task content", encoding="utf-8")
        task = queue.claim_next("w0")
        assert task is not None
        assert task.path.name == "001_test.md.running.w0"

        queue.release(task)
        # .running 文件已消失
        assert not task.path.exists()
        # 原始 .md 文件恢复
        restored = workspace / "tasks" / "001_test.md"
        assert restored.exists()
        assert restored.read_text(encoding="utf-8") == "task content"

    def test_release_can_be_reclaimed(self, queue: TaskQueue, workspace: Path):
        """release 后任务可被再次 claim."""
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")
        task = queue.claim_next("w0")
        queue.release(task)

        task2 = queue.claim_next("w1")
        assert task2 is not None
        assert task2.name == "001_test"


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


# ── extract_dependencies ─────────────────────────────────────

class TestExtractDependencies:
    def test_no_deps(self):
        assert extract_dependencies("normal content") == []

    def test_single(self):
        assert extract_dependencies("<!-- DEPENDS: 001 -->\ncontent") == [1]

    def test_multiple(self):
        assert extract_dependencies("<!-- DEPENDS: 001, 002, 003 -->\ncontent") == [1, 2, 3]

    def test_whitespace_variants(self):
        assert extract_dependencies("<!-- DEPENDS:  1 , 2 -->\ncontent") == [1, 2]

    def test_with_retry(self):
        content = "<!-- DEPENDS: 001 -->\n<!-- RETRY: 1 -->\ncontent"
        assert extract_dependencies(content) == [1]


# ── first_content_line ────────────────────────────────────────

class TestFirstContentLine:
    def test_simple(self):
        assert first_content_line("hello world\n") == "hello world"

    def test_skips_comments(self):
        content = "<!-- DEPENDS: 001 -->\n<!-- RETRY: 1 -->\nreal content\n"
        assert first_content_line(content) == "real content"

    def test_empty(self):
        assert first_content_line("") == ""

    def test_only_comments(self):
        assert first_content_line("<!-- comment -->\n") == ""

    def test_truncate(self):
        line = "x" * 200
        assert len(first_content_line(line, max_len=120)) == 120

    def test_skips_empty_lines(self):
        content = "\n\n  \nhello\n"
        assert first_content_line(content) == "hello"


# ── next_task_number ──────────────────────────────────────────

class TestNextTaskNumber:
    def test_empty(self, workspace: Path):
        task_dir = workspace / "tasks"
        done_dir = workspace / "tasks" / "done"
        fail_dir = workspace / "tasks" / "failed"
        assert next_task_number(task_dir, done_dir, fail_dir) == 1

    def test_pending_only(self, workspace: Path):
        task_dir = workspace / "tasks"
        (task_dir / "003_task.md").write_text("x", encoding="utf-8")
        done_dir = workspace / "tasks" / "done"
        fail_dir = workspace / "tasks" / "failed"
        assert next_task_number(task_dir, done_dir, fail_dir) == 4

    def test_running(self, workspace: Path):
        task_dir = workspace / "tasks"
        (task_dir / "005_task.md.running.w0").write_text("x", encoding="utf-8")
        done_dir = workspace / "tasks" / "done"
        fail_dir = workspace / "tasks" / "failed"
        assert next_task_number(task_dir, done_dir, fail_dir) == 6

    def test_done(self, workspace: Path):
        task_dir = workspace / "tasks"
        done_dir = workspace / "tasks" / "done"
        fail_dir = workspace / "tasks" / "failed"
        (done_dir / "20240101_120000_000000_007_old.md").write_text("x", encoding="utf-8")
        assert next_task_number(task_dir, done_dir, fail_dir) == 8

    def test_failed(self, workspace: Path):
        task_dir = workspace / "tasks"
        done_dir = workspace / "tasks" / "done"
        fail_dir = workspace / "tasks" / "failed"
        (fail_dir / "20240101_120000_000000_010_bad.md").write_text("x", encoding="utf-8")
        assert next_task_number(task_dir, done_dir, fail_dir) == 11

    def test_mixed(self, workspace: Path):
        """最大编号来自 done，其余来源编号更小."""
        task_dir = workspace / "tasks"
        done_dir = workspace / "tasks" / "done"
        fail_dir = workspace / "tasks" / "failed"
        (task_dir / "001_pending.md").write_text("x", encoding="utf-8")
        (task_dir / "002_run.md.running.w0").write_text("x", encoding="utf-8")
        (done_dir / "20240101_120000_000000_005_done.md").write_text("x", encoding="utf-8")
        (fail_dir / "20240101_120000_000000_003_fail.md").write_text("x", encoding="utf-8")
        assert next_task_number(task_dir, done_dir, fail_dir) == 6


# ── _make_slug ────────────────────────────────────────────────

class TestMakeSlug:
    def test_simple(self):
        assert _make_slug("hello world") == "hello_world"

    def test_cjk(self):
        slug = _make_slug("分析代码库")
        assert "分析代码库" in slug

    def test_special_chars(self):
        slug = _make_slug("foo/bar baz?qux")
        assert "/" not in slug
        assert "?" not in slug

    def test_max_len(self):
        slug = _make_slug("a" * 100, max_len=30)
        assert len(slug) <= 30

    def test_multiline_takes_first(self):
        slug = _make_slug("first line\nsecond line")
        assert "second" not in slug


# ── claim_next 依赖 ──────────────────────────────────────────

class TestClaimNextDependencies:
    def test_skips_blocked_task(self, queue: TaskQueue, workspace: Path):
        """依赖未满足的任务被跳过."""
        (workspace / "tasks" / "001_first.md").write_text(
            "<!-- DEPENDS: 999 -->\ntask 1", encoding="utf-8",
        )
        (workspace / "tasks" / "002_second.md").write_text("task 2", encoding="utf-8")

        task = queue.claim_next("w0")
        assert task is not None
        assert task.name == "002_second"

    def test_claims_when_dep_done(self, queue: TaskQueue, workspace: Path):
        """依赖已完成时可认领."""
        (workspace / "tasks" / "done" / "20240101_120000_000000_001_first.md").write_text(
            "done", encoding="utf-8",
        )
        (workspace / "tasks" / "002_second.md").write_text(
            "<!-- DEPENDS: 001 -->\ntask 2", encoding="utf-8",
        )

        task = queue.claim_next("w0")
        assert task is not None
        assert task.name == "002_second"
        assert task.depends_on == [1]

    def test_all_blocked_returns_none(self, queue: TaskQueue, workspace: Path):
        """所有任务都被依赖阻塞时返回 None."""
        (workspace / "tasks" / "001_a.md").write_text(
            "<!-- DEPENDS: 999 -->\ntask a", encoding="utf-8",
        )
        (workspace / "tasks" / "002_b.md").write_text(
            "<!-- DEPENDS: 998 -->\ntask b", encoding="utf-8",
        )

        task = queue.claim_next("w0")
        assert task is None

    def test_no_deps_field_when_empty(self, queue: TaskQueue, workspace: Path):
        """无依赖的任务 depends_on 为 None."""
        (workspace / "tasks" / "001_test.md").write_text("task", encoding="utf-8")

        task = queue.claim_next("w0")
        assert task is not None
        assert task.depends_on is None
