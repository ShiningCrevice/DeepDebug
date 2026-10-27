# 开发进度

## Step 01 — 项目初始化（2026-10-27）

完成范围：

- 建立 `src/` Python 包与 CLI，支持帮助、版本和模块启动。
- 配置 uv、Pydantic v2、pytest、Ruff 与构建后端，锁定依赖。
- 预留 Agent、工具、权限、模型接口、报告、案例与评测目录。
- 添加 README、AGENTS.md、架构决策、环境配置说明与敏感数据忽略规则。

验证结果（Linux / Python 3.12.3）：

- `uv sync` 成功，生成 `uv.lock`；受限网络首次安装失败后，获准联网安装完成。
- `ruff check .` 与 `ruff format --check .` 通过。
- `pytest`：3 项通过，覆盖安装入口、模块入口和未知命令拒绝。
- `uv build --offline` 成功生成 sdist，并从 sdist 构建 wheel。
- `deepdebug --help` 正确显示初始化阶段说明。

本环境检查通过 `--cache-dir /tmp/deepdebug-uv-cache` 使用可写缓存目录；普通开发环境可直接使用 README 命令。其他 Python 版本和操作系统尚未实际验证。

边界：本次仅初始化，不代表第一周里程碑整体完成；尚无诊断、环境采集、模型调用、Web 页面或评测结果。无需 GPU 与 API key。

下一步：准备缺少依赖与错误解释器两个开发案例；定义材料、证据、工具返回、动作、状态、报告的 Pydantic 结构，建立协议验证。
