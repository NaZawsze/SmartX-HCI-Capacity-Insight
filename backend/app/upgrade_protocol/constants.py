from __future__ import annotations


RUNNER_PROTOCOL_VERSION = 1
TASK_SCHEMA_VERSION = 2

RUNNER_CAPABILITIES = frozenset(
    {
        "backup.v1",
        "image.v1",
        "files.v1",
        "compose.v1",
        "compose.project.v1",
        "script.sandbox.v1",
        "health.v1",
        "task.recovery.v1",
        "rollback.v1",
    }
)

LEGACY_CAPABILITY_ALIASES = {
    "backup.create": "backup.v1",
    "image.load": "image.v1",
    "files.sync": "files.v1",
    "compose.override": "compose.v1",
    "compose.apply": "compose.v1",
    "compose.project_migrate.v1": "compose.project.v1",
    "health.http": "health.v1",
    "health.prometheus": "health.v1",
    "checkpoint.write": "task.recovery.v1",
    "rollback.restore": "rollback.v1",
}

ACTION_CAPABILITIES = {
    "backup.create": "backup.v1",
    "image.load": "image.v1",
    "files.sync": "files.v1",
    "compose.override": "compose.v1",
    "compose.apply": "compose.v1",
    "compose.project_migrate": "compose.project.v1",
    "script.run_sandboxed": "script.sandbox.v1",
    "health.http": "health.v1",
    "health.prometheus": "health.v1",
    "checkpoint.write": "task.recovery.v1",
    "rollback.restore": "rollback.v1",
}
