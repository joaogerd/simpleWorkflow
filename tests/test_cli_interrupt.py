from __future__ import annotations

from types import SimpleNamespace

import simpleworkflow.cli as cli


def test_run_reconciles_and_returns_130_on_keyboard_interrupt(
    monkeypatch: object, capsys: object
) -> None:
    class FakeState:
        def __init__(self) -> None:
            self.reconciled: list[str | None] = []
            self.closed = False

        def reconcile_running(self, *, cycle_id: str | None = None) -> None:
            self.reconciled.append(cycle_id)

        def close(self) -> None:
            self.closed = True

    class FakeEngine:
        tasks: list[dict[str, str]] = []
        cycle_id = None

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
    assert engine.state.reconciled == [None]
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
                signature_schema=4,
                signature_payload={"signature_schema": 4},
                attempt_path="attempt-001",
            )

        def get_status(self, _task: str, *, cycle_id: str | None = None) -> str:
            assert cycle_id == "cycle-a"
            return self.current.status

        def reconcile_running(self, *, cycle_id: str | None = None) -> None:
            assert cycle_id == "cycle-a"
            self.current = SimpleNamespace(
                status="interrupted",
                signature="sig",
                signature_schema=4,
                signature_payload={"signature_schema": 4},
                attempt_path="attempt-001",
            )

        def get_task_state(
            self, _task: str, *, cycle_id: str | None = None
        ) -> SimpleNamespace:
            assert cycle_id == "cycle-a"
            return self.current

        def set_status(
            self,
            _task: str,
            status: str,
            _return_code: int | None,
            signature: str | None,
            reason: str,
            attempt_path: str | None,
            *,
            cycle_id: str | None = None,
            signature_schema: int | None = None,
            signature_payload: dict[str, object] | None = None,
        ) -> None:
            assert cycle_id == "cycle-a"
            self.current = SimpleNamespace(
                status=status,
                signature=signature,
                signature_schema=signature_schema,
                signature_payload=signature_payload,
                reason=reason,
                attempt_path=attempt_path,
            )

    engine = SimpleNamespace(
        cycle_id="cycle-a",
        tasks=[{"name": "analysis", "executor": "pbs"}],
        state=FakeState(),
    )

    cli._reconcile_after_interrupt(engine)  # type: ignore[arg-type]

    assert engine.state.current.status == "unknown"
    assert engine.state.current.signature == "sig"
    assert engine.state.current.attempt_path == "attempt-001"
    assert "verifique o escalonador" in engine.state.current.reason
