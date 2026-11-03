# DeepDebug Agent

面向 PyTorch 训练与推理故障的诊断助手。目标是根据日志、代码、配置和环境快照，按需补充证据，输出可追溯的候选根因、修复建议和验证方法。

**当前状态：已完成 Step 10（五类真实故障种子），可采集环境快照、检查登记路径、通过 BM25 检索本地官方文档摘要并通过 CLI 只读取证，尚不支持自动诊断。** 包含材料边界、日志解析、Python/包元数据与可选 PyTorch/CUDA、GPU 采集、15 条文档语料、证据编号和工具记录。

## 文档导航

| 文档 | 职责 |
|---|---|
| [项目规划](DeepDebug_planning.md) | 产品范围、里程碑与验收目标 |
| 本 README | 环境准备、使用入口和当前能力概览 |
| [架构设计](docs/design.md) | 按模块说明当前架构与设计理由 |
| [工具协议](docs/tool-api.md) | 按协议和工具说明当前参数、返回值及约束 |
| [开发进度](docs/progress.md) | 按 Step 保留改动历史、实际验证、验收进展及下一步 |
| [语料说明](knowledge/README.md) | 当前文档来源清单、评分公式和分词规则 |

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

测试覆盖 CLI、协议非法输入、报告引用与验证状态、证据原始位置、路径边界、探针隔离与超时/输出限制、无 GPU 降级、文档检索相关性与语料隔离。诊断效果待模型循环接入后评测。

## 本地取证

在 Linux/POSIX 环境中运行：

```bash
uv run --locked deepdebug collect \
  --root benchmark/dev/dep_002/materials \
  --log log.txt \
  --code dependency_demo.py \
  --config launch.json \
  --snapshot target_snapshot.json \
  --snapshot project_snapshot.json
```

命令只读取和解析材料，将 `DiagnosisState` JSON 输出到标准输出，包含异常摘要、登记材料、带原始行号或 JSON 字段位置的证据，以及工具状态和耗时。内容尚未经自动脱敏，材料保留 `pending` 状态；输出仅供本地检查。

`--root` 必须是独立材料目录，其他参数均为其内部相对路径；不遍历或自动导入目录文件。默认不保存会话，可自行将标准输出重定向到本地文件。单文件上限 2 MiB，每次最多 10 份；只接受 UTF-8 文本，YAML 目前仅作为文本读取。文件内容在登记时固定，之后使用材料 ID 读取。普通文本最多返回 200 行及 16,000 字符；完整工具结果最多 64 KiB，截取会标记 `truncated`，过大的结构化结果会明确拒绝。

第一份 `--snapshot` 是目标环境，其余用于比较；目标快照无效时不会自动换成对照环境。`collect` 保留快照原始采集时间，环境与 GPU 信息均从快照读取。追加 `--query-gpu` 可读取每份快照的 GPU 摘要，缺少该字段时记录 `unavailable`。退出码：`0` 表示本次工具调用均成功，`1` 表示有工具失败但仍输出完整状态，`2` 表示参数/材料登记失败；`0` 不等于训练问题已修复。

追加 `--path data/model.pt --path datasets` 可检查显式登记的路径，最多 10 个；默认基准目录为 `--root`，也可通过 `--path-root /absolute/data-directory` 授权另一个独立目录。结果包含 `P001…` 引用 ID、相对路径、授权基准目录、存在性和文件/目录类型，不读取内容或列出邻近文件。不存在的路径是成功查询得到的 `exists=false`；越界、链接等返回 `denied`。路径证据标记为 `local/collector`，只反映运行命令这台机器的采集时刻，不能代替远端故障环境的文件状态。

安全读取依赖 POSIX 的目录文件描述符与 `O_NOFOLLOW`，当前实际验证平台为 Linux；Windows 上会明确拒绝取证操作，Schema 导出仍可使用。所有符号链接（包括指向目录内部的链接）、硬链接、隐藏路径、目录穿越和 `benchmark/gold` 访问均拒绝，不能把整个仓库设为材料根目录。这些检查约束本地文件读取，不提供通用进程隔离。

## 本地文档检索

```bash
uv run --locked deepdebug search-docs '错误解释器' --category dependency --max-results 2
uv run --locked deepdebug search-docs 'mat1 and mat2 shapes cannot be multiplied'
```

输出含工具记录与文档证据的 `DiagnosisState` JSON。每条结果包含 `D001…` 文档编号、官方来源 URL、适用版本、整理时间、中文摘要和排序分数；对应 `E001…` 证据指向该文档的 `/excerpt`。文档证据时间是整理时间，工具结果时间是本次检索时间。

15 条语料覆盖五类故障，来源与维护说明见 [文档清单](knowledge/README.md)。查询长度为 1～500 字符，BM25 排序每次最多返回 3 条，支持 `--category cuda_oom/device_mismatch/dependency/path/configuration` 过滤；`unknown/out_of_scope` 当前无语料。无匹配返回 `ok` 和空列表；结果有省略时标记 `truncated=true`，已返回的摘要保持完整。退出码 `0` 表示查询成功，`1` 表示工具失败，`2` 表示 CLI 参数错误。

BM25 根据词的文档频率、出现次数和文档长度评分。标题、关键词、摘要合并为索引文本；保留完整异常名、下划线标识符和点分 API 及其后缀，例如 `torch.nn.Linear` 同时匹配 `nn.Linear`、`Linear`。中文继续使用相邻双字片段，英文忽略大小写。可直接查询完整报错或 API 名称，例如 `search-docs "ModuleNotFoundError: No module named torch"`、`search-docs "torch.nn.Linear"`。

在 `collect` 命令后追加 `--docs-query 'ModuleNotFoundError' --docs-category dependency`，可把文档证据加入同一取证状态，保留目标环境和原始材料证据。检索仅读取随包发布的固定语料，不接受语料路径参数。固定包目录允许位于 `.venv` 等隐藏安装目录下，文件仍拒绝链接；用户材料目录的隐藏路径限制保持有效。

从 wheel 安装时，使用 `uv pip install --link-mode copy dist/deepdebug_agent-0.1.0-py3-none-any.whl`；uv 默认硬链接安装会使语料读取返回 `denied`。仓库内 `uv sync --locked` 的可编辑安装直接读取源码语料。

文档是人工改写的背景资料，版本标注为 PyTorch 2.9 或 Python 3.12；当前不自动判断与目标环境的版本兼容性。排序分数不表示诊断置信度，文档不能单独证明当前实例的根因。检索和取证均在本地执行。

## 采集用户环境快照

在需要采集的机器上运行 DeepDebug，显式指定目标 Python 的绝对路径和环境标识：

```bash
uv run --locked deepdebug snapshot \
  --python /absolute/target-env/bin/python \
  --environment-id TRAIN_ENV \
  --package torch --package numpy \
  > /absolute/materials/environment.json
```

替换示例路径并先创建输出目录；重定向会覆盖同名文件。随后用 `collect --snapshot environment.json` 导入。脚本入口 `uv run --locked python scripts/collect_environment.py` 接受相同参数。

默认只采集 Python 标识及明确请求的包元数据，最多 10 个包，不导入这些包。`--torch-cuda` 额外在隔离子进程中导入 PyTorch，返回版本、编译 CUDA 版本、CUDA 可用性及设备数；CPU-only PyTorch 可成功返回 `cuda_available=false`。`--gpu` 额外调用系统路径中的 `nvidia-smi`，返回 GPU 名称与总/已用显存（MiB）。两个选项可单独使用；未请求的字段省略。

Python 探针使用 `-I` 和项目目录外的临时工作目录；元数据探针限时 10 秒，PyTorch/CUDA 和 GPU 探针各 15 秒，每个进程合并输出最多 64 KiB。超时或输出超限时终止并回收该探针进程。目标环境中已安装的包仍属于用户选择的运行环境，隔离参数不构成通用安全沙箱。

`snapshot` 退出码：`0` 表示请求的采集均成功（包的 `not_found` 是查询结果）；`1` 表示保留有效 Python 快照，同时有包查询或可选探针失败；`2` 表示参数或 Python 身份采集失败，标准输出无快照。缺少 PyTorch、没有 `nvidia-smi` 或 GPU 列表为空时记录 `unavailable`；超时记录 `timeout`，非零退出及无效输出记录 `error`。导入时 `inspect_environment` 成功表示快照读取成功，各探针状态仍保留在结果中。

每份快照包含环境标识、解释器和带时区采集时间，GPU 与 PyTorch 探针另有采样时间。这些值描述采集时刻，不能还原失败训练进程的历史显存。快照包含本机路径，尚未经自动脱敏，仅供本地检查。已实跑无 PyTorch 降级及真实 CUDA 可用性采集。当前 WSL 主机的 `nvidia-smi` 位于系统默认搜索路径之外，自动 GPU 显存摘要仍返回 `unavailable`；快照中的 `torch_cuda` 可独立返回成功。

## 数据协议与开发案例

`deepdebug schema <kind>` 输出 JSON Schema，`kind` 可选 `action`、`state`、`report`、`snapshot`。接口字段及约束见 [协议说明](docs/tool-api.md)。

依赖案例位于 `benchmark/dev/dep_001` 与 `dep_002`。它们具有相同的 `ModuleNotFoundError` 日志，分别通过环境快照和启动配置体现“目标环境缺包”与“使用了错误解释器”。日志和快照来自实际 Python 进程，未执行 PyTorch 训练；所有 `/demo/` 路径均为脱敏别名，不能直接执行。案例分属同一案例族，均留在开发集。

新增 `benchmark/dev/path_001`：真实相对路径读取失败，包含工作目录、配置引用、故障环境中的文件布局和快照。另有 `shape_001` 的 CPU Linear 维度不匹配、`device_001` 的 CPU 输入/CUDA 权重冲突，以及 `oom_001` 的 CUDA 分配器配额 OOM。当前共 6 个真实开发案例，覆盖五类故障；GPU 案例已在 PyTorch 2.9.1+cu128 / RTX 5060 Ti 上采集。OOM 固定申请 64 MiB，超过约 16.28 MiB 的进程配额，不代表整卡显存耗尽。

[人工参考报告与说明](benchmark/gold/dev/README.md) 仅供开发与评测，修复验证均为“未执行”，不能作为 Agent 可读取的材料。材料目录只存放输入。

可在离线环境重新采集到一个**尚不存在**的目录：

```bash
uv run --locked python scripts/capture_dependency_cases.py runs/dependency-capture
```

脚本创建临时空虚拟环境、运行固定依赖导入程序，并查询当前项目环境的 pydantic 元数据；不安装包。现有输出目录会被拒绝。新采集的时间、版本可能变化，不会自动更新仓库中的参考答案。

项目采集环境可执行 `uv sync --locked --group capture`，安装锁定的 PyTorch 2.9.1 与 NumPy（Linux/Windows 的 torch 使用 CUDA 12.8 wheel）；默认安装不包含此组。

其余故障的固定采集入口见 [采集脚本说明](scripts/README.md#其余故障种子采集)。`path_001` 只需 Python；`shape_001` 需要 PyTorch，`device_001/oom_001` 还需要 CUDA。显式指定 `--python` 和 `--case`，缺少环境时记录 `unavailable`。OOM 案例采用进程分配器配额，固定申请 64 MiB。

## 目录与后续实现

| 路径 | 职责 |
|---|---|
| `src/deepdebug/cli.py` | 命令行参数与入口 |
| `src/deepdebug/agent/` | 已实现协议、动作校验与状态；控制器待实现 |
| `src/deepdebug/tools/` | 材料登记、日志解析、环境采集与快照读取、路径引用、本地文档检索和取证会话 |
| `src/deepdebug/knowledge/`、`knowledge/` | 随包发布的固定文档语料、来源清单与维护说明 |
| `src/deepdebug/security/` | 已实现只读路径边界；自动脱敏待实现 |
| `src/deepdebug/agent/evidence.py` | 会话内稳定证据编号与去重 |
| `src/deepdebug/collection.py` | 宿主驱动的 CLI 取证流程 |
| `tests/` | 自动化检查 |
| `docs/` | 架构决策与逐步进度 |
| `benchmark/`、`scripts/` | 六个开发案例、人工参考状态、开发案例与用户环境采集脚本 |
| `examples/` | 演示材料的预留位置 |

模型接口与报告渲染模块在实现对应功能时创建。Streamlit 和模型 SDK 在对应阶段引入；当前 BM25 检索使用标准库。

## 范围与边界

首版聚焦 OOM、设备不一致、依赖/解释器、路径和配置/形状五类问题。采用单 Agent 状态机，默认导入环境快照；本机采集需要用户明确选择。模型不得执行任意代码或 shell、安装依赖、修改用户文件或重跑真实训练。上传材料和检索文档均是不可信数据。

当前已实现材料与路径边界、大小检查、固定环境探针的超时和输出限制、固定语料检索；尚未实现自动脱敏、模型动作调度、会话预算强制停止或证据语义判断。取证状态中的调用次数和耗时仅作记录。内置验证只针对开发者维护的预置案例，不能等同于真实训练恢复。`runs/`、`sessions/` 已被 Git 忽略，尚无自动保存或清理功能。不得提交真实密钥和私有日志。

下一步：推进第 3 周模型接口、单 Agent 控制循环、预算停止和运行轨迹；接入云端模型前完成脱敏预览与材料范围确认。
