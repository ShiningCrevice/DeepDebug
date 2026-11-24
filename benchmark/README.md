# benchmark

`dev/dep_001`、`dev/dep_002` 是真实采集的 Python 依赖导入失败案例，同属 `dependency_interpreter` 案例族；实际日志相同，环境和预期解释器证据不同。`case.json` 描述采集来源，`materials/` 只包含诊断输入。

新增 `dev/path_001` 属于 `relative_working_directory` 案例族，记录配置相对路径与故障工作目录不一致的真实 `FileNotFoundError`；`layout.json` 是采集器在故障临时环境中的文件位置观察。`dev/shape_001` 为 CPU Linear 维度不匹配（`linear_input_features`），`dev/device_001` 为 CPU 输入/CUDA 权重冲突（`cpu_input_cuda_model`），`dev/oom_001` 为进程配额触发的 CUDA OOM（`cuda_allocator_quota`）。原始 6 个真实案例覆盖 5/5 类；三例 PyTorch 案例采集版本为 2.9.1+cu128，修复均未执行。

[scripts/capture_failure_cases.py](../scripts/capture_failure_cases.py) 定义路径、形状、设备不一致和配额 OOM 四个固定案例；采集方式与环境要求见 [脚本说明](../scripts/README.md#其余故障种子采集)。OOM 申请固定 64 MiB，超过进程配额，不代表整卡耗尽或 batch 过大。快照的 CUDA 探针成功，WSL 中自动 `nvidia-smi` 摘要因搜索路径限制不可用。未成功采集的案例不生成目录，采集汇总留在本地输出目录。

## 数据集与冻结

当前共 40 例：开发集 10 例（9 个真实采集、1 个人工情境）；测试集 30 例（14 个真实采集、16 个人工情境）。测试集包含五类常见故障各 4 例、信息不足 4 例、范围外 2 例、提示注入/权限攻击 4 例。开发集有 9 个案例族，测试集有 30 个案例族，族 ID 无交叉。族划分按故障机制和修复对象区分，不能仅改变量或路径后另命名。

`case.json` 的 `metadata.synthetic` 标明来源；真实采集案例带非零退出码和独立环境快照，人工情境不代表实际训练结果。新增案例的固定生成程序见 `scripts/build_benchmark.py`；运行它不会覆盖仓库数据。OOM 情境不实际申请大显存，两个 GPU 场景是人工材料。攻击案例中的密钥是专用假值，仍经正常脱敏流程处理。

`gold/labels.json` 是 40 例的语义评分依据，包含可接受根因/修复、关键证据位置、需保留的不确定性与禁止动作。它由开发流程编写，尚未经过人工评分复核。`gold/dev/` 保留原六例人工参考状态。gold 仅供评测器读取，材料根目录边界拒绝将其暴露给 Agent。评分规则见 [rubric](rubric.md)。

```bash
uv run --locked python -m deepdebug.evaluation.dataset validate
uv run --locked python -m deepdebug.evaluation.dataset verify
```

`frozen.json` 记录输入、清单、标签、评分规则与当前 Agent 指令的 SHA-256；verify 在内容改变时失败。冻结操作使用 `freeze`，拒绝覆盖已有文件。当前冻结的是数据和 Agent 指令；B0/B1 提示词、评测参数及代码版本随评测执行计划一起固定。只在开发集调试，不根据测试结果修改提示词。效果评测尚未执行。
