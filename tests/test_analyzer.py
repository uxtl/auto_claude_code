"""测试 analyzer.py — 执行诊断分析."""

from vibe.analyzer import MAX_DIAGNOSTICS_LEN, analyze_execution
from vibe.manager import TaskResult


class TestAnalyzeExecution:
    def test_success_returns_empty(self):
        """成功的 result 不生成诊断."""
        result = TaskResult(
            success=True,
            tool_calls=[{"name": "Read", "id": "1", "input": {"file_path": "/a.py"}}],
            tool_results=[{"tool_use_id": "1", "content": "ok"}],
        )
        assert analyze_execution(result) == ""

    def test_no_tool_calls_returns_empty(self):
        """无结构化数据不生成诊断."""
        result = TaskResult(success=False, error="退出码 1: error")
        assert analyze_execution(result) == ""

    def test_basic_failure_diagnosis(self):
        """基本失败诊断包含关键信息."""
        result = TaskResult(
            success=False,
            error="退出码 1: error",
            return_code=1,
            duration_seconds=45.2,
            tool_calls=[
                {"name": "Bash", "id": "tc1", "input": {"command": "uv run pytest tests/ -v"}},
            ],
            tool_results=[
                {"tool_use_id": "tc1", "is_error": True, "content": "FAILED tests/test_foo.py::test_bar"},
            ],
            files_changed=["/a.py"],
        )
        diag = analyze_execution(result)
        assert "执行诊断" in diag
        assert "45.2s" in diag
        assert "退出码 1" in diag
        assert "1 次失败" in diag
        assert "Bash" in diag

    def test_correlate_calls_and_results(self):
        """通过 ID 正确关联 tool_calls 和 tool_results."""
        result = TaskResult(
            success=False,
            error="error",
            return_code=1,
            duration_seconds=10.0,
            tool_calls=[
                {"name": "Read", "id": "tc1", "input": {"file_path": "/a.py"}},
                {"name": "Edit", "id": "tc2", "input": {"file_path": "/b.py"}},
            ],
            tool_results=[
                {"tool_use_id": "tc1", "content": "file content"},
                {"tool_use_id": "tc2", "is_error": True, "content": "No match found for old_string"},
            ],
        )
        diag = analyze_execution(result)
        assert "1 次失败" in diag
        assert "Edit" in diag
        assert "/b.py" in diag

    def test_detect_repeated_failures(self):
        """检测同一目标重复失败."""
        result = TaskResult(
            success=False,
            error="error",
            return_code=1,
            duration_seconds=30.0,
            tool_calls=[
                {"name": "Edit", "id": "tc1", "input": {"file_path": "/x.py"}},
                {"name": "Edit", "id": "tc2", "input": {"file_path": "/x.py"}},
                {"name": "Edit", "id": "tc3", "input": {"file_path": "/x.py"}},
            ],
            tool_results=[
                {"tool_use_id": "tc1", "is_error": True, "content": "no match"},
                {"tool_use_id": "tc2", "is_error": True, "content": "no match"},
                {"tool_use_id": "tc3", "is_error": True, "content": "no match"},
            ],
        )
        diag = analyze_execution(result)
        assert "重复失败" in diag
        assert "/x.py" in diag

    def test_detect_test_failure(self):
        """检测 pytest 失败."""
        result = TaskResult(
            success=False,
            error="error",
            return_code=1,
            duration_seconds=60.0,
            tool_calls=[
                {"name": "Bash", "id": "tc1", "input": {"command": "uv run pytest tests/ -v"}},
            ],
            tool_results=[
                {
                    "tool_use_id": "tc1",
                    "is_error": True,
                    "content": "FAILED tests/test_foo.py::test_bar - AssertionError\nFAILED tests/test_baz.py::test_qux",
                },
            ],
        )
        diag = analyze_execution(result)
        assert "测试失败" in diag
        assert "test_foo.py::test_bar" in diag
        assert "test_baz.py::test_qux" in diag
        assert "2 个测试失败" in diag

    def test_detect_high_error_rate(self):
        """高失败率检测 (>50%)."""
        result = TaskResult(
            success=False,
            error="error",
            return_code=1,
            duration_seconds=20.0,
            tool_calls=[
                {"name": "Bash", "id": "tc1", "input": {"command": "cmd1"}},
                {"name": "Bash", "id": "tc2", "input": {"command": "cmd2"}},
                {"name": "Bash", "id": "tc3", "input": {"command": "cmd3"}},
            ],
            tool_results=[
                {"tool_use_id": "tc1", "is_error": True, "content": "error"},
                {"tool_use_id": "tc2", "is_error": True, "content": "error"},
                {"tool_use_id": "tc3", "content": "ok"},
            ],
        )
        diag = analyze_execution(result)
        assert "高失败率" in diag
        assert "66%" in diag

    def test_truncation(self):
        """超长诊断被截断到 MAX_DIAGNOSTICS_LEN."""
        # 创建很多失败的工具调用来产生长诊断
        tool_calls = []
        tool_results = []
        for i in range(200):
            tc_id = f"tc{i}"
            tool_calls.append({
                "name": "Edit",
                "id": tc_id,
                "input": {"file_path": f"/very/long/path/to/deeply/nested/directory/file_{i:04d}.py"},
            })
            tool_results.append({
                "tool_use_id": tc_id,
                "is_error": True,
                "content": f"No match found for old_string in file_{i:04d}.py " * 10,
            })

        result = TaskResult(
            success=False,
            error="error",
            return_code=1,
            duration_seconds=100.0,
            tool_calls=tool_calls,
            tool_results=tool_results,
        )
        diag = analyze_execution(result)
        assert len(diag) <= MAX_DIAGNOSTICS_LEN
        assert diag.endswith("...")

    def test_bash_failure_detail(self):
        """Bash 失败包含命令和错误输出."""
        result = TaskResult(
            success=False,
            error="error",
            return_code=1,
            duration_seconds=5.0,
            tool_calls=[
                {"name": "Bash", "id": "tc1", "input": {"command": "uv run pytest tests/ -v"}},
            ],
            tool_results=[
                {
                    "tool_use_id": "tc1",
                    "is_error": True,
                    "content": "exit code 1\nFAILED tests/test_foo.py::test_bar",
                },
            ],
        )
        diag = analyze_execution(result)
        assert "Bash" in diag
        assert "uv run pytest" in diag

    def test_tool_use_id_key_variant(self):
        """tool_result 使用 'id' 代替 'tool_use_id' 也能匹配."""
        result = TaskResult(
            success=False,
            error="error",
            return_code=1,
            duration_seconds=5.0,
            tool_calls=[
                {"name": "Bash", "tool_use_id": "tc1", "input": {"command": "ls"}},
            ],
            tool_results=[
                {"id": "tc1", "is_error": True, "content": "permission denied"},
            ],
        )
        diag = analyze_execution(result)
        assert "1 次失败" in diag

    def test_last_operation_shown(self):
        """诊断包含最后操作信息."""
        result = TaskResult(
            success=False,
            error="error",
            return_code=1,
            duration_seconds=10.0,
            tool_calls=[
                {"name": "Read", "id": "tc1", "input": {"file_path": "/a.py"}},
                {"name": "Bash", "id": "tc2", "input": {"command": "uv run pytest"}},
            ],
            tool_results=[
                {"tool_use_id": "tc1", "content": "file content"},
                {"tool_use_id": "tc2", "is_error": True, "content": "error"},
            ],
        )
        diag = analyze_execution(result)
        assert "最后操作" in diag
        assert "Bash" in diag

    def test_content_as_list(self):
        """tool_result content 为列表时正确提取."""
        result = TaskResult(
            success=False,
            error="error",
            return_code=1,
            duration_seconds=5.0,
            tool_calls=[
                {"name": "Bash", "id": "tc1", "input": {"command": "test"}},
            ],
            tool_results=[
                {
                    "tool_use_id": "tc1",
                    "is_error": True,
                    "content": [{"type": "text", "text": "FAILED tests/test_x.py::test_y"}],
                },
            ],
        )
        diag = analyze_execution(result)
        assert "test_x.py::test_y" in diag
