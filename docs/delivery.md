# 交付索引

工程功能、数据集、评测工具、六案例固定运行检查与干净环境复现已完成。正式评测、人工评分、六案例模型建议匹配验证和最终视频仍待完成，当前不能标为完整课程交付。

| 材料 | 位置 | 当前状态 |
|---|---|---|
| 源码与依赖锁 | src/、app.py、pyproject.toml、uv.lock | 已实现并验证 |
| 使用入口 | [README](../README.md) | 已提供 |
| 架构与工具协议 | [design](design.md)、[tool-api](tool-api.md) | 与当前实现同步 |
| 技术报告 | [technical-report](technical-report.md) | 实现章节完成；实测结果待补；Markdown 约 6,900 字符，排版页数未验证 |
| 数据集与 rubric | [benchmark](../benchmark/README.md) | 10 开发、30 测试，已冻结；标签待人工评分复核 |
| 检索语料来源 | [knowledge](../knowledge/README.md) | 15 条摘要，来源与版本完整 |
| 对照评测结果 | 运行目录中的 plan/result/trace/summary | 首次三项通过；纯文本接口缺陷已修复，保留原批次并准备同版重跑 120 项 |
| 代表性报告 | 本地 runs/clean-smoke/report.md 与 report.json | 独立克隆已导出 synthetic 演示，双格式一致 |
| 运行验证 | builtin-check 与 verify-report | 六个选定案例固定回归 6/6；与实际模型建议的端到端匹配待补 |
| 复现记录 | [reproduction](reproduction.md) | 独立环境 495 项测试、构建、报告和 UI 启动通过 |
| 第三方说明 | [third-party](third-party.md) | 语料来源和安装依赖元数据已列出 |
| 项目许可证 | [LICENSE](../LICENSE) | MIT，2026 ShiningCrevice |
| 视频脚本 | [demo-script](demo-script.md) | 六分钟分镜已提供，结果段待实测 |
| 演示视频 | 本地交付目录 | 尚未录制 |

运行产物、私有材料和密钥不提交 Git。最终交付包另存本地目录，选入可公开报告与轨迹时逐项核查，并保持 synthetic、真实运行、人工评分和修复执行状态的原有标记。

正式评测完成后，更新技术报告的结果与失败分析，至少说明五个典型失败、各指标分母、真实/synthetic 分组、模型与代码版本及费用来源。保留不达标项，不修改冻结标签来提高分数。课程模板、署名和视频格式未提供，应在最终打包前据实际要求调整。

## 本地交付预览包

`runs/delivery-step29/DeepDebug-preview.zip` 基于源码提交 `c9fe536`，含该版已跟踪源码、锁文件、文档和案例，以及 sample/ 中的公开演示资料。ZIP 为 626,163 字节、379 个条目；未包含 .env、runs、sessions 或 .venv 目录。

sample/ 提供 Markdown/JSON 报告、完整状态和 JSONL 轨迹，以及六案例固定检查和无 PyTorch 对照的脱敏副本。诊断来自 synthetic 固定响应，修复未执行；运行检查的模型建议匹配仍待人工核查。DELIVERY.json 记录源码版本、各示例文件摘要和剩余项。

已验证 ZIP CRC、报告双格式一致性、会话与轨迹一致性以及示例脱敏。该包是本地预览，正式评测、人工评分、建议匹配、许可证、最终报告和视频补齐后需重新打包。
