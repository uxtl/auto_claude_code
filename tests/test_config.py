"""测试 config.py — 纯函数 + 环境变量."""

from pathlib import Path

import pytest

from vibe.config import Config, _coerce, _parse_dotenv, load_config


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
        cfg = load_config(workspace=tmp_path)
        assert cfg.use_worktree is True
        assert cfg.plan_mode is False
        assert cfg.plan_auto_approve is True
