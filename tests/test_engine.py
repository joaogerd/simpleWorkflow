from simpleworkflow.engine import WorkflowEngine


def test_plan_orders_dependencies():
    config = {
        "workflow": {"name": "test"},
        "context": {},
        "tasks": [
            {"name": "second", "run": "pwd", "depends_on": ["first"]},
            {"name": "first", "run": "pwd"},
        ],
    }

    engine = WorkflowEngine(config=config, workdir=".test-simpleworkflow")

    assert engine.plan() == ["first", "second"]
