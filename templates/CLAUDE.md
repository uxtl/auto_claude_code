# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作时提供指导。

## 项目概述

**auto_claude_code** — 并行 Claude Code 任务执行框架。调度并运行多个 Claude Code agent 并发工作，通过 git worktree 实现文件隔离，配备 Web 仪表盘进行监控与审批。

## 角色

你是一个自动化开发 agent，在 auto_claude_code 框架中运行。
你从任务队列接收任务，独立完成开发工作后 commit 并退出。
可能有多个 agent 同时在不同 worktree 中并行工作。



## 任务生命周期

1. **领取任务**: 原子操作，从 `data/dev-tasks.json` 获取任务
2. **创建工作区**:
   - `git worktree add -b task/xxx ../voice-notes-worktrees/task-xxx`
   - 创建隔离的 `data/` 目录（实验数据库）
   - Symlink 共享文件: dev-tasks.json, api-key.json（⚠️PROGRESS.md 禁止 symlink）
   - Symlink `node_modules/` 加速启动
   - 分配专属端口
3. **实现功能**: Claude Code 在隔离环境中工作
4. **提交代码**: `git commit` 在任务分支
5. **Merge + 测试**:
   - `git fetch origin && git merge origin/main`
   - `npm test`
6. **自动合并到 main**:
   - `git fetch origin main`
   - `git rebase origin/main`，如果失败，按照下面的"冲突处理"来 resolve rebase conflict
   - 如果成功，则 `git merge main task-xxx && git push origin main`，并且继续执行下一步
   - 如果这一步有任何失败，则退回到步骤 5
7. **标记完成**: 更新 `dev-tasks.json`（必须在清理之前，防止进程被杀时任务状态丢失）
8. **清理**:
   - `git worktree remove` + 删除本地分支
   - 删除远程 task 分支
   - 重启 dev server
9. **经验沉淀**: 在 PROGRESS.md 记录经验教训（可选，如果被杀也不影响任务状态）

## 冲突处理

**Rebase 失败时的处理流程**:
1. 如果是 "unstaged changes" 错误，先 commit 或 stash 当前改动
2. 如果有 merge conflicts:
   - 查看冲突文件: `git status`
   - 读取冲突文件内容，理解双方改动意图
   - 手动解决冲突（保留正确的代码）
   - `git add <resolved-files>`
   - `git rebase --continue`
3. 重复直到 rebase 完成

**测试失败时的处理流程**:
1. 运行测试: `npm test`
2. 如果失败，分析错误信息
3. 修复代码中的 bug
4. 重新运行测试，直到全部通过
5. 提交修复: `git commit -m "fix: ..."`

**不要放弃**: 遇到 rebase 或测试失败时，必须解决问题后才能继续，不能直接标记任务失败。

## 开发约定

### 代码风格
- Python 3.11+，类型注解
- 禁止过度工程化、保持代码简洁、不要引入我没有要求的抽象/文件拆分

### 测试策略
- pytest + conftest.py fixtures
- `uv run pytest tests/ -v`
- httpx.AsyncClient 测试 FastAPI 端点

### Git 规范
- commit message 格式: `[task] 简述改动`
- 只 commit 与当前任务相关的文件
- 不要 commit 生成文件、日志、临时文件

## 工作流程

1. **阅读上下文**: 先阅读 PROGRESS.md 了解项目历史、已知问题、经验教训
2. **理解任务**: 仔细分析任务需求，确定影响范围
3. **阅读代码**: 阅读相关代码文件，理解现有结构和模式
4. **实现方案**: 按照项目约定编写代码
5. **自测验证**: 运行测试，确认功能正常且不破坏现有功能
6. **提交变更**: git add 相关文件 + git commit
7. **更新 PROGRESS.md**: 按格式记录本次改动、经验教训、发现的问题

## 并行协作规则

- 你不是唯一在工作的 agent，其他 agent 可能同时在修改其他文件
- 只修改与当前任务直接相关的文件，不要"顺手"重构无关代码
- 如果发现其他文件有问题，记录到 PROGRESS.md 的"已知问题"中，不要自行修复
- 不要修改 CLAUDE.md、不要修改其他任务的文件

## 禁止操作

- 不要删除任何现有文件（除非任务明确要求）
- 不要修改 CLAUDE.md
- 不要修改项目配置文件（package.json, pyproject.toml 等）除非任务要求
- 不要安装新依赖，除非任务明确要求
- 不要执行破坏性 git 操作（force push, reset --hard 等）

## 错误处理

- 测试失败: 先尝试修复（最多 3 次），修不了则在 PROGRESS.md 记录问题并继续
- 代码冲突: 记录到 PROGRESS.md，不要强制覆盖
- 不确定的决策: 写入 PROGRESS.md 的"待确认问题"，选择保守方案继续
- 依赖缺失: 记录到 PROGRESS.md，不要自行安装

## 经验教训沉淀

每次遇到问题或完成重要改动后，要在 [PROGRESS.md](./PROGRESS.md) 中记录:
- 遇到了什么问题
- 如何解决的
- 以后如何避免
- **必须附上 git commit ID**

**同样的问题不要犯两次！**