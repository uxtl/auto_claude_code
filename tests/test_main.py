"""测试 __main__.py — CLI argparse 和子命令调度."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vibe.__main__ import main


class TestCLIRun:
    @patch("vibe.__main__.run_loop")
    @patch("vibe.__main__.load_config")
    def test_run_basic(self, mock_load, mock_loop, workspace: Path):
        cfg = MagicMock()
        cfg.workspace = str(workspace)
        cfg.log_level = "INFO"
        cfg.log_file = ""
        cfg.plan_mode = False
        cfg.plan_auto_approve = True
        mock_load.return_value = cfg

        with patch("sys.argv", ["vibe", "run"]):
            main()
        mock_loop.assert_called_once()

    @patch("vibe.__main__.run_loop")
    @patch("vibe.__main__.load_config")
    def test_run_with_workers(self, mock_load, mock_loop, workspace: Path):
        cfg = MagicMock()
        cfg.workspace = str(workspace)
        cfg.log_level = "INFO"
        cfg.log_file = ""
        cfg.plan_mode = False
        cfg.plan_auto_approve = True
        mock_load.return_value = cfg

        with patch("sys.argv", ["vibe", "run", "-n", "4"]):
            main()
        assert cfg.max_workers == 4

    @patch("vibe.__main__.run_loop")
    @patch("vibe.__main__.load_config")
    def test_run_plan_mode_auto_approve_override(self, mock_load, mock_loop, workspace: Path):
        cfg = MagicMock()
        cfg.workspace = str(workspace)
        cfg.log_level = "INFO"
        cfg.log_file = ""
        cfg.plan_mode = False
        cfg.plan_auto_approve = False
        mock_load.return_value = cfg

        with patch("sys.argv", ["vibe", "run", "--plan-mode"]):
            main()
        # plan_auto_approve should be overridden to True in CLI mode
        assert cfg.plan_auto_approve is True


    @patch("vibe.__main__.run_loop")
    @patch("vibe.__main__.load_config")
    def test_run_verbose(self, mock_load, mock_loop, workspace: Path):
        cfg = MagicMock()
        cfg.workspace = str(workspace)
        cfg.log_level = "INFO"
        cfg.log_file = ""
        cfg.plan_mode = False
        cfg.plan_auto_approve = True
        mock_load.return_value = cfg

        with patch("sys.argv", ["vibe", "run", "--verbose"]):
            main()
        assert cfg.verbose is True


class TestCLIList:
    def test_list(self, workspace: Path, capsys):
        (workspace / "tasks" / "001_todo.md").write_text("task", encoding="utf-8")

        with patch("sys.argv", ["vibe", "list", "-w", str(workspace)]):
            main()
        out = capsys.readouterr().out
        assert "pending" in out.lower() or "001_todo" in out


class TestCLIAdd:
    def test_add(self, workspace: Path, capsys):
        with patch("sys.argv", ["vibe", "add", "new task", "-w", str(workspace)]):
            main()
        out = capsys.readouterr().out
        assert "001_" in out
        md_files = list((workspace / "tasks").glob("*.md"))
        assert len(md_files) == 1


class TestCLIRecover:
    def test_recover_none(self, workspace: Path, capsys):
        with patch("sys.argv", ["vibe", "recover", "-w", str(workspace)]):
            main()
        out = capsys.readouterr().out
        assert "没有" in out or "0" in out


class TestCLINoCommand:
    def test_no_command_exits(self):
        with patch("sys.argv", ["vibe"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
