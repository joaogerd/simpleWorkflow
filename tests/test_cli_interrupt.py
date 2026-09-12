from __future__ import annotations

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
