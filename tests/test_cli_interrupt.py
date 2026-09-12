from __future__ import annotations

from types import SimpleNamespace

import simpleworkflow.cli as cli


def test_run_reconciles_and_returns_130_on_keyboard_interrupt(
    monkeypatch: object, capsys: object
) -> None:
    class FakeState:
        def __init__(self) -> None:
            self.reconciled: list[str] = []
            self.closed = False

        def reconcile_running(self, workflow: str) -> None:
            self.reconciled.append(workflow)

        def close(self) -> None:
            self.closed = True

    class FakeEngine:
        state_key = "display_test"
        tasks: list[dict[str, str]] = []

        def __init__(self) -> None:
            self.state = FakeState()

        def run(self) -> int:
            raise KeyboardInterrupt

    engine = FakeEngine()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        cli, "load_workflow", lambda _path: {"workflow": {"name": "display_test"}}
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        cli, "_cycle_engines", lambda _config, _args, _reporter: [(None, engine)]
    )

    assert cli.main(["run", "workflow.yaml", "--color", "never"]) == 130
    assert engine.state.reconciled == ["display_test"]
    assert engine.state.closed is True

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "interrompida pelo usuário" in captured.err
    assert "Traceback" not in captured.err


def test_pbs_interrupt_before_job_id_remains_unknown() -> None:
    class FakeState:
        def __init__(self) -> None:
            self.current = SimpleNamespace(
                status="running",
                signature="sig",
                attempt_dir="attempt-001",
            )

        def get_status(self, _workflow: str, _task: str) -> str:
            return self.current.status

        def reconcile_running(self, _workflow: str) -> None:
            self.current = SimpleNamespace(
                status="interrupted",
                signature="sig",
                attempt_dir="attempt-001",
            )

        def get_task_state(self, _workflow: str, _task: str) -> SimpleNamespace:
            return self.current

        def set_status(
            self,
            _workflow: str,
            _task: str,
            status: str,
            _return_code: int | None,
            signature: str | None,
            reason: str,
            attempt_dir: str | None,
        ) -> None:
            self.current = SimpleNamespace(
                status=status,
                signature=signature,
                reason=reason,
                attempt_dir=attempt_dir,
            )

    engine = SimpleNamespace(
        state_key="pbs-test",
        tasks=[{"name": "analysis", "executor": "pbs"}],
        state=FakeState(),
    )

    cli._reconcile_after_interrupt(engine)  # type: ignore[arg-type]

    assert engine.state.current.status == "unknown"
    assert engine.state.current.signature == "sig"
    assert engine.state.current.attempt_dir == "attempt-001"
    assert "verifique o escalonador" in engine.state.current.reason
