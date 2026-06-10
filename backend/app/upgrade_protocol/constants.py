from __future__ import annotations


RUNNER_PROTOCOL_VERSION = 1
TASK_SCHEMA_VERSION = 2

RUNNER_CAPABILITIES = frozenset(
    {
        "backup.create",
        "image.load",
        "files.sync",
        "compose.override",
        "compose.apply",
        "script.sandbox.v1",
        "health.http",
        "health.prometheus",
        "checkpoint.write",
        "rollback.restore",
    }
)
