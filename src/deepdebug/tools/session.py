"""Host-driven evidence collection. Model dispatch and diagnosis are separate stages."""

import json
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from deepdebug.agent.actions import (
    CheckPathsArguments,
    ParseLogArguments,
    ReadArtifactArguments,
    SearchDocsArguments,
)
from deepdebug.agent.evidence import EvidenceRegistry
from deepdebug.agent.schemas import (
    Category,
    FieldLocation,
    LineLocation,
    Source,
    TargetEnvironment,
    ToolName,
    ToolRecord,
    ToolResult,
)
from deepdebug.agent.state import DiagnosisState
from deepdebug.security.paths import MaterialError
from deepdebug.tools.artifacts import Excerpt, MaterialRegistry, RegisteredMaterial, excerpt
from deepdebug.tools.docs_search import DocumentIndex
from deepdebug.tools.environment import load_snapshot
from deepdebug.tools.log_parser import parse_log
from deepdebug.tools.path_references import PathReferences

MAX_RESULT_BYTES = 64 * 1024
OperationOutput = tuple[dict, list[dict], bool, TargetEnvironment | None, str | None]


class ObservationFailure(Exception):
    def __init__(self, status: str, error: str, source: Source, collected_at: datetime):
        self.status = status
        self.error = error
        self.source = source
        self.collected_at = collected_at


class CollectionSession:
    def __init__(self, materials: MaterialRegistry):
        self.materials = materials
        self.evidence = EvidenceRegistry()
        self.state = DiagnosisState(session_id=uuid4().hex, inputs=materials.artifacts())
        self._started = monotonic()
        self._documents: DocumentIndex | None = None

    def _run(
        self,
        tool: ToolName,
        artifact_id: str | None,
        purpose: str,
        operation: Callable[[RegisteredMaterial | None], OperationOutput],
        *,
        arguments_summary: str,
        as_target: bool = False,
        local_source: Source | None = None,
    ) -> ToolResult:
        started = monotonic()
        timestamp = datetime.now(timezone.utc)
        # Unknown IDs cannot masquerade as a registered artifact source.
        source = local_source or Source(
            kind="local", id="material_registry", environment_id="collector"
        )
        preserve_source = False
        observations: list[dict] = []
        target = None
        summary = None
        data: dict = {}
        truncated = False
        error = None
        status = "ok"
        try:
            item = self.materials.get(artifact_id) if artifact_id is not None else None
            if item is not None:
                source = Source(kind="artifact", id=item.artifact.artifact_id)
            data, observations, truncated, target, summary = operation(item)
            if target is not None:
                source = Source(
                    kind="snapshot", id=artifact_id, environment_id=target.environment_id
                )
                timestamp = target.collected_at
            if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > MAX_RESULT_BYTES:
                raise MaterialError("工具结果超过 64 KiB；请缩小材料或读取范围。")
        except MaterialError as exc:
            status, error = "denied", str(exc)
        except ObservationFailure as exc:
            status, error = exc.status, exc.error
            source, timestamp = exc.source, exc.collected_at
            preserve_source = True
        except (ValueError, RecursionError):
            # Validation details may contain raw input: only expose a fixed message.
            status, error = "error", "工具参数或材料结构无效。"
        if error:
            data, observations, target, summary, truncated = {}, [], None, None, False
            if source.kind == "snapshot" and not preserve_source:
                source = Source(kind="artifact", id=artifact_id)
                timestamp = datetime.now(timezone.utc)
        candidate_evidence = deepcopy(self.evidence)
        evidence_ids = []
        for observation in observations:
            entry = candidate_evidence.register(**observation)
            if entry.evidence_id not in evidence_ids:
                evidence_ids.append(entry.evidence_id)
        result = ToolResult(
            tool_call_id=f"T{len(self.state.tool_history) + 1:03}",
            status=status,
            data=data,
            evidence_ids=evidence_ids,
            source=source,
            collected_at=timestamp,
            duration_ms=int((monotonic() - started) * 1000),
            truncated=truncated,
            error=error,
        )
        # Bound the complete envelope, including IDs and source, before committing observations.
        if len(result.model_dump_json().encode("utf-8")) > MAX_RESULT_BYTES:
            result = ToolResult(
                tool_call_id=result.tool_call_id,
                status="denied",
                data={},
                evidence_ids=[],
                source=Source(kind="artifact", id=artifact_id) if artifact_id else source,
                collected_at=datetime.now(timezone.utc),
                duration_ms=result.duration_ms,
                error="工具结果超过 64 KiB；请缩小材料或读取范围。",
            )
            target, summary = None, None
        else:
            self.evidence = candidate_evidence
        # Reconstruct and validate at the boundary, rather than trusting in-place updates.
        payload = self.state.model_dump()
        payload["evidence"] = self.evidence.values()
        payload["tool_history"].append(
            ToolRecord(
                tool=tool,
                purpose=purpose,
                arguments_summary=arguments_summary,
                result=result,
            )
        )
        payload["budget"]["tool_calls"] += 1
        payload["budget"]["elapsed_ms"] = int((monotonic() - self._started) * 1000)
        if summary is not None:
            payload["error_summary"] = summary
        if target is not None and as_target:
            payload["target_environment"] = target
        self.state = DiagnosisState.model_validate(payload)
        return result

    @staticmethod
    def _line_observation(item: RegisteredMaterial, piece: Excerpt) -> dict:
        return dict(
            source=Source(kind="artifact", id=item.artifact.artifact_id),
            location=LineLocation(start=piece.start, end=piece.end),
            content=piece.content,
            collected_at=item.registered_at,
            truncated=piece.truncated,
        )

    def parse_log(self, artifact_id: str, context_lines: int = 5) -> ToolResult:
        def operation(item):
            args = ParseLogArguments(artifact_id=artifact_id, context_lines=context_lines)
            if item.artifact.kind != "log":
                raise MaterialError("日志解析只能读取已登记的日志材料。")
            data, pieces, truncated = parse_log(item.text, args.context_lines)
            # Exact error lines remain available even when a surrounding long line is clipped.
            lines = item.text.splitlines()
            error_pieces = [excerpt(lines, e["line"], 1, 1200) for e in data["exceptions"]]
            observations = [
                self._line_observation(item, p) for p in [*error_pieces, *pieces] if p and p.content
            ]
            data["context"] = [
                dict(start=p.start, end=p.end, content=p.content, truncated=p.truncated)
                for p in pieces
            ]
            summary = None
            if data["exceptions"]:
                final = data["exceptions"][-1]
                summary = f"{final['type']}: {final['message']}"
            return data, observations, truncated, None, summary

        return self._run(
            "parse_log",
            artifact_id,
            "提取异常、堆栈和原始行号。",
            operation,
            arguments_summary=f"artifact_id={artifact_id}, context_lines={context_lines}",
        )

    def read_artifact(
        self, artifact_id: str, start_line: int = 1, max_lines: int = 200
    ) -> ToolResult:
        def operation(item):
            args = ReadArtifactArguments(
                artifact_id=artifact_id, start_line=start_line, max_lines=max_lines
            )
            lines = item.text.splitlines()
            piece = excerpt(lines, args.start_line, args.max_lines)
            if piece is None:
                return (
                    {
                        "total_lines": len(lines),
                        "content": "",
                        "start_line": None,
                        "end_line": None,
                    },
                    [],
                    bool(lines),
                    None,
                    None,
                )
            data = dict(
                total_lines=len(lines),
                start_line=piece.start,
                end_line=piece.end,
                content=piece.content,
            )
            observations = [self._line_observation(item, piece)] if piece.content else []
            return data, observations, piece.truncated, None, None

        return self._run(
            "read_artifact",
            artifact_id,
            "读取已登记材料的有限文本片段。",
            operation,
            arguments_summary=(
                f"artifact_id={artifact_id}, start_line={start_line}, max_lines={max_lines}"
            ),
        )

    def inspect_snapshot(self, artifact_id: str, *, as_target: bool = True) -> ToolResult:
        """Host binds an explicit artifact; future model dispatch will resolve environment IDs."""

        def operation(item):
            snapshot, raw = self._snapshot(item)
            target = snapshot.environment
            # Use the original JSON values, so omitted optional fields aren't invented evidence.
            source = Source(kind="snapshot", id=artifact_id, environment_id=target.environment_id)
            observations = [
                dict(
                    source=source,
                    location=FieldLocation(pointer=pointer),
                    content=json.dumps(value, ensure_ascii=False),
                    collected_at=target.collected_at,
                )
                for pointer, value in [
                    ("/environment", raw["environment"]),
                    ("/python_version", raw["python_version"]),
                ]
            ]
            for index, package in enumerate(raw.get("packages", [])):
                observations.append(
                    dict(
                        source=source,
                        location=FieldLocation(pointer=f"/packages/{index}"),
                        content=json.dumps(package, ensure_ascii=False),
                        collected_at=target.collected_at,
                    )
                )
            if raw.get("torch_cuda") is not None:
                observations.append(
                    dict(
                        source=source,
                        location=FieldLocation(pointer="/torch_cuda"),
                        content=json.dumps(raw["torch_cuda"], ensure_ascii=False),
                        collected_at=snapshot.torch_cuda.collected_at,
                    )
                )
            return snapshot.model_dump(mode="json"), observations, False, target, None

        return self._run(
            "inspect_environment",
            artifact_id,
            "读取指定环境快照中的解释器与包元数据。",
            operation,
            as_target=as_target,
            arguments_summary=f"snapshot_artifact_id={artifact_id}, as_target={as_target}",
        )

    def query_gpu(self, artifact_id: str) -> ToolResult:
        def operation(item):
            snapshot, raw = self._snapshot(item)
            source = Source(
                kind="snapshot",
                id=artifact_id,
                environment_id=snapshot.environment.environment_id,
            )
            gpu = snapshot.gpu
            if gpu is None:
                raise ObservationFailure(
                    "unavailable",
                    "快照未包含 GPU 采集结果。",
                    source,
                    snapshot.environment.collected_at,
                )
            if gpu.status != "ok":
                raise ObservationFailure(gpu.status, gpu.error, source, gpu.collected_at)
            # The GPU sample has its own time; querying it never replaces the target environment.
            target = TargetEnvironment(
                **{**snapshot.environment.model_dump(), "collected_at": gpu.collected_at}
            )
            observation = dict(
                source=source,
                location=FieldLocation(pointer="/gpu"),
                content=json.dumps(raw["gpu"], ensure_ascii=False),
                collected_at=gpu.collected_at,
            )
            return raw["gpu"], [observation], False, target, None

        return self._run(
            "query_gpu",
            artifact_id,
            "读取指定快照在采集时刻的 GPU 摘要。",
            operation,
            arguments_summary=f"snapshot_artifact_id={artifact_id}",
        )

    def _snapshot(self, item: RegisteredMaterial):
        if item.artifact.kind != "snapshot":
            raise MaterialError("环境检查只能读取登记为 snapshot 的材料。")
        snapshot, raw = load_snapshot(item.text)
        for record in self.state.tool_history:
            source = record.result.source
            if (
                source.kind == "snapshot"
                and source.environment_id == snapshot.environment.environment_id
                and source.id != item.artifact.artifact_id
            ):
                raise ValueError("ambiguous environment ID")
        return snapshot, raw

    def check_paths(self, references: PathReferences, reference_ids: list[str]) -> ToolResult:
        source = Source(kind="local", id="path_references", environment_id="collector")

        def operation(_item):
            args = CheckPathsArguments(path_reference_ids=reference_ids)
            timestamp = datetime.now(timezone.utc)
            data = {ref: references.inspect(ref) for ref in args.path_reference_ids}
            observations = [
                dict(
                    source=source,
                    location=FieldLocation(pointer=f"/{ref}"),
                    content=json.dumps(value, ensure_ascii=False),
                    collected_at=timestamp,
                )
                for ref, value in data.items()
            ]
            return data, observations, False, None, None

        return self._run(
            "check_paths",
            None,
            "检查显式登记的本机路径引用是否存在及其类型。",
            operation,
            arguments_summary=f"path_reference_ids={reference_ids}",
            local_source=source,
        )

    def search_docs(
        self, query: str, category: Category | None = None, max_results: int = 3
    ) -> ToolResult:
        def operation(_item):
            args = SearchDocsArguments(query=query, category=category, max_results=max_results)
            if self._documents is None:
                self._documents = DocumentIndex()
            matches, total = self._documents.search(args)
            observations = [
                dict(
                    source=Source(
                        kind="document",
                        id=hit["document_id"],
                        url=hit["url"],
                        applicable_version=hit["applicable_version"],
                    ),
                    location=FieldLocation(pointer="/excerpt"),
                    content=hit["excerpt"],
                    collected_at=hit["collected_at"],
                )
                for hit in matches
            ]
            return (
                {
                    "query": args.query,
                    "category": args.category,
                    "matches": matches,
                    "total": total,
                },
                observations,
                total > len(matches),
                None,
                None,
            )

        return self._run(
            "search_docs",
            None,
            "检索本地官方文档摘要，提供带版本的背景资料。",
            operation,
            arguments_summary=(
                f"query={query[:500]!r}, category={category}, max_results={max_results}"
            ),
            local_source=Source(kind="local", id="docs_index", environment_id="collector"),
        )
