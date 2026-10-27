# benchmark

`dev/dep_001`、`dev/dep_002` 是真实采集的 Python 依赖导入失败案例，同属 `dependency_interpreter` 案例族；实际日志相同，环境和预期解释器证据不同。`case.json` 描述采集来源，`materials/` 只包含诊断输入。

`gold/dev/` 保存人工参考状态（内含报告），仅开发检查和后续评测器可读；不能传给模型或作为工具读取根目录。`test_inputs/` 和 `checks/` 仍为空，尚无冻结测试集、运行验证或效果评测结果。目录分离不等同于已实现权限校验。
