# 数据协议 v1

协议实现位于 `src/deepdebug/agent/`，不执行文件读取、探针或模型调用。使用 `deepdebug schema action/state/report/snapshot` 导出当前 JSON Schema。

## 类型与边界

| 类型 | 约束与用途 |
|---|---|
| `Artifact` | 材料 ID、类型、显示名、来源、声明大小、脱敏审阅状态；声明大小上限 2 MiB，不含服务器路径 |
| `EnvironmentSnapshot` | 环境标识、解释器、带时区采集时间、Python 版本、指定包元数据；缺包与查询失败分开表示 |
| `Evidence` | 稳定 ID、来源、原始行号或 JSON Pointer、原始内容、采集时间与截断标记 |
| `Hypothesis` | 原因、置信度标签、支持/反对证据、待检查项；最多 3 个候选 |
| `ToolResult` | `ok/unavailable/denied/timeout/error`；非成功必须说明原因，不接受正常结果 data |
| `DiagnosisReport` | 摘要、环境、事实证据、候选原因、修复适用条件与影响、验证步骤与结果、未决问题、工具记录和停止原因 |
| `DiagnosisState` | 材料、证据、假设、下一动作、工具记录、预算、停止原因和报告；检查跨对象引用 |

协议拒绝未知字段；计数必须是整数，不能用布尔值充当。所有采集/执行时间必须带时区。环境观察需要环境标识；文档观察需要来源 URL 和适用版本（采集日期由 Evidence.collected_at 表示）。材料 ID 用 `A001`，证据用 `E001`，假设用 `H1`，工具调用用 `T001`。

快照中的“not_found”仅表示没有查到该分发包元数据，不能单独证明任意 import 一定失败。`EnvironmentSnapshot` 当前仅包含首批案例需要的 Python 与包元数据，CUDA/GPU 字段在环境工具阶段添加。`target_environment=null` 明确表示目标环境尚未确定。

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

环境 ID 和路径引用 ID 是不透明标识，后续工具注册表必须检查它们是否获授权；类型合法不等于可以执行。单次错误动作重试、缓存和停止策略由后续控制器落实。

## 报告与状态一致性

报告中所有修复、假设和验证的证据引用必须存在；支持型置信度至少要有支持证据。完成状态需要有支持的候选原因，缺信息状态必须列出具体问题。

附加到状态的报告必须与当前会话、目标环境、假设、工具记录、停止原因一致；其证据内容必须与状态中已登记证据相同。状态还会拒绝重复 ID、未经登记的材料引用及超过 10 份材料的输入。

验证状态为 `静态检查通过/预置复现通过/失败/无法执行/未执行`。前三种必须附执行时间、环境、退出码、输出和证据引用；通过要求退出码为 0；失败输出不得截断。后两种不接受已经执行检查的记录，必须说明原因。若探测环境失败，应在工具历史中记录该探测，而非伪造验证执行。

这些校验检查的是结构与一致性，不能证明模型提供的内容真实、证据语义充分或检查真的运行过。后续控制器必须自己登记证据与执行记录，不能直接信任模型提交的状态/执行结果。最终报告应通过完整 `DiagnosisState` 校验，而非只做独立报告校验。

## 预算与更新

`Budget` 默认 6 次决策、8 次工具、1 次报告修正、50,000 token（含预留 5,000）、120 秒总时限，普通工具 10 秒、GPU 探针 15 秒。当前只校验配置和计数，尚不执行预算扣减和停止；允许记录超过上限的实际用量，以便保留超时/超支事实。

协议对象不是不可变存储。嵌套列表修改、直接赋值或 `model_copy(update=...)` 不自动完成全状态校验；在后续持久化、调度和输出边界调用 `DiagnosisState.model_validate`（对象会重新校验）或 `model_validate_json`。
