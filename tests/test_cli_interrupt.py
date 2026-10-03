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


def test_interrupt_reconciliation_uses_conservative_state_result() -> None:
    class FakeState:
        def __init__(self) -> None:
            self.current = SimpleNamespace(
                status="running",
                signature="sig",
                signature_schema=4,
                signature_payload={"signature_schema": 4},
                attempt_path="attempt-001",
                reason="tarefa iniciada",
            )
            self.reconciled: list[str | None] = []

        def reconcile_running(self, *, cycle_id: str | None = None) -> None:
            assert cycle_id == "cycle-a"
            self.reconciled.append(cycle_id)
            self.current = SimpleNamespace(
                status="unknown",
                signature="sig",
                signature_schema=4,
                signature_payload={"signature_schema": 4},
                attempt_path="attempt-001",
                reason="a execução foi iniciada, mas o resultado não pôde ser confirmado",
            )

    engine = SimpleNamespace(
        cycle_id="cycle-a",
        tasks=[{"name": "analysis", "executor": "pbs"}],
        state=FakeState(),
    )

    cli._reconcile_after_interrupt(engine)  # type: ignore[arg-type]

    assert engine.state.reconciled == ["cycle-a"]
    assert engine.state.current.status == "unknown"
    assert engine.state.current.signature == "sig"
    assert engine.state.current.attempt_path == "attempt-001"
    assert "não pôde ser confirmado" in engine.state.current.reason

