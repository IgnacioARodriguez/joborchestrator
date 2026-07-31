from __future__ import annotations

from joborchestrator import api
from joborchestrator import (
    linkedin_worker,
)
from joborchestrator import worker


class FakeOperationsDb:
    def __init__(self) -> None:
        self.active: dict[
            str,
            dict,
        ] = {}

        self.created: list[
            tuple[str, dict, str]
        ] = []

        self.requeued: list[
            tuple[list[str], int]
        ] = []

    def requeue_stale_operations(
        self,
        operation_types: list[str],
        stale_seconds: int,
    ) -> int:
        self.requeued.append(
            (
                operation_types,
                stale_seconds,
            )
        )

        return 0

    def get_active_operation(
        self,
        operation_type: str,
    ) -> dict | None:
        return self.active.get(
            operation_type
        )

    def create_operation(
        self,
        operation_type: str,
        payload: dict,
        message: str,
    ) -> int:
        self.created.append(
            (
                operation_type,
                payload,
                message,
            )
        )

        return 100 + len(self.created)


def test_queue_scan_all_splits_lanes(
    monkeypatch,
) -> None:
    fake_db = FakeOperationsDb()

    monkeypatch.setattr(
        api,
        "db",
        fake_db,
    )

    result = api.queue_scan_all(
        api.UnifiedScanPayload(
            include_ats=True,
            include_search=True,
            include_linkedin=True,
            queries=[
                "Backend Developer"
            ],
        )
    )

    assert [
        item[0]
        for item in fake_db.created
    ] == [
        "job_scan",
        "linkedin_scan",
    ]

    public_payload = (
        fake_db.created[0][1]
    )

    linkedin_payload = (
        fake_db.created[1][1]
    )

    assert (
        public_payload["include_ats"]
        is True
    )

    assert (
        public_payload["include_search"]
        is True
    )

    assert (
        public_payload[
            "include_linkedin"
        ]
        is False
    )

    assert (
        linkedin_payload["include_ats"]
        is False
    )

    assert (
        linkedin_payload[
            "include_search"
        ]
        is False
    )

    assert (
        linkedin_payload[
            "include_linkedin"
        ]
        is True
    )

    assert result["operation_id"] == 101

    assert (
        result[
            "linkedin_operation_id"
        ]
        == 102
    )

    assert result["operation_ids"] == {
        "job_scan": 101,
        "linkedin_scan": 102,
    }

    assert (
        result["already_running"]
        is False
    )


def test_linkedin_has_dedicated_worker(
) -> None:
    assert (
        "linkedin_scan"
        not in worker.OPERATION_TYPES
    )

    assert (
        linkedin_worker.OPERATION_TYPES
        == ["linkedin_scan"]
    )
