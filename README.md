# DeepDebug Agent

面向 PyTorch 训练与推理故障的诊断助手。目标是根据日志、代码、配置和环境快照，按需补充证据，输出可追溯的候选根因、修复建议和验证方法。

**当前状态：初始化完成，尚不支持诊断。** 本阶段提供可安装的 Python 包、CLI 入口、依赖锁文件与开发检查。完整范围见 [项目规划](DeepDebug_planning.md)，逐步交付记录见 [开发进度](docs/progress.md)。规划中的指标是目标，不是实验结果。

## 环境与启动

需要 Python 3.10+ 和 uv。本仓库默认开发解释器为 Python 3.12（`.python-version`）；当前实际验证环境为 Linux / Python 3.12。无需 GPU、PyTorch 或 API key。

```bash
uv sync --locked
uv run --locked deepdebug --help
uv run --locked deepdebug --version
uv run --locked python -m deepdebug
```

`uv sync` 创建项目内 `.venv`，安装项目与开发依赖；首次安装需要可用的包源。若使用其他兼容解释器，可执行 `uv sync --locked --python 3.10`。依赖精确版本保存在 `uv.lock`。初始化阶段不读取 `.env`，`.env.example` 仅说明后续配置位置。

## 开发检查

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv build
```

测试覆盖安装后的命令行入口和模块入口，以及未实现命令的拒绝行为；此阶段不代表任何诊断效果验证。

## 目录与后续实现

| 路径 | 职责 |
|---|---|
| `src/deepdebug/cli.py` | 命令行参数与入口 |
| `src/deepdebug/agent/` | 后续状态、协议与单 Agent 控制器 |
| `src/deepdebug/tools/` | 后续日志解析、材料读取、环境探针等 |
| `src/deepdebug/security/` | 后续路径权限与脱敏 |
| `src/deepdebug/llm/` | 后续统一模型接口 |
| `src/deepdebug/reporting/` | 后续报告校验与导出 |
| `tests/` | 自动化检查 |
| `docs/` | 架构决策与逐步进度 |
| `examples/`、`knowledge/`、`benchmark/`、`scripts/` | 案例、语料、评测与固定采集脚本的预留位置 |

预留包当前只包含职责说明。Streamlit、模型 SDK 和检索依赖在对应阶段引入。

## 范围与边界

首版聚焦 OOM、设备不一致、依赖/解释器、路径和配置/形状五类问题。采用单 Agent 状态机，默认导入环境快照；本机采集需要用户明确选择。模型不得执行任意代码或 shell、安装依赖、修改用户文件或重跑真实训练。上传材料和检索文档均是不可信数据。

后续工具需要在代码中落实材料登记、路径白名单、预算与证据校验；目录骨架本身尚未提供这些权限控制。内置验证只针对开发者维护的预置案例，不能等同于真实训练恢复。运行数据保存在忽略的 `runs/`、`sessions/`，不得提交真实密钥和私有日志。

下一步：准备“缺少依赖”和“检查了错误解释器”两个开发案例，定义材料、证据、动作、工具结果、状态与报告的 Pydantic 协议。
