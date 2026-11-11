# 开发进度

本文集中记录各 Step 的改动、实际验证、验收进展和下一步。历史条目描述当时状态；当前架构见 [架构设计](design.md)，当前接口见 [工具协议](tool-api.md)。

## 当前量化进度（2026-11-11）

| 指标 | 当前结果 | 剩余缺口 |
|---|---|---|
| 完整验收里程碑 | 2 / 6 | 第 1、2 周已验收；第 3～6 周待完成 |
| 第 1 周验收项 | 3 / 3 | 六个真实开发案例覆盖五类，协议和人工参考诊断已完成 |
| 第 2 周验收项 | 3 / 3 | CLI 真实工具结果、路径越界/探针超时/无 GPU 降级、文档引用与版本标注已完成 |
| 第 3 周验收项 | 2 / 4 | 预算停止与工具轨迹完成；假设变化已有固定响应演示，真实模型假设更新及五类端到端报告待验收 |
| 开发案例类别覆盖 | 5 / 5 | 共六例；两个依赖案例同族；尚未扩充和冻结测试集 |
| 自动诊断端到端案例 | 0 / 5 | dep_002 离线回放已跑通；固定响应不计入真实模型诊断 |
| 文档语料 | 15 / 15～25 | 五类各 3 条，达到 MVP 数量下限；检索效果尚未做 benchmark 评测 |

整体工程完成度估算 **约 40%（29/72）**：按规划权重，第 1、2 周的 22 份已完成交付，加第 3 周模型接口、离线循环、预算与轨迹估算 7 份。该比例衡量工程交付，不表示实耗工时或诊断效果；第 3 周完整里程碑尚未完成。

当前完成 Step 11：`replay` 使用固定模型响应驱动真实只读工具，维护假设、缓存、预算、停止报告与 JSONL 轨迹；`collect` 继续执行固定取证。模型接口拒绝 remote 客户端，脱敏预览、材料范围确认与云端适配是下一步。输出和轨迹未经脱敏，仅供本地检查。同步工具在返回后检查总时限；真实网络超时和 token 计量未验证。Windows 取证、文档读取及探针执行暂不支持；当前 WSL 的 nvidia-smi 不在系统默认搜索路径，自动 GPU 显存摘要仍不可用。

各步验证环境为 Linux / Python 3.12.3，其他平台与 Python 版本未验证。检查命令见 [README](../README.md#开发检查)；受限环境使用 `UV_CACHE_DIR=/tmp/deepdebug-uv-cache`。历史安装或构建曾因网络受限、构建缓存缺失而失败，补齐既有依赖后通过；离线复现需要先准备依赖缓存。

## Step 11 — 离线单 Agent 控制循环（2026-11-11）

新增能力：

- `replay --responses FILE`：登记用户指定材料，固定解析首份日志，再由人工模型响应选择只读工具、更新假设并输出包含 JSON 报告的完整状态。支持代码、配置、快照和授权路径引用；`schema decision` 导出模型决策结构。
- `replay --trace FILE`：新建 JSONL 轨迹，逐次记录决策请求、用量、假设变化、真实工具调用、缓存命中、错误与停止时的完整状态。
- `--max-decisions/--max-tools/--max-seconds`：调整循环预算；预算耗尽、无进展、缺信息或接口/动作错误时保留证据与报告。固定响应中的 token 用量为模拟值，默认 0。
- `examples/dep_002_replay.json`：用真实日志、启动配置及两份环境快照演示假设由缺包细化为解释器不一致，报告给出证据引用、修复建议和验证判据；修复验证为“未执行”。示例为 synthetic 固定响应，不计入模型诊断效果。

完成范围：

- `src/deepdebug/llm/client.py`：定义 ModelClient 请求、响应与分类失败；唯一客户端为本地 ReplayModelClient。控制器拒绝 remote，保留云端接入前的脱敏/确认边界。
- `src/deepdebug/agent/decision.py`、`controller.py`：模型仅生成观察摘要、假设、动作和结束结论；宿主维护事实与报告。加入首轮日志解析、全状态/引用重校验、决策和工具次数/总时间/token 预算、一次无效决策修正、一次瞬时接口重试、连续两轮无进展停止；所有停止路径组装 JSON 报告。`schemas.py` 增加 model_error 停止原因。
- `src/deepdebug/tools/registry.py`、`tools/session.py`：显式白名单调度，按环境 ID 绑定唯一快照、按探针选择返回字段和证据，路径 ID 限于授权清单；缓存复用原结果与证据。调度失败入历史，内置验证保留 unavailable；比较快照和 GPU 查询不替换目标环境。
- `src/deepdebug/agent/trace.py`：逐行写入校验后的完整状态、事件序号、时间、决策摘要和工具调用关联，缓存动作指向原调用 ID。
- `src/deepdebug/replay.py`、`cli.py`：离线回放入口、显式材料登记、固定响应加载、预算参数和新建轨迹文件；状态 JSON 输出到标准输出，异常停止保留明确退出码。
- `tests/test_controller.py`：新增 42 项检查，覆盖真实工具反馈、假设变化、缓存、预算、错误修正/重试、证据伪造拒绝、路径与环境权限、来源语义、未执行验证及轨迹校验。
- `README.md`、`AGENTS.md`、`docs/design.md`、`docs/tool-api.md`、`examples/README.md`：同步当前能力、调用契约、运行示例与阶段限制。

验证结果：

- `uv run --locked ruff check .`、`uv run --locked ruff format --check .`、pytest **263 项**（新增 42 项）、`git diff --check` 通过；23 处本地文档链接及锚点检查通过。
- CLI 实跑 dep_002：**4 次决策、4 次工具调用、9 条证据、18 条 JSONL 事件**，停止原因为 completed；目标保持 ENV_EMPTY，假设随配置和快照证据变化，最终报告验证状态为“未执行”。轨迹最后一条状态与标准输出一致。
- 同例设置 `--max-tools 2`：**1 次决策、2 次工具调用、3 条证据、7 条轨迹事件** 后以 budget_exhausted 停止并输出报告，退出码 1。重复指定已有轨迹文件返回 2，保留原文件。
- 所有材料及轨迹仍为本地未脱敏内容；当前回放不调用供应商 API。报告无需额外模型生成，报告修正计数为 0；同步只读工具返回后检查总时限，单次抢占和真实请求超时未实现。

开发进度：对应第 3 周，预算停止与调用轨迹 **2/4 项验收完成**；假设变化已通过固定响应演示，真实模型五类端到端报告及假设更新待验收。完整里程碑仍为 **2/6**，整体工程估算 **约 40%（29/72）**，不表示实耗工时或诊断效果。后续仍有界面/Markdown 报告、内置修复验证、冻结评测和课程交付。

下一步：实现发送前脱敏预览与材料范围确认，再接入云端 ModelClient，核验真实用量和超时，并完成五类真实模型端到端诊断。

## Step 10 — 补齐五类真实故障种子（2026-11-03）

新增能力：

- `scripts/capture_failure_cases.py OUTPUT --python ABSOLUTE_PATH --case CASE_ID`：显式选择解释器与固定案例，采集路径、形状、设备不一致、配额 OOM 的真实失败日志、配置、源码与环境快照；环境不足时记录状态，输出目录中不生成虚假案例。
- `uv sync --locked --group capture`：准备项目专用 PyTorch 2.9.1 / NumPy 采集环境，Linux/Windows 的 torch 使用官方 CUDA 12.8 wheel；默认开发/取证依赖不包含该组。
- `benchmark/dev/` 现有六个真实案例，覆盖五类故障，均可通过既有 `collect` 入口回放并输出证据；对应人工参考报告位于 `benchmark/gold/dev/`，修复验证均为“未执行”。

完成范围：

- `scripts/capture_failure_cases.py`：四个固定程序在临时目录运行，核验非零退出及预期错误后保存材料和采集清单；子进程限时 15 秒、输出上限 64 KiB。路径案例附带故障环境的工作目录/文件布局；配额 OOM 固定申请 64 MiB，配额为总显存的 0.1% 且最多 32 MiB。采集汇总保留未取得案例的原因；输出目录已存在则拒绝。
- `src/deepdebug/tools/process.py`：内部进程结果增加实际退出码，保留有界非零退出输出，供开发采集器识别失败；环境探针仍将非零退出映射为错误。
- `benchmark/dev/{path_001,shape_001,device_001,oom_001}/`：新增四个真实案例，各自保存来源、时间、版本、路径替换与适用范围；输入目录不包含参考答案。
- `benchmark/gold/dev/{path_001,shape_001,device_001,oom_001}.json`：新增人工参考状态与报告，保留证据来源、候选原因、建议、验证判据和未决问题；工具历史为空，预算用量为零。
- `pyproject.toml`、`uv.lock`：新增非默认 `capture` 依赖组和显式 PyTorch 官方索引；按用户授权在项目虚拟环境安装。NumPy 用于完成 PyTorch 初始化，避免缺包警告混入环境探针 JSON。
- `tests/test_failure_capture.py`、`tests/test_dev_cases.py`：新增 19 项检查，覆盖真实路径采集、无 PyTorch 降级、输出目录保护、固定案例选择、非零退出输出、五类覆盖及六例取证的原始证据一致性；测试不运行 benchmark 输入代码。
- `README.md`、`AGENTS.md`、`scripts/README.md`、`benchmark/README.md`、`benchmark/gold/dev/README.md`、`docs/design.md`：同步使用入口、依赖、采集范围、来源语义与当前进度。

验证结果：

- `uv run --locked ruff check .`、`uv run --locked ruff format --check .`、pytest **221 项**、`uv build --offline`、`git diff --check` 通过。
- Linux / Python 3.12.3 / PyTorch 2.9.1+cu128 / RTX 5060 Ti 实跑：四个新增案例均得到真实非零退出。形状错误为 `(2×5) @ (4×3)`；设备错误为 CPU 输入与 CUDA 权重冲突；OOM 申请 64 MiB，进程配额约 16.28 MiB，日志显示当时整卡仍有约 14.80 GiB 空闲。该 OOM 只能支持配额限制，不能据此标注整卡耗尽、batch 过大、泄漏或碎片化。
- 六例 CLI 取证全部成功，`report=null`。新增路径/形状/设备/OOM 案例分别输出 **7/10/10/8 条证据**及 **5/4/4/4 次工具调用**；原两个依赖案例保留 7/10 条证据及 4/5 次工具调用。
- 使用空虚拟环境实跑缺少 PyTorch 的降级分支，明确返回 `unavailable`，不生成对应案例目录。真实 CUDA 可用性探针返回 `ok`；本机 WSL 的 `nvidia-smi` 位于 `/usr/lib/wsl/lib`，不在现有自动探针的系统默认搜索路径，GPU 显存摘要保存为 `unavailable`。
- 原始日志和快照已替换本机目录前缀并检查证据位置；采集器不自动更新 gold。全部人工参考报告的修复验证为“未执行”。

开发进度：第 1、2 周各 3/3 项验收完成，完整里程碑 **2/6**；整体工程估算 **约 31%（22/72）**，不表示实耗工时或诊断效果。自动诊断仍为 0/5，模型循环、界面/报告、内置修复验证、冻结评测和课程交付待完成。

下一步：推进第 3 周的模型接口、单 Agent 状态机、工具调度、预算停止与 JSONL 轨迹；在接入云端模型前补齐脱敏预览及材料范围确认，控制器测试使用固定模型响应。

## Step 09 — 明确文档分工（2026-11-03）

新增能力：无新增运行功能。本步整理文档职责与导航。

完成范围：

- `docs/design.md`：按基础工程、数据流与模块、材料边界、协议与证据、环境来源、文档检索和标签隔离组织当前设计；合并检索设计，移除按日期追加的历史段落及过时状态。
- `docs/tool-api.md`：按协议、材料登记、取证会话、环境采集、路径检查和文档检索组织接口；去除 Step 标题和演进措辞，保留参数、返回值、来源、失败状态与限制。
- `knowledge/README.md`：保留语料来源、评分公式和分词规则，将回归对比结果改为指向本进度文档。
- `README.md`、`AGENTS.md`：增加文档导航与维护分工，明确更新当前章节、历史集中记录的规则。

验证结果：Ruff 检查与格式检查、pytest **202 项**、`git diff --check` 通过；本次涉及文档的 **22 处本地链接及锚点**检查通过。`design.md` 与 `tool-api.md` 已移除 Step 和日期更新标题。

开发进度：本步为文档整理，第 2 周验收仍为 3/3，完整里程碑 1/6；整体工程估算仍约 28%（27%～29%），不表示实耗工时或诊断效果。第 1 周仍缺其余四类真实故障种子。

下一步：补齐 OOM、设备不一致、路径和配置/形状四类真实故障种子，再推进模型接口、脱敏确认、工具调度和预算停止。

## Step 08 — BM25 排序与技术标识符分词（2026-11-03）

新增能力：

- `search-docs` 与 `collect --docs-query` 改用 BM25，根据词的文档频率、出现次数及文档长度排序。
- 可直接查询完整缺包日志和点分 API 名称，例如 `ModuleNotFoundError: No module named torch`、`torch.nn.Linear`、`torch.cuda.memory.empty_cache`；完整名称和后缀别名参与匹配，原有类别过滤和证据入口继续使用。

完成范围：

- `src/deepdebug/tools/docs_search.py`：标题、关键词和摘要合并索引，标准库 `Counter` 保存词频和文档频率，BM25 使用正值 IDF、固定 `k1=1.2/b=0.75`。类别过滤不改变完整语料统计，查询词去重并按固定顺序累加，结果保留确定性排序。
- 同文件 `_terms()`：保留完整异常名、下划线标识符、点分 API 及逐级后缀，英文忽略大小写，中文沿用相邻双字切分；文档词频保留，替换原来的集合计数。
- `tests/test_docs_search.py`：新增 17 项检查，包含 12 条不指定类别的开发回归查询，以及分词、BM25 参考数值、长度归一化、单文档和无可检索词的语料；类别过滤验证评分统计保持一致。
- `README.md`、`AGENTS.md`、`knowledge/README.md`、`docs/tool-api.md`、`docs/design.md`：同步入口说明、评分公式及来源、分词规则和实际对比结果。

验证结果：

- Ruff 检查与格式检查、pytest **202 项**（其中检索测试 53 项）、`git diff --check` 通过。
- 同一组 12 条开发查询：首条结果相关从 **9/12 → 12/12**，前三条至少包含一条相关结果从 **11/12 → 12/12**。该对比同时包含分词与评分变更，属于当前语料的开发回归，不代表独立 benchmark 或诊断效果。
- CLI 实跑：完整缺包日志返回 `D009/D007`；`torch.nn.Linear` 返回 `D013`；`torch.cuda.memory.empty_cache` 返回 `D003/D001`。均成功输出带来源的文档证据，`report=null`。

开发进度：本步完善第 2 周文档检索，验收仍为 3/3；完整里程碑 1/6，整体工程估算仍约 28%（27%～29%），不表示实耗工时或诊断效果。

下一步：补齐 OOM、设备不一致、路径和配置/形状四类真实故障种子，完成第 1 周验收，再推进模型接口、脱敏确认、工具调度和预算停止。

## Step 07 — 本地官方文档检索与证据接入（2026-11-03）

新增能力：

- `search-docs QUERY`：离线检索 15 条官方文档的人工摘要，覆盖五类故障；可按类别过滤，每次最多返回 3 条，结果包含文档编号、来源 URL、版本和整理时间。
- `collect --docs-query QUERY --docs-category CATEGORY`：在现有取证状态中追加文档结果和证据 ID，保留目标快照环境。
- 文档语料随发布包分发，从仓库外运行也可检索；同一会话固定语料内容，重复命中复用证据 ID。

完成范围：

- `src/deepdebug/tools/docs_search.py`：固定语料加载、结构/唯一 ID 校验、中英文关键词匹配、类别过滤和确定性排序。采用规划 MVP 允许的关键词方案，不引入检索依赖；无匹配返回空列表。
- `src/deepdebug/knowledge/documents.json`、`knowledge/README.md`：新增五类各 3 条中文摘要，逐条核对 PyTorch 2.9 / Python 3.12 官方来源，保存 URL、版本、整理时间和来源清单；唯一语料随 sdist/wheel 发布。
- `src/deepdebug/tools/session.py`、`agent/actions.py`：接入 `search_docs` 工具记录与 `document` 证据，位置指向文档 `/excerpt`；保留整理时间和独立查询时间，拒绝空白查询及非法参数。
- `src/deepdebug/collection.py`、`cli.py`：增加独立检索与取证末尾追加检索入口，输出完整校验后的 `DiagnosisState`。
- `src/deepdebug/security/paths.py`：固定包目录允许隐藏安装路径（如 `.venv`），仍拒绝所有链接、越界和 gold；材料目录与相对文件名继续拒绝隐藏路径。
- `tests/test_docs_search.py`：新增 36 项检查，覆盖五类中英文查询、过滤/排序/条数、空结果、非法语料、准确出处与时间、语料固定、gold/链接隔离及 CLI 接入。
- `README.md`、`AGENTS.md`、`docs/tool-api.md`、`docs/design.md`：同步结构、入口、协议、安装方式和阶段进展。

验证结果：

- Ruff 检查与格式检查、pytest **185 项**、`git diff --check` 通过。
- `uv build` 通过，sdist 和 wheel 包含语料。wheel 使用 `uv pip install --no-deps --link-mode copy` 安装到临时隐藏目录，复用现有依赖、从仓库外运行：查询“错误解释器”命中 `D008`，输出 1 条文档证据及 `Python 3.12` 版本标注。
- `dep_002` CLI 追加 `ModuleNotFoundError` 检索：5 份材料、12 条证据、6 次成功工具调用，命中 `D007/D009`，目标仍为 `ENV_EMPTY`，`report=null`。
- uv 默认硬链接安装的语料会被读取边界拒绝；改用 `--link-mode copy` 后通过。包构建首次联网补齐已声明的 hatchling 构建依赖后通过，离线构建仍需缓存。

阶段限制：关键词分数仅表示检索匹配，不能替代实例证据或诊断置信度。文档版本不会自动与目标环境匹配；模型提示注入与证据语义支持尚未验证。第 2 周三个验收项已完成，第 1 周仍为 2/3，整体工程估算约 28%。

下一步：补齐 OOM、设备不一致、路径和配置/形状四类真实故障种子，完成第 1 周验收，再推进模型接口、脱敏确认、工具调度和预算停止。

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
