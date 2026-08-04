from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _between(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


def test_submitted_application_updates_loaded_collections_without_refetch() -> None:
    store = _source("lib/store.tsx")
    callback = _between(
        store,
        "const recordApplication = useCallback",
        "const setSelectedRankingVersion = useCallback",
    )

    assert "setApplications(" in callback
    assert "setJobs(" in callback
    assert "setPreparationJobs(" in callback
    assert "void refresh()" not in callback
    assert "void refreshPreparationQueue()" not in callback


def test_operation_polling_request_count_is_independent_of_operation_count() -> None:
    pipeline = _source("components/screens/pipeline-screen.tsx")

    assert "trackedOperationIds(operationByJob, applicationOperationByJob)" in pipeline
    assert "api.getOperationsByIds(operationIds)" in pipeline


def test_sync_revision_poll_uses_lightweight_visible_request() -> None:
    sync_hook = _source("lib/use-sync-revisions.ts")
    visible_polling = _source("lib/use-visible-polling.ts")

    assert "const current = await api.getSyncStatus()" in sync_hook
    assert "intervalMs = 5000" in sync_hook
    assert "useVisiblePolling" in sync_hook
    assert "inFlightRef.current" in sync_hook
    assert 'document.visibilityState === "visible"' in visible_polling
    assert "setInterval(" not in sync_hook
    assert "setInterval(" not in visible_polling


def test_sync_consumer_does_not_load_unopened_applications() -> None:
    app_shell = _source("components/app-shell.tsx")
    handler = _between(
        app_shell,
        "const handleSyncStatus = useCallback",
        "const checkSyncStatus = useSyncRevisions",
    )

    assert 'applicationsStatus !== "idle"' in handler
    assert "canRefreshResource(applicationsStatus)" in handler
    assert "refreshApplications().then" in handler


def test_jobs_wait_for_background_work_before_staging_snapshot() -> None:
    app_shell = _source("components/app-shell.tsx")
    handler = _between(
        app_shell,
        "const handleSyncStatus = useCallback",
        "const checkSyncStatus = useSyncRevisions",
    )

    assert "backgroundJobsActive" in handler
    assert "jobsSyncPendingRef.current" in handler
    assert "await stageJobUpdates()" in handler
