"""Application workflow for explicit local material collection, without diagnosis."""

from pathlib import Path

from deepdebug.agent.state import DiagnosisState
from deepdebug.security.paths import AuthorizedRoot
from deepdebug.tools.artifacts import MaterialRegistry
from deepdebug.tools.session import CollectionSession


def collect(
    root: Path, log: str, code: list[str], config: list[str], snapshots: list[str]
) -> DiagnosisState:
    registry = MaterialRegistry()
    with AuthorizedRoot(root) as authorized:
        log_artifact = registry.register(authorized, log, "log")
        attachments = [registry.register(authorized, name, "code") for name in code]
        attachments += [registry.register(authorized, name, "config") for name in config]
        environments = [registry.register(authorized, name, "snapshot") for name in snapshots]
    session = CollectionSession(registry)
    session.parse_log(log_artifact.artifact_id)
    for artifact in attachments:
        session.read_artifact(artifact.artifact_id)
    for index, artifact in enumerate(environments):
        session.inspect_snapshot(artifact.artifact_id, as_target=index == 0)
    return DiagnosisState.model_validate(session.state)
