"""集中配置 — 从默认值 / .env / 环境变量加载."""

import logging
import os
from dataclasses import dataclass, fields
from pathlib import Path

logger = logging.getLogger(__name__)


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
    use_docker: bool = False
    docker_image: str = "auto-claude-code"
    docker_extra_args: str = ""
    poll_interval: int = 30
    verbose: bool = False


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


def _coerce(value: str, target_type: type, field_name: str = "") -> object | None:
    """将字符串值转换为目标类型. 转换失败返回 None."""
    if target_type is int:
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning("配置项 %s 值 %r 无法转为 int，保留默认值", field_name, value)
            return None
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
            coerced = _coerce(raw, f.type, f.name)
            if coerced is not None:
                setattr(config, f.name, coerced)

    # 范围校验
    if config.timeout <= 0:
        logger.warning("timeout=%d 无效，重置为 600", config.timeout)
        config.timeout = 600
    if config.max_retries < 0:
        logger.warning("max_retries=%d 无效，重置为 2", config.max_retries)
        config.max_retries = 2
    if config.max_workers < 1:
        logger.warning("max_workers=%d 无效，重置为 1", config.max_workers)
        config.max_workers = 1

    return config
