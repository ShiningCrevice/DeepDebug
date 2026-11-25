# DeepDebug Agent

面向 PyTorch 训练与推理故障的诊断助手。目标是根据日志、代码、配置和环境快照，按需补充证据，输出可追溯的候选根因、修复建议和验证方法。

**当前状态：已完成 Step 33（六案例匹配与拒绝请求处理）。** 六个固定实验已由 Shivice 确认与模型建议匹配，匹配且回归通过 6/6；518 项测试通过。模型错误显示 HTTP 状态，评测遇到 401/403 会保存结果并停止批次。当前 API 复测仍返回每日配额相关的 403；完整里程碑 4/6，完整评测、语义评分和最终媒体交付待完成。详见 [评测记录](docs/evaluation-results.md)、[交付索引](docs/delivery.md) 与 [进度记录](docs/progress.md)。项目采用 [MIT License](LICENSE)。

## 文档导航

| 文档 | 职责 |
|---|---|
| [交付索引](docs/delivery.md) | 技术报告、演示脚本、第三方说明及剩余交付项 |
| [项目规划](DeepDebug_planning.md) | 产品范围、里程碑与验收目标 |
| 本 README | 环境准备、使用入口和当前能力概览 |
| [架构设计](docs/design.md) | 按模块说明当前架构与设计理由 |
| [工具协议](docs/tool-api.md) | 按协议和工具说明当前参数、返回值及约束 |
| [干净环境复现](docs/reproduction.md) | 安装、启动、报告导出及无 PyTorch 行为的实跑记录 |
| [开发进度](docs/progress.md) | 按 Step 保留改动历史、实际验证、验收进展及下一步 |
| [语料说明](knowledge/README.md) | 当前文档来源清单、评分公式和分词规则 |

## 环境与启动

需要 Python 3.10+ 和 uv。本仓库默认开发解释器为 Python 3.12（`.python-version`）；当前实际验证环境为 Linux / Python 3.12。本地取证与回放无需 GPU、PyTorch 或 API key；云端诊断需要 `OPENAI_API_KEY`。

```bash
uv sync --locked
uv run --locked deepdebug --help
uv run --locked deepdebug --version
uv run --locked python -m deepdebug
uv run --locked deepdebug schema action
```

`uv sync` 创建项目内 `.venv`，安装项目与开发依赖；首次安装需要可用的包源。若使用其他兼容解释器，可执行 `uv sync --locked --python 3.10`。依赖精确版本保存在 `uv.lock`。`diagnose` 自动加载当前工作目录的 `.env`，已有环境变量优先；模型客户端从 `OPENAI_API_KEY` 读取密钥，变量说明见 `.env.example`。

## 开发检查

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
uv build
```

测试覆盖 CLI、协议与证据引用、路径边界、探针隔离与降级、文档检索、控制循环，以及 HTTP 模拟下的外发授权、凭据保护、用量和超时取消。测试不调用付费 API；真实模型诊断效果待评测。

## 本地界面

在项目根目录运行：

```bash
uv sync --locked --extra ui
uv run --locked --extra ui streamlit run app.py
```

浏览器打开 `http://127.0.0.1:8501`。仓库配置只监听本机，单文件上传上限 2 MiB。先粘贴或上传一份日志，再选择源码、配置和环境快照（第一份为目标），每次最多 10 份材料。点击“生成脱敏预览”，逐份核查正文，勾选确认；填写模型和 API 基础地址，检查显示的最终目的地，点击“授权发送并开始诊断”。密钥从服务器进程的 `OPENAI_API_KEY` 读取，项目根目录 `.env` 中已有配置可用，环境变量优先。

材料变动会清除旧预览、结果与轨迹，重新生成后需要重新确认。页面显示当前目标环境和快照采集时刻、决策/工具次数、证据数量、工具与假设时间线；结束后可下载 Markdown、JSON 报告、完整状态和 JSONL 轨迹。诊断调用共享 CLI 控制器和发送边界；预算在页面展开配置。

“离线预置演示”运行 dep_002 的固定响应与真实工具，无需密钥。该演示用于展示工具反馈改变假设，修复未执行，不计为模型效果。演示需要仓库中的案例和响应文件；当前启动入口是源码根目录 `app.py`。

页面运行中的材料、报告和轨迹保存在服务器内存；“保存当前会话”将它们写入本机专用目录。可从保存列表重新打开或删除；“清除当前会话”只移除当前页面内存状态。下载文件由用户自行管理。已保存会话视图支持补充材料、重新核查并继续诊断。

界面检查：`uv run --locked --extra ui pytest`。不安装 ui 时，界面交互测试跳过，上传与预览后端仍可测试。

## 脱敏预览与材料确认

```bash
mkdir -p runs
uv run --locked deepdebug preview \
  --root benchmark/dev/dep_002/materials \
  --log log.txt --config launch.json \
  --snapshot target_snapshot.json --snapshot project_snapshot.json \
  --output runs/dep_002-preview.json
```

查看输出 JSON 中每份材料的 `text`、类型与顺序，核查全部脱敏内容和范围。材料按日志、代码、配置、快照的顺序编号，文件名显示为 `A001.txt` 等别名；首份快照仍为目标环境。自动规则覆盖常见 API key/token/密码字段、Bearer 凭据、常见独立 token、URL 用户名密码、PEM 私钥块，以及 `/home/用户名`、`/Users/用户名`、Windows 用户目录前缀。相同敏感值使用一致别名，保留物理行数；JSON 字符串先解码再替换，保留有效 JSON 和快照字段位置。

自动脱敏会遗漏非标准格式、私有业务内容及其他目录路径；请逐项核查。需要补充脱敏或缩小材料范围时，修改本地材料副本或调整参数，再生成新预览。预览和确认文件仅新建，权限为 `0600`，父目录须已存在；JSON 同时输出到标准输出。不要将未核查的预览视为可公开材料。

核查全部材料内容和范围后执行 `confirm`，该命令表示确认已完成核查：

```bash
uv run --locked deepdebug confirm \
  --preview runs/dep_002-preview.json \
  --output runs/dep_002-reviewed.json

uv run --locked deepdebug replay \
  --reviewed runs/dep_002-reviewed.json \
  --responses examples/dep_002_replay.json \
  --trace runs/dep_002-reviewed-trace.jsonl
```

`confirm` 将全部预览材料作为本地回放范围，绑定脱敏内容、类型、顺序和登记时间。程序自动校验文件中的摘要；内容与摘要不符会拒绝确认。运行时在标准错误输出列出材料名称、类型和大小，无需复制摘要。已确认回放只读取这份固定副本，原文件后续修改不会改变证据；状态材料标记为 `reviewed`，并以 `material_review_sha256` 关联确认记录。证据、JSON 报告和轨迹中的材料内容均来自该副本，行号和 JSON Pointer 指向预览内容。

`--reviewed` 与原始材料参数及 `--path/--path-root` 互斥；本机路径观察尚未纳入预览范围。确认记录用于本地内容一致性检查，不是数字签名；`confirm` 本身不授权外发，云端诊断还需执行下述授权命令。`preview/confirm` 成功返回 `0`，输入、摘要或输出错误返回 `2`。固定响应文件是另外提供的人工演示文本，不经过材料脱敏；示例不计为模型诊断效果。

## 云端诊断

先完成 `preview → 人工核查 → confirm`，并配置 `OPENAI_API_KEY`。在项目根目录将 `.env.example` 复制为 `.env`，填写密钥与 `OPENAI_BASE_URL`；从该目录运行 `diagnose` 时自动加载。已有环境变量优先于文件，`.env` 已被 Git 忽略。以下命令明确授权：把已确认材料中按工具选取的片段、工具结果、文档摘要和模型判断发送至所选服务。默认服务为 OpenAI；替换模型占位符后运行，模型须支持 Responses API 的 JSON mode，账户须有访问权限。

```bash
uv run --locked deepdebug diagnose \
  --reviewed runs/dep_002-reviewed.json \
  --send-to https://api.openai.com/v1/responses \
  --model '你的模型ID' \
  --trace runs/dep_002-cloud-trace.jsonl
```

`--max-tokens` 默认 50,000，包含 5,000 报告预留；单次输出上限仍为 4,096。请求按 UTF-8 字节数保守预留输入额度，材料和历史增长时可能压缩输出空间。dep_002 在线复测使用 `--max-tokens 65000 --max-decisions 6 --max-tools 7 --max-seconds 60`；预算是上限，实际 token 用量见状态与轨迹。

执行 `diagnose --reviewed ... --send-to ... --model ...` 表示同意发送该确认副本；程序列出材料清单、目的地和模型，自动将副本摘要绑定到发送记录。命令仅消费确认副本，不接受追加原始材料或本机路径。每轮发送前校验登记内容、摘要、目的地、模型和当前会话，再对实际请求中的文本做常见规则脱敏。完整源文件不直接附加到请求，工具按需选取片段；模型输出也在进入状态和轨迹前脱敏。自动规则的覆盖限制仍适用，应在预览时核查全部材料。

自定义服务示例：

```bash
uv run --locked deepdebug diagnose \
  --reviewed runs/dep_002-reviewed.json \
  --base-url https://gateway.example/api/v1 \
  --send-to https://gateway.example/api/v1/responses \
  --model '你的模型ID'
```

地址优先级为 `--base-url` → `OPENAI_BASE_URL` → `https://api.openai.com/v1`。基础地址包含服务要求的版本/网关前缀，程序去掉尾斜杠后追加 `/responses`，不自动添加 `/v1`；基础地址不能已经包含末尾 `/responses`。`--send-to` 必须匹配最终地址，协议、主机、端口或路径不符会在发送前拒绝。状态与轨迹保存规范化后的完整地址。

支持 HTTPS 和 HTTP（例如 `http://localhost:8000/v1`）；HTTP 会明文传输凭据和材料。地址不能包含用户名密码、查询参数、片段或空白，密钥继续通过 `OPENAI_API_KEY` 提供。程序不跟随重定向，不读取代理环境变量。自定义服务须支持现有 Responses 请求字段与响应结构；仅实现 Chat Completions 的服务暂不适用。请求设置 `store=false`，该设置不等于供应商的零保留承诺。请求格式依据 [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)；JSON mode 由本地 Pydantic 继续检查动作结构和证据引用。

默认预算与回放相同，可通过 `--max-decisions/--max-tools/--max-seconds` 调整。每次输出上限最多 4,096 token，输入按请求 UTF-8 字节数加 1,024 的余量保守估算；余量不足时以 `budget_exhausted` 停止，不裁掉证据后继续发送。用量取 API 返回的 `input_tokens/output_tokens`，拒答与截断也记账。网络异常或无有效用量时 `budget.usage_complete=false`，此时 `tokens_used` 只包含已知用量，不能作为完整账单或硬性费用上限。超时取消本机等待，服务端是否已生成或计费无法据此确定。

输出为完整状态 JSON，含 `cloud_consent`（摘要、目的地、模型、确认时间）和报告。报告修复验证仍为“未执行”。`--trace` 仅新建 JSONL 文件；退出码 `0` 表示完成、缺信息或无进展，`1` 表示预算/模型/动作/工具异常停止，`2` 表示启动参数、材料、密钥或输出路径错误。具体原因见 `stop_reason` 和轨迹。五类开发案例已完成在线运行，完整报告累计验收通过 5/5（来自不同 Step 的开发复测）。`replay/diagnose` 在首轮请求前，从首份有效且环境 ID 唯一的快照绑定 `target_environment`；不额外增加工具调用，后续文本读取或对照快照不改变目标。快照无效或环境 ID 重复时，目标保持未知。逐例结果见 [进度记录](docs/progress.md)。

## 离线控制循环回放

```bash
mkdir -p runs
uv run --locked deepdebug replay \
  --root benchmark/dev/dep_002/materials \
  --log log.txt --config launch.json \
  --snapshot target_snapshot.json --snapshot project_snapshot.json \
  --responses examples/dep_002_replay.json \
  --trace runs/dep_002-trace.jsonl
```

命令将含 `report` 的完整状态 JSON 输出到标准输出。示例固定响应先提出缺包候选，再通过真实的配置和快照工具结果更新为解释器不一致；响应是人工编写的 synthetic 演示，不调用云端、不计入诊断效果。报告保留证据引用、修复建议和验证判据，修复状态为“未执行”。

`--trace` 可选，逐行写入决策、工具调用、缓存命中、错误及停止时的完整状态；仅新建文件，重复运行需换一个文件名。以上 `--root` 模式的状态与轨迹保留未脱敏的原始材料片段、路径及环境信息，仅供本地检查；当前无自动清理。响应格式见 [示例说明](examples/README.md)，决策 Schema 可用 `deepdebug schema decision` 导出。

默认最多 6 次决策、8 次工具调用、120 秒；可用 `--max-decisions`、`--max-tools`、`--max-seconds` 调整。首轮日志解析计入工具预算。同名同参调用复用结果和证据；连续两轮没有新证据或假设变化时停止。无效决策最多修正一次，瞬时模型接口失败最多重试一次，均计入决策预算。回放 token 用量由响应文件提供模拟值，默认 0。

回放沿用 `--code`、`--config`、`--snapshot`、`--path` 与 `--path-root` 的显式登记边界。第一份快照为目标，环境 ID 必须唯一；模型只能读取选定探针对应的快照字段。退出码：`0` 表示完成、请求补充信息或无进展停止；`1` 表示预算、模型接口、无效动作或工具不可用导致停止；`2` 表示输入或输出文件错误。具体原因以状态的 `stop_reason` 和工具历史为准。

`need_info` 可附带已有依据的摘要、分类和条件性修复建议，报告同时保留动作中的补充问题；未提供结论时沿用日志摘要和 unknown 分类。普通文本证据的 `collected_at` 是材料登记时间，不能用来推断故障发生时间。模型在关键事实缺失且日志片段被截断时，可通过 `read_artifact` 补读省略区间。

## 保存与管理会话

```bash
uv run --locked deepdebug sessions save --state runs/dep_002.state.json \
  --reviewed runs/dep_002-reviewed.json --trace runs/dep_002-trace.jsonl
uv run --locked deepdebug sessions list
uv run --locked deepdebug sessions load --id 保存时返回的ID
uv run --locked deepdebug sessions delete --id 保存时返回的ID
uv run --locked deepdebug sessions cleanup
```

默认目录为当前工作目录下 `sessions/`，可用 `--directory` 指定专用目录；父目录须已存在。每份会话位于独立随机 ID 目录，目录权限 0700，数据文件权限 0600。保存完整状态，可同时保存对应的确认副本和轨迹；轨迹序号、会话身份与末状态须一致。`load` 输出含 state/review/trace 的会话包，读取不启动模型请求。`save --id ...` 更新已有同一诊断会话，保存失败保留旧版本。

保留期从最后保存起算 7 天。页面打开/交互及每次 sessions 命令自动清理过期记录，也可显式执行 cleanup；程序未运行时不在后台清理。删除只处理本工具管理的单文件会话目录；遇到链接、损坏数据或额外文件会报错并保留数据。`runs/`、用户下载及其他手动保存文件不受此保留期管理。

页面“保存与打开本地会话”提供相同能力；打开后进入独立的已保存会话视图，恢复原材料、报告及轨迹；无报告的取证状态可查看并下载。保存预览核查后的副本仍可能含人工未发现的敏感内容，请按私有数据管理目录。

## 补充材料后继续诊断

保存时需包含已确认副本。先查看 `sessions load --id ...` 输出中的历史状态，核查此前证据、判断和未决问题；随后准备补充材料：

```bash
uv run --locked deepdebug extend-preview --session 保存ID \
  --root /absolute/new-materials --log more.log --config extra.json \
  --output runs/continued-preview.json
# 核查全部旧/新材料以及保存的历史状态后：
uv run --locked deepdebug confirm --preview runs/continued-preview.json --output runs/continued-reviewed.json
uv run --locked deepdebug continue --session 保存ID \
  --reviewed runs/continued-reviewed.json --review-history \
  --send-to https://api.openai.com/v1/responses --model '你的模型ID'
```

`extend-preview` 只追加已选 log/code/config/snapshot，旧副本、编号、顺序和登记时间保持不变；合计仍最多 10 份。新增脱敏别名从已有编号之后分配，避免把不同值误认为相同；原始值与旧别名的映射不保存，跨轮相同敏感值不会自动合并。核查内容时可据已知信息判断关联。已确认新副本必须完整保留旧材料前缀，不能用续跑替换旧日志或修改旧证据。

`--review-history` 表示已核查保存状态中的旧证据与判断；云端续跑重新指定目的地、模型并授权发送旧历史与新增范围。离线续跑用 `--responses 固定响应.json` 替代云端参数。允许不添加材料后重试，但仍需核查历史。每轮 `--max-decisions/--max-tools/--max-tokens/--max-seconds` 表示新增额度，状态保留累计实际用量，未知用量标记不会因续跑消失。

续跑复用未变材料对应的工具缓存，结果仍指原采集时刻；旧报告与验证记录保留在原轨迹，新的报告重新形成，修复匹配需再次核查。成功返回后更新同一保存 ID；模型异常停止也保存有明确停止原因的状态。准备失败时原记录保留。页面“已保存会话 → 补充材料并继续诊断”提供相同核查和授权流程。

## 预置修复检查

```bash
uv run --locked deepdebug builtin-check
uv run --locked deepdebug builtin-check --case path --check before_fix
uv run --locked deepdebug builtin-check --case path --check after_fix
```

不指定案例时列出固定修复与成功判据。案例为 `dependency/path/shape/device`，阶段为 `before_fix/after_fix`。错误版返回“失败”并保留完整输出，修复版通过返回“预置复现通过”；缺解释器、PyTorch/CUDA、超时或无法取得完整输出时返回“无法执行”。退出码为 0 通过、1 未通过/无法执行、2 参数错误。默认使用当前解释器，可通过 `--python /absolute/python` 显式选择本机环境；形状与设备案例需要 PyTorch，设备案例还需要 CUDA。

检查只在临时目录执行开发者固定程序，使用 Python `-I`，普通案例限时 10 秒、设备案例 15 秒，输出上限 64 KiB。依赖案例创建一个预置模块并修正导入目录，路径案例保持工作目录并修正权重引用；不安装包、不修改用户代码。每次结果包含执行环境、解释器、时间、退出码和输出。

核查报告中的建议与列出的预置修复匹配后，可以关联前后对照：

```bash
uv run --locked deepdebug verify-report --state runs/path.state.json \
  --case path --fix-index 1 --matches-preset --output runs/path.verified.json
uv run --locked deepdebug report --state runs/path.verified.json --output runs/path.verified.md
```

`--fix-index` 从 1 开始；`--matches-preset` 表示用户已核查匹配关系。省略确认标志时只记录“未执行”，不运行检查。退出码取本次修复版检查结果。验证后的完整状态保留原诊断与历史检查，新增证据和工具记录；错误版失败与修复版通过分别列出，不将预置成功当作用户训练或生成补丁验证。后置检查由用户另行触发，独立于已结束的诊断预算，每次仍受固定超时与输出限制。

页面报告下的“预置案例修复验证”提供同一流程，执行环境为页面进程的本机解释器；运行后报告与下载轨迹同步更新。Agent 工具也可调用固定案例，结果留在工具记录；只有经过上述匹配确认流程才关联到修复建议。

## 报告导出与一致性检查

先将 `replay` 或 `diagnose` 的标准输出保存为状态 JSON，例如 `runs/dep_002.state.json`，再执行：

```bash
uv run --locked deepdebug report --state runs/dep_002.state.json --output runs/report.md
uv run --locked deepdebug report --state runs/dep_002.state.json --format json --output runs/report.json
uv run --locked deepdebug check-report --json runs/report.json --markdown runs/report.md
```

导出前重新校验完整状态及报告引用；尚无报告的 `collect` 状态不可导出。JSON 文件是独立的 `DiagnosisReport`，Markdown 包含同一报告的全部字段，包括材料编号与显示名称目录、证据原文、位置、采集时间、文档 URL/版本、工具结果、修复条件和执行状态。文本以字面量显示，保留代码及 Markdown 符号。导出不会运行模型或修复。

省略 `--output` 时输出到标准输出；指定文件时仅新建，权限 `0600`，父目录须已存在。原始回放的报告仍含未脱敏材料；导出沿用输入状态中的内容。`check-report` 将 JSON 重新渲染后与 Markdown 精确比较，人工改动排版也会报告不一致；它检查格式间内容一致性，不判断诊断结论是否正确。退出码为 `0` 成功/一致、`1` 不一致、`2` 输入或输出错误。

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

`deepdebug schema <kind>` 输出 JSON Schema，`kind` 可选 `action`、`state`、`report`、`snapshot`、`decision`。接口字段及约束见 [协议说明](docs/tool-api.md)。

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
| `src/deepdebug/agent/` | 协议、单 Agent 控制器、决策校验、预算停止与轨迹 |
| `src/deepdebug/llm/`、`src/deepdebug/replay.py` | 模型接口、固定响应客户端与离线回放流程 |
| `src/deepdebug/tools/` | 材料登记、日志解析、环境采集与快照读取、路径引用、本地文档检索和取证会话 |
| `src/deepdebug/knowledge/`、`knowledge/` | 随包发布的固定文档语料、来源清单与维护说明 |
| `src/deepdebug/security/` | 只读路径边界、常见规则脱敏、预览与内容摘要确认 |
| `src/deepdebug/agent/evidence.py` | 会话内稳定证据编号与去重 |
| `src/deepdebug/collection.py` | 宿主驱动的 CLI 取证流程 |
| `src/deepdebug/reporting/`、`ui/` | 双格式报告、内容一致性校验与 Streamlit 展示 |
| `src/deepdebug/sessions.py`、`continuation.py` | 本地会话保存、保留期和补充材料续跑 |
| `src/deepdebug/evaluation/` | 固定版本评测执行、人工评分与指标汇总 |
| `tests/` | 自动化检查 |
| `docs/` | 架构决策与逐步进度 |
| `benchmark/`、`scripts/` | 10 个开发案例、30 个测试案例、语义标签及固定采集脚本 |
| `examples/` | 人工固定响应与回放演示说明 |

JSON 报告由控制器组装并校验，Markdown 从同一结构渲染，Streamlit 调用共享流程。云端适配使用 HTTPX；BM25 检索使用标准库。

## 范围与边界

首版聚焦 OOM、设备不一致、依赖/解释器、路径和配置/形状五类问题。采用单 Agent 状态机，默认导入环境快照；本机采集需要用户明确选择。模型不得执行任意代码或 shell、安装依赖、修改用户文件或重跑真实训练。上传材料和检索文档均是不可信数据。

当前已实现材料与路径边界、大小检查、固定环境探针的超时和输出限制、固定语料检索，以及控制器的动作调度和预算停止。脱敏确认支持离线回放与显式授权后的云端请求，证据语义和真实诊断效果待评测。`collect` 中的调用次数和耗时仅作记录，`replay/diagnose` 执行停止判断；同步本地工具在返回后检查总时限，不提供抢占式中断。内置验证只针对开发者维护的预置案例，不能等同于真实训练恢复。`runs/`、`sessions/` 已被 Git 忽略，专用会话目录支持手动保存与访问时的七天过期清理。不得提交真实密钥和私有日志。

下一步：完成 B0/B1/A 真实评测、人工评分与失败分析，补齐技术报告与视频交付。
