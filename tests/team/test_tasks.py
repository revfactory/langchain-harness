"""H4: concurrent claim race; H5: DAG cycle detection."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from langchain_harness.team import registry, tasks
from langchain_harness.team.types import CycleError, VersionConflictError


def _bootstrap(workspace: Path, team_name: str = "tq") -> None:
    registry.team_create(
        workspace,
        team_name=team_name,
        lead_name="lead",
        shared_objective="",
    )


def test_concurrent_claim_only_one_wins(workspace: Path) -> None:
    _bootstrap(workspace)
    task = tasks.create_task(
        workspace,
        "tq",
        title="shared",
        description="",
        created_by="lead",
    )
    results: list[str] = []
    errors: list[Exception] = []
    start = threading.Barrier(3)

    def claim(who: str) -> None:
        start.wait()
        try:
            t = tasks.claim_task(workspace, "tq", task.task_id, claimed_by=who)
            results.append(t.claimed_by or "")
        except (VersionConflictError, Exception) as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=claim, args=(f"m{i}",)) for i in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1, f"exactly one winner expected, got={results}, errs={errors}"
    assert len(errors) == 2


def test_dag_cycle_detection(workspace: Path) -> None:
    _bootstrap(workspace, "tq2")
    a = tasks.create_task(
        workspace,
        "tq2",
        title="A",
        description="",
        created_by="lead",
    )
    b = tasks.create_task(
        workspace,
        "tq2",
        title="B",
        description="",
        created_by="lead",
        depends_on=[a.task_id],
    )
    # Attempt to make A depend on B (would create A -> B -> A cycle).
    # Since create_task makes a new task, we build the cycle via a new task C
    # whose depends_on includes B, then try to make B depend on C (indirect cycle).
    c = tasks.create_task(
        workspace,
        "tq2",
        title="C",
        description="",
        created_by="lead",
        depends_on=[b.task_id],
    )
    # Now make a task that depends on c and would include a.task_id pointing back
    # Direct case: creating a task with depends_on=[a.task_id, c.task_id] is fine.
    # The cycle case: create task D whose depends_on contains c, then attempt
    # to create A' that also depends on D... Our implementation detects cycle
    # when candidate_id itself appears in the transitive depends_on. We can
    # reproduce by simulating a cycle via direct graph: create task E with
    # depends_on including E (self-cycle).
    # Simpler: verify self-reference raises.
    # Our API assigns a fresh uuid, so we force an invalid pre-existing chain.
    # Build: X depends on Y; Y depends on X — by editing tasks on disk.
    import json
    from langchain_harness.team.types import TeamTask

    x = tasks.create_task(
        workspace, "tq2", title="X", description="", created_by="lead"
    )
    y = tasks.create_task(
        workspace,
        "tq2",
        title="Y",
        description="",
        created_by="lead",
        depends_on=[x.task_id],
    )
    # Manually patch X to depend on Y (simulating an out-of-band edit) so the
    # next create() that walks the graph hits a cycle.
    x_path = registry.task_path(workspace, "tq2", x.task_id)
    data = json.loads(x_path.read_text())
    data["depends_on"] = [y.task_id]
    x_path.write_text(json.dumps(data))

    with pytest.raises(CycleError):
        tasks.create_task(
            workspace,
            "tq2",
            title="Z",
            description="",
            created_by="lead",
            depends_on=[x.task_id, y.task_id],
        )

    _ = (c, b)  # silence unused


def test_update_task_cas_version(workspace: Path) -> None:
    _bootstrap(workspace, "tq3")
    t = tasks.create_task(
        workspace, "tq3", title="T", description="", created_by="lead"
    )
    claimed = tasks.claim_task(workspace, "tq3", t.task_id, claimed_by="lead")
    updated = tasks.update_task(
        workspace,
        "tq3",
        t.task_id,
        new_status="in_progress",
        expected_version=claimed.version,
        updated_by="lead",
    )
    assert updated.status == "in_progress"
    with pytest.raises(VersionConflictError):
        tasks.update_task(
            workspace,
            "tq3",
            t.task_id,
            new_status="done",
            expected_version=claimed.version,  # stale
            updated_by="lead",
        )
