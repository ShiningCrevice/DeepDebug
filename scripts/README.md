# scripts

`capture_dependency_cases.py` 使用固定代码采集两个开发案例：临时空虚拟环境导入 pydantic 失败，以及当前项目环境存在该包的元数据证据。运行方式：`uv run --locked python scripts/capture_dependency_cases.py runs/dependency-capture`，输出目录必须不存在。

脚本不安装依赖、不执行上传文件、不采集任意环境变量。启动配置的预期解释器是开发者设定，报错和包元数据来自真实进程；路径替换为 `/demo/` 别名，时间保留实际带时区时间。原始材料不是修复验证结果。

此脚本仅供开发准备案例。面向用户的通用快照采集入口与 Agent 环境工具将在后续步骤实现。
