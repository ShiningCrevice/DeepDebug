# 交付索引

工程功能、数据集、评测工具、六案例固定运行检查与干净环境复现已完成。六案例模型建议已由 Shivice 确认匹配。120 项真实运行、AI 评分及 Opus 5.5 独立复评已完成，完整里程碑 5/6；最终 PDF、视频和交付包待同步评分结果。

| 材料 | 位置 | 当前状态 |
|---|---|---|
| 源码与依赖锁 | src/、app.py、pyproject.toml、uv.lock | 已实现并验证 |
| 使用入口 | [README](../README.md) | 已提供 |
| 架构与工具协议 | [design](design.md)、[tool-api](tool-api.md) | 与当前实现同步 |
| 技术报告 | [technical-report](technical-report.md) | Markdown 已含语义结果和失败分析；历史 9 页 PDF 待重新导出 |
| 数据集与 rubric | [benchmark](../benchmark/README.md) | 10 开发、30 测试，已冻结；报告 AI 交叉评分完成，标签未作外部盲审 |
| 检索语料来源 | [knowledge](../knowledge/README.md) | 15 条摘要，来源与版本完整 |
| 对照评测结果 | 运行目录中的 plan/result/trace/summary | [评测记录](evaluation-results.md)：119 正常结束、1 项决策预算停止；120 项评分、用量和裁定完整 |
| 代表性报告 | 本地 runs/clean-smoke/report.md 与 report.json | 独立克隆已导出 synthetic 演示，双格式一致 |
| 运行验证 | builtin-check 与 verify-report | 六个选定案例匹配且固定回归通过 6/6，人工署名 Shivice；对应 f767edd 报告 |
| 复现记录 | [reproduction](reproduction.md) | 独立环境 495 项测试、构建、报告和 UI 启动通过 |
| 第三方说明 | [third-party](third-party.md) | 语料来源和安装依赖元数据已列出 |
| 项目许可证 | [LICENSE](../LICENSE) | MIT，2026 ShiningCrevice |
| 视频脚本 | [demo-script](demo-script.md) | 六分钟分镜已同步语义结果、评分来源和失败案例 |
| 演示视频 | 本地交付目录 | 六分钟、1920×1080、25 fps 历史核查版已生成；最终版待同步语义结果 |

运行产物、私有材料和密钥不提交 Git。最终交付包另存本地目录，选入可公开报告与轨迹时逐项核查，并保持 synthetic、真实运行、人工评分和修复执行状态的原有标记。

技术报告已含语义结果、评分来源、十类失败分析、各指标分母、真实/synthetic 分组、模型与版本及费用来源。下一步生成最终 PDF、视频与离线包；采用规划规定的 8～12 页、5～7 分钟格式，保留实际结果及原冻结标签。

## 历史交付预览包

`runs/delivery-step29/DeepDebug-preview.zip` 基于源码提交 `c9fe536`，含该版已跟踪源码、锁文件、文档和案例，以及 sample/ 中的公开演示资料。ZIP 为 626,163 字节、379 个条目；未包含 .env、runs、sessions 或 .venv 目录。

sample/ 提供 Markdown/JSON 报告、完整状态和 JSONL 轨迹，以及六案例固定检查和无 PyTorch 对照的脱敏副本。诊断来自 synthetic 固定响应，修复未执行；运行检查的模型建议匹配仍待人工核查。DELIVERY.json 记录源码版本、各示例文件摘要和剩余项。

已验证 ZIP CRC、报告双格式一致性、会话与轨迹一致性以及示例脱敏。该包是本地预览，正式评测、人工评分、建议匹配、许可证、最终报告和视频补齐后需重新打包。

## 历史完整运行核查材料

- `runs/eval-step34-dev/`、`runs/eval-step34-test/`：固定版本 184c5d1 的 120 项结果与轨迹、完整运行汇总、空白评分表，以及人工核查/填写页面。
- `runs/delivery-step34/DeepDebug-technical-report.pdf`：含本轮用量、耗时与失败说明的技术报告核查版。
- `runs/delivery-step34/DeepDebug-demo-review.mp4` 与同名 `.srt`：360 秒、1080p 核查视频及字幕。主界面回放使用标明 f767edd 的既有 dep_002 会话；信息不足、范围外、攻击与运行统计使用 184c5d1 本轮记录。

两份 score-review.html 的判定初始为空，人工填表并下载后保存为对应目录的 scores-reviewed.json。六案例匹配记录仍绑定原 f767edd 报告。这些历史核查材料保留当时“语义评分待完成”标记，当前结果以 scores-ai.json/summary-ai.json 为准。

## 历史离线交付核查包

`runs/delivery-step35/DeepDebug-review.zip` 为 9,854,020 字节、1,415 个条目。解压后打开根目录 START_HERE.html，可进入开发/测试评分页、查看 9 页 PDF 和六分钟视频，或阅读代表性 Markdown/JSON 报告。

包内源码固定于提交 `3483ebd`，本轮评测为 `184c5d1`，六案例匹配和视频主界面回放为 `f767edd`。源码快照保留 Step 34 状态；包版本、剩余项及逐文件 SHA-256 见 DELIVERY.json。评测计划、结果、轨迹、预算历史和原匹配核查提案均保留原字节，提案的旧“待确认”状态由 runtime-step33-matched.json 中的 Shivice 确认记录补充。

本轮及历史数据保留在包内 runs/ 的原相对位置。runs/clean-smoke/ 提供独立环境的 synthetic 演示报告、状态和轨迹，修复未执行。媒体目录包含字体声明与工具版本。包内不含 .env、.git、.venv；包含用于配置说明的 .env.example。若要重新执行模型评测，按 benchmark/README.md 使用 Git 克隆；离线查看与填表无需安装产品依赖。

已验证 ZIP CRC、逐文件摘要、120 项汇总/轨迹绑定、六案例匹配来源摘要、示例报告双格式与终态一致性，以及解压后的入口链接和人工评分下载流程。评分下载验证使用临时 UI 测试值，正式评分保持空白。当前 AI 评分已完成，下一步更新媒体并重新生成最终包。

## 当前评分交付材料

两个 runs/eval-step34-{dev,test}/ 目录新增 scores-ai.json 和 summary-ai.json，覆盖全部 120 份报告。runs/ai-scoring-step37/ 保存固定材料包、Codex 主评、claude-opus-5-5 独立复评、最终裁定和分歧统计；原报告、轨迹、空白表单及历史包保持原状态。完整指标与解释见[评测记录](evaluation-results.md)。后续验收由获授权 AI 执行并记录实际执行者，无需等待人工填表。
