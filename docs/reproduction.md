# 干净环境复现

已从提交 `0de383e` 创建独立克隆和全新虚拟环境，按锁文件安装基础与 UI 依赖。Linux / Python 3.12.3 下，495 项测试、Ruff 检查和构建通过；未安装 PyTorch。其他操作系统和 Python 版本未验证。

## 安装与检查

```bash
git clone https://github.com/ShiningCrevice/DeepDebug.git
cd DeepDebug
git checkout 0de383e
uv sync --locked --extra ui
uv run --locked --extra ui ruff check .
uv run --locked --extra ui ruff format --check .
uv run --locked --extra ui pytest -q
uv build
```

实际复现使用本机仓库的独立克隆 `/tmp/deepdebug-clean-step26`，使用系统 Python 和新建 `.venv`，没有复制原开发环境。安装了 47 个包；构建生成 sdist 和 wheel。首次依赖下载被网络沙箱阻止，允许锁定包下载后安装通过。离线复现需预先准备相同依赖缓存。

## 无模型服务的完整报告流程

```bash
set -o noclobber
mkdir -p runs/clean-smoke
uv run --locked deepdebug preview \
  --root benchmark/dev/dep_002/materials --log log.txt --config launch.json \
  --snapshot target_snapshot.json --snapshot project_snapshot.json \
  --output runs/clean-smoke/preview.json
# 核查 preview.json 的全部材料后执行：
uv run --locked deepdebug confirm \
  --preview runs/clean-smoke/preview.json --output runs/clean-smoke/reviewed.json
uv run --locked deepdebug replay \
  --reviewed runs/clean-smoke/reviewed.json --responses examples/dep_002_replay.json \
  --trace runs/clean-smoke/trace.jsonl > runs/clean-smoke/state.json
uv run --locked deepdebug report --state runs/clean-smoke/state.json \
  --output runs/clean-smoke/report.md
uv run --locked deepdebug report --state runs/clean-smoke/state.json \
  --format json --output runs/clean-smoke/report.json
uv run --locked deepdebug check-report \
  --json runs/clean-smoke/report.json --markdown runs/clean-smoke/report.md
```

实跑结论为 completed，产生 9 条证据和 4 次真实只读工具调用；JSON 与 Markdown 检查返回“报告内容一致”。所有材料标为 reviewed，修复验证为“未执行”。模型响应来自明确标注的 synthetic 示例，仅验证控制流程和导出，不代表模型诊断效果。

CLI 输出仅新建文件，示例用 noclobber 阻止 shell 重定向覆盖已有 state.json；重复复现需另选空输出目录。原始运行产物保留在本地 runs，不纳入 Git。

## 页面启动

```bash
uv run --locked --extra ui streamlit run app.py
```

默认打开 `http://127.0.0.1:8501`。实际检查使用临时端口 8526，健康接口返回 `ok`，主页 HTTP 200；检查后服务已停止。页面交互由同次 AppTest 测试覆盖，包括上传确认、离线演示、报告下载、会话恢复和继续诊断。HTTP 主页检查本身不等于完成了浏览器人工操作。

## 无 PyTorch / GPU 的行为

```bash
uv run --locked deepdebug builtin-check --case shape --check after_fix
```

干净环境实跑返回退出码 1、状态“无法执行”、原因 `PyTorch unavailable`，execution 为 null；没有把缺依赖标成验证通过。快照读取、日志分析、检索、离线回放、报告导出和 UI 不依赖本机 PyTorch。现场形状/设备修复检查需显式选择准备好依赖的解释器，详见 README 的预置检查入口。
