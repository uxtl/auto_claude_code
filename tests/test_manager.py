"""测试 manager.py — 纯函数 + subprocess mock."""

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibe.manager import (
    TaskResult, _build_docker_cmd, _parse_stream_json, _read_stream,
    check_docker_available, ensure_docker_image,
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


# ── _build_docker_cmd ────────────────────────────────────────

class TestBuildDockerCmd:
    def test_basic(self):
        claude_cmd = ["claude", "-p", "hello", "--output-format", "stream-json"]
        result = _build_docker_cmd(claude_cmd, Path("/my/project"), "my-image")
        assert result[:2] == ["docker", "run"]
        assert "--rm" in result
        assert "-i" in result
        assert "-v" in result
        # 找到 -v 后面的参数
        v_idx = result.index("-v")
        assert result[v_idx + 1] == "/my/project:/workspace"
        # -w /workspace
        w_idx = result.index("-w")
        assert result[w_idx + 1] == "/workspace"
        # -e ANTHROPIC_API_KEY
        e_idx = result.index("-e")
        assert result[e_idx + 1] == "ANTHROPIC_API_KEY"
        # 镜像名
        assert "my-image" in result
        # claude 命令在末尾
        assert result[-5:] == claude_cmd

    def test_extra_args(self):
        claude_cmd = ["claude", "-p", "hi"]
        result = _build_docker_cmd(
            claude_cmd, Path("/proj"), "img", "--network=none --memory=4g"
        )
        assert "--network=none" in result
        assert "--memory=4g" in result

    def test_no_extra_args(self):
        claude_cmd = ["claude", "-p", "hi"]
        result = _build_docker_cmd(claude_cmd, Path("/proj"), "img", "")
        # 不应有空字符串参数
        assert "" not in result


# ── check_docker_available ───────────────────────────────────

class TestCheckDockerAvailable:
    def test_available(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("vibe.manager.subprocess.run", return_value=mock_result):
            ok, msg = check_docker_available()
        assert ok is True

    def test_not_available(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = b"Cannot connect to Docker daemon"
        with patch("vibe.manager.subprocess.run", return_value=mock_result):
            ok, msg = check_docker_available()
        assert ok is False
        assert "不可用" in msg

    def test_not_installed(self):
        with patch("vibe.manager.subprocess.run", side_effect=FileNotFoundError):
            ok, msg = check_docker_available()
        assert ok is False
        assert "未找到" in msg

    def test_timeout(self):
        import subprocess
        with patch("vibe.manager.subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 10)):
            ok, msg = check_docker_available()
        assert ok is False
        assert "超时" in msg


# ── ensure_docker_image ──────────────────────────────────────

class TestEnsureDockerImage:
    def test_image_exists(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("vibe.manager.subprocess.run", return_value=mock_result):
            ok, msg = ensure_docker_image("my-image")
        assert ok is True
        assert "已存在" in msg

    def test_image_not_exists_no_dockerfile(self, tmp_path):
        inspect_result = MagicMock()
        inspect_result.returncode = 1
        with patch("vibe.manager.subprocess.run", return_value=inspect_result):
            ok, msg = ensure_docker_image("my-image", tmp_path)
        assert ok is False
        assert "Dockerfile" in msg

    def test_image_not_exists_build_success(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM ubuntu", encoding="utf-8")

        call_count = 0

        def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # docker image inspect → 不存在
                result.returncode = 1
            else:
                # docker build → 成功
                result.returncode = 0
            return result

        with patch("vibe.manager.subprocess.run", side_effect=mock_run):
            ok, msg = ensure_docker_image("my-image", tmp_path)
        assert ok is True
        assert "构建成功" in msg

    def test_image_not_exists_build_failure(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM ubuntu", encoding="utf-8")

        call_count = 0

        def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.returncode = 1
            else:
                result.returncode = 1
                result.stderr = b"build error"
            return result

        with patch("vibe.manager.subprocess.run", side_effect=mock_run):
            ok, msg = ensure_docker_image("my-image", tmp_path)
        assert ok is False
        assert "构建失败" in msg


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

    def test_docker_mode(self, tmp_path):
        """use_docker=True → Popen 收到 docker run 命令."""
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

        with patch("vibe.manager.subprocess.Popen", return_value=mock_proc) as mock_popen:
            result = run_task(
                "hello", cwd=tmp_path,
                use_docker=True, docker_image="test-img",
            )
        assert result.success is True
        # 验证传入 Popen 的命令以 docker run 开头
        actual_cmd = mock_popen.call_args[0][0]
        assert actual_cmd[0] == "docker"
        assert actual_cmd[1] == "run"
        assert "test-img" in actual_cmd
        # Docker 模式下 cwd 应为 None
        assert mock_popen.call_args[1]["cwd"] is None

    def test_docker_not_found(self, tmp_path):
        """Docker 模式下 docker 不存在 → 错误消息包含 docker."""
        with patch("vibe.manager.subprocess.Popen", side_effect=FileNotFoundError):
            result = run_task(
                "hello", cwd=tmp_path, use_docker=True,
            )
        assert result.success is False
        assert "docker" in result.error


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
