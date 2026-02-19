"""测试 manager.py — 纯函数 + subprocess mock."""

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from vibe.manager import (
    TaskResult, _parse_stream_json, _read_stream,
    execute_plan, generate_plan, run_plan, run_task,
)


# ── _parse_stream_json ───────────────────────────────────────

class TestParseStreamJson:
    def test_empty(self):
        result = _parse_stream_json([])
        assert result.success is True
        assert result.output == ""

    def test_text(self):
        event = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "hello world"}]
            },
        }
        result = _parse_stream_json([json.dumps(event)])
        assert "hello world" in result.output

    def test_tool_use(self):
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}}
                ]
            },
        }
        result = _parse_stream_json([json.dumps(event)])
        assert len(result.tool_calls) == 1

    def test_files_changed(self):
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Write",
                        "input": {"file_path": "/foo.py"},
                    }
                ]
            },
        }
        result = _parse_stream_json([json.dumps(event)])
        assert "/foo.py" in result.files_changed

    def test_non_json(self):
        result = _parse_stream_json(["not json at all"])
        assert "not json at all" in result.output

    def test_result_event(self):
        event = {"type": "result", "result": "final answer"}
        result = _parse_stream_json([json.dumps(event)])
        assert "final answer" in result.output


# ── _read_stream ─────────────────────────────────────────────

class TestReadStream:
    def test_basic(self):
        stream = io.BytesIO(b"line1\nline2\n")
        lines: list[str] = []
        _read_stream(stream, lines)
        assert lines == ["line1", "line2"]


# ── run_task ─────────────────────────────────────────────────

class TestRunTask:
    def test_not_found(self, tmp_path):
        with patch("vibe.manager.subprocess.Popen", side_effect=FileNotFoundError):
            result = run_task("hello", cwd=tmp_path)
        assert result.success is False
        assert "未找到" in result.error

    def test_timeout(self, tmp_path):
        import subprocess

        mock_proc = MagicMock()
        mock_proc.stdout = io.BytesIO(b"")
        mock_proc.stderr = io.BytesIO(b"")
        # First call (with timeout=) raises; second call (after kill) succeeds
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("claude", 10), None]
        mock_proc.kill.return_value = None

        with patch("vibe.manager.subprocess.Popen", return_value=mock_proc):
            result = run_task("hello", cwd=tmp_path, timeout=10)
        assert result.success is False
        assert "超时" in result.error

    def test_nonzero_exit(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = io.BytesIO(b"")
        mock_proc.stderr = io.BytesIO(b"error msg\n")
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1

        with patch("vibe.manager.subprocess.Popen", return_value=mock_proc):
            result = run_task("hello", cwd=tmp_path)
        assert result.success is False
        assert result.return_code == 1

    def test_success(self, tmp_path):
        event = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "done"}]},
        }
        stdout_bytes = json.dumps(event).encode() + b"\n"

        mock_proc = MagicMock()
        mock_proc.stdout = io.BytesIO(stdout_bytes)
        mock_proc.stderr = io.BytesIO(b"")
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("vibe.manager.subprocess.Popen", return_value=mock_proc):
            result = run_task("hello", cwd=tmp_path)
        assert result.success is True
        assert "done" in result.output


# ── run_plan ─────────────────────────────────────────────────

class TestRunPlan:
    def test_plan_failure(self, tmp_path):
        """第一步失败 → 不执行第二步."""
        mock_proc = MagicMock()
        mock_proc.stdout = io.BytesIO(b"")
        mock_proc.stderr = io.BytesIO(b"plan error\n")
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1

        with patch("vibe.manager.subprocess.Popen", return_value=mock_proc):
            result = run_plan("hello", cwd=tmp_path)
        assert result.success is False
        assert "计划生成失败" in result.error

    def test_success(self, tmp_path):
        """两步都成功 → 输出包含 [计划] 和 [执行结果]."""
        plan_event = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "my plan"}]},
        }
        exec_event = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "executed"}]},
        }

        call_count = 0

        def mock_popen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            proc = MagicMock()
            if call_count == 1:
                proc.stdout = io.BytesIO(json.dumps(plan_event).encode() + b"\n")
            else:
                proc.stdout = io.BytesIO(json.dumps(exec_event).encode() + b"\n")
            proc.stderr = io.BytesIO(b"")
            proc.wait.return_value = None
            proc.returncode = 0
            return proc

        with patch("vibe.manager.subprocess.Popen", side_effect=mock_popen):
            result = run_plan("hello", cwd=tmp_path)
        assert result.success is True
        assert "[计划]" in result.output
        assert "[执行结果]" in result.output


# ── generate_plan ────────────────────────────────────────────

class TestGeneratePlan:
    def test_success(self, tmp_path):
        plan_event = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "step 1\nstep 2"}]},
        }
        mock_proc = MagicMock()
        mock_proc.stdout = io.BytesIO(json.dumps(plan_event).encode() + b"\n")
        mock_proc.stderr = io.BytesIO(b"")
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("vibe.manager.subprocess.Popen", return_value=mock_proc):
            result = generate_plan("hello", cwd=tmp_path)
        assert result.success is True
        assert "step 1" in result.output

    def test_failure(self, tmp_path):
        mock_proc = MagicMock()
        mock_proc.stdout = io.BytesIO(b"")
        mock_proc.stderr = io.BytesIO(b"error\n")
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1

        with patch("vibe.manager.subprocess.Popen", return_value=mock_proc):
            result = generate_plan("hello", cwd=tmp_path)
        assert result.success is False
        assert "计划生成失败" in result.error


# ── execute_plan ─────────────────────────────────────────────

class TestExecutePlan:
    def test_success(self, tmp_path):
        exec_event = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "done executing"}]},
        }
        mock_proc = MagicMock()
        mock_proc.stdout = io.BytesIO(json.dumps(exec_event).encode() + b"\n")
        mock_proc.stderr = io.BytesIO(b"")
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("vibe.manager.subprocess.Popen", return_value=mock_proc):
            result = execute_plan("my plan text", cwd=tmp_path)
        assert result.success is True
        assert "[计划]" in result.output
        assert "my plan text" in result.output
        assert "[执行结果]" in result.output
