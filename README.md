# cq

> Claude Code 的轻量级任务队列 / 缓冲区。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

`cq` 让你把任务扔进队列，然后由 Claude Code 一个一个消化它们。它解决的是这个经典问题：

> “我刚想到任务 B，但 Claude 还在做任务 A。”

不用打断当前会话，把新任务塞进队列，`cq` 会自动喂给 Claude Code。

---

## 目录

- [功能特性](#功能特性)
- [安装](#安装)
- [快速开始](#快速开始)
- [使用 TUI](#使用-tui)
- [命令速查](#命令速查)
- [工作原理](#工作原理)
- [配置](#配置)
- [开发与测试](#开发与测试)
- [贡献与许可](#贡献与许可)

---

## 功能特性

- **简洁 CLI**：从终端添加、查看、管理任务。
- **TUI 界面**：全屏交互，查看队列、任务输出、运行状态。
- **后台运行**：`cq run` 默认在后台运行，不阻塞控制台。
- **SQLite 持久化**：本地数据库存储，无需外部服务。
- **上下文策略**：默认继续上一次对话；可指定某个任务开启新对话。
- **自动清理**：已完成任务默认保留 24 小时，超时后自动删除。
- **易扩展**：清晰的 Python 包结构，带测试用例。

---

## 安装

`cq` 只需要当前 Python 环境里能执行 `pip install`，**不需要额外创建虚拟环境**。如果你已经在 Conda、venv 或系统 Python 里工作，直接装进去即可。

### 方式一：使用 install.py（推荐）

```bash
git clone https://github.com/leaveWhite9088/cq.git
# 或者把它放进另一个项目的根目录下
cd cq

python install.py
# 开发依赖（测试工具）
python install.py --dev
```

`install.py` 会自动用当前 Python 解释器执行 `pip install -e .`，不会新建 venv。

### 方式二：直接用 pip

```bash
cd cq
pip install -e .
# 开发依赖
pip install -e ".[dev]"
```

### 嵌入到另一个项目里

把 `cq` 整个目录复制（或 git submodule）到另一个项目的根目录：

```text
your-project/
├── cq/
│   ├── install.py
│   ├── cq/
│   └── ...
└── ...
```

然后进入 `your-project` 的 Python 环境，执行一键安装：

```bash
python cq/install.py
```

安装完成后，在该环境里任意位置都能使用：

```bash
cq init
cq tui
```

---

## 快速开始

详细步骤示例见 [USAGE.md](USAGE.md)。

1. **初始化队列**：

   ```bash
   cq init
   ```

2. **添加任务**：

   ```bash
   cq add "修复登录页跳转"
   cq add "优化数据库查询"
   ```

3. **后台运行队列**（不阻塞控制台）：

   ```bash
   cq run
   ```

   输出示例：

   ```text
   Started background runner. Logs: D:\Project2\code-260706-auto-vibecoding\cq\.cq\run.log
   ```

4. **继续添加任务**：

   ```bash
   cq add "更新 README"
   ```

5. **查看队列和结果**：

   ```bash
   cq list
   ```

6. **前台运行**（需要实时输出时）：

   ```bash
   cq run --foreground
   ```

---

## 使用 TUI

启动全屏界面：

```bash
cq tui
```

界面布局：

- 上半部分：任务队列表格
- 下半部分：Output / Log 面板，显示运行日志和选中任务的输出

### 常用操作

| 键位 | 作用 |
|------|------|
| `a` | 添加任务 |
| `e` | 编辑选中任务 |
| `r` | 运行队列 |
| `R` | 重置卡住/失败任务 |
| `C` | 清理已完成任务 |
| `n` | 手动领取下一个任务 |
| `Enter` | 查看选中任务的完整输出 |
| `x` | 标记选中任务为 completed |
| `d` | 删除选中任务 |
| `D` | 删除所有任务 |
| `Tab` | 切换焦点 |
| `?` | 帮助 |
| `q` / `Ctrl+C` | 退出 |

---

## 命令速查

| 命令 | 说明 |
|------|------|
| `cq init` | 创建队列数据库。 |
| `cq add "..."` | 添加任务（默认继续上一次对话）。 |
| `cq add "..." --new` | 添加任务，并让 Claude 开启新对话。 |
| `cq edit ID --description "..."` | 修改任务描述。 |
| `cq edit ID --new` / `--continue` | 修改任务的上下文策略。 |
| `cq list` | 显示所有任务。 |
| `cq list --status pending` | 只显示 pending 任务。 |
| `cq next` | 手动领取下一个 pending 任务。 |
| `cq complete ID` | 标记任务为 completed。 |
| `cq reset` | 重置 in_progress 任务回 pending。 |
| `cq reset --failed` | 同时重置 failed 任务。 |
| `cq run` | 后台运行队列。 |
| `cq run --foreground` | 前台运行，实时输出。 |
| `cq run --once` | 只运行一个任务。 |
| `cq cleanup` | 清理已完成的老任务。 |
| `cq cleanup --retention-hours 0` | 清理所有 completed 任务。 |
| `cq delete ID` | 删除指定任务。 |
| `cq delete --all` | 删除所有任务。 |
| `cq tui` | 启动交互式 TUI。 |

---

## 工作原理

`cq run` 默认会启动一个**后台**进程来顺序处理 pending 任务，主进程立即返回，因此你可以继续往队列里添加新任务。日志写入 `.cq/run.log`。需要前台实时输出时用 `cq run --foreground`。

对于每个任务，`cq` 会调用 Claude Code 的 headless 模式：

```text
You are working through a task queue. Current task (N): <description>. Complete ...
```

- 默认任务使用 `claude -c -p`，让 Claude 继续上一次对话。
- 使用 `--new` 的任务使用 `claude -p`，开启新对话。
- 所有调用都附带 `--dangerously-skip-permissions`，避免运行过程中弹出权限确认。

每个任务仍然在独立进程中运行，因此一个任务失败不会影响其他任务。每个任务结束后，`cq` 会自动删除超过保留期的 completed 任务。

---

## 配置

| 文件 / 环境变量 | 作用 |
|-----------------|------|
| `.cq/queue.db` | 默认 SQLite 队列数据库。 |
| `.cq/run.log` | `cq run` 后台运行时的日志。 |
| `CQ_DB_PATH` | 环境变量，覆盖数据库路径。 |
| `--db PATH` | 每条命令的数据库路径覆盖。 |
| `CQ_COMPLETED_RETENTION_HOURS` | 已完成任务保留小时数（默认 24，设为 0 则禁用自动清理）。 |
| `--retention-hours HOURS` | 每条命令的保留时间覆盖。 |
| `.claude/CLAUDE.md` | Claude Code 被 `cq run` 调用时加载的项目指示。 |

示例：

```bash
export CQ_DB_PATH=/path/to/my-queue.db
export CQ_COMPLETED_RETENTION_HOURS=12
cq init
cq add "部署 staging 构建"
cq run
```

---

## 开发与测试

项目结构：

```text
.
├── cq/              # 主包
│   ├── cli.py       # CLI 入口
│   ├── store.py     # SQLite 后端
│   ├── wrapper.py   # Claude 调用封装
│   └── tui.py       # Textual TUI
├── tests/           # 测试集
├── pyproject.toml   # 项目元数据与依赖
├── README.md        # 本文件
└── USAGE.md         # 详细使用示例
```

运行测试：

```bash
pytest
```

查看详细输出：

```bash
pytest -v
```

---

## 贡献与许可

欢迎贡献！

1. Fork 本仓库。
2. 创建 feature 分支：`git checkout -b feature/my-feature`。
3. 提交更改，并在适当位置添加测试。
4. 确保测试通过：`pytest`。
5. 提交 Pull Request，并在描述中说明修改内容。

重大变更或新功能建议先开 issue 讨论设计。

---

## License

This project is licensed under the [MIT License](LICENSE).
