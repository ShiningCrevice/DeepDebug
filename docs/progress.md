# 开发进度

## 当前量化进度（2026-10-30）

| 指标 | 当前结果 | 剩余缺口 |
|---|---|---|
| 完整验收里程碑 | 0 / 6 | 第 1 周缺其他四类真实种子案例 |
| 第 1 周验收项 | 2 / 3 | 协议和人工参考诊断已完成；五类种子未齐 |
| 第 2 周验收项 | 1 / 3 | CLI 已返回带证据 ID 的工具结果；超时/GPU 降级和文档检索尚未完成 |
| 开发案例类别覆盖 | 1 / 5 | 两个案例均属于依赖/解释器类别 |
| 自动诊断端到端案例 | 0 / 5 | 当前只跑通两个案例的取证，不含模型循环 |
| 文档语料 | 0 / 15～25 | 尚未整理与检索 |

整体工程完成度估算 **约 20%（18%～22%）**：按规划 72 小时权重，以第 1 周完成 75%～85%、第 2 周完成 45%～60% 折算，其他周暂不计完成量。该比例衡量工程交付，不表示实耗工时或诊断效果。

当前完成第 1 周的协议与人工参考诊断、第 2 周的 CLI 取证。取证输出未经脱敏，仅供本地检查；自动诊断、用户环境采集、GPU 探测、路径引用检查、检索、工具超时和预算停止仍待实现。Windows 取证暂不支持。

各步验证环境为 Linux / Python 3.12.3，其他平台与 Python 版本未验证。检查命令见 [README](../README.md#开发检查)；受限环境使用 `UV_CACHE_DIR=/tmp/deepdebug-uv-cache`。历史安装或构建曾因网络受限、构建缓存缺失而失败，补齐既有依赖后通过；离线复现需要先准备依赖缓存。

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
