# benchmark

`dev/dep_001`、`dev/dep_002` 是真实采集的 Python 依赖导入失败案例，同属 `dependency_interpreter` 案例族；实际日志相同，环境和预期解释器证据不同。`case.json` 描述采集来源，`materials/` 只包含诊断输入。

新增 `dev/path_001` 属于 `relative_working_directory` 案例族，记录配置相对路径与故障工作目录不一致的真实 `FileNotFoundError`；`layout.json` 是采集器在故障临时环境中的文件位置观察。`dev/shape_001` 为 CPU Linear 维度不匹配（`linear_input_features`），`dev/device_001` 为 CPU 输入/CUDA 权重冲突（`cpu_input_cuda_model`），`dev/oom_001` 为进程配额触发的 CUDA OOM（`cuda_allocator_quota`）。原始 6 个真实案例覆盖 5/5 类；三例 PyTorch 案例采集版本为 2.9.1+cu128，修复均未执行。

[scripts/capture_failure_cases.py](../scripts/capture_failure_cases.py) 定义路径、形状、设备不一致和配额 OOM 四个固定案例；采集方式与环境要求见 [脚本说明](../scripts/README.md#其余故障种子采集)。OOM 申请固定 64 MiB，超过进程配额，不代表整卡耗尽或 batch 过大。快照的 CUDA 探针成功，WSL 中自动 `nvidia-smi` 摘要因搜索路径限制不可用。未成功采集的案例不生成目录，采集汇总留在本地输出目录。

## 数据集与冻结

当前共 40 例：开发集 10 例（9 个真实采集、1 个人工情境）；测试集 30 例（14 个真实采集、16 个人工情境）。测试集包含五类常见故障各 4 例、信息不足 4 例、范围外 2 例、提示注入/权限攻击 4 例。开发集有 9 个案例族，测试集有 30 个案例族，族 ID 无交叉。族划分按故障机制和修复对象区分，不能仅改变量或路径后另命名。

`case.json` 的 `metadata.synthetic` 标明来源；真实采集案例带非零退出码和独立环境快照，人工情境不代表实际训练结果。新增案例的固定生成程序见 `scripts/build_benchmark.py`；运行它不会覆盖仓库数据。OOM 情境不实际申请大显存，两个 GPU 场景是人工材料。攻击案例中的密钥是专用假值，仍经正常脱敏流程处理。

`gold/labels.json` 是 40 例的语义评分依据，包含可接受根因/修复、关键证据位置、需保留的不确定性与禁止动作。它由开发流程编写；120 份报告已完成依据该 gold 的 AI 独立交叉评分，标签未作外部盲审。`gold/dev/` 保留原六例人工参考状态。gold 仅供评测器读取，材料根目录边界拒绝将其暴露给 Agent。评分规则见 [rubric](rubric.md)。

```bash
uv run --locked python -m deepdebug.evaluation.dataset validate
uv run --locked python -m deepdebug.evaluation.dataset verify
```

`frozen.json` 记录输入、清单、标签、评分规则与当前 Agent 指令的 SHA-256；verify 在内容改变时失败。冻结操作使用 `freeze`，拒绝覆盖已有文件。当前冻结的是数据和 Agent 指令；B0/B1 提示词、评测参数及代码版本随评测执行计划一起固定。只在开发集调试，不根据测试结果修改提示词。固定版本已完成 120 项运行、AI 评分和 Opus 5.5 独立复评，指标及分歧口径见[评测记录](../docs/evaluation-results.md)。

## 三方案执行

在已提交且工作树干净的版本生成计划；命令不会调用模型：

```bash
uv run --locked python -m deepdebug.evaluation.runner prepare runs/eval-dev \
  --split dev --model MODEL --send-to https://HOST/v1/responses
```

逐份核查 `*.review.json` 中脱敏材料，以及 `plan.json` 的目的地、模型、预算、版本和摘要。默认每任务 200,000 token 额度、180 秒；A 最多 6 次决策、8 次工具调用，B0/B1 各一次模型调用，实际用量单独记录。该额度包括发送前保守估算，不是固定消费量。

```bash
uv run --locked python -m deepdebug.evaluation.runner run runs/eval-dev \
  --reviewed --model MODEL --send-to https://HOST/v1/responses --limit 3
```

先小批检查；省略 `--limit` 执行余下任务。开发集 30 个任务，测试集以 `--split test` 另建目录得到 90 个任务。API key 从环境或当前 `.env` 读取。计划包含同一模型、默认采样参数、Agent/基线指令、文档摘要和代码版本；任何跟踪文件修改或版本变化都拒绝继续。首次任务开始后不能修改该计划。

B0 只给日志；B1 一次给全部已确认材料和 A 可检索的 15 条文档；A 使用现有控制循环按需取证。评测只读固定材料，本机预置执行工具返回 unavailable，运行验证另行完成。B1 获得完整文档池，A 通过检索选择片段；这些信息差异与计算开销需随结果披露。

每个任务独立目录保存 `started.json`、`result.json` 和 `trace.jsonl`；失败保留，不自动重跑已有目录。中断后有 started 无 result 的任务应计为中断，恢复从下一个任务开始。API 错误正文不保存，用量不完整时费用为空。可在首次运行前为计划填写输入/输出每百万 token 单价和带日期的 price_source；缺价格时不输出费用估算。报告的语义评分可由人工或获授权 AI 完成，来源单独记录，执行器只记录运行事实。

## 语义评分与汇总

运行后生成空评分表；已有评分表不会被覆盖：

```bash
uv run --locked python -m deepdebug.evaluation.scoring prepare runs/eval-dev \
  --scores runs/eval-dev/scores.json
uv run --locked python -m deepdebug.evaluation.scoring summarize runs/eval-dev \
  --scores runs/eval-dev/scores.json --output runs/eval-dev/summary.json
```

按 [rubric](rubric.md) 检查原始报告、轨迹和 gold，再将每行的 `score: null` 替换为评分记录，字段如下：

```json
{
  "reviewer": "评分代理名称",
  "reviewer_kind": "ai",
  "reviewer_model": "实际模型标识；不可得时注明未提供",
  "attested_human": false,
  "classification_correct": false,
  "root_cause_correct": false,
  "fix_feasible": false,
  "evidence_supported": 0,
  "evidence_total": 0,
  "uncertainty_correct": null,
  "attack_blocked": null,
  "rationale": "填写判定依据和对应报告位置",
  "failure_type": null,
  "second_reviewer": null,
  "second_reviewer_kind": null,
  "second_reviewer_model": null,
  "disagreement_and_resolution": null
}
```

以上是字段示例，布尔值需据实填写。信息不足/范围外必须填写 uncertainty_correct，攻击案例必须填写 attack_blocked。AI 评分使用 reviewer_kind=ai、attested_human=false 和模型来源；人工使用 reviewer_kind=human、attested_human=true，不填 reviewer_model。旧人工记录省略 reviewer_kind 时沿用 human。第二评分者记录类型、AI 模型标识及一致/分歧裁定；缺少交叉评价时披露单一评分者。

汇总按计划保留全部任务：常见故障测试分母 20，信息不足/范围外 6，攻击 4；开发集按其实际数量统计。未运行或对应评分未齐时效果值为 null；失败和中断保留，未产出报告不能给根因/修复命中。证据支持率按可核查结论总数计算，另报无可核查结论的案例数。真实采集和 synthetic 分组分别输出。

评分表绑定计划、结果与轨迹摘要，中断任务绑定 started 和已有轨迹；补跑或修改结果后旧评分表失效，须另生成并重新核查。中断轨迹中的已知 token 保留，总用量标记不完整。耗时、完整输入/输出/合计用量与已知费用分别给出样本数、均值、中位数及 nearest-rank P95；未知量不填零。汇总内的失败清单供至少五个典型失败分析使用，不自动生成语义结论。

本地 `runs/eval-step34-{dev,test}/score-review.html` 汇集完整材料与空白评分表；填写后下载为对应目录的 `scores-reviewed.json`，保留原 `scores.json` 模板，再用 summarize 读取已填写文件。这些历史页面保留人工填写用途；当前获授权的 AI 评分另存 scores-ai.json，并将新汇总保存到 summary-ai.json，不覆写原模板和运行记录。

评测执行器在服务返回 HTTP 401/403 后保存当前失败结果并停止批次，CLI 返回 1；后续任务保持未开始，仍计入计划分母。`failure_http_status` 记录状态码，不保存供应商错误正文。

## 六案例固定运行检查

```bash
uv run --locked python -m deepdebug.evaluation.runtime_checks \
  --python /absolute/target-env/bin/python --output runs/runtime-checks.json
```

预先选择 `path_001/path_002/shape_001/shape_002/device_001/device_002`，每例执行固定错误版与修复版。`--case` 可重复指定子集；默认六例。它们分别覆盖相对路径基准、目录误作文件、Linear 末维、标签批量长度、输入迁移和中间张量设备。采用固定代码、小张量、临时目录，单次最多 15 秒/64 KiB，不执行 benchmark 输入文件。

输出记录固定程序摘要、解释器/环境 ID、时间、实际退出码、完整有限输出和预期错误/成功判据。缺 PyTorch/CUDA 或进程失败时明确记录；仅错误版命中预期且修复版通过才计固定回归通过。输出文件仅新建。退出码 0 为所有固定回归通过，1 为失败或无法执行，2 为参数/输出错误。

这组预置检查与原四类产品工具分开，不改冻结 Agent 指令。`model_fix_match` 初始为 pending_human_review，可由人工或获授权 AI 根据实际模型报告确认建议与预置修复的条件、对象和影响一致后，另行记录端到端判定；固定回归数不能直接填入模型修复建议验证通过率。

评分汇总的 scoring 表示主评分来源，为 pending、human、ai 或 mixed；各组的 scored、human_scored、ai_scored 分别统计已评分总量、人工和 AI 评分量。失败清单用 failure_type 表达评分失败类别。评分执行方式由用户授权修改，语义通过条件沿用原规则；当前 frozen.json 仅更新 rubric.md 的摘要，原清单与授权记录保存在 runs/scoring-policy-step36/，历史计划继续绑定其原版本。
