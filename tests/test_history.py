"""测试 history.py — SQLite 执行历史."""

from pathlib import Path

import pytest

from vibe.history import ExecutionHistory
from vibe.manager import TaskResult


@pytest.fixture
def history(tmp_path: Path) -> ExecutionHistory:
    db_path = tmp_path / ".vibe_history.db"
    return ExecutionHistory(db_path)


def _make_result(success: bool = True, **kwargs) -> TaskResult:
    defaults = {
        "output": "hello world",
        "error": "",
        "files_changed": ["foo.py"],
        "tool_calls": [{"name": "Edit", "input": {"file_path": "foo.py"}}],
        "tool_results": [],
        "duration_seconds": 12.5,
        "return_code": 0,
        "result_text": "",
    }
    defaults.update(kwargs)
    return TaskResult(success=success, **defaults)


class TestRecord:
    def test_record_and_list(self, history: ExecutionHistory):
        result = _make_result()
        history.record("task1", "w0", result)

        rows = history.list_recent()
        assert len(rows) == 1
        row = rows[0]
        assert row["task_name"] == "task1"
        assert row["worker_id"] == "w0"
        assert row["success"] is True
        assert row["output"] == "hello world"
        assert row["files_changed"] == ["foo.py"]
        assert row["tool_calls_count"] == 1
        assert row["duration_seconds"] == 12.5
        assert row["return_code"] == 0

    def test_record_failure(self, history: ExecutionHistory):
        result = _make_result(success=False, error="exit code 1", return_code=1)
        history.record("task2", "w1", result)

        rows = history.list_recent()
        assert len(rows) == 1
        assert rows[0]["success"] is False
        assert rows[0]["error"] == "exit code 1"

    def test_output_truncation(self, history: ExecutionHistory):
        long_output = "x" * 60000
        result = _make_result(output=long_output)
        history.record("task3", "w0", result)

        rows = history.list_recent()
        assert len(rows[0]["output"]) == 50000

    def test_result_text_stored(self, history: ExecutionHistory):
        result = _make_result(result_text="Final answer from Claude")
        history.record("task_rt", "w0", result)

        rows = history.list_recent()
        assert rows[0]["result_text"] == "Final answer from Claude"

    def test_result_text_truncation(self, history: ExecutionHistory):
        long_text = "r" * 60000
        result = _make_result(result_text=long_text)
        history.record("task_rt2", "w0", result)

        rows = history.list_recent()
        assert len(rows[0]["result_text"]) == 50000

    def test_tool_results_summary_stored(self, history: ExecutionHistory):
        result = _make_result(
            tool_results=[
                {"tool_use_id": "t1", "name": "Bash", "is_error": False, "content": "ok output"},
                {"tool_use_id": "t2", "name": "Read", "is_error": True, "content": "file not found"},
            ],
        )
        history.record("task_trs", "w0", result)

        rows = history.list_recent()
        summary = rows[0]["tool_results_summary"]
        assert len(summary) == 2
        assert summary[0]["tool_use_id"] == "t1"
        assert summary[0]["name"] == "Bash"
        assert summary[0]["is_error"] is False
        assert "ok output" in summary[0]["snippet"]
        assert summary[1]["is_error"] is True


class TestQuery:
    def test_list_recent_limit(self, history: ExecutionHistory):
        for i in range(10):
            history.record(f"task_{i}", "w0", _make_result())

        rows = history.list_recent(limit=3)
        assert len(rows) == 3
        # 最新的在前
        assert rows[0]["task_name"] == "task_9"

    def test_get_by_task(self, history: ExecutionHistory):
        history.record("alpha", "w0", _make_result())
        history.record("beta", "w1", _make_result())
        history.record("alpha", "w0", _make_result(success=False, error="fail"))

        rows = history.get_by_task("alpha")
        assert len(rows) == 2
        assert all(r["task_name"] == "alpha" for r in rows)

    def test_get_by_id(self, history: ExecutionHistory):
        history.record("task1", "w0", _make_result())
        rows = history.list_recent()
        row_id = rows[0]["id"]

        result = history.get_by_id(row_id)
        assert result is not None
        assert result["task_name"] == "task1"

    def test_get_by_id_not_found(self, history: ExecutionHistory):
        assert history.get_by_id(9999) is None

    def test_get_by_task_empty(self, history: ExecutionHistory):
        assert history.get_by_task("nonexistent") == []


class TestToolCallsSummary:
    def test_tool_summary_format(self, history: ExecutionHistory):
        result = _make_result(tool_calls=[
            {"name": "Edit", "input": {"file_path": "/src/foo.py"}},
            {"name": "Bash", "input": {"command": "pytest tests/"}},
        ])
        history.record("task1", "w0", result)

        rows = history.list_recent()
        summary = rows[0]["tool_calls_summary"]
        assert len(summary) == 2
        assert summary[0]["name"] == "Edit"
        assert summary[0]["target"] == "/src/foo.py"
        assert summary[1]["name"] == "Bash"
        assert summary[1]["target"] == "pytest tests/"


class TestMigration:
    def test_migrate_adds_missing_columns(self, tmp_path: Path):
        """旧 schema 的数据库应自动迁移新列."""
        import sqlite3

        db_path = tmp_path / "migrate_test.db"
        conn = sqlite3.connect(str(db_path))
        # 创建不含新列的旧表
        conn.execute("""
            CREATE TABLE executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                output TEXT DEFAULT '',
                error TEXT DEFAULT '',
                files_changed TEXT DEFAULT '[]',
                tool_calls_summary TEXT DEFAULT '[]',
                tool_calls_count INTEGER DEFAULT 0,
                duration_seconds REAL DEFAULT 0.0,
                return_code INTEGER,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        # ExecutionHistory 初始化应自动迁移
        history = ExecutionHistory(db_path)
        result = _make_result(result_text="migrated result")
        history.record("migrated_task", "w0", result)

        rows = history.list_recent()
        assert rows[0]["result_text"] == "migrated result"
        assert rows[0]["tool_results_summary"] == []
