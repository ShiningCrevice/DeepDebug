# 数据协议与工具接口 v1

本文按协议和工具说明当前参数、返回值及约束。架构与设计理由见 [架构设计](design.md)，改动历史与验证结果见 [开发进度](progress.md)，CLI 使用示例见 [README](../README.md)。

协议实现位于 `src/deepdebug/agent/`，协议自身不执行文件读取、探针或模型调用。使用 `deepdebug schema action/state/report/snapshot/decision` 导出当前 JSON Schema。宿主接口见下文的材料登记、取证会话、环境采集、路径检查和文档检索章节。

## 类型与边界

| 类型 | 约束与用途 |
|---|---|
| `Artifact` | 材料 ID、类型、显示名、来源、声明大小、脱敏审阅状态；声明大小上限 2 MiB，不含服务器路径 |
| `EnvironmentSnapshot` | 环境标识、解释器、带时区采集时间、Python 版本、指定包元数据，可选 PyTorch/CUDA 与 GPU 观察；缺包与查询失败分开表示 |
| `Evidence` | 稳定 ID、来源、原始行号或 JSON Pointer、原始内容、采集时间与截断标记 |
| `Hypothesis` | 原因、置信度标签、支持/反对证据、待检查项；最多 3 个候选 |
| `ToolResult` | `ok/unavailable/denied/timeout/error`；非成功必须说明原因，不接受正常结果 data |
| `DiagnosisReport` | 摘要、环境、事实证据、候选原因、修复适用条件与影响、验证步骤与结果、未决问题、工具记录和停止原因 |
| `DiagnosisState` | 材料、证据、假设、下一动作、工具记录、预算、停止原因和报告；检查跨对象引用 |
| `CloudConsent` | 已确认材料摘要、已授权 HTTP/HTTPS Responses 端点、模型 ID、确认时间和发送范围版本；随状态保存 |

协议拒绝未知字段；计数必须是整数，不能用布尔值充当。所有采集/执行时间必须带时区。环境观察需要环境标识；文档观察需要来源 URL 和适用版本（采集日期由 Evidence.collected_at 表示）。材料 ID 用 `A001`，证据用 `E001`，假设用 `H1`，工具调用用 `T001`。

快照中的“not_found”仅表示没有查到该分发包元数据，不能单独证明任意 import 一定失败。`EnvironmentSnapshot` 的可选 `torch_cuda/gpu` 字段兼容旧快照，缺失或 null 表示未采集；采集后的状态为 `ok/unavailable/timeout/error`，失败必须带 `error` 且不能携带成功数据。PyTorch 成功观察包含版本、CUDA 可用性和设备数，编译 CUDA 版本可为 null；GPU 成功观察包含非空设备列表及 MiB 显存摘要。两种观察各有带时区采样时间。`target_environment=null` 明确表示目标环境尚未确定。

## 动作协议

按 `action` 区分 `tool/need_info/finish`，工具动作再按 `tool` 区分参数。每次工具动作必须写明要回答的问题 `purpose`；尚未建立假设时可不填关联假设。

```json
{
  "action": "tool",
  "tool": "inspect_environment",
  "arguments": {
    "environment_id": "ENV_EMPTY",
    "probe_ids": ["python_identity", "package_metadata"]
  },
  "purpose": "比较实际解释器与依赖安装环境",
  "related_hypotheses": ["H1"]
}
```

七个规划工具均有参数类型：日志解析、材料读取、路径检查、环境检查、GPU 查询、文档检索和内置检查。读取最多 200 行，路径检查最多 10 个登记引用，检索最多 3 条。探针只允许 `python_identity/package_metadata/torch_cuda`；`dependency_import/interpreter_identity` 是预留的内置检查 ID，当前没有执行器。`need_info` 必须给出具体问题。

环境 ID 和路径引用 ID 是不透明标识。`ToolDispatcher` 把环境 ID 映射到登记快照，重复或无效环境拒绝绑定；路径 ID 必须在宿主授权清单中。只读工具接受校验后的参数，内置检查返回 `unavailable`。

## 报告与状态一致性

报告中所有修复、假设和验证的证据引用必须存在；支持型置信度至少要有支持证据。完成状态需要有支持的候选原因，缺信息状态必须列出具体问题。

附加到状态的报告必须与当前会话、目标环境、假设、工具记录、停止原因一致；其证据内容必须与状态中已登记证据相同。状态还会拒绝重复 ID、未经登记的材料引用及超过 10 份材料的输入。

验证状态为 `静态检查通过/预置复现通过/失败/无法执行/未执行`。前三种必须附执行时间、环境、退出码、输出和证据引用；通过要求退出码为 0；失败输出不得截断。后两种不接受已经执行检查的记录，必须说明原因。若探测环境失败，应在工具历史中记录该探测，而非伪造验证执行。

协议校验覆盖结构与一致性。证据真实性、语义支持和实际执行情况需另行核实；控制器只接受模型判断字段，由工具登记证据；未确认建议与预置修复匹配时，报告不关联执行结果；后置验证由宿主记录。最终报告须通过完整 `DiagnosisState` 校验。

`report --state FILE --format markdown|json [--output FILE]` 在输出边界重新校验完整状态，要求存在 report。JSON 输出为独立 `DiagnosisReport`；Markdown 包含同一报告全部字段。报告 materials 目录保留材料编号、显示名称、类型及脱敏状态，非空目录须与状态 inputs 一致；旧状态导出从 inputs 补齐目录。输入使用既有安全读取边界，状态文件上限 128 MiB；输出文件仅新建、权限 0600，省略路径时写标准输出。导出沿用原有材料脱敏状态，不自动确认或外发。

`check-report --json FILE --markdown FILE` 校验独立 JSON 报告并重渲染，与 Markdown 作精确文本比较。退出码 0 表示一致、1 表示不一致、2 表示文件或协议错误。该检查不核实证据语义或真实修复效果。

## 预算与更新

`Budget` 默认 6 次决策、8 次工具、1 次报告修正、50,000 token（含预留 5,000）、120 秒总时限，普通工具 10 秒、GPU 探针 15 秒。`collect` 仅记账；`Controller` 在决策、模型返回和工具边界检查决策数、工具数、总 token 与总耗时。首轮日志解析计入工具数，修正无效决策和重试接口失败计入决策数；缓存命中不增加工具计数。最后一次允许的决策仍可正常结束或执行预算内工具，下轮不再请求模型。

决策可用 token 是总额减报告预留与已用量；返回时耗尽额度则保留用量并停止，不执行该响应动作。回放用量是文件声明的模拟值，默认 0；云端用量取供应商响应。`usage_complete` 默认 true，发生网络异常或缺少有效用量后保持 false，表示 tokens_used 仅为已知合计。报告由宿主组装，无额外模型调用；`max_report_repairs/report_repairs` 暂保留，后者为 0。允许记录超过限额的实际返回值，以保留超时/超支事实。同步本地工具不能被总时限抢占，返回后停止后续工作；工具单次 timeout 字段尚不作用于这些内存/文件查询。

连续两轮无新证据或假设变化时 `no_progress`；无效决策最多修正一次，仍无效时 `invalid_action`。模型接口 timeout/unavailable 最多重试一次，失败时 `model_error`；非瞬时 error 直接停止。所有停止路径输出通过完整状态校验的 JSON 报告，预算与错误停止保留已有证据、候选和未决问题。

协议对象不是不可变存储。嵌套列表修改、直接赋值或 `model_copy(update=...)` 不自动完成全状态校验；持久化、调度和输出边界调用 `DiagnosisState.model_validate`（对象会重新校验）或 `model_validate_json`。

## 模型接口与决策

`ModelClient.decide(ModelRequest) → ModelResponse`：请求含 `instructions`、`state` 副本、`environments`（环境 ID → 材料 ID）、`path_reference_ids`、`response_schema`、可选 `correction`、`timeout_seconds` 与 `max_tokens`（输入输出合计剩余额度）。响应含 JSON `content`、非负整数 `input_tokens/output_tokens` 和可选 `failure=refused/incomplete/error`；failure 非空时先记用量再以 model_error 停止。`ReplayModelClient` 提供离线响应；remote 仅接受绑定确认边界的 `OpenAIResponsesClient`。

`Decision` 含 `observation`（新增事实/判断变化摘要）、`hypotheses`、`action`；finish 必须含 `conclusion={summary, category, fixes, unresolved_questions}`，need_info 可选该字段，tool 不接受结论。need_info 的结论引用在接纳假设前校验；报告保留结论中的摘要、分类及建议，并按动作问题在前的顺序合并、去重两处未决问题。未提供结论的 need_info 保留旧行为（日志摘要、unknown 分类、无修复建议）。finish 可声明 completed/tools_unavailable/no_progress；缺信息须用 need_info，预算与接口错误由宿主决定。结论不接受证据内容、工具历史或验证执行字段，引用在提交前按当前状态校验。材料与文档通过请求状态提供，系统指令明确其为不可信数据；同时区分材料登记、工具读取、快照采集及故障时间，并要求在关键事实缺失时补读截断日志的省略区间。 结束前还需核对候选的实例证据与置信度，以及每条修复对其他配置和路径的影响；不同条件或验证步骤的方案分别输出 fixes 项。这些语义要求由模型指令引导，协议仍校验字段及引用，效果通过真实报告核查。

`replay --responses FILE` 的文件是数组，每项包含 `decision` 对象或原始字符串，以及可选模拟用量；原始字符串可用于测试无效 JSON。文件通过相同只读目录边界加载，最多 2 MiB；响应不是执行代码。示例与命令见 [examples](../examples/README.md)。

### 云端发送协议

`diagnose(review, consent, budget=None, trace_stream=None) → DiagnosisState`：从 confirmed 副本创建新会话，记录 `material_review_sha256` 和 `cloud_consent`，首轮解析日志后进入同一控制循环。CLI 必填 `--reviewed/--send-to/--model`，命令本身表示同意发送选定副本；程序显示材料清单、目的地及模型，从副本自动取得摘要写入 CloudConsent；无原始材料或路径参数。CLI 在启动诊断时加载当前工作目录的 `.env`，已有环境变量优先；密钥从 `OPENAI_API_KEY` 读取。库调用方自行配置环境变量。

`CloudConsent` 的 `material_review_sha256` 必须与状态和副本一致；`endpoint` 为规范化后的 HTTP/HTTPS 完整地址，路径以 `/responses` 结尾，不含凭据、查询参数、片段或空白；`model` 为 1～128 位 ASCII 模型标识；`confirmed_at` 必须带时区；`scope` 固定为 `reviewed-evidence-tools-judgments-v1`。确认覆盖所选材料的工具片段、工具结果、固定文档摘要及模型判断；不是对未来任意材料的授权。

CLI 新增可选 `--base-url`，优先于环境变量 `OPENAI_BASE_URL`，两者都未设置时使用 `https://api.openai.com/v1`。`responses_endpoint(base_url)` 保留基础地址的路径前缀，去尾斜杠后追加 `/responses`，不自动添加 `/v1`；误传完整 Responses 地址会拒绝。`--send-to` 经同一规范化后必须等于计算结果，不匹配返回 2，尚未创建轨迹或请求模型。自定义服务仍使用 Responses 协议，不自动切换到 Chat Completions。库调用方直接在 CloudConsent 中提供完整目的地；适配器不重新读取地址环境变量。

`OutboundBoundary` 每轮核验固定登记内容、当前宿主状态及证据、环境映射、指令、Schema 和剩余额度；拒绝新增路径、材料、替换会话或改目的地/模型。实际请求不带完整源文件、报告、授权记录和本地预算对象，保留材料目录、目标环境身份、证据、工具历史和假设。序列化文本再次脱敏，模型响应也在入库前脱敏；证据行号及 JSON Pointer 仍以确认副本为准。

适配器向已确认 endpoint 发送 POST（默认 `/v1/responses`），使用 `text.format.type=json_object`、`store=false`，不提供供应商工具调用接口。输出上限为 `min(4096, 剩余token - 请求UTF-8字节数 - 1024)`，低于 16 时返回本地 budget 失败；输入预留是保守估算，实际用量取响应字段。HTTP 读取上限为解码后的 1 MiB，异步超时覆盖本次 HTTP 操作。供应商错误正文、拒答正文和无效原始决策不写入轨迹。

`ModelFailure.kind`：timeout 表示请求超时；unavailable 表示传输错误、HTTP 408/429/5xx；error 表示其他 HTTP 状态、无效响应或边界拒绝；budget 表示请求准备期间时间/额度不足。timeout/unavailable 共用控制器的一次重试；适配器不隐式重试、不跟随重定向、不读取代理配置。`http_status` 在 HTTP 拒绝时记录数字状态码，其他失败为 null；控制器将其写入 model_error 事件，终止报告显示该状态码，不包含供应商错误正文。`usage_unknown=true` 会使预算统计标为不完整。收到有效用量但生成不完整/拒答时，记账后停止，不使用部分决策。

`diagnose --max-tokens N` 设置总 token 预算（默认 50,000），包含固定 5,000 报告预留；小于预留的值在启动时拒绝。实际请求使用扣除预留及已用量后的额度，再按上述保守输入预留计算输出上限；因此总预算仍有余量时也可能发生输出截断。单次输出最多 4,096。

`diagnose` 退出码与回放一致：0 为 completed/need_info/no_progress，1 为其他停止原因，2 为启动失败。模型标识由用户选择；真实调用与诊断验收结果见 [开发进度](progress.md)。

## JSONL 轨迹

`JsonlTrace(stream).write(event, state, details)` 在写入前重校验完整状态，并逐行 flush。每行含递增 `sequence`、带时区 `recorded_at`、`session_id`、`event`、`details` 和完整 `state`。

事件为 start、resume、checkpoint、model_request、model_response、model_error、invalid_decision、decision、tool、stop、verification。start/resume 标注 offline/remote；checkpoint 标注缺少旧轨迹时保存的已有状态，verification 记录后置验证结果；model_response 记录输入输出用量；model_error 记录固定分类、用量未知标记及可用的 http_status。decision 保存观察摘要和新假设；tool 保存完整动作、原始工具调用 ID 与 cached 标记。成功、拒绝和不可用结果均可通过状态的 tool_history 追溯；缓存命中不会新增历史项。无效原始响应不写入轨迹。`--trace` 仅新建文件，不自动删除，支持核查历史和追加材料后的显式续跑。`--root` 的轨迹包含原始材料；`--reviewed` 的材料内容来自脱敏副本，每个状态保留 `material_review_sha256`；云端状态另保留 `cloud_consent`。

## 材料登记

`MaterialRegistry.register` 只在用户指定的独立根目录内登记显式相对路径，先校验扩展名、文件类型、2 MiB 实际字节上限与 UTF-8 文本，再分配 `A001…`。`origin=local` 表示本地材料输入，不代表执行了本机探针。最多 10 份材料，记录保持 `pending` 脱敏状态。内容在登记时固定，后续工具按 ID 读取内存副本。

`AuthorizedRoot` 使用 POSIX 目录描述符逐级打开，不跟随符号链接，拒绝硬链接、非普通文件、隐藏路径、`..` 和 `benchmark/gold`。目录描述符可防止已打开根目录被替换为链接后转向其他目录；该边界不覆盖系统级权限攻击。路径检查无法识别用户复制到其他位置的 gold 内容，运行时只应登记授权材料。

## 脱敏预览与确认

`preview_materials(root, log, code, config, snapshots) → MaterialReview`：沿用显式材料登记边界，生成完整脱敏副本。材料顺序为日志、代码、配置、快照；只接受一份日志，第一份快照仍为目标环境。显示名为 `A001.txt` 等 ID 别名，原文件名和替换映射不持久化。常见规则及用户核查步骤见 [README](../README.md#脱敏预览与材料确认)。

`MaterialReview` 字段：

| 字段 | 约束 |
|---|---|
| `content.format_version` | 固定为 1 |
| `content.redaction_version` | 固定为 common-secrets-home-v1 |
| `content.materials` | 1～10 份有序材料；每份为 artifact、完整 text、带时区 registered_at |
| `sha256` | content 的规范 JSON（键排序、UTF-8、紧凑分隔符）SHA-256；校验时重新计算 |
| `status` | preview 或 confirmed |
| `confirmed_at` | confirmed 必须有带时区时间；preview 必须为空 |

每份实际 UTF-8 内容最多 2 MiB，字节数须与 artifact 一致，禁止 NUL。快照保留采集时间；有效 JSON 字符串在解码后脱敏，保留物理行数，证据 JSON Pointer 指向处理后的字段。预览和确认文件中的 artifact 保持 pending，消费有效确认记录时才导入为 reviewed。

`confirm_materials(review)`：自动校验 preview 内容与文件内摘要，返回 confirmed 副本。CLI `confirm --preview FILE --output FILE` 表示用户已核查全部材料，输出材料清单，不要求用户输入摘要。修改文本、材料范围、类型、顺序、时间或规则版本后，旧摘要失效。摘要不是签名；确认仅供本地回放，不授权云端发送。

`save_review(path, review)`：重校验后以 0600 权限新建文件，不覆盖已有路径。`load_review(path)`：复用链接/gold/目录边界，读取外层 JSON 最多 128 MiB，再校验摘要、单份内容和总份数。扩大外层读取上限用于容纳十份输入及 JSON 转义，不改变原始材料 2 MiB 限制。

`reviewed_registry(review)` 只接受 confirmed，建立内容固定且状态为 reviewed 的登记表。`replay_reviewed` 用该表运行原控制器，将确认摘要写入 `DiagnosisState.material_review_sha256`；该字段非空时输入必须全部为 reviewed。材料、证据与工具结果不再从原路径读取。CLI `replay --reviewed FILE` 拒绝同时提供 root/log/code/config/snapshot/path/path-root；预览范围之外的路径观察不开放。

`preview/confirm` 成功输出完整 JSON，退出码 0；输入、确认摘要或输出文件错误返回 2，错误信息不回显材料内容。预览、确认和回放只在本地处理；云端发送须另经 `diagnose` 授权。人工固定响应文件独立提供，不经过材料脱敏。

## 取证会话

`CollectionSession` 当前提供六个宿主方法：

| 方法 | 输出与边界 |
|---|---|
| `parse_log(artifact_id, context_lines=5)` | 普通 Python 异常摘要、原始日志行号、文件/行号/函数堆栈位置与有限上下文；保留最近 5 个异常和 10 个帧，不判断根因 |
| `read_artifact(artifact_id, start_line=1, max_lines=200)` | 最多 200 行、16,000 字符；保留起止行和截断标志，不执行 Python 或解析 YAML |
| `inspect_snapshot(artifact_id, as_target=True, probe_ids=None)` | 以 `inspect_environment` 记录快照模式结果；校验快照及环境 ID 冲突，证据保留采集时间、JSON Pointer 与原始 JSON 值 |
| `query_gpu(artifact_id)` | 读取已登记快照的 GPU 字段，成功证据指向 `/gpu`；保留采样时间，失败状态进入历史，缺字段返回 `unavailable` |
| `check_paths(references, reference_ids)` | 查询宿主已登记的最多 10 个路径引用，结果含存在性、文件/目录类型和授权基准目录；观察来源为 `local/collector` |
| `search_docs(query, category=None, max_results=3)` | 检索固定本地语料，返回文档 ID、URL、版本、整理时间与摘要，登记 `document` 来源证据 |

快照宿主接口显式绑定材料 ID；调度层把 `environment_id` 绑定至授权快照，按 `probe_ids` 返回环境元数据及所选字段：python_identity → python_version、package_metadata → packages、torch_cuda → torch_cuda。环境元数据始终返回，未采集 torch_cuda 时字段为 null；证据保留原始 JSON，缺失字段不生成证据。`probe_ids=None` 沿用宿主全字段读取。`replay/diagnose` 初始化调度器时，从首份有效且环境 ID 唯一的快照绑定 `target_environment`（环境标识、解释器及采集时间），首轮轨迹和模型请求即包含该身份信息；此步骤不新增证据或工具调用。`read_artifact` 将快照作为普通文本读取，不改变该绑定，文本证据的 `collected_at` 使用材料登记时间。该时间不能作为故障发生时间。CLI 只把第一份快照作为目标，后续比较快照使用 `as_target=False`；第一份失败时目标保持未知。

工具结果完整 JSON 最多 64 KiB，超限返回拒绝结果。证据内容总量另受材料大小和片段上限约束。读取片段时只要省略原文部分就标记 `truncated`。日志支持常见 Python traceback 和异常链；分布式前缀、多语言日志、ExceptionGroup 树形堆栈尚未专门支持。无匹配时返回空异常列表。

`EvidenceRegistry` 根据来源、位置、内容、时间与截断标记去重；重复读取复用证据 ID，宿主直接调用仍记录新 `T001…`；控制器调度的同名同参调用由缓存复用原结果。每次工具执行后重新校验完整状态。工具历史记录失败，未知材料 ID 返回 `denied`，非法参数/快照返回 `error`，二者不携带成功 data。登记阶段失败则中止 CLI，不构造不完整会话。

取证输出 `DiagnosisState`，假设列表为空，报告与诊断停止原因为 null。调用数与取证会话耗时会记录，预算上限和自动清理尚未执行。固定环境子进程已执行单次超时和输出限制。所有输出只在本地，未经脱敏。

## 环境采集与快照查询

`capture_environment(interpreter, environment_id, packages, torch_cuda=False, gpu=False)` 由宿主显式调用，返回可导入的 `EnvironmentSnapshot`。CLI `snapshot` 与 `scripts/collect_environment.py` 共用入口，要求解释器绝对路径和环境标识，包名限制为最多 10 个分发包名称。默认只采集 Python 标识和包元数据；两个可选探针分别通过 `--torch-cuda/--gpu` 启用。

固定 Python 参数为 `-I -c <内置探针> ...`，工作目录为临时目录；包查询使用 `importlib.metadata`。GPU 查询仅从系统 `os.defpath` 查找 `nvidia-smi`，固定参数为 `--query-gpu=index,name,memory.total,memory.used --format=csv,noheader,nounits`。元数据限时 10 秒，其余探针各 15 秒；`process.run_probe` 对合并 stdout/stderr 读取上限 64 KiB，超时/超限终止并回收探针。该执行器是内部实现，模型没有任意命令入口。

Python 身份采集失败不输出快照；可选探针失败时仍保留 Python 信息与各探针状态。CPU-only PyTorch 可成功返回 `cuda_available=false`；缺少 PyTorch、未找到 GPU 程序或查询列表为空时为 `unavailable`，非零退出或无效输出为 `error`。`inspect_snapshot` 的成功表示读取有效快照，各探针的失败仍作为原始数据保留；`query_gpu` 将 GPU 失败状态写入工具结果，并保留快照来源和采样时间。GPU 查询不改变会话目标环境。

## 路径引用检查

`PathReferences` 由宿主绑定一个 `AuthorizedRoot`，显式登记相对路径后返回 `P001…`。CLI `--path` 登记引用，`--path-root` 指定授权基准目录（默认材料根目录）。检查使用保持打开的目录描述符，只做逐级目录访问与最终节点 stat，拒绝符号链接、硬链接、特殊文件、隐藏路径、越界及 gold；不扫描配置或遍历目录。路径缺失返回成功结果中的 `exists=false/type=null`；未登记 ID 或越权返回 `denied`，参数数量非法返回 `error`。批量中任一引用失败时整次结果失败，不登记部分成功证据。

路径结果包含授权时的基准目录名称，来源 `local/collector` 表示命令运行主机，采集时间是检查时刻。与目标环境的关联需要用户提供事实，不能由导入快照推定。该目录句柄须保持打开直到检查完成；材料读取仍使用登记时固定内容。

## 本地文档检索

`SearchDocsArguments` 接受去除首尾空白后 1～500 字符的查询、可选故障类别及 1～3 条结果限制。`DocumentIndex` 只从固定包目录安全读取 `documents.json`，首次查询后在会话内固定内容。语料模型校验文档 ID 唯一、URL、版本、带时区整理时间、摘要长度及最多 25 条记录；不接受引用外部文件的字段。安装目录可包含 `.venv` 等隐藏组件，所有链接、越界、gold 与隐藏的相对文件路径仍被拒绝。

当前语料为 15 条人工改写摘要，`content_kind=curated_summary`，五类故障各 3 条。检索采用 BM25 排序，标题、关键词和摘要合并索引，固定 `k1=1.2/b=0.75`，采用正值 IDF。索引保留词频；查询词去重并排序后累加，以保证重复查询词不增加分数及排序可复现。完整语料统计不随类别过滤变化。英文忽略大小写，保留异常名、下划线标识符、点分 API 及逐级后缀；中文按相邻双字切分。先过滤类别，再返回正分数结果，同分按文档 ID 排序；计算公式见 [语料说明](../knowledge/README.md)。

返回 `data={query, category, matches, total}`；`matches` 每项包含文档完整元数据、`excerpt` 与浮点 `score`。`total` 是过滤后正分数匹配总数，超出返回条数时工具标记 `truncated=true`，摘要本身不截断。无匹配是 `ok` 加空列表；参数或语料结构非法为 `error`，固定语料读取受权限/路径限制时为 `denied`。失败保留工具记录，不登记部分证据。

文档证据来源为 `document/D001…`，包含来源 URL 和适用版本；位置 `/excerpt` 相对于该文档记录，`collected_at` 是语料整理时间。工具结果来源为 `local/docs_index/collector`，时间是本次查询时刻。同一会话的重复命中复用证据 ID，宿主直接调用仍计数，控制器缓存命中不计数。该工具不修改目标环境或产生诊断报告。

独立入口为 `search-docs QUERY [--category CATEGORY] [--max-results N]`；`collect --docs-query QUERY [--docs-category CATEGORY]` 在取证末尾追加一次检索。两者均输出完整校验后的 `DiagnosisState`。文档版本不自动与目标环境匹配，文档内容仍是不可信数据；模型使用文档作实例结论的语义支持检查尚未实现。

## 上传与界面入口

`MaterialRegistry.register_bytes(name, raw, kind, origin="upload")` 登记显式提供的字节，与本地登记共享 2 MiB/10 份上限、后缀、UTF-8 和 NUL 校验；名称不用于文件读取。`preview_registry` 将已登记内容转换为既有 MaterialReview。界面上传不会写成可执行文件，也不执行上传代码。

Streamlit 页面使用同一 `diagnose` 和 `replay_reviewed`；外发动作由“授权发送并开始诊断”按钮触发，要求已核查预览及有效目的地/模型，凭据仍仅读取 `OPENAI_API_KEY`。`ProgressStream` 接收 JSONL 完整事件，重校验事件状态后交给界面回调；事件数据和下载轨迹来自同一流。

## 固定预置验证

`run_builtin_check` 的 case_id 支持 dependency/path/shape/device，check_id 支持 before_fix/after_fix。旧保留值 dependency_import/interpreter_identity 仍接受协议解析，但无对应执行实现，返回 unavailable。未知案例同样 unavailable。固定检查使用当前解释器，source 为 local/builtin，带实际执行环境标识；不把本机结果当作目标快照事实。

工具 data 保留案例、阶段、预置修复、成功判据、检查状态、解释器、环境标识、时间及 execution；执行成功取得检查结果时工具 status=ok，data.status 区分失败与预置复现通过。工具失败时 data 为空、error 说明原因；缺环境为 unavailable，超时为 timeout，无法保留完整输出为 error。固定普通/设备检查超时为 10/15 秒，输出最多 64 KiB。

`Verification.fix_index` 为可选的从 1 开始修复建议序号，须在 report.fixes 范围内。`verify-report` 读取完整状态，用户通过 matches-preset 确认匹配后执行前后对照，追加证据/工具记录/验证，并重新校验完整状态。未确认时仅记录未执行。CLI 新建验证后状态文件；UI 更新当前结果并追加完整状态轨迹事件。匹配确认是调用方的核查声明，可由用户或获授权 AI 代理执行；实际核查者另附来源记录，不把 AI 声明标成人工评分。

## 本地会话存储

`SavedSession` 包含 saved_at/state/review/trace；可选 review 必须 confirmed 且材料目录与 state.inputs、确认摘要一致。每条 trace 经 TraceEvent 校验 sequence/event/recorded_at/session_id/details/state 字段及类型；序号从 1 连续递增，会话 ID 和 checkpoint 状态一致，末状态等于保存状态。无轨迹也可保存状态。

`SessionStore` 只管理 32 位小写十六进制随机目录 ID。单份会话包最多 128 MiB，文件读写拒绝链接并限制为普通单链接文件。保存既有 ID 时须为同一诊断 session_id；删除要求目录只有有效 session.json。每次保存更新 saved_at；cleanup 删除距最后保存至少 7 天的有效记录，非法记录报错并保留。

`sessions save/list/load/delete/cleanup` 共用该存储，默认 sessions/，可用 --directory 指定专用根目录。CLI 每次操作前先清理过期记录；成功返回 0，文件、结构或引用错误返回 2。save 的 --reviewed/--trace 可选，--id 指定更新已有记录；load 返回整个会话包，不发起诊断。

## 续跑协议

`extend_review(confirmed_review, additions)` 返回 preview，保持旧 PreviewMaterial 前缀完全相同，追加连续材料 ID；首份仍须 log，后续可包含补充日志，合计不超过 10。新增文本使用保留旧别名序号的脱敏器，不推断跨轮原值相等性。

`continue_session(saved, review, history_reviewed, allowance, consent|replay_model)` 要求旧会话有确认副本并已停止，历史已核查，新 review confirmed 且保留旧前缀；云端与回放模型二选一。新增 Budget 不得有已消费计数。状态继续使用相同 session_id，累计已用计数保持，新上限为已用量加本次额度；continued_from_sha256 记录续跑前完整状态摘要，previous_conclusion 保存上一轮摘要/分类/修复/未决问题。

恢复时重新校验登记材料与状态、证据 ID、工具缓存参数、外发授权和最终报告。环境绑定未变时旧工具失败也作为历史缓存保留；新增快照改变绑定或使 ID 歧义时，环境/GPU 调用重新调度。旧报告保留在轨迹，当前报告重新生成；轨迹序号连续，末状态等于保存状态。CLI continue 成功/缺信息/无进展返回 0，运行异常停止返回 1，准备或保存错误返回 2。准备失败不覆盖保存记录。

## 评测评分来源

`evaluation.scoring.SemanticScore` 的 reviewer 标识实际评分者，reviewer_kind 为 human（缺省，兼容旧记录）或 ai。人工的 attested_human=true 且 reviewer_model 为空；AI 的 attested_human=false 且 reviewer_model 必填，未知精确标识须注明未提供。来源与声明冲突会被拒绝。

second_reviewer、second_reviewer_kind、second_reviewer_model 记录复评者；旧记录未填复评类型时按 human 解释。AI 复评必须有模型来源，所有复评均需 disagreement_and_resolution；无复评者不能只填来源。primary/secondary 身份不能相同。评分字段及证据计数见 benchmark/README.md。

汇总的 scoring 表示主评分来源，为 pending/human/ai/mixed；每组 scored 是总评分量，human_scored 与 ai_scored 分别统计来源。failure_type 为评分失败类别。记录持续绑定原计划和结果/轨迹摘要，AI 评分不改运行状态、分母或已保存的诊断结论。
