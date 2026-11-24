"""Single-agent loop with host-owned facts, bounded decisions and local replay."""

from collections.abc import Callable
from time import monotonic

from pydantic import ValidationError

from deepdebug.agent.actions import ParseLogAction, ParseLogArguments
from deepdebug.agent.decision import INSTRUCTIONS, Conclusion, Decision
from deepdebug.agent.schemas import DiagnosisReport, Verification
from deepdebug.agent.state import DiagnosisState
from deepdebug.agent.trace import JsonlTrace
from deepdebug.llm.client import ModelClient, ModelFailure, ModelRequest, ModelResponse
from deepdebug.llm.openai import OpenAIResponsesClient
from deepdebug.tools.registry import ToolDispatcher


class Controller:
    def __init__(
        self,
        dispatcher: ToolDispatcher,
        model: ModelClient,
        *,
        trace: JsonlTrace | None = None,
        clock: Callable[[], float] = monotonic,
    ):
        if model.transport != "offline":
            if not isinstance(model, OpenAIResponsesClient):
                raise ValueError("云端模型需要已确认的发送边界与内置适配器。")
            model.boundary.validate_dispatcher(dispatcher)
        self.dispatcher = dispatcher
        self.session = dispatcher.session
        self.model = model
        self.trace = trace
        self.clock = clock
        self.started = clock()
        self.initial_elapsed = self.session.state.budget.elapsed_ms

    @property
    def state(self) -> DiagnosisState:
        return self.session.state

    def _update(self, **changes) -> None:
        self.session.state = DiagnosisState.model_validate({**self.state.model_dump(), **changes})

    def _tick(self) -> None:
        budget = self.state.budget.model_dump()
        budget["elapsed_ms"] = self.initial_elapsed + max(
            0, int((self.clock() - self.started) * 1000)
        )
        self._update(budget=budget)

    def _event(self, event: str, **details) -> None:
        self._tick()
        if self.trace is not None:
            self.trace.write(event, self.state, details)

    def _exhausted(self, *, calls: bool = True) -> bool:
        self._tick()
        budget = self.state.budget
        return (
            budget.elapsed_ms >= budget.max_duration_seconds * 1000
            or budget.tokens_used >= budget.max_tokens - budget.reserved_report_tokens
            or (
                calls
                and (
                    budget.decision_calls >= budget.max_decision_calls
                    or budget.tool_calls >= budget.max_tool_calls
                )
            )
        )

    @staticmethod
    def _report(
        state: DiagnosisState,
        reason: str,
        conclusion: Conclusion | None = None,
        questions: list[str] | None = None,
    ) -> DiagnosisReport:
        return DiagnosisReport(
            materials=state.inputs,
            session_id=state.session_id,
            summary=conclusion.summary if conclusion else (state.error_summary or "诊断已停止。"),
            category=conclusion.category if conclusion else "unknown",
            target_environment=state.target_environment,
            evidence=state.evidence,
            hypotheses=state.hypotheses,
            fixes=conclusion.fixes if conclusion else [],
            verifications=[
                Verification(
                    check_id="none",
                    status="未执行",
                    reason=(
                        "预置检查结果见工具记录；尚未确认建议匹配，未关联修复验证。"
                        if any(r.tool == "run_builtin_check" for r in state.tool_history)
                        else "本次仅执行只读取证，未运行修复验证。"
                    ),
                )
            ],
            unresolved_questions=list(
                dict.fromkeys(
                    [*(questions or []), *(conclusion.unresolved_questions if conclusion else [])]
                )
            ),
            tool_history=state.tool_history,
            stop_reason=reason,
        )

    def _stop(
        self,
        reason: str,
        *,
        conclusion: Conclusion | None = None,
        questions: list[str] | None = None,
    ) -> DiagnosisState:
        self._tick()
        report = self._report(self.state, reason, conclusion, questions)
        self._update(next_action=None, stop_reason=reason, report=report)
        self._event("stop", reason=reason)
        return DiagnosisState.model_validate(self.state)

    def run(self, log_artifact_id: str, *, resume: bool = False) -> DiagnosisState:
        DiagnosisState.model_validate(self.state)
        if self.state.stop_reason is not None or (self.state.tool_history and not resume):
            raise ValueError("控制器需要新登记或经过续跑准备的会话。")
        self._event("resume" if resume else "start", mode=self.model.transport)
        if self._exhausted():
            return self._stop("budget_exhausted", questions=["资源预算不足，尚未完成取证。"])
        if not resume:
            initial = ParseLogAction(
                tool="parse_log",
                arguments=ParseLogArguments(artifact_id=log_artifact_id),
                purpose="首轮固定解析失败日志。",
            )
            result, _ = self.dispatcher.dispatch(initial)
            self._event(
                "tool",
                action=initial.model_dump(mode="json"),
                tool_call_id=result.tool_call_id,
                cached=False,
            )
        correction = None
        repaired = False
        retried = False
        idle_rounds = 0
        while True:
            if self._exhausted():
                return self._stop("budget_exhausted", questions=["预算已耗尽，候选原因仍需验证。"])
            budget = self.state.budget.model_dump()
            budget["decision_calls"] += 1
            self._update(budget=budget)
            request = ModelRequest(
                instructions=INSTRUCTIONS,
                state=DiagnosisState.model_validate(self.state),
                environments=dict(self.dispatcher.environments),
                path_reference_ids=self.dispatcher.path_reference_ids,
                response_schema=Decision.model_json_schema(),
                correction=correction,
                timeout_seconds=(
                    self.state.budget.max_duration_seconds - self.state.budget.elapsed_ms / 1000
                ),
                max_tokens=(
                    self.state.budget.max_tokens
                    - self.state.budget.reserved_report_tokens
                    - self.state.budget.tokens_used
                ),
            )
            self._event(
                "model_request",
                correction=correction,
                timeout_seconds=request.timeout_seconds,
                max_tokens=request.max_tokens,
            )
            # Schema construction and trace I/O also consume the session deadline.
            if self._exhausted(calls=False):
                return self._stop("budget_exhausted", questions=["模型调用前预算已耗尽。"])
            request.timeout_seconds = (
                self.state.budget.max_duration_seconds - self.state.budget.elapsed_ms / 1000
            )
            try:
                response = ModelResponse.model_validate(self.model.decide(request))
            except ValidationError:
                self._event("model_error", kind="invalid_response")
                return self._stop("model_error", questions=["模型接口返回了无效响应或用量字段。"])
            except ModelFailure as exc:
                if exc.usage_unknown:
                    budget = self.state.budget.model_dump()
                    budget["usage_complete"] = False
                    self._update(budget=budget)
                self._event("model_error", kind=exc.kind, usage_unknown=exc.usage_unknown)
                if exc.kind == "budget":
                    return self._stop("budget_exhausted", questions=["剩余请求额度不足。"])
                if self._exhausted():
                    return self._stop("budget_exhausted", questions=["模型请求期间预算耗尽。"])
                if exc.kind in {"timeout", "unavailable"} and not retried:
                    retried = True
                    continue
                return self._stop("model_error", questions=["模型接口失败，诊断未完成。"])
            budget = self.state.budget.model_dump()
            budget["tokens_used"] += response.tokens_used
            self._update(budget=budget)
            self._event(
                "model_response",
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
            if self._exhausted(calls=False):
                return self._stop("budget_exhausted", questions=["模型响应到达时预算已耗尽。"])
            if response.failure is not None:
                self._event("model_error", kind=response.failure)
                return self._stop("model_error", questions=["模型未返回完整诊断决策。"])
            try:
                decision = Decision.model_validate_json(response.content)
                candidate = DiagnosisState.model_validate(
                    {
                        **self.state.model_dump(),
                        "hypotheses": decision.hypotheses,
                        "next_action": decision.action,
                    }
                )
                if decision.action.action == "finish":
                    # Validate references before accepting any part of this decision.
                    self._report(candidate, decision.action.stop_reason, decision.conclusion)
                elif decision.action.action == "need_info":
                    self._report(
                        candidate, "need_info", decision.conclusion, decision.action.questions
                    )
            except (ValidationError, ValueError):
                self._event("invalid_decision", correction_available=not repaired)
                if repaired:
                    return self._stop(
                        "invalid_action", questions=["模型修正后仍有无效动作或证据引用。"]
                    )
                repaired = True
                correction = "输出无效；请按 Schema 修正动作、结论和已登记证据/假设引用。"
                continue
            correction = None
            before_hypotheses = self.state.hypotheses
            before_evidence = len(self.state.evidence)
            self.session.state = candidate
            self._event("decision", observation=decision.observation)
            action = decision.action
            if action.action == "finish":
                return self._stop(action.stop_reason, conclusion=decision.conclusion)
            if action.action == "need_info":
                return self._stop(
                    "need_info", conclusion=decision.conclusion, questions=action.questions
                )
            # Dispatch is permitted for the last decision, but never past time/token/tool limits.
            if self._exhausted(calls=False) or (
                self.state.budget.tool_calls >= self.state.budget.max_tool_calls
            ):
                return self._stop("budget_exhausted", questions=["工具执行前预算已耗尽。"])
            result, cached = self.dispatcher.dispatch(action)
            self._update(next_action=None)
            self._event(
                "tool",
                action=action.model_dump(mode="json"),
                tool_call_id=result.tool_call_id,
                cached=cached,
            )
            changed = (
                len(self.state.evidence) != before_evidence
                or self.state.hypotheses != before_hypotheses
            )
            idle_rounds = 0 if changed else idle_rounds + 1
            if self._exhausted(calls=False):
                return self._stop("budget_exhausted", questions=["工具返回时预算已耗尽。"])
            if idle_rounds >= 2:
                return self._stop("no_progress", questions=["连续两轮无新证据或假设变化。"])
