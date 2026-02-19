"""集中配置 — 从默认值 / .env / 环境变量加载."""

import os
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass
class Config:
    """Vibe 全局配置.

    加载优先级: 默认值 < .env 文件 < 环境变量
    环境变量前缀: VIBE_（如 VIBE_MAX_WORKERS=4）
    """

    task_dir: str = "tasks"
    done_dir: str = "tasks/done"
    fail_dir: str = "tasks/failed"
    timeout: int = 600
    max_retries: int = 2
    max_workers: int = 1
    workspace: str = "."
    log_level: str = "INFO"
    log_file: str = ""
    use_worktree: bool = True
    plan_mode: bool = False
    plan_auto_approve: bool = True


_ENV_PREFIX = "VIBE_"


def _parse_dotenv(path: Path) -> dict[str, str]:
    """解析 .env 文件，返回键值对.

    支持格式:
      KEY=value
      KEY="value"
      KEY='value'
      # 注释行
      空行
    """
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # 去掉引号
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result[key] = value
    return result


def _coerce(value: str, target_type: type) -> object:
    """将字符串值转换为目标类型."""
    if target_type is int:
        return int(value)
    if target_type is bool:
        return value.lower() in ("1", "true", "yes")
    return value


def load_config(workspace: Path | None = None) -> Config:
    """加载配置: 默认值 → .env → 环境变量.

    Args:
        workspace: 工作目录，用于查找 .env 文件
    """
    config = Config()

    # 1. 从 .env 文件加载
    if workspace is None:
        workspace = Path.cwd()
    dotenv = _parse_dotenv(workspace / ".env")

    # 2. 合并 .env 和环境变量（环境变量优先）
    for f in fields(Config):
        env_key = _ENV_PREFIX + f.name.upper()
        # 尝试从 .env 获取
        raw = dotenv.get(env_key)
        # 环境变量覆盖
        raw = os.environ.get(env_key, raw)
        if raw is not None:
            setattr(config, f.name, _coerce(raw, f.type))

    return config
