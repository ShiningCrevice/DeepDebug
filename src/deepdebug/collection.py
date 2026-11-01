"""Application workflow for explicit local material collection, without diagnosis."""

from pathlib import Path

from deepdebug.agent.state import DiagnosisState
from deepdebug.security.paths import AuthorizedRoot
from deepdebug.tools.artifacts import MaterialRegistry
from deepdebug.tools.path_references import PathReferences
from deepdebug.tools.session import CollectionSession


def collect(
    root: Path,
    log: str,
    code: list[str],
    config: list[str],
    snapshots: list[str],
    *,
    paths: list[str] | None = None,
    path_root: Path | None = None,
    query_gpu: bool = False,
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
        if query_gpu:
            session.query_gpu(artifact.artifact_id)
    if paths:
        with AuthorizedRoot(path_root or root) as authorized:
            references = PathReferences(authorized)
            reference_ids = [references.register(path) for path in paths]
            session.check_paths(references, reference_ids)
    return DiagnosisState.model_validate(session.state)
