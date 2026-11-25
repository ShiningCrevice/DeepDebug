# 交付验收对应表

依据 [项目规划](../DeepDebug_planning.md) 的必做范围、六个里程碑、评测及提交清单核查。当前产品代码与独立复现提交 `7aa498a` 相同，诊断评测为 `184c5d1`、评分器为 `389a02f`；六案例匹配仍关联 `f767edd`。核查执行者为获授权的 Codex，AI 评分及历史人工匹配分别保留来源。

## 功能与工程约束

| 规划要求 | 当前实现与直接证据 | 结论及适用范围 |
|---|---|---|
| §2.1 输入：粘贴/上传、可选代码/配置/快照、2 MiB 与 10 文件、预览 | `ui/workflow.py`、`tools/artifacts.py`、`security/review.py`；test_upload_review_limits_and_origin、test_invalid_uploads_are_rejected、test_material_size_limit_counts_utf8_bytes、test_count_limit_and_duplicate_registration | 通过；UTF-8 文本输入，YAML 作为文本读取，不执行或反序列化 |
| §2.1 日志：异常、堆栈、原行号、上下文截断 | `tools/log_parser.py`；test_real_case_collects_traceable_evidence_without_diagnosis、test_path_log_can_be_completed_without_changing_evidence_times | 通过；补读沿用登记时正文及时间 |
| §2.1/§3.2 环境：默认快照，显式解释器采集，来源/时间/目标标识 | `tools/capture.py`、`tools/environment.py`；环境/路径/GPU 测试及 benchmark 原快照 | 通过；本机 collector 不冒充目标环境。当前 WSL 默认系统搜索路径缺 nvidia-smi，GPU 摘要降级；已有真实 PyTorch/CUDA 固定实验 |
| §2.1/§5 单 Agent 循环、最多三候选、反馈改变假设 | `agent/controller.py`、`agent/actions.py`；test_tool_observation_reaches_next_request_and_trace、test_real_dependency_example_changes_hypothesis；真实 dep_002 报告与轨迹 | 通过；固定响应流程与真实模型效果分开标记 |
| §5 动作枚举、一次纠错、缓存、连续两轮无进展停止、预算/超时/一次重试 | controller 测试的 invalid_decision、cache_and_two_round_no_progress_stop、call_budgets、token_reserve、time_limit、retry；真实 path_001/A 预算停止记录 | 通过；默认 6 决策、8 工具、120 秒、50K token，报告预留 5K；可选独立格式修正未启用 |
| §2.1/§6 文档检索：15～25 条、ID/URL/版本/时间、最多三条 | 随包 documents.json 有 15 条；test_corpus_covers_five_categories_with_official_versioned_sources、检索相关性及 gold 隔离测试；knowledge/README.md | 通过；PyTorch 2.9 / Python 3.12 官方摘要，BM25；未运行可选 A-no-docs 消融 |
| §2.1/§5.5 报告字段与双格式导出 | `reporting/render.py`、schemas/state；test_export_preserves_complete_report 逐标量验证 Markdown，非法引用/状态校验测试；本次 clean-smoke 报告对 | 通过；JSON/Markdown 内容一致，未执行修复保持“未执行” |
| §2.1/§3.1/§7.3 UI、目标环境、进度/时间线、下载、保存/删除/续跑 | `ui/app.py`、sessions、continuation；AppTest 覆盖上传、确认、演示、四下载、保存/恢复/删除/追加；本次健康接口 ok、主页 HTTP 200 | 通过；127.0.0.1 单用户。七天过期在后续访问时清理，程序关闭期间无清理进程 |
| §2.1/§6 内置验证与状态区分 | dependency/path/shape/device 四类固定程序，枚举参数；builtin/runtime_checks 测试；六例实际前后对照与匹配；本次 no-torch.json | 通过；6/6 历史匹配回归，缺 PyTorch 返回“无法执行”及 exit 1，不计通过 |
| §6.1/§6.2 全部七种工具及统一结果 | parse_log、read_artifact、check_paths、inspect_environment、query_gpu、search_docs、run_builtin_check；`docs/tool-api.md`、dispatcher/session 及协议测试 | 通过；状态、来源、证据、时间、截断和错误保留；工具不可用不改写成模型猜测 |
| §6.3/§7.1 固定探针、隔离、超时/输出限额 | capture 使用 Python -I、临时目录、importlib.metadata；process 使用固定 argv、shell=False、超时回收及 64 KiB 限额；环境采集和运行检查测试 | 通过；只执行开发者固定程序，未开放 shell 或上传代码执行 |
| §7/§13 路径穿越、链接、未经登记材料、仓库/gold 拒绝 | `security/paths.py` 的 dir_fd/O_NOFOLLOW；collection 中真实文件、嵌套链接、gold/仓库根、特殊文件测试；dispatcher 越界拒绝 | 通过；当前安全读取依赖 POSIX，其他平台未实跑 |
| §7/§13 脱敏、确认副本、目的地绑定、密钥与响应保护 | review/redaction、Responses 适配器；请求边界、确认摘要、重定向拒绝、错误正文不落盘、响应再脱敏测试；12 个攻击任务实际轨迹核查 | 通过；4/4 小型攻击回归。假密钥预先脱敏，不外推任意明文秘密场景 |
| §7.3 本地会话七天保留、权限和删除 | sessions 测试核对 0700/0600、七天边界、损坏文件不误删、原子替换失败保留旧数据；UI 删除与 CLI 删除测试 | 通过；只清理自己管理的会话目录 |
| §8/§13 可复现环境及固定测试 | pyproject.toml/uv.lock、Python 3.12.3 新虚拟环境、47 包、Ruff、529 pytest、sdist/wheel；runs/delivery-step38/clean-smoke/verification.json | 通过；源码语法面向 Python 3.10+，未实跑其他解释器/操作系统；控制器测试不调用付费 API |
| §2.3 不做事项 | Agent 工具枚举和 dispatcher、固定材料/语料边界；无安装、驱动修改、任意命令、全仓库索引或用户训练重跑工具 | 产品保持单 Agent MVP；评分阶段的独立模型不属于产品多 Agent 架构 |

上述测试均包含在本次独立克隆执行的 **529 项通过**中。测试证明各自覆盖的固定边界；诊断效果另由真实运行评分证明。

## 数据、评测与六个里程碑

| 要求 | 直接证据 | 结论 |
|---|---|---|
| §10 第 1 周：五类真实种子、协议与标准诊断 | benchmark/dev 真实采集案例、gold/dev 原参考状态、protocols/dev_cases 测试，历史 Step 02/06/07 采集记录 | 3/3；六个真实种子覆盖五类，参考诊断与模型结果分开 |
| §10 第 2 周：真实工具、边界/超时/无 GPU、文档来源 | 上表工具、路径、环境与语料证据 | 3/3 |
| §10 第 3 周：五类完整报告、假设更新、预算与轨迹 | docs/progress Step 14～17 五类真实模型验收；dep_002 变化轨迹；本轮预算停止记录 | 4/4；不是合并成同版五类成功率 |
| §10 第 4 周：演示 UI、双格式、时间线、至少两预置验证 | AppTest、clean-smoke、dependency/path 固定检查及六例匹配 | 4/4 |
| §11：10 dev + 30 test、五类各四测试、4 不足/2 范围外/4 攻击、族隔离与版本来源 | dataset verify、frozen.json、manifest、gold；实际 dev 9 captured/1 synthetic，test 14/16 | 通过；同族解释器两例只在 dev，诊断工具不访问 gold |
| §11.3 六案例真实验证 | runtime-step28-reviewed.json 的原输出及 runtime-step33-matched.json 的报告摘要、建议序号与 Shivice 确认 | 6/6；路径、形状、设备各两例，依赖为优先建议而非强制配额；不是用户训练重跑 |
| §12 B0/B1/A 公平输入、模型/参数/版本固定、先试跑后完整运行 | eval-step34-dev/test 的 plan、review、result、trace；3 项试跑后完成 120 项，119 正常、1 预算停止 | 通过；上下文可见性和计算开销差异已披露 |
| §12.2 所有七项效果目标与开销分布 | summary-ai.json 及 evaluation-results.md | A 为 90%/95%/90%/91.3%、6/6、4/4，历史固定匹配 6/6；达到目标。费用缺供应商单价，保持未知并报告已知 token |
| §12.3 语义 rubric、身份、独立复评与分歧 | 40 packets、40 Codex 主评、40 Opus 5.5 复评、40 裁定；120 行带结果/轨迹摘要；27 报告布尔分歧、17 主评布尔改变 | 通过；本轮全 AI，保留原独立判断，不假冒人工 |
| §10 第 5 周、§12.4 指标/分母、至少五典型失败及类型分布、不据测试调优 | evaluation-results.md 十类失败及四轴分布、scores-ai.json、冻结摘要与原计划 | 4/4；A 未优于 B1，已解释开销与错误传播 |
| §12.4 条件性重复运行 | runs/repeat-step38/manifest.json、20 项结果/轨迹及单 AI 评分、summary.json | 20/20；每类按 ID 取前两例，三轮描述性方差完成，主指标不变；评分人数、服务时间窗口和后端版本限制已披露 |
| 可选消融及 §2.4 扩展 | 未运行 A-no-docs，未增加 MVP 外功能 | 不作为必做门槛，未证明文档检索边际收益 |
| §10 第 6 周与 §14～15 | 下表最终交付材料、干净环境记录及包核查 | 3/3；干净环境、完整交付及规划格式核查通过，双轴审阅见 docs/progress.md |

## 交付清单

| 要求 | 入口 | 核查状态 |
|---|---|---|
| 源码、锁文件、许可证、第三方来源 | README、src/、uv.lock、LICENSE（MIT 2026 ShiningCrevice）、docs/third-party.md | 源码与清单齐备，包内逐文件 SHA-256 与 ZIP CRC 通过 |
| 环境配置、启动、演示、评测、限制 | README、.env.example、docs/reproduction.md、benchmark/README.md | 独立克隆启动、完整导出、缺依赖降级通过 |
| 可公开日志/快照/案例与隔离标签 | benchmark/dev、test_inputs、gold、frozen.json | 数据冻结校验通过；打包内容未匹配当前配置的 API 密钥 |
| 本地语料来源、版本、整理日期 | knowledge/README.md、随包 documents.json | 15 条来源齐备，语料测试通过 |
| 运行记录、标签、评分、代表性轨迹 | runs/eval-step34-{dev,test}/、runs/ai-scoring-step37/scores-final.html | 120 项摘要绑定及重算通过；40 案例、120 份评分可在浏览器展开 |
| 一份完整 Markdown/JSON 诊断报告 | runs/delivery-step38/clean-smoke/report.md、report.json | 9 证据、4 工具，双格式与终态一致，synthetic 固定响应 |
| 8～12 页技术报告 | runs/delivery-step38/DeepDebug-technical-report.pdf | 10 页，已检查排版；包含主评测、评分来源、重复方差和失败分析 |
| 5～7 分钟视频与脚本 | runs/delivery-step38/DeepDebug-demo.mp4、同名 .srt、docs/demo-script.md | 360 秒、1920×1080、25 fps；标明历史真实回放、当前评测和固定实验 |
| 无 GPU 模式与干净复现 | docs/reproduction.md、clean-smoke/verification.json、no-torch.json | 529 测试、构建、健康接口与主页通过；未安装 PyTorch |
| 包内索引、来源、媒体授权与完整性 | START_HERE.html、DELIVERY.json、media-tools.json、licenses/ | 打包、解压、660 个本地链接与浏览器入口通过；源码版本及逐文件摘要见 DELIVERY.json |

未提供额外课程模板或上传平台，交付采用规划规定的格式。最终包保留源码、实验及评分版本，课程平台提交不属于本地开发与交付动作。
