# 离线回放示例

`dep_002_replay.json` 是 **synthetic 人工固定模型响应**，驱动真实只读工具演示单 Agent 循环，不是模型输出或评测答案。输入使用 `benchmark/dev/dep_002/materials/` 的真实日志、启动配置和两份快照；回放不读取 gold。

```bash
mkdir -p runs
uv run --locked deepdebug replay \
  --root benchmark/dev/dep_002/materials \
  --log log.txt --config launch.json \
  --snapshot target_snapshot.json --snapshot project_snapshot.json \
  --responses examples/dep_002_replay.json \
  --trace runs/dep_002-trace.jsonl
```

按示例顺序登记材料后，A001 为日志、A002 为配置、A003/A004 为目标/项目快照。固定响应引用这些 ID 和工具真实生成的证据编号；改变材料或读取顺序后应更新响应，错误引用将进入控制器的修正/停止流程。

演示依次读取配置、目标快照和项目快照，将缺包候选细化为解释器不一致，最后输出带建议和验证判据的 JSON 报告。修复未执行，快照仅代表采集时刻。标准输出是完整状态；轨迹需要新文件名，父目录须存在。

响应文件格式：

```json
[
  {
    "decision": {
      "observation": "缺少环境证据。",
      "hypotheses": [],
      "action": {
        "action": "need_info",
        "questions": ["请提供故障解释器的环境快照。"],
        "reason": "无法区分候选原因。"
      }
    },
    "input_tokens": 0,
    "output_tokens": 0
  }
]
```

用量字段为可选模拟计数，默认 0。`decision` 也可为原始 JSON 字符串，以演示结构修正；合法决策结构可用 `deepdebug schema decision` 导出。`--root` 回放输出和轨迹包含输入原文。可按 [脱敏预览与材料确认](../README.md#脱敏预览与材料确认) 生成确认副本，再使用 `--reviewed` 回放；上述四份材料的顺序保持一致。两种 replay 入口均为本地固定响应；云端使用 diagnose，并显式指定已确认副本、目的地与模型。完整报告导出命令和干净环境实跑见 [复现记录](../docs/reproduction.md)。
