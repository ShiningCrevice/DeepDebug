# 开发进度

## 当前量化进度（2026-11-01）

| 指标 | 当前结果 | 剩余缺口 |
|---|---|---|
| 完整验收里程碑 | 0 / 6 | 第 1 周缺其他四类真实种子案例 |
| 第 1 周验收项 | 2 / 3 | 协议和人工参考诊断已完成；五类种子未齐 |
| 第 2 周验收项 | 2 / 3 | CLI 带证据 ID 的结果、路径越界/探针超时/无 GPU 降级已完成；缺本地文档检索 |
| 开发案例类别覆盖 | 1 / 5 | 两个案例均属于依赖/解释器类别 |
| 自动诊断端到端案例 | 0 / 5 | 当前只跑通两个案例的取证，不含模型循环 |
| 文档语料 | 0 / 15～25 | 尚未整理与检索 |

整体工程完成度估算 **约 24%（22%～25%）**：按规划 72 小时权重，以第 1 周完成 75%～85%、第 2 周完成 70%～80% 折算，其他周暂不计完成量。该比例衡量工程交付，不表示实耗工时或诊断效果。

当前完成第 1 周的协议与人工参考诊断、第 2 周的 CLI 取证及工具边界/降级。取证输出未经脱敏，仅供本地检查；其余四类种子、文档检索、自动诊断和会话预算停止仍待实现。Windows 取证与探针执行暂不支持；真实 GPU 成功采集未验证。

各步验证环境为 Linux / Python 3.12.3，其他平台与 Python 版本未验证。检查命令见 [README](../README.md#开发检查)；受限环境使用 `UV_CACHE_DIR=/tmp/deepdebug-uv-cache`。历史安装或构建曾因网络受限、构建缓存缺失而失败，补齐既有依赖后通过；离线复现需要先准备依赖缓存。

## Step 06 — 用户环境采集、路径引用与 GPU 降级（2026-11-01）

新增能力：

- `snapshot`：指定解释器采集 Python、包元数据及可选 PyTorch/CUDA、GPU 信息，输出可导入的环境快照。
- `collect --path`：检查已登记路径的存在性、文件/目录类型和授权边界；可通过 `--path-root` 指定基准目录。
- `collect --query-gpu`：读取快照中的 GPU 摘要，保留不可用、超时和错误状态及原始采样时间。
- 固定环境探针具备超时、输出限制和进程回收，部分采集失败时保留已取得的 Python 信息。

完成范围：

- `src/deepdebug/tools/capture.py`、`process.py`：显式指定解释器，用固定 `-I` 探针在临时工作目录采集 Python 与选定包元数据；可选 PyTorch/CUDA 和系统 `nvidia-smi` 摘要。元数据限时 10 秒，其余探针各 15 秒，进程合并输出最多 64 KiB；超时/超限终止并回收探针，失败保留独立状态。
- `src/deepdebug/agent/schemas.py`：扩展兼容旧快照的可选 `torch_cuda/gpu` 字段，校验探针状态、采样时间及 GPU 数据，区分未采集、不可用、超时和错误。
- `src/deepdebug/security/paths.py`、`tools/path_references.py`：登记最多 10 个显式路径引用，按 ID 查询存在性、类型和授权基准目录；复用 POSIX 根目录描述符，拒绝越界、隐藏路径、链接、特殊文件及 gold，不读取内容或列出目录。
- `src/deepdebug/tools/session.py`：新增快照 `query_gpu` 与本机 `check_paths`，沿用证据编号、完整状态校验和工具记录；保留 GPU 采样时间，路径证据标记 `local/collector`，不替换目标环境。
- `src/deepdebug/cli.py`、`collection.py`、`scripts/collect_environment.py`：新增 `snapshot` 及脚本入口，接通 `collect --query-gpu/--path/--path-root`；明确部分采集失败与无快照输出的退出码。
- `tests/test_environment_capture.py`、`tests/test_path_and_gpu_tools.py`：新增 51 项检查，覆盖真实空虚拟环境、项目同名模块隔离、子进程超时/超限与回收、GPU 状态与原始证据、路径权限和环境来源。
- `README.md`、`AGENTS.md`、`docs/tool-api.md`、`docs/design.md`、`scripts/README.md`：同步使用方式、协议、进度及实际限制。

验证结果：

- Ruff 检查与格式检查、pytest **149 项**、`git diff --check` 通过。
- 用户采集脚本实跑：Python 3.12.3、pydantic 2.14.1，torch 元数据 `not_found`；PyTorch 与 `nvidia-smi` 均不可用，快照保留 Python 信息，退出码 `1`。
- 导出后再导入 CLI：2 份材料、8 条证据、4 次工具调用；GPU `unavailable`、路径存在/缺失结果分别为 `true/false`，目标保持 `DEV_LOCAL`，`report=null`。
- 原 `dep_002` CLI 实跑保持 5 份材料、10 条证据、5 次成功工具调用，目标 `ENV_EMPTY`。

阶段限制：GPU 成功解析和 CPU-only PyTorch 返回使用固定响应测试，真实 GPU/PyTorch 成功采集未验证。路径观察来自命令运行主机，不代表远端快照环境。总会话预算与模型调度仍待实现。

下一步：补齐其余四类真实故障种子及本地文档检索，完成第 1～2 周剩余验收项后推进模型循环。

## Step 05 — 文档表述整理（2026-10-30）

完成范围：

- `docs/progress.md`：为各步补充主要代码文件，合并重复限制，验证结果保留检查结论和关键实跑数据。
- `README.md`、`docs/design.md`、`docs/tool-api.md`：精简重复说明，将能力限制放在相关接口或结果旁。
- `AGENTS.md`：明确进度记录的文件定位与验证摘要要求。

验证结果：Ruff 检查与格式检查、pytest **98 项**、`git diff --check` 通过。

下一步：完善用户环境采集、路径引用检查和无 GPU 降级，再补齐其余故障种子与文档检索。

## Step 04 — 结构精简（2026-10-30）

完成范围：

- `src/deepdebug/tools/environment.py`、`src/deepdebug/tools/session.py`：快照 JSON 解析一次，返回校验模型与原始值；会话统一记录错误，保留重复键、模式、结构及嵌套过深的错误处理。
- `src/deepdebug/tools/artifacts.py`：删除被 2 MiB 字节上限覆盖的字符数检查，保留 UTF-8 与 NUL 检查。
- 删除 `src/deepdebug/llm/__init__.py`、`src/deepdebug/reporting/__init__.py` 两个无实现、无调用的占位包，随对应功能创建。
- `tests/test_collection.py`：新增 4 项检查，覆盖 ASCII/多字节文本大小边界、嵌套过深的 JSON 错误，以及快照证据保留原始值。

验证结果：

- Ruff 检查与格式检查、pytest **98 项**、`git diff --check` 通过。
- `uv build` 通过，生成 sdist 和 wheel。

下一步：完善用户环境采集、路径引用检查和无 GPU 降级，再补齐其余故障种子与文档检索。

## Step 03 — CLI 只读取证与材料边界（2026-10-28）

完成范围：

- `src/deepdebug/cli.py`、`src/deepdebug/collection.py`：新增 `collect`，显式登记日志、代码、配置及快照，输出带工具记录的状态 JSON。
- `src/deepdebug/security/paths.py`：用 POSIX 目录描述符逐级读取文件，拒绝路径越界、链接、非普通文件、隐藏路径、仓库根目录与 benchmark 答案目录。
- `src/deepdebug/tools/artifacts.py`：登记时固定材料内容，限制单文件 2 MiB、每会话 10 份和 UTF-8 编码；文本读取最多 200 行、16,000 字符。
- `src/deepdebug/tools/log_parser.py`、`src/deepdebug/tools/environment.py`：提取异常、有限堆栈及原始行号；读取快照并保留环境标识、采集时间。
- `src/deepdebug/tools/session.py`、`src/deepdebug/agent/evidence.py`、`src/deepdebug/agent/schemas.py`：按内容与来源去重复用证据 ID，登记本地材料来源；工具失败进入历史，完整结果限制 64 KiB，每次更新重校验状态。目标快照无效时保持目标未知。
- `tests/test_collection.py`：新增 35 项工具与集成检查，覆盖文件边界、材料限制、证据位置、快照错误、日志截断及输入代码只读。

验证结果：

- Ruff 检查与格式检查、pytest **94 项**、`git diff --check` 通过；两个开发案例取证通过集成测试。
- CLI 实跑 `dep_002`：5 份材料、10 条证据、5 次成功工具调用，目标为 `ENV_EMPTY`，`report=null`。
- `uv build` 通过，生成 sdist 和 wheel；运行依赖及锁文件保持不变。

下一步：完善用户环境采集、路径引用检查和无 GPU 降级，并推进其余故障种子与文档检索。

## Step 02 — 数据协议与依赖开发案例（2026-10-28）

完成范围：

- `src/deepdebug/agent/schemas.py`、`src/deepdebug/agent/actions.py`、`src/deepdebug/agent/state.py`：用 Pydantic 定义材料、证据、快照、动作、工具结果、预算、状态和报告；校验工具参数、跨记录引用及验证状态。
- `src/deepdebug/cli.py`：新增 `schema action/state/report/snapshot`，导出 JSON Schema。
- `scripts/capture_dependency_cases.py`、`benchmark/dev/dep_001/`、`benchmark/dev/dep_002/`：采集两个相同缺包日志、不同环境上下文的案例，记录来源、时间和路径替换；两例同属一个案例族，均留在开发集。
- `benchmark/gold/dev/`：保存人工参考状态与报告，与输入材料分开；修复验证为“未执行”。
- `tests/test_protocols.py`、`tests/test_dev_cases.py`、`tests/test_cli.py`：覆盖动作白名单、字段限制、引用和验证状态、JSON 往返、Schema 导出及原始证据位置。

验证结果：

- Ruff 检查与格式检查、pytest **59 项**、`git diff --check` 通过。
- 采集脚本取得两个真实失败日志及目标/项目快照，路径替换为 `/demo/` 别名。
- `uv build --offline` 通过，生成 sdist 和 wheel；运行依赖及锁文件保持不变。

阶段范围：协议负责结构与一致性校验；文件权限、脱敏、预算执行和证据语义由后续工具与控制器落实。案例覆盖 Python 依赖导入，未执行修复或 PyTorch/GPU 训练。

下一步：实现材料登记与路径权限、保留行号的日志解析、快照读取、稳定证据编号，并通过 CLI 展示取证结果。

## Step 01 — 项目初始化（2026-10-27）

完成范围：

- `src/deepdebug/cli.py`、`src/deepdebug/__main__.py`：建立 `src/` 包和 CLI，支持帮助、版本及模块启动。
- `pyproject.toml`、`uv.lock`、`.python-version`：配置 Python 版本、uv、Pydantic v2、pytest、Ruff 和构建后端，锁定依赖。
- `src/deepdebug/`、`benchmark/`：预留 Agent、工具、权限、模型接口、报告、案例和评测目录。
- `README.md`、`AGENTS.md`、`docs/design.md`、`.env.example`、`.gitignore`：记录开发约定、架构决策、环境配置及敏感数据忽略规则。
- `tests/test_cli.py`：检查安装入口、模块入口和未知命令拒绝。

验证结果：

- `uv sync`、Ruff 检查与格式检查、pytest **3 项**通过；`deepdebug --help` 显示初始化说明。
- `uv build --offline` 通过，生成 sdist 和 wheel。

下一步：准备缺少依赖与错误解释器两个开发案例，定义材料、工具返回、状态、动作与报告协议。
