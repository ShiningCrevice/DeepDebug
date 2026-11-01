# scripts

`capture_dependency_cases.py` 使用固定代码采集两个开发案例：临时空虚拟环境导入 pydantic 失败，以及当前项目环境存在该包的元数据证据。运行方式：`uv run --locked python scripts/capture_dependency_cases.py runs/dependency-capture`，输出目录必须不存在。

脚本不安装依赖、不执行上传文件、不采集任意环境变量。启动配置的预期解释器是开发者设定，报错和包元数据来自真实进程；路径替换为 `/demo/` 别名，时间保留实际带时区时间。原始材料不是修复验证结果。

此脚本仅供开发准备案例。

`collect_environment.py` 是用户环境快照入口，与 `deepdebug snapshot` 共用实现：

```bash
uv run --locked python scripts/collect_environment.py \
  --python /absolute/target-env/bin/python --environment-id TRAIN_ENV \
  --package torch --package numpy --torch-cuda --gpu
```

输出 JSON 到标准输出，可重定向后由 `collect --snapshot` 导入。解释器必须使用绝对路径；包元数据最多查询 10 项，PyTorch/CUDA 和 GPU 探针由对应选项启用。固定探针的时限、输出限制、状态及退出码见 [README](../README.md#采集用户环境快照)。输出尚未经脱敏。
