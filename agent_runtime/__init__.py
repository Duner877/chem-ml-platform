"""Agent task runtime (v0.7.1 -- spec task B).

The single, auditable execution path for every agent task:

    Plan -> Review -> Execute -> Verify -> Complete
    (abort: Failed / Cancelled)

Public API::

    from agent_runtime import scheduler
    task = scheduler.submit("预测咖啡因的 logP", require_approval=True)
    task = scheduler.approve(task.task_id)
"""

from .tasks import AgentTask, TaskScheduler, assess_plan, scheduler

__version__ = "0.7.1"

__all__ = ["AgentTask", "TaskScheduler", "assess_plan", "scheduler", "__version__"]
