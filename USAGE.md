# cq 使用示例

下面用一个具体场景演示 `cq` 的用法。

## 场景

你正在维护一个项目，发现版本一上有两个问题：

- **任务 A**：修复登录页跳转错误
- **任务 B**：更新 README 里的安装说明

你不想让 Claude 做 A 的时候被打断，希望 A 做完后自动做 B。

---

## 使用 Route B：`cq run`

`cq run` 用 `claude -c -p` 顺序执行队列里的任务。每个任务单独调一次 Claude，但会用 `-c` 继续上一次的对话上下文，既保证隔离又保留连续性。如果你某个任务想完全 fresh start，可以加 `--context-policy new`。

### 1. 准备

```bash
cd D:\Project2\code-260706-auto-vibecoding
.venv\Scripts\activate
```

### 2. 把任务塞进队列

```bash
cq add "修复登录页跳转错误"
cq add "更新 README 里的安装说明"
```

如果想让某个任务不继承上文（完全 fresh start）：

```bash
cq add "做一个和之前无关的实验" --context-policy new
```

查看队列：

```bash
cq list
```

输出：

```text
ID     Status       Created              Description
----------------------------------------------------------------------
2      pending      2026-07-06T16:17:23  更新 README 里的安装说明
1      pending      2026-07-06T16:17:23  修复登录页跳转错误
```

### 3. 让 Claude 顺序执行

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
Running task 1: 修复登录页跳转错误
Task 1 finished with status=completed
Running task 2: 更新 README 里的安装说明
Task 2 finished with status=completed
Queue is empty. Nothing to do.
```

### 4. 查看结果

```bash
cq list
```

两个任务都变成 `completed`，`result` 字段里存了 Claude 的输出摘要。

### 5. 自动清理已完成的任务

默认 completed 任务保留 24 小时，`cq run` 跑完会自动清理超过时限的。你可以改保留时间：

```bash
# 只保留 1 小时
cq run --retention-hours 1

# 或者用环境变量（Windows）
set CQ_COMPLETED_RETENTION_HOURS=1
cq run
```

想手动清理：

```bash
cq cleanup --retention-hours 24
```

如果想一直保留，设为 0 即可：

```bash
cq run --retention-hours 0
```

### 6. 如果任务卡住

如果某次运行中途崩溃，任务会卡在 `in_progress`。用 reset 重置：

```bash
cq reset
```

---

## 日常 workflow 建议

1. **工作时随时加任务**：想到什么就 `cq add "..."`，不用等 Claude。
2. **批量处理**：
   ```bash
   cq run
   ```
3. **手动插队/查看**：
   ```bash
   cq list
   cq next
   cq complete 5 --result "已完成"
   ```
4. **清理卡住任务**：
   ```bash
   cq reset
   ```
5. **清理旧 completed 任务**：
   ```bash
   cq cleanup --retention-hours 24
   ```

---

## 配置环境变量

如果想把队列数据库放到别处：

```bash
set CQ_DB_PATH=D:\my-queue.db
cq init
cq add "..."
```

或在每次命令时用：

```bash
cq --db D:\my-queue.db list
```

调整 completed 任务保留时间：

```bash
set CQ_COMPLETED_RETENTION_HOURS=12
cq run
```
