"""Allow `python -m vibe` to run the task loop."""

import argparse
import logging
import sys
from pathlib import Path

from .config import load_config
from .loop import run_loop
from .task import TaskQueue


def _setup_logging(config) -> None:
    """配置日志."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if config.log_file:
        handlers.append(logging.FileHandler(config.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def cmd_run(args: argparse.Namespace) -> None:
    """执行任务队列."""
    config = load_config(Path(args.workspace) if args.workspace else None)
    if args.workspace:
        config.workspace = args.workspace
    if args.workers is not None:
        config.max_workers = args.workers
    if args.no_worktree:
        config.use_worktree = False
    if args.plan_mode:
        config.plan_mode = True
    if args.docker:
        config.use_docker = True
    if args.docker_image:
        config.docker_image = args.docker_image
    if config.plan_mode and not config.plan_auto_approve:
        print(
            "WARNING: plan_auto_approve=False 在 CLI 模式下无法审批（无 Web 服务器），"
            "已自动覆盖为 plan_auto_approve=True"
        )
        config.plan_auto_approve = True
    _setup_logging(config)
    run_loop(config)


def cmd_serve(args: argparse.Namespace) -> None:
    """启动 Web 管理界面 + 后台任务循环."""
    config = load_config(Path(args.workspace) if args.workspace else None)
    if args.workspace:
        config.workspace = args.workspace
    if args.workers is not None:
        config.max_workers = args.workers
    if args.docker:
        config.use_docker = True
    if args.docker_image:
        config.docker_image = args.docker_image
    _setup_logging(config)

    from .server import start_server
    start_server(config, host=args.host, port=args.port)


def cmd_list(args: argparse.Namespace) -> None:
    """列出任务状态."""
    config = load_config(Path(args.workspace) if args.workspace else None)
    if args.workspace:
        config.workspace = args.workspace
    workspace = Path(config.workspace).resolve()
    task_dir = workspace / config.task_dir
    done_dir = workspace / config.done_dir
    fail_dir = workspace / config.fail_dir

    print("=== 待执行 (pending) ===")
    pending = sorted(task_dir.glob("*.md"))
    for f in pending:
        print(f"  {f.name}")
    if not pending:
        print("  (无)")

    print("\n=== 执行中 (running) ===")
    running = sorted(task_dir.glob("*.md.running.*"))
    for f in running:
        print(f"  {f.name}")
    if not running:
        print("  (无)")

    print("\n=== 已完成 (done) ===")
    done = sorted(done_dir.glob("*.md")) if done_dir.is_dir() else []
    for f in done:
        print(f"  {f.name}")
    if not done:
        print("  (无)")

    print("\n=== 已失败 (failed) ===")
    failed = sorted(fail_dir.glob("*.md")) if fail_dir.is_dir() else []
    for f in failed:
        print(f"  {f.name}")
    if not failed:
        print("  (无)")


def cmd_add(args: argparse.Namespace) -> None:
    """快速添加任务."""
    config = load_config(Path(args.workspace) if args.workspace else None)
    if args.workspace:
        config.workspace = args.workspace
    workspace = Path(config.workspace).resolve()
    task_dir = workspace / config.task_dir
    task_dir.mkdir(parents=True, exist_ok=True)

    # 自动编号
    existing = sorted(task_dir.glob("*.md"))
    if existing:
        # 提取最大编号
        max_num = 0
        for f in existing:
            parts = f.stem.split("_", 1)
            try:
                max_num = max(max_num, int(parts[0]))
            except ValueError:
                pass
        next_num = max_num + 1
    else:
        next_num = 1

    # 生成文件名
    slug = args.description[:30].replace(" ", "_").replace("/", "_")
    filename = f"{next_num:03d}_{slug}.md"
    task_file = task_dir / filename
    task_file.write_text(args.description + "\n", encoding="utf-8")
    print(f"已添加任务: {filename}")


def cmd_retry(args: argparse.Namespace) -> None:
    """重试失败任务 — 清除错误注释，移回任务队列."""
    config = load_config(Path(args.workspace) if args.workspace else None)
    if args.workspace:
        config.workspace = args.workspace
    workspace = Path(config.workspace).resolve()
    task_dir = workspace / config.task_dir
    fail_dir = workspace / config.fail_dir

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    retried = TaskQueue.retry_failed(task_dir, fail_dir, name=args.name)
    if retried:
        for name in retried:
            print(f"  已重试: {name}")
        print(f"共重试 {len(retried)} 个任务")
    else:
        print("没有需要重试的失败任务")


def cmd_recover(args: argparse.Namespace) -> None:
    """恢复 .running 文件."""
    config = load_config(Path(args.workspace) if args.workspace else None)
    if args.workspace:
        config.workspace = args.workspace
    workspace = Path(config.workspace).resolve()
    task_dir = workspace / config.task_dir

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    count = TaskQueue.recover_running(task_dir)
    if count:
        print(f"已恢复 {count} 个任务")
    else:
        print("没有需要恢复的任务")


def main() -> None:
    """CLI 入口."""
    parser = argparse.ArgumentParser(
        prog="vibe",
        description="Claude Code Vibe Coding 脚手架 — 并行任务执行",
    )
    subparsers = parser.add_subparsers(dest="command")

    # run
    p_run = subparsers.add_parser("run", help="执行任务队列")
    p_run.add_argument("--workspace", "-w", help="工作目录（目标项目）")
    p_run.add_argument("--workers", "-n", type=int, help="并行 worker 数量")
    p_run.add_argument("--no-worktree", action="store_true", help="禁用 git worktree 隔离")
    p_run.add_argument("--plan-mode", action="store_true", help="启用 Plan 模式（先生成计划再执行）")
    p_run.add_argument("--docker", action="store_true", help="启用 Docker 隔离模式")
    p_run.add_argument("--docker-image", default=None, help="Docker 镜像名（默认 auto-claude-code）")
    p_run.set_defaults(func=cmd_run)

    # serve
    p_serve = subparsers.add_parser("serve", help="启动 Web 管理界面")
    p_serve.add_argument("--workspace", "-w", help="工作目录（目标项目）")
    p_serve.add_argument("--workers", "-n", type=int, help="并行 worker 数量")
    p_serve.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    p_serve.add_argument("--port", type=int, default=8080, help="监听端口（默认 8080）")
    p_serve.add_argument("--docker", action="store_true", help="启用 Docker 隔离模式")
    p_serve.add_argument("--docker-image", default=None, help="Docker 镜像名（默认 auto-claude-code）")
    p_serve.set_defaults(func=cmd_serve)

    # list
    p_list = subparsers.add_parser("list", help="列出任务状态")
    p_list.add_argument("--workspace", "-w", help="工作目录")
    p_list.set_defaults(func=cmd_list)

    # add
    p_add = subparsers.add_parser("add", help="快速添加任务")
    p_add.add_argument("description", help="任务描述")
    p_add.add_argument("--workspace", "-w", help="工作目录")
    p_add.set_defaults(func=cmd_add)

    # recover
    p_recover = subparsers.add_parser("recover", help="恢复 .running 任务文件")
    p_recover.add_argument("--workspace", "-w", help="工作目录")
    p_recover.set_defaults(func=cmd_recover)

    # retry
    p_retry = subparsers.add_parser("retry", help="重试失败任务")
    p_retry.add_argument("name", nargs="?", default=None, help="任务名（可选，为空则重试所有）")
    p_retry.add_argument("--workspace", "-w", help="工作目录")
    p_retry.set_defaults(func=cmd_retry)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
