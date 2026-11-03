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

## 其余故障种子采集

`capture_failure_cases.py` 使用显式指定的解释器运行四个固定开发案例：

```bash
uv run --locked --group capture python scripts/capture_failure_cases.py runs/failure-capture \
  --python /absolute/target-env/bin/python \
  --case path_001 --case shape_001 --case device_001 --case oom_001
```

若使用项目环境采集，先运行 `uv sync --locked --group capture`，再将 `--python` 指向本项目 `.venv/bin/python` 的绝对路径。`capture` 组包含 PyTorch 2.9.1 与 NumPy（用于完整初始化 PyTorch），Linux/Windows 使用官方 CUDA 12.8 wheel 源；版本与安装源见 [PyTorch 官方说明](https://pytorch.org/get-started/previous-versions/#v291)。此依赖组不参与默认安装。使用已有外部解释器时可以省略 `--group capture`。

输出目录必须不存在，`--case` 可多次指定且不能重复。脚本在临时目录中写入并运行内置程序，不读取 `benchmark` 中的 Python 输入。目标环境需要预先准备依赖；脚本不安装包。

| 案例 | 运行条件与实际故障 |
|---|---|
| `path_001` | Python 标准库；从 `project/jobs` 打开相对路径，文件实际在 `project/checkpoints`，触发 `FileNotFoundError` |
| `shape_001` | PyTorch，CPU 即可；输入末维 5 与 Linear 的 `in_features=4` 不匹配 |
| `device_001` | PyTorch 与可用 CUDA；小型 CUDA Linear 接收 CPU 输入 |
| `oom_001` | PyTorch 与可用 CUDA；将进程分配器配额设为总显存的 0.1%（最多 32 MiB），申请固定 64 MiB |

OOM 使用 [PyTorch 进程显存配额 API](https://docs.pytorch.org/docs/2.9/generated/torch.cuda.memory.set_per_process_memory_fraction.html) 触发真实分配失败。它反映进程配额限制，不能作为整卡耗尽、batch 过大、泄漏或碎片化的案例。CUDA 初始化本身会占用设备资源。

每个成功采集的案例包含失败日志、固定源码、实际使用的配置、独立进程环境快照及采集清单。路径案例额外记录故障工作目录和两种路径基准下的文件存在性；该布局在故障临时环境中采集，与后续 `collect --path` 的本机观察分开。路径及解释器前缀替换为 `/demo/` 别名，保留行号、真实时间和版本。

每个故障子进程限时 15 秒，合并输出上限 64 KiB；超时或超限后回收该子进程。只有实际非零退出并匹配预期错误的结果才生成案例。缺少环境、超时及其他失败写入 `capture_summary.json`，不会生成占位日志或标成已采集。退出码 `0` 表示所选案例均已采集，`1` 表示有案例未取得预期失败，`2` 表示参数或输出路径错误。汇总仅供本地查看。

新采集结果不会自动覆盖仓库案例或生成人工参考答案；失败采集也不代表修复验证。该脚本仅供开发准备案例，不是 Agent 工具。
