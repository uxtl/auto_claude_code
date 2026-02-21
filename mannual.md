以后在普通终端中：
cd /mnt/d/python_project/auto_claude_code

# 1. 添加任务
uv run python -m vibe add "你的任务描述" -w /path/to/your/project

# 2. 执行（单 worker）
uv run python -m vibe run -w /path/to/your/project

# 3. 或者并行执行 + Web 仪表盘
uv run python -m vibe serve -w /path/to/your/project -n 3 --port 8080



# 必须有这些
npm install -g @anthropic-ai/claude-code   # Claude Code CLI
export ANTHROPIC_API_KEY=sk-ant-...         # API Key
git --version                               # Git（worktree 隔离需要）

# 如果要 Docker 隔离，还需要
docker info                                 # Docker 守护进程运行中

Step 1：安装本工具

git clone <repo-url> auto_claude_code
cd auto_claude_code
uv sync

Step 2：初始化你的目标项目

假设你的项目在 /path/to/myproject：

bash scripts/init.sh /path/to/myproject

这会往你的项目里注入 3 样东西：

┌──────────────────────┬────────────────────────────────────────────────┐
│         文件         │                      作用                      │
├──────────────────────┼────────────────────────────────────────────────┤
│ CLAUDE.md            │ agent 行为规范（记得改里面的 {project_name}）  │
├──────────────────────┼────────────────────────────────────────────────┤
│ PROGRESS.md          │ agent 间共享的经验日志，每个任务做完会自动更新 │
├──────────────────────┼────────────────────────────────────────────────┤
│ tasks/ + tasks/done/ │ 任务队列目录                                   │
└──────────────────────┴────────────────────────────────────────────────┘

Step 3：写任务

每个 .md 文件就是一个任务，放进 tasks/ 目录：

# 手动创建
echo "实现用户登录 API，使用 JWT 认证" > /path/to/myproject/tasks/001_login.md
echo "给 User 模型添加单元测试" > /path/to/myproject/tasks/002_user_test.md

# 或者用 CLI
uv run python -m vibe add "实现用户登录 API" -w /path/to/myproject

Step 4：配置 .env（在目标项目根目录）

根据你的需求选一种：

最简单（不隔离，直接跑）：
# /path/to/myproject/.env
VIBE_MAX_WORKERS=1
VIBE_TIMEOUT=600

推荐生产用法（Docker 隔离 + Plan 审批）：
# /path/to/myproject/.env
VIBE_MAX_WORKERS=2
VIBE_TIMEOUT=900
VIBE_USE_DOCKER=true
VIBE_DOCKER_IMAGE=auto-claude-code
VIBE_DOCKER_EXTRA_ARGS=--memory=4g --user 1000:1000
VIBE_PLAN_MODE=true
VIBE_PLAN_AUTO_APPROVE=false

用 Docker 的话，首次需要构建镜像：

cd auto_claude_code
docker build -t auto-claude-code .

（之后框架启动时会自动检测，镜像不存在也会自动构建）

Step 5：跑起来

两种方式：

方式 A — CLI 直接跑（适合 CI/脚本/快速测试）：

uv run python -m vibe run -w /path/to/myproject
# 加 Docker 隔离
uv run python -m vibe run -w ../smart_sensor --docker
# 加 Plan 模式（CLI 下只能自动审批）
uv run python -m vibe run -w /path/to/myproject --docker --plan-mode

跑完所有任务自动退出。完成的任务移到 tasks/done/，失败的移到 tasks/failed/。

方式 B — Web 仪表盘（推荐，可审批 + 实时监控）：

uv run python -m vibe serve -w ../smart_sensor/ --port 8080 --docker

打开 http://localhost:8080，你能：
- 看到所有任务状态（pending/running/done/failed）
- 实时看日志流
- 动态添加/删除任务
- Plan Mode 下审批执行计划（Approve / Reject）

serve 模式同时在后台跑任务，不用另开 run。

---
总结一句话：init.sh 注入模板 → 往 tasks/ 丢 .md 文件 → vibe run 或 vibe serve 开跑。加 --docker 就是容器隔离，加 --plan-mode 就是先看计划再执行。




# 卸载旧版本
sudo apt-get remove docker docker-engine docker.io containerd runc

# 安装依赖
sudo apt-get update
sudo apt-get install ca-certificates curl gnupg

# 添加 Docker GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 添加仓库
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME")    
stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 安装
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 免 sudo 使用
sudo usermod -aG docker $USER
# 重新登录 WSL 后生效

# 启动 Docker（WSL2 没有 systemd 时）
sudo service docker start

# 验证
docker run hello-world

方式一更省事，方式二更轻量。


