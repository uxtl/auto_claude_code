"""测试 config.py — 纯函数 + 环境变量."""

from pathlib import Path
from unittest.mock import patch

import pytest

from vibe.config import Config, _coerce, _parse_dotenv, load_config, log_active_config


# ── _parse_dotenv ────────────────────────────────────────────

class TestParseDotenv:
    def test_empty(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("", encoding="utf-8")
        assert _parse_dotenv(env_file) == {}

    def test_comments_blanks(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\n  # another\n", encoding="utf-8")
        assert _parse_dotenv(env_file) == {}

    def test_quoted(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            'VIBE_A="hello"\nVIBE_B=\'world\'\n',
            encoding="utf-8",
        )
        result = _parse_dotenv(env_file)
        assert result["VIBE_A"] == "hello"
        assert result["VIBE_B"] == "world"

    def test_missing_file(self, tmp_path: Path):
        assert _parse_dotenv(tmp_path / "nonexistent") == {}


# ── _coerce ──────────────────────────────────────────────────

class TestCoerce:
    def test_int(self):
        assert _coerce("42", int) == 42

    @pytest.mark.parametrize("val", ["1", "true", "yes"])
    def test_bool_truthy(self, val: str):
        assert _coerce(val, bool) is True

    @pytest.mark.parametrize("val", ["0", "false", "no"])
    def test_bool_falsy(self, val: str):
        assert _coerce(val, bool) is False

    def test_str(self):
        assert _coerce("hello", str) == "hello"


# ── load_config ──────────────────────────────────────────────

class TestLoadConfig:
    def test_defaults(self, tmp_path: Path):
        with patch("vibe.config.Path.cwd", return_value=tmp_path):
            cfg = load_config(workspace=tmp_path)
        assert cfg.task_dir == "tasks"
        assert cfg.timeout == 600
        assert cfg.max_retries == 2
        assert cfg.max_workers == 1
        assert cfg.log_level == "INFO"

    def test_dotenv(self, tmp_path: Path):
        (tmp_path / ".env").write_text(
            "VIBE_MAX_WORKERS=4\nVIBE_TIMEOUT=300\n", encoding="utf-8"
        )
        cfg = load_config(workspace=tmp_path)
        assert cfg.max_workers == 4
        assert cfg.timeout == 300

    def test_env_overrides(self, tmp_path: Path, monkeypatch):
        (tmp_path / ".env").write_text("VIBE_MAX_WORKERS=2\n", encoding="utf-8")
        monkeypatch.setenv("VIBE_MAX_WORKERS", "8")
        cfg = load_config(workspace=tmp_path)
        assert cfg.max_workers == 8

    def test_new_fields_defaults(self, tmp_path: Path):
        with patch("vibe.config.Path.cwd", return_value=tmp_path):
            cfg = load_config(workspace=tmp_path)
        assert cfg.use_worktree is True
        assert cfg.plan_mode is False
        assert cfg.plan_auto_approve is True

    def test_docker_defaults(self, tmp_path: Path):
        with patch("vibe.config.Path.cwd", return_value=tmp_path):
            cfg = load_config(workspace=tmp_path)
        assert cfg.use_docker is False
        assert cfg.docker_image == "auto-claude-code"
        assert cfg.docker_extra_args == ""

    def test_docker_env_override(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("VIBE_USE_DOCKER", "true")
        monkeypatch.setenv("VIBE_DOCKER_IMAGE", "my-image")
        monkeypatch.setenv("VIBE_DOCKER_EXTRA_ARGS", "--network=none --memory=4g")
        cfg = load_config(workspace=tmp_path)
        assert cfg.use_docker is True
        assert cfg.docker_image == "my-image"
        assert cfg.docker_extra_args == "--network=none --memory=4g"

    def test_docker_dotenv(self, tmp_path: Path):
        (tmp_path / ".env").write_text(
            "VIBE_USE_DOCKER=true\nVIBE_DOCKER_IMAGE=custom\n",
            encoding="utf-8",
        )
        cfg = load_config(workspace=tmp_path)
        assert cfg.use_docker is True
        assert cfg.docker_image == "custom"

    def test_poll_interval_default(self, tmp_path: Path):
        with patch("vibe.config.Path.cwd", return_value=tmp_path):
            cfg = load_config(workspace=tmp_path)
        assert cfg.poll_interval == 30

    def test_poll_interval_env_override(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("VIBE_POLL_INTERVAL", "10")
        cfg = load_config(workspace=tmp_path)
        assert cfg.poll_interval == 10

    def test_poll_interval_dotenv(self, tmp_path: Path):
        (tmp_path / ".env").write_text(
            "VIBE_POLL_INTERVAL=15\n", encoding="utf-8"
        )
        cfg = load_config(workspace=tmp_path)
        assert cfg.poll_interval == 15

    def test_verbose_default(self, tmp_path: Path):
        with patch("vibe.config.Path.cwd", return_value=tmp_path):
            cfg = load_config(workspace=tmp_path)
        assert cfg.verbose is False

    def test_verbose_env_override(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("VIBE_VERBOSE", "true")
        cfg = load_config(workspace=tmp_path)
        assert cfg.verbose is True

    def test_verbose_dotenv(self, tmp_path: Path):
        (tmp_path / ".env").write_text(
            "VIBE_VERBOSE=true\n", encoding="utf-8"
        )
        cfg = load_config(workspace=tmp_path)
        assert cfg.verbose is True


# ── 双路径 .env 加载 ────────────────────────────────────────

class TestDualDotenv:
    def test_dotenv_from_cwd(self, tmp_path: Path):
        """CWD 下的 .env 能正确加载."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        ws = tmp_path / "workspace"
        ws.mkdir()
        (cwd / ".env").write_text(
            "VIBE_PLAN_MODE=true\nVIBE_MAX_WORKERS=3\n", encoding="utf-8"
        )
        with patch("vibe.config.Path.cwd", return_value=cwd):
            cfg = load_config(workspace=ws)
        assert cfg.plan_mode is True
        assert cfg.max_workers == 3

    def test_dotenv_from_workspace(self, tmp_path: Path):
        """workspace 下的 .env 能正确加载."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".env").write_text(
            "VIBE_PLAN_MODE=true\nVIBE_MAX_WORKERS=5\n", encoding="utf-8"
        )
        with patch("vibe.config.Path.cwd", return_value=cwd):
            cfg = load_config(workspace=ws)
        assert cfg.plan_mode is True
        assert cfg.max_workers == 5

    def test_workspace_overrides_cwd(self, tmp_path: Path):
        """workspace 的 .env 覆盖 CWD 的 .env."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        ws = tmp_path / "workspace"
        ws.mkdir()
        (cwd / ".env").write_text(
            "VIBE_MAX_WORKERS=2\nVIBE_PLAN_MODE=true\n", encoding="utf-8"
        )
        (ws / ".env").write_text("VIBE_MAX_WORKERS=8\n", encoding="utf-8")

        with patch("vibe.config.Path.cwd", return_value=cwd):
            cfg = load_config(workspace=ws)
        # workspace 覆盖了 CWD 的 max_workers
        assert cfg.max_workers == 8
        # CWD 的 plan_mode 仍然生效（workspace 没有覆盖）
        assert cfg.plan_mode is True

    def test_env_var_overrides_dotenv(self, tmp_path: Path, monkeypatch):
        """环境变量优先于 .env."""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        ws = tmp_path / "workspace"
        ws.mkdir()
        (cwd / ".env").write_text("VIBE_MAX_WORKERS=3\n", encoding="utf-8")
        (ws / ".env").write_text("VIBE_MAX_WORKERS=5\n", encoding="utf-8")
        monkeypatch.setenv("VIBE_MAX_WORKERS", "7")

        with patch("vibe.config.Path.cwd", return_value=cwd):
            cfg = load_config(workspace=ws)
        assert cfg.max_workers == 7

    def test_same_cwd_and_workspace(self, tmp_path: Path):
        """workspace == CWD 时只加载一次 .env."""
        (tmp_path / ".env").write_text("VIBE_MAX_WORKERS=6\n", encoding="utf-8")
        with patch("vibe.config.Path.cwd", return_value=tmp_path):
            cfg = load_config(workspace=tmp_path)
        assert cfg.max_workers == 6

    def test_workspace_none_uses_cwd(self, tmp_path: Path):
        """workspace=None 时使用 CWD."""
        (tmp_path / ".env").write_text("VIBE_PLAN_MODE=true\n", encoding="utf-8")
        with patch("vibe.config.Path.cwd", return_value=tmp_path):
            cfg = load_config(None)
        assert cfg.plan_mode is True

    def test_dotenv_bare_keys(self, tmp_path: Path):
        """无前缀键能正确加载."""
        (tmp_path / ".env").write_text(
            "PLAN_MODE=true\nMAX_WORKERS=3\nUSE_DOCKER=true\n",
            encoding="utf-8",
        )
        with patch("vibe.config.Path.cwd", return_value=tmp_path):
            cfg = load_config(workspace=tmp_path)
        assert cfg.plan_mode is True
        assert cfg.max_workers == 3
        assert cfg.use_docker is True

    def test_dotenv_prefixed_overrides_bare(self, tmp_path: Path):
        """有前缀的键覆盖无前缀的."""
        (tmp_path / ".env").write_text(
            "MAX_WORKERS=3\nVIBE_MAX_WORKERS=5\n",
            encoding="utf-8",
        )
        with patch("vibe.config.Path.cwd", return_value=tmp_path):
            cfg = load_config(workspace=tmp_path)
        assert cfg.max_workers == 5

    def test_dotenv_bare_and_prefixed_mixed(self, tmp_path: Path):
        """混合前缀/无前缀键的 .env 文件能正确加载."""
        (tmp_path / ".env").write_text(
            "VIBE_TIMEOUT=1800\nUSE_DOCKER=true\nPLAN_MODE=true\n"
            "PLAN_AUTO_APPROVE=false\nMAX_WORKERS=3\n",
            encoding="utf-8",
        )
        with patch("vibe.config.Path.cwd", return_value=tmp_path):
            cfg = load_config(workspace=tmp_path)
        assert cfg.timeout == 1800
        assert cfg.use_docker is True
        assert cfg.plan_mode is True
        assert cfg.plan_auto_approve is False
        assert cfg.max_workers == 3

    def test_env_var_overrides_bare_dotenv(self, tmp_path: Path, monkeypatch):
        """环境变量（VIBE_ 前缀）覆盖 .env 中的无前缀键."""
        (tmp_path / ".env").write_text("MAX_WORKERS=3\n", encoding="utf-8")
        monkeypatch.setenv("VIBE_MAX_WORKERS", "7")
        with patch("vibe.config.Path.cwd", return_value=tmp_path):
            cfg = load_config(workspace=tmp_path)
        assert cfg.max_workers == 7


# ── log_active_config ───────────────────────────────────────

class TestLogActiveConfig:
    def test_log_output(self, tmp_path: Path, caplog):
        """log_active_config 输出关键配置值."""
        import logging
        cfg = Config()
        cfg.workspace = str(tmp_path)
        cfg.max_workers = 3
        cfg.plan_mode = True
        with caplog.at_level(logging.INFO, logger="vibe.config"):
            log_active_config(cfg)
        assert "活跃配置" in caplog.text
        assert "max_workers=3" in caplog.text
        assert "plan_mode=True" in caplog.text
