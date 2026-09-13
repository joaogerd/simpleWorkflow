# PBS interruption and recovery

For PBS tasks, `simpleWorkflow` stays in the foreground while it checks the scheduler for completion.

If the user interrupts that wait with Ctrl+C after a PBS job identifier has been recorded, the runner requests cancellation with `qdel`. The cancellation request and its result are preserved in `scheduler.json`.

The command returns exit code 130. The workflow state is reconciled before the CLI exits. A PBS task with a recorded scheduler job is kept as `unknown` rather than automatically repeated, because accepting a cancellation request does not by itself prove the final scheduler result.

Before rerunning such a task, confirm the final job state in PBS and then reset the workflow state explicitly when appropriate.

Scheduler polling is logged in compact form. The full `qstat` payload is not copied into the task log.
