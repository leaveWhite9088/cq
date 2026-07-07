# cq 使用指南

本文通过几个具体场景，演示如何使用 `cq` 管理 Claude Code 任务队列，包括 CLI、TUI 和会话（Session）管理。

---

## 场景一：最基础用法（无会话）

你正在维护一个项目，发现有两个问题要修：

- **任务 A**：修复登录页跳转错误
- **任务 B**：更新 README 里的安装说明

你不想让 Claude 做 A 的时候被打断，希望 A 做完后自动做 B。

### 1. 准备

```bash
cd D:\Project2\code-260706-auto-vibecoding\fifo-tui
.venv\Scripts\activate
```

### 2. 初始化队列

```bash
cq init
```

会在当前目录创建 `.cq/queue.db`。

### 3. 添加任务

```bash
cq add "修复登录页跳转错误"
cq add "更新 README 里的安装说明"
```

不指定 `--session` 时，任务会进入 `default` 会话。

### 4. 查看队列

```bash
cq list
```

输出：

```text
ID     Session          Status       Created              Description
--------------------------------------------------------------------------------------
2      default          pending      2026-07-07T13:00:00  更新 README 里的安装说明
1      default          pending      2026-07-07T13:00:00  修复登录页跳转错误
```

### 5. 运行队列

只跑一个：

```bash
cq run --once
```

连续跑完：

```bash
cq run
```

输出示例：

```text
Running task 1 [default]: 修复登录页跳转错误
Task 1 finished with status=completed
Running task 2 [default]: 更新 README 里的安装说明
Task 2 finished with status=completed
Queue is empty. Nothing to do.
```

### 6. 查看结果

```bash
cq list
```

两个任务都变成 `completed`，`result` 字段里存了 Claude 的输出摘要。

---

## 场景二：用会话把任务分组

你同时要处理两个独立方向：

- **auth 会话**：登录、权限相关
- **docs 会话**：文档、README 相关

你想分开管理，避免混在一起。

### 添加任务到不同会话

```bash
cq add "修复登录页跳转" --session auth
cq add "增加密码强度校验" --session auth
cq add "更新 README 安装说明" --session docs
cq add "补充 API 文档" --session docs
```

### 查看所有会话

```bash
cq sessions
```

输出：

```text
auth
default
docs
```

### 只看某个会话

```bash
cq list --session auth
```

输出：

```text
ID     Session          Status       Created              Description
--------------------------------------------------------------------------------------
2      auth             pending      2026-07-07T13:00:00  增加密码强度校验
1      auth             pending      2026-07-07T13:00:00  修复登录页跳转
```

### 运行某个会话

```bash
cq run --session auth
```

只会执行 `auth` 会话里的任务。

### 运行所有会话

```bash
cq run --all-sessions
```

会按会话名顺序依次处理每个会话里的 pending 任务。

### 只跑一个任务（任意会话）

```bash
cq run --once
```

不指定 `--session` 时，会领取全局最早的 pending 任务。

---

## 场景三：任务卡住或失败

运行过程中如果 Claude 崩溃或你手动中断了，任务会卡在 `in_progress`。

### 查看状态

```bash
cq list
```

发现某个任务状态是 `in_progress` 或 `failed`。

### 重置当前会话

```bash
cq reset
```

默认会把 `in_progress` 任务重置为 `pending`。

### 重置指定会话

```bash
cq reset --session auth
```

### 同时重置 failed 任务

```bash
cq reset --session auth --failed
```

---

## 场景四：用 TUI 管理队列

如果你不想记命令，可以直接启动 TUI：

```bash
cq tui
```

界面布局：

- 左侧：会话列表
- 右侧：当前选中会话的任务队列
- 底部：状态栏

### 常用操作

| 操作 | 按键 |
|------|------|
| 添加任务 | `a` |
| 运行当前会话 | `r` |
| 重置当前会话 | `R` |
| 清理当前会话已完成任务 | `C` |
| 领取下一个任务 | `n` |
| 标记选中任务完成 | `x` |
| 删除选中任务 | `d` |
| 切换上一个 / 下一个会话 | `-` / `+` |
| 显示帮助 | `?` |
| 退出 | `q` / `Ctrl+C` |

### 典型流程

1. 启动 `cq tui`。
2. 按 `a` 输入任务描述，选择目标会话，添加任务。
3. 用 `+` / `-` 在不同会话间切换，查看各自队列。
4. 选中会话后按 `r` 运行该会话。
5. 运行结束后任务状态会自动刷新。

---

## 场景五：会话整理

### 重命名会话

```bash
cq rename-session auth authentication
```

该会话下所有任务的 `session` 字段都会被修改。

### 删除会话

```bash
cq delete-session temp-experiment
```

会删除该会话下的所有任务，请谨慎使用。

### 清理旧 completed 任务

```bash
# 清理所有会话里超过 24 小时的 completed 任务
cq cleanup

# 只清理 docs 会话
cq cleanup --session docs

# 清理所有 completed 任务（不管多久）
cq cleanup --retention-hours 0
```

---

## 场景六：自定义数据库路径

如果你想把队列数据库放在别处：

```bash
set CQ_DB_PATH=D:\my-queue.db
cq init
cq add "示例任务"
```

或者每次命令指定：

```bash
cq --db D:\my-queue.db list
```

---

## 场景七：组合工作流

推荐的日常使用方式：

```bash
# 1. 随时想到任务就加
cq add "重构 auth 模块" --session auth
cq add "补充部署文档" --session docs

# 2. 通过 TUI 直观查看和管理
cq tui

# 3. 批量处理某个方向
cq run --session auth

# 4. 处理剩余所有方向
cq run --all-sessions

# 5. 清理已完成任务
cq cleanup
```

---

## 常见问题

### Q: `cq list` 为什么不显示某个会话的任务？

不指定 `--session` 时，`cq list` 会显示所有会话的任务。如果只想看一个会话，用：

```bash
cq list --session auth
```

### Q: `cq run` 和 `cq run --all-sessions` 有什么区别？

- `cq run`：全局 FIFO，领取最早的 pending 任务，不管它在哪个会话。
- `cq run --all-sessions`：按会话逐个处理，每个会话内部按 FIFO。

### Q: 删除任务和完成任务有什么区别？

- **完成**（`cq complete` 或 TUI 里 `x`）：任务保留在数据库，状态变为 `completed`，可被清理。
- **删除**（TUI 里 `d`）：任务从数据库直接移除。

### Q: TUI 里能运行所有会话吗？

当前 TUI 的 `r` 只运行当前选中会话。要运行所有会话，可以回到 CLI 执行 `cq run --all-sessions`。
