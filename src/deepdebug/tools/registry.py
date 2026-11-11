"""Explicit tool dispatch and per-run cache over a frozen material registry."""

import json

from deepdebug.agent.actions import ACTION_ADAPTER, ToolAction
from deepdebug.agent.schemas import ToolResult
from deepdebug.agent.state import DiagnosisState
from deepdebug.tools.environment import load_snapshot
from deepdebug.tools.path_references import PathReferences
from deepdebug.tools.session import CollectionSession


class ToolDispatcher:
    def __init__(
        self,
        session: CollectionSession,
        paths: PathReferences | None = None,
        path_reference_ids: list[str] | None = None,
    ):
        self.session = session
        self.paths = paths
        self.path_reference_ids = list(path_reference_ids or [])
        self.environments: dict[str, str] = {}
        snapshots = [a for a in session.state.inputs if a.kind == "snapshot"]
        self.target_artifact_id = snapshots[0].artifact_id if snapshots else None
        ambiguous = set()
        for artifact in snapshots:
            try:
                snapshot, _ = load_snapshot(session.materials.get(artifact.artifact_id).text)
            except (ValueError, RecursionError):
                continue
            environment_id = snapshot.environment.environment_id
            if environment_id in self.environments:
                ambiguous.add(environment_id)
            self.environments[environment_id] = artifact.artifact_id
        for environment_id in ambiguous:
            del self.environments[environment_id]
        self._cache: dict[str, ToolResult] = {}

    @staticmethod
    def key(action: ToolAction) -> str:
        return json.dumps([action.tool, action.arguments.model_dump(mode="json")], sort_keys=True)

    def dispatch(self, action: ToolAction) -> tuple[ToolResult, bool]:
        action = ACTION_ADAPTER.validate_python(action)
        candidate = self.session.state.model_dump()
        candidate["next_action"] = action
        DiagnosisState.model_validate(candidate)
        key = self.key(action)
        if key in self._cache:
            return ToolResult.model_validate(self._cache[key]), True
        args = action.arguments.model_dump()
        tool = action.tool
        if tool == "parse_log":
            result = self.session.parse_log(**args)
        elif tool == "read_artifact":
            result = self.session.read_artifact(**args)
        elif tool == "search_docs":
            result = self.session.search_docs(**args)
        elif tool in {"inspect_environment", "query_gpu"}:
            artifact_id = self.environments.get(args["environment_id"])
            if artifact_id is None:
                result = self.session.record_failure(
                    tool, action.purpose, key, "denied", "环境 ID 未登记、快照无效或 ID 不唯一。"
                )
            elif tool == "query_gpu":
                result = self.session.query_gpu(artifact_id)
            else:
                result = self.session.inspect_snapshot(
                    artifact_id,
                    as_target=artifact_id == self.target_artifact_id,
                    probe_ids=args["probe_ids"],
                )
        elif tool == "check_paths":
            if self.paths is None or not set(args["path_reference_ids"]) <= set(
                self.path_reference_ids
            ):
                result = self.session.record_failure(
                    tool, action.purpose, key, "denied", "路径引用 ID 未授权。"
                )
            else:
                result = self.session.check_paths(self.paths, args["path_reference_ids"])
        else:  # The validated protocol reserves only run_builtin_check here.
            result = self.session.record_failure(
                tool, action.purpose, key, "unavailable", "内置验证执行器尚未实现。"
            )
        payload = self.session.state.model_dump()
        payload["tool_history"][-1]["purpose"] = action.purpose
        payload["tool_history"][-1]["arguments_summary"] = key
        self.session.state = DiagnosisState.model_validate(payload)
        self._cache[key] = ToolResult.model_validate(result)
        return result, False
