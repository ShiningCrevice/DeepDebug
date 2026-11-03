# benchmark

`dev/dep_001`、`dev/dep_002` 是真实采集的 Python 依赖导入失败案例，同属 `dependency_interpreter` 案例族；实际日志相同，环境和预期解释器证据不同。`case.json` 描述采集来源，`materials/` 只包含诊断输入。

新增 `dev/path_001` 属于 `relative_working_directory` 案例族，记录配置相对路径与故障工作目录不一致的真实 `FileNotFoundError`；`layout.json` 是采集器在故障临时环境中的文件位置观察。`dev/shape_001` 为 CPU Linear 维度不匹配（`linear_input_features`），`dev/device_001` 为 CPU 输入/CUDA 权重冲突（`cpu_input_cuda_model`），`dev/oom_001` 为进程配额触发的 CUDA OOM（`cuda_allocator_quota`）。当前 6 个真实案例覆盖 5/5 类；三例 PyTorch 案例采集版本为 2.9.1+cu128，修复均未执行。

[scripts/capture_failure_cases.py](../scripts/capture_failure_cases.py) 定义路径、形状、设备不一致和配额 OOM 四个固定案例；采集方式与环境要求见 [脚本说明](../scripts/README.md#其余故障种子采集)。OOM 申请固定 64 MiB，超过进程配额，不代表整卡耗尽或 batch 过大。快照的 CUDA 探针成功，WSL 中自动 `nvidia-smi` 摘要因搜索路径限制不可用。未成功采集的案例不生成目录，采集汇总留在本地输出目录。

`gold/dev/` 保存人工参考状态（内含报告），仅开发检查和后续评测器可读；不能传给模型或作为工具读取根目录。`test_inputs/` 和 `checks/` 仍为空，尚无冻结测试集、运行验证或效果评测结果。目录分离不等同于已实现权限校验。
