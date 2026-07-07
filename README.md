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
- [会话管理](#会话管理)
- [命令速查](#命令速查)
- [工作原理](#工作原理)
- [配置](#配置)
- [开发与测试](#开发与测试)
- [贡献与许可](#贡献与许可)

---

## 功能特性

- **简洁 CLI**：从终端添加、查看、管理任务。
- **TUI 界面**：全屏交互，可视化切换会话、查看队列、运行任务。
- **会话（Session）管理**：把任务分组到不同会话，每个会话有独立队列，也可以一键运行全部会话。
- **SQLite 持久化**：本地数据库存储，无需外部服务。
- **上下文策略**：`continue` 继续上一次对话上下文；`new` 开启新上下文。
- **自动清理**：已完成任务默认保留 24 小时，超时后自动删除。
- **易扩展**：清晰的 Python 包结构，带测试用例。

---

## 安装

Clone 仓库并以 editable 模式安装：

```bash
git clone https://github.com/leaveWhite9088/fifo-tui.git
cd fifo-tui
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e .
```

开发版依赖（包含测试工具）：

```bash
pip install -e ".[dev]"
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

3. **运行队列**：

   ```bash
   cq run
   ```

   `cq` 会依次调用 Claude Code 处理每个任务，直到队列为空。

---

## 使用 TUI

启动全屏界面：

```bash
cq tui
```

界面布局：

- 左侧：会话列表
- 右侧：当前会话的任务队列
- 底部：状态栏与快捷键提示

常用快捷键：

| 键位 | 作用 |
|------|------|
| `a` | 添加任务 |
| `r` | 运行当前会话队列 |
| `R` | 重置当前会话的卡住/失败任务 |
| `C` | 清理当前会话已完成任务 |
| `n` | 手动领取下一个任务 |
| `x` | 标记选中任务为 completed |
| `d` | 删除选中任务 |
| `+` / `-` | 切换上一个 / 下一个会话 |
| `Tab` | 切换焦点 |
| `?` | 帮助 |
| `q` / `Ctrl+C` | 退出 |

---

## 会话管理

会话就是任务的分组。默认会话叫 `default`。

**按会话添加任务**：

```bash
cq add "修复登录页跳转" --session auth
cq add "更新 README" --session docs
```

**查看某个会话的队列**：

```bash
cq list --session auth
```

**运行某个会话**：

```bash
cq run --session auth
```

**运行所有会话**：

```bash
cq run --all-sessions
```

**管理会话**：

```bash
# 列出所有会话
cq sessions

# 重命名
cq rename-session old-name new-name

# 删除某个会话下的所有任务
cq delete-session old-name
```

---

## 命令速查

| 命令 | 说明 |
|------|------|
| `cq init` | 创建队列数据库。 |
| `cq add "..."` | 添加任务到默认会话。 |
| `cq add "..." --session X` | 添加任务到会话 X。 |
| `cq add "..." --context-policy new` | 任务使用新上下文。 |
| `cq list` | 显示所有会话的任务（不指定 `--session` 时）。 |
| `cq list --session X` | 显示会话 X 的任务。 |
| `cq next` | 手动领取下一个 pending 任务（跨会话）。 |
| `cq next --session X` | 领取会话 X 的下一个任务。 |
| `cq complete ID` | 标记任务为 completed。 |
| `cq reset` | 重置 in_progress 任务回 pending（跨会话）。 |
| `cq reset --session X` | 重置会话 X 的 in_progress 任务。 |
| `cq reset --failed` | 同时重置 failed 任务。 |
| `cq run` | 运行所有 pending 任务（跨会话，保持旧行为）。 |
| `cq run --session X` | 只运行会话 X 的队列。 |
| `cq run --all-sessions` | 按会话逐个运行所有队列。 |
| `cq run --once` | 只运行一个任务。 |
| `cq cleanup` | 清理已完成的老任务（跨会话）。 |
| `cq cleanup --session X` | 只清理会话 X 的已完成任务。 |
| `cq rename-session OLD NEW` | 重命名会话。 |
| `cq delete-session SESSION` | 删除某会话下的所有任务。 |
| `cq tui` | 启动交互式 TUI。 |

---

## 工作原理

`cq run` 会顺序处理 pending 任务。对于每个任务，它会调用 Claude Code 的 headless 模式：

```text
You are working through a task queue. Current task (N): <description>. Complete ...
```

- `context_policy == "continue"` 时使用 `claude -c -p`，保留上一个任务的对话上下文。
- `context_policy == "new"` 时使用 `claude -p`，开启新上下文。

每个任务仍然在独立进程中运行，因此一个任务失败不会影响其他任务。每个任务结束后，`cq` 会自动删除超过保留期的 completed 任务。

---

## 配置

| 文件 / 环境变量 | 作用 |
|-----------------|------|
| `.cq/queue.db` | 默认 SQLite 队列数据库。 |
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
