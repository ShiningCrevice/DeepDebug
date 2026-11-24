"""Streamlit presentation only; diagnosis uses the shared controller workflow."""

import hashlib
import io
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from deepdebug.agent.schemas import CloudConsent
from deepdebug.agent.state import Budget
from deepdebug.agent.trace import JsonlTrace, TraceEvent
from deepdebug.diagnosis import diagnose
from deepdebug.replay import load_replay, replay_reviewed
from deepdebug.reporting.render import export_report
from deepdebug.security.destination import DEFAULT_BASE_URL, responses_endpoint
from deepdebug.security.review import confirm_materials, preview_materials
from deepdebug.sessions import SavedSession, SessionStore
from deepdebug.tools.builtin_checks import PRESETS
from deepdebug.ui.workflow import ProgressStream, preview_uploads
from deepdebug.verification import verify_report


def _timeline(events: list[dict]) -> None:
    for entry in events:
        state = entry["state"]
        with st.expander(f"{entry['sequence']}. {entry['event']}"):
            st.json(entry["details"])
            if state["hypotheses"]:
                st.json(state["hypotheses"])
            if state["tool_history"]:
                st.json(state["tool_history"][-1])


def _run(review, *, consent=None, budget=None, demo_root=None):
    status = st.empty()
    environment = st.empty()
    timeline = st.container()

    def update(entry):
        state = entry["state"]
        status.info(
            f"阶段：{entry['event']} · 决策 {state['budget']['decision_calls']} 次 · "
            f"工具 {state['budget']['tool_calls']} 次 · 证据 {len(state['evidence'])} 条"
        )
        target = state["target_environment"]
        environment.write(
            f"目标环境：{target['environment_id']}（{target['mode']}，"
            f"采集于 {target['collected_at']}）"
            if target
            else "目标环境：未知，需补充快照。"
        )
        with timeline:
            _timeline([entry])

    stream = ProgressStream(update)
    st.session_state.reviewed = review
    st.session_state.pop("saved_id", None)
    # Discard the preceding run before starting another one.
    for key in ("result", "trace", "events"):
        st.session_state.pop(key, None)
    try:
        if demo_root is not None:
            state = replay_reviewed(
                review, load_replay(demo_root / "examples/dep_002_replay.json"), trace_stream=stream
            )
        else:
            state = diagnose(review, consent, budget=budget, trace_stream=stream)
        st.session_state.result = state
        status.success(f"诊断停止：{state.stop_reason}")
    except (OSError, ValueError):
        status.error("诊断启动失败：检查材料、目的地、模型、密钥及预算配置。")
    finally:
        st.session_state.trace = stream.getvalue()
        st.session_state.events = stream.events


def _downloads() -> None:
    state = st.session_state.get("result")
    if state is not None and state.report is not None:
        json_report, markdown = export_report(state)
        st.subheader("诊断报告")
        st.caption("环境数据描述采集时刻；修复执行状态见报告中的验证结果。")
        st.markdown(markdown)
        st.download_button("下载 Markdown", markdown, "report.md", "text/markdown")
        st.download_button("下载 JSON 报告", json_report, "report.json", "application/json")
    if state is not None:
        if state.report is None:
            st.info("此会话尚无诊断报告，可查看和下载取证状态。")
            st.json(state.model_dump(mode="json"))
        st.download_button(
            "下载完整状态", state.model_dump_json(indent=2), "state.json", "application/json"
        )
    if st.session_state.get("trace"):
        st.download_button(
            "下载运行轨迹", st.session_state.trace, "trace.jsonl", "application/x-ndjson"
        )


def _verification() -> None:
    state = st.session_state.get("result")
    if state is None or state.report is None or not state.report.fixes:
        return
    with st.expander("预置案例修复验证"):
        case = st.selectbox("预置案例", list(PRESETS))
        st.write(PRESETS[case]["fix"])
        st.write("成功判据：" + PRESETS[case]["criteria"])
        st.text(f"执行环境：本机 {sys.executable}")
        index = st.selectbox("关联修复建议", range(1, len(state.report.fixes) + 1))
        st.write(state.report.fixes[index - 1].description)
        st.caption("仅运行开发者固定错误版和修复版；结果不代表用户训练或生成补丁验证。")
        matches = st.checkbox(
            "已核查所选建议与上述预置修复匹配",
            key=f"match_{state.session_id}_{case}_{index}",
        )
        if st.button("运行预置前后对照", disabled=not matches):
            try:
                updated = verify_report(state, case, index, matches_preset=True)
                stream = io.StringIO(st.session_state.get("trace", ""))
                stream.seek(0, io.SEEK_END)
                trace = JsonlTrace(stream)
                trace.sequence = len(st.session_state.get("events", []))
                trace.write("verification", updated, {"case_id": case, "fix_index": index})
                st.session_state.result = updated
                st.session_state.trace = stream.getvalue()
                st.session_state.events = [
                    TraceEvent.model_validate_json(line).model_dump(mode="json")
                    for line in stream.getvalue().splitlines()
                ]
                st.rerun()
            except (OSError, ValueError):
                st.error("预置检查失败，请检查执行环境与当前报告。")


def main() -> None:
    st.set_page_config(page_title="DeepDebug", layout="wide")
    st.title("DeepDebug 故障诊断")
    st.caption("本地单用户 · 默认导入故障环境快照 · 日志、代码和配置只作为诊断材料")
    store = None
    try:
        store = SessionStore(Path("sessions"))
        expired = store.cleanup()
        if expired:
            st.info(f"已清理 {len(expired)} 个超过 7 天未保存的会话。")
    except (OSError, ValueError, KeyError):
        st.error("本地会话目录无法读取或记录损坏；请检查 sessions 目录。")
    if store is not None and st.session_state.get("load_session_id"):
        selected = st.session_state.pop("load_session_id")
        try:
            bundle = store.load(selected)
            st.session_state.result = bundle.state
            st.session_state.reviewed = bundle.review
            st.session_state.trace = bundle.trace
            st.session_state.events = [
                TraceEvent.model_validate_json(line).model_dump(mode="json")
                for line in bundle.trace.splitlines()
            ]
            st.session_state.saved_id = selected
            st.session_state.mode = "已保存会话"
            st.session_state.active_mode = "已保存会话"
        except (OSError, ValueError, KeyError):
            st.error("所选会话无法打开。")
    if st.button("清除当前会话"):
        st.session_state.clear()
        st.rerun()
    mode = st.radio("运行方式", ["上传材料诊断", "离线预置演示", "已保存会话"], key="mode")
    if st.session_state.get("active_mode") != mode:
        for key in ("preview", "reviewed", "result", "trace", "events", "input_digest", "saved_id"):
            st.session_state.pop(key, None)
        st.session_state.active_mode = mode
    ran = False
    if mode == "离线预置演示":
        st.info("演示使用人工固定响应驱动真实工具，不调用模型；修复未执行。")
        root = Path(__file__).resolve().parents[3]
        if st.button("运行依赖案例演示"):
            try:
                preview = preview_materials(
                    root / "benchmark/dev/dep_002/materials",
                    "log.txt",
                    [],
                    ["launch.json"],
                    ["target_snapshot.json", "project_snapshot.json"],
                )
                _run(confirm_materials(preview), demo_root=root)
                ran = True
            except (OSError, ValueError):
                st.error("演示材料不可读取；请从项目源码目录启动。")
    elif mode == "上传材料诊断":
        pasted = st.text_area("粘贴日志", key="pasted_log")
        uploaded = []
        for kind, label, extensions, multiple in (
            ("log", "或上传日志", ["txt", "log"], False),
            ("code", "源码片段", ["py"], True),
            ("config", "配置", ["json", "yaml", "yml"], True),
            ("snapshot", "环境快照（第一份为目标环境）", ["json"], True),
        ):
            files = st.file_uploader(
                label, type=extensions, accept_multiple_files=multiple, key=kind
            )
            for item in (files or []) if multiple else ([files] if files else []):
                uploaded.append((item.name, item.getvalue(), kind))
        digest = hashlib.sha256(pasted.encode("utf-8"))
        for name, content, kind in uploaded:
            for part in (name.encode(), content, kind.encode()):
                digest.update(len(part).to_bytes(8, "big"))
                digest.update(part)
        signature = digest.hexdigest()
        if st.session_state.get("input_digest") != signature:
            for key in ("preview", "reviewed", "result", "trace", "events", "saved_id"):
                st.session_state.pop(key, None)
            st.session_state.input_digest = signature
        if st.button("生成脱敏预览"):
            try:
                st.session_state.preview = preview_uploads(pasted, uploaded)
            except (OSError, ValueError):
                st.error("材料无效：选择一份日志，最多 10 份 UTF-8 材料，每份不超过 2 MiB。")
        preview = st.session_state.get("preview")
        if preview is not None:
            st.subheader("核查脱敏材料")
            st.warning(
                "自动脱敏可能遗漏，请核查每份正文和材料范围。云端诊断会将选取的内容发送至下方目的地。"
            )
            for item in preview.content.materials:
                with st.expander(
                    f"{item.artifact.display_name} · {item.artifact.kind}", expanded=True
                ):
                    st.code(item.text, language="text", line_numbers=True)
            reviewed = st.checkbox("我已核查全部脱敏内容与材料范围", key=f"review_{preview.sha256}")
            load_dotenv(Path.cwd() / ".env", override=False)
            base_url = st.text_input(
                "API 基础地址", value=os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
            )
            model = st.text_input("模型 ID")
            try:
                endpoint = responses_endpoint(base_url)
                st.text(f"发送目的地：{endpoint}")
                if endpoint.startswith("http://"):
                    st.warning("该 HTTP 地址会明文传输凭据和材料。")
            except ValueError:
                endpoint = None
                st.error("API 基础地址无效。")
            with st.expander("调用预算"):
                decisions = st.number_input("最多决策次数", min_value=1, value=6)
                tools = st.number_input("最多工具次数", min_value=1, value=8)
                tokens = st.number_input(
                    "总 token 上限（含 5,000 报告预留）", min_value=5000, value=50000
                )
                seconds = st.number_input("总时限（秒）", min_value=1, value=120)
            if st.button("授权发送并开始诊断", disabled=not (reviewed and endpoint and model)):
                try:
                    consent = CloudConsent(
                        material_review_sha256=preview.sha256,
                        endpoint=endpoint,
                        model=model,
                        confirmed_at=datetime.now(timezone.utc),
                    )
                    budget = Budget(
                        max_decision_calls=decisions,
                        max_tool_calls=tools,
                        max_tokens=tokens,
                        max_duration_seconds=seconds,
                    )
                    _run(confirm_materials(preview), consent=consent, budget=budget)
                    ran = True
                except ValueError:
                    st.error("模型 ID 或预算配置无效。")
    else:
        st.info("从下方保存列表打开会话，查看其材料、报告和轨迹。")
        if st.session_state.get("reviewed") is not None:
            for item in st.session_state.reviewed.content.materials:
                with st.expander(f"已保存材料：{item.artifact.display_name}"):
                    st.code(item.text, language="text", line_numbers=True)
    if not ran and st.session_state.get("events"):
        st.subheader("工具与决策时间线")
        _timeline(st.session_state.events)
    _verification()
    _downloads()
    if store is not None:
        _saved_sessions(store)


def _saved_sessions(store: SessionStore) -> None:
    with st.expander("保存与打开本地会话"):
        st.caption("会话保存到本机 sessions 目录；从最后保存起保留 7 天，打开页面时清理过期记录。")
        try:
            if st.session_state.get("result") is not None and st.button("保存当前会话"):
                bundle = SavedSession(
                    saved_at=datetime.now(timezone.utc),
                    state=st.session_state.result,
                    review=st.session_state.get("reviewed"),
                    trace=st.session_state.get("trace", ""),
                )
                st.session_state.saved_id = store.save(bundle, st.session_state.get("saved_id"))
                st.success("会话已保存。")
            saved = dict(store.list_sessions())
            if saved:
                selected = st.selectbox(
                    "已保存会话",
                    list(saved),
                    format_func=lambda key: (
                        f"{saved[key].saved_at.isoformat()} · {saved[key].state.session_id}"
                    ),
                )
                if st.button("打开选中会话"):
                    st.session_state.load_session_id = selected
                    st.rerun()
                if st.button("删除选中会话"):
                    store.delete(selected)
                    if st.session_state.get("saved_id") == selected:
                        for key in ("result", "reviewed", "trace", "events", "saved_id"):
                            st.session_state.pop(key, None)
                    st.rerun()
        except (OSError, ValueError, KeyError):
            st.error("会话保存/读取失败，请检查文件权限与状态、确认副本和轨迹的一致性。")
