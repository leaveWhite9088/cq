# Claude Code Task Queue

This project uses `cq` (Claude Code Task Queue) to feed tasks to Claude Code one at a time.

When you are invoked by `cq run`, you are processing a single task from the queue. Focus on that task only:

1. Read or explore the codebase as needed.
2. Complete the task using the appropriate tools.
3. Do not try to claim or process additional tasks in the same session.
4. Do not ask the user clarifying questions unless the task is genuinely ambiguous.

The `cq` wrapper will handle queue bookkeeping and invoke you again for the next task if one exists.
