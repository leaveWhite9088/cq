# cq 使用指南

本文通过具体场景，演示如何使用 `cq` 管理 Claude Code 任务队列，包括 CLI、TUI、后台运行和查看任务输出。

---

## 场景一：最基础用法

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

### 4. 查看队列

```bash
cq list
```

输出：

```text
ID     Status       Policy     Created              Description
--------------------------------------------------------------------------------
2      pending      continue   2026-07-07T13:00:00  更新 README 里的安装说明
1      pending      continue   2026-07-07T13:00:00  修复登录页跳转错误
```

### 5. 后台运行队列

```bash
cq run
```

`cq run` 默认在后台运行，不会锁住控制台。你会看到：

```text
Started background runner. Logs: D:\Project2\code-260706-auto-vibecoding\fifo-tui\.cq\run.log
```

然后你可以继续添加更多任务：

```bash
cq add "优化数据库查询"
```

后台 runner 会按顺序把它们都跑完。

### 6. 查看运行日志

```bash
type .cq\run.log
```

或者在 PowerShell：

```bash
Get-Content .cq\run.log -Wait
```

### 7. 查看结果

```bash
cq list
```

两个任务都变成 `completed`，`result` 字段里存了 Claude 的输出摘要。

---

## 场景二：某个任务要开启新对话

默认情况下，所有任务都会继续上一次对话。如果你某个任务想和之前完全没关系，用 `--new`：

```bash
cq add "做一个和当前项目无关的实验" --new
```

这个任务运行时不会带 `-c`，Claude 会开启全新上下文。

---

## 场景三：修改任务

你添加了一个任务，后来发现描述写得不清楚：

```bash
cq add "修复登录问题"
```

修改描述：

```bash
cq edit 1 --description "修复登录页微信扫码后跳转错误"
```

或者把一个已完成任务改个描述，让它重新跑一遍：

```bash
cq edit 1 --description "优化登录页加载速度" --continue
```

如果任务是 `completed` 或 `failed`，修改后会自动变回 `pending`，之前的输出会被清空。

---

## 场景四：任务卡住或失败

运行过程中如果 Claude 崩溃或你手动中断了，任务会卡在 `in_progress`。

### 查看状态

```bash
cq list
```

发现某个任务状态是 `in_progress` 或 `failed`。

### 重置

```bash
cq reset
```

默认会把 `in_progress` 任务重置为 `pending`。

### 同时重置 failed 任务

```bash
cq reset --failed
```

---

## 场景五：用 TUI 管理队列

如果你不想记命令，可以直接启动 TUI：

```bash
cq tui
```

界面布局：

- 上半部分：任务队列表格
- 下半部分：Output / Log 面板

### 常用操作

| 操作 | 按键 |
|------|------|
| 添加任务 | `a` |
| 编辑选中任务 | `e` |
| 运行队列 | `r` |
| 重置队列 | `R` |
| 清理已完成任务 | `C` |
| 领取下一个任务 | `n` |
| 查看选中任务输出 | `Enter` |
| 标记选中任务完成 | `x` |
| 删除选中任务 | `d` |
| 删除所有任务 | `D` |
| 显示帮助 | `?` |
| 退出 | `q` / `Ctrl+C` |

### 典型流程

1. 启动 `cq tui`。
2. 按 `a` 输入任务描述，选择是否开启新对话。
3. 按 `r` 运行队列，下方 Log 面板会显示运行进度。
4. 选中一个 completed 任务，按 `Enter` 查看完整输出。

---

## 场景六：清理和删除

### 删除单个任务

```bash
cq delete 5
```

### 删除所有任务

```bash
cq delete --all
```

需要输入 `y` 确认。

### 清理旧 completed 任务

```bash
# 清理超过 24 小时的 completed 任务
cq cleanup

# 清理所有 completed 任务（不管多久）
cq cleanup --retention-hours 0
```

---

## 场景七：自定义数据库路径

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

## 场景八：组合工作流

推荐的日常使用方式：

```bash
# 1. 随时想到任务就加
cq add "重构 auth 模块"
cq add "补充部署文档"

# 2. 启动后台 runner，不阻塞终端
cq run

# 3. 继续加任务，runner 会自动处理
cq add "修复边界情况"

# 4. 通过 TUI 直观查看进度和输出
cq tui

# 5. 清理旧 completed 任务
cq cleanup
```

---

## 常见问题

### Q: `cq run` 前台运行怎么退出？

`cq run --foreground` 是前台阻塞运行。按 `Ctrl+C` 可以中断，但会留下一个 `in_progress` 任务，之后用 `cq reset` 重置即可。

### Q: 后台 runner 怎么停止？

在 Windows 上：

```powershell
Get-Process python | Stop-Process
```

或者更精确地找到对应的 `cq run --foreground` 进程。

### Q: `--new` 和默认 `continue` 有什么区别？

- `continue`：调用 `claude -c -p`，继续上一次对话。
- `--new`：调用 `claude -p`，开启新对话。

### Q: 为什么调用带 `--dangerously-skip-permissions`？

这样 Claude 在运行任务时不会停下来问你要权限，否则后台 runner 会卡住等你确认。

### Q: 任务输出存在哪里？

- 后台运行时的实时日志：`.cq/run.log`
- 每个任务的完整输出：存在 SQLite 的 `result` 字段，可以在 TUI 里按 `Enter` 查看
