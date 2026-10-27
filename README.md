# DeepDebug Agent

面向 PyTorch 训练与推理故障的诊断助手。目标是根据日志、代码、配置和环境快照，按需补充证据，输出可追溯的候选根因、修复建议和验证方法。

**当前状态：完成初始化、数据协议与两个开发案例，尚不支持自动诊断。** 已提供 Pydantic 校验、JSON Schema 导出，以及真实采集的依赖导入失败材料和人工参考报告。完整范围见 [项目规划](DeepDebug_planning.md)，逐步交付记录见 [开发进度](docs/progress.md)。规划中的指标是目标，不是实验结果。

## 环境与启动

需要 Python 3.10+ 和 uv。本仓库默认开发解释器为 Python 3.12（`.python-version`）；当前实际验证环境为 Linux / Python 3.12。无需 GPU、PyTorch 或 API key。

```bash
uv sync --locked
uv run --locked deepdebug --help
uv run --locked deepdebug --version
uv run --locked python -m deepdebug
uv run --locked deepdebug schema action
```

`uv sync` 创建项目内 `.venv`，安装项目与开发依赖；首次安装需要可用的包源。若使用其他兼容解释器，可执行 `uv sync --locked --python 3.10`。依赖精确版本保存在 `uv.lock`。初始化阶段不读取 `.env`，`.env.example` 仅说明后续配置位置。

## 开发检查

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv build
```

测试覆盖 CLI、协议非法输入、报告引用与验证状态、案例证据的原始位置。此阶段不代表诊断效果评测。

## 数据协议与开发案例

`deepdebug schema <kind>` 输出 JSON Schema，`kind` 可选 `action`、`state`、`report`、`snapshot`。接口字段及约束见 [协议说明](docs/tool-api.md)。

两个开发案例位于 `benchmark/dev/dep_001` 与 `dep_002`。它们具有相同的 `ModuleNotFoundError` 日志，分别通过环境快照和启动配置体现“目标环境缺包”与“使用了错误解释器”。日志和快照来自实际 Python 进程，未执行 PyTorch 训练；所有 `/demo/` 路径均为脱敏别名，不能直接执行。案例分属同一案例族，均留在开发集。

[人工参考报告与说明](benchmark/gold/dev/README.md) 仅供开发与评测，修复验证均为“未执行”，不能作为 Agent 可读取的材料。材料目录只存放输入。

可在离线环境重新采集到一个**尚不存在**的目录：

```bash
uv run --locked python scripts/capture_dependency_cases.py runs/dependency-capture
```

脚本创建临时空虚拟环境、运行固定依赖导入程序，并查询当前项目环境的 pydantic 元数据；不安装包。现有输出目录会被拒绝。新采集的时间、版本可能变化，不会自动更新仓库中的参考答案。

## 目录与后续实现

| 路径 | 职责 |
|---|---|
| `src/deepdebug/cli.py` | 命令行参数与入口 |
| `src/deepdebug/agent/` | 已实现协议、动作校验与状态；控制器待实现 |
| `src/deepdebug/tools/` | 后续日志解析、材料读取、环境探针等 |
| `src/deepdebug/security/` | 后续路径权限与脱敏 |
| `src/deepdebug/llm/` | 后续统一模型接口 |
| `src/deepdebug/reporting/` | 后续报告校验与导出 |
| `tests/` | 自动化检查 |
| `docs/` | 架构决策与逐步进度 |
| `benchmark/`、`scripts/` | 两个开发案例、人工参考状态和开发案例采集脚本 |
| `examples/`、`knowledge/` | 演示材料与文档语料的预留位置 |

工具、权限、模型与报告渲染包仍为预留位置。Streamlit、模型 SDK 和检索依赖在对应阶段引入。

## 范围与边界

首版聚焦 OOM、设备不一致、依赖/解释器、路径和配置/形状五类问题。采用单 Agent 状态机，默认导入环境快照；本机采集需要用户明确选择。模型不得执行任意代码或 shell、安装依赖、修改用户文件或重跑真实训练。上传材料和检索文档均是不可信数据。

当前已检查协议字段、引用一致性和验证状态所需记录；尚未实现文件访问控制、实际文件大小检查、脱敏流程、预算执行或证据语义判断。后续工具必须落实这些约束。内置验证只针对开发者维护的预置案例，不能等同于真实训练恢复。运行数据保存在忽略的 `runs/`、`sessions/`，不得提交真实密钥和私有日志。

下一步：实现材料登记与路径权限、日志解析、快照读取和证据编号，通过 CLI 展示真实取证结果；随后再接入模型决策循环。
