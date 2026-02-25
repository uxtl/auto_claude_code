"""SQLite 执行历史 — 持久化每次任务执行的结构化结果."""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .manager import TaskResult

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS executions (
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
    created_at TEXT NOT NULL,
    result_text TEXT DEFAULT '',
    tool_results_summary TEXT DEFAULT '[]'
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_executions_task_name ON executions (task_name)
"""

_MAX_OUTPUT_LEN = 50000


class ExecutionHistory:
    """管理 SQLite 执行历史数据库."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE)
        self._conn.execute(_CREATE_INDEX)
        self._conn.commit()
        self._migrate()
        logger.info("执行历史数据库已初始化: %s", self._db_path)

    def _migrate(self) -> None:
        """检测缺失列并自动迁移."""
        cursor = self._conn.execute("PRAGMA table_info(executions)")
        existing_cols = {row[1] for row in cursor.fetchall()}

        migrations = [
            ("result_text", "TEXT DEFAULT ''"),
            ("tool_results_summary", "TEXT DEFAULT '[]'"),
        ]
        for col_name, col_def in migrations:
            if col_name not in existing_cols:
                self._conn.execute(
                    f"ALTER TABLE executions ADD COLUMN {col_name} {col_def}"
                )
                logger.info("迁移: 添加列 %s", col_name)
        self._conn.commit()

    def record(self, task_name: str, worker_id: str, result: TaskResult) -> None:
        """记录一次任务执行结果."""
        tool_calls_summary = [
            {"name": tc.get("name", "?"), "target": _tool_target(tc)}
            for tc in result.tool_calls
        ]
        # 构建工具结果摘要
        tool_results_summary = []
        for tr in result.tool_results:
            content = tr.get("content", tr.get("output", ""))
            if isinstance(content, list):
                # stream-json 中 content 可能是 block 列表
                snippets = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        snippets.append(block.get("text", ""))
                content = "\n".join(snippets)
            snippet = str(content)[:200] if content else ""
            tool_results_summary.append({
                "tool_use_id": tr.get("tool_use_id", ""),
                "name": tr.get("name", ""),
                "is_error": bool(tr.get("is_error", False)),
                "snippet": snippet,
            })

        output = result.output[:_MAX_OUTPUT_LEN] if result.output else ""
        result_text = result.result_text[:_MAX_OUTPUT_LEN] if result.result_text else ""
        now = datetime.now(timezone.utc).isoformat()

        self._conn.execute(
            """INSERT INTO executions
               (task_name, worker_id, success, output, error,
                files_changed, tool_calls_summary, tool_calls_count,
                duration_seconds, return_code, created_at,
                result_text, tool_results_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_name,
                worker_id,
                result.success,
                output,
                result.error or "",
                json.dumps(result.files_changed),
                json.dumps(tool_calls_summary),
                len(result.tool_calls),
                result.duration_seconds,
                result.return_code,
                now,
                result_text,
                json.dumps(tool_results_summary),
            ),
        )
        self._conn.commit()
        logger.debug("记录执行历史: %s (success=%s)", task_name, result.success)

    def list_recent(self, limit: int = 50) -> list[dict]:
        """获取最近的执行记录."""
        cursor = self._conn.execute(
            "SELECT * FROM executions ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]

    def get_by_task(self, task_name: str) -> list[dict]:
        """获取某任务的所有执行记录."""
        cursor = self._conn.execute(
            "SELECT * FROM executions WHERE task_name = ? ORDER BY id DESC",
            (task_name,),
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]

    def get_by_id(self, execution_id: int) -> dict | None:
        """按 ID 获取单条执行记录."""
        cursor = self._conn.execute(
            "SELECT * FROM executions WHERE id = ?", (execution_id,)
        )
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None

    def close(self) -> None:
        """关闭数据库连接."""
        self._conn.close()


def _tool_target(tc: dict) -> str:
    """从工具调用中提取目标信息."""
    inp = tc.get("input", {})
    if not isinstance(inp, dict):
        return ""
    return inp.get("file_path", inp.get("command", inp.get("pattern", "")))[:120]


def _row_to_dict(row: sqlite3.Row) -> dict:
    """将 sqlite3.Row 转为 dict，解析 JSON 字段."""
    d = dict(row)
    for key in ("files_changed", "tool_calls_summary", "tool_results_summary"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                d[key] = []
    d["success"] = bool(d.get("success"))
    return d
