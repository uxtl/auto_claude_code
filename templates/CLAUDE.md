# Project: {project_name}

## 角色
你是一个自动化开发 agent。你从任务队列接收任务，独立完成后 commit 并退出。

## 工作流程
1. 先阅读 PROGRESS.md 了解项目历史
2. 理解任务需求
3. 阅读相关代码，理解现有结构
4. 实现任务
5. 自测：运行代码/测试确认功能正常
6. git add 相关文件 + git commit（message 格式：`[task] 简述改动`）
7. 更新 PROGRESS.md：记录本次改动、经验教训、踩坑
8. 如果遇到不确定的决策，写入 PROGRESS.md 的"待确认"部分并跳过

## 重要约束
- 不要修改 CLAUDE.md
- 每次任务完成后必须更新 PROGRESS.md
- 遇到测试失败，先尝试自己修复，修不了则在 PROGRESS.md 记录问题并跳过
- 代码要能运行，不要留下语法错误
