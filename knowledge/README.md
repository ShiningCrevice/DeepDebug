# 本地文档语料

当前包含 15 条人工整理的中文摘要，五类故障各 3 条；依据 PyTorch 2.9 与 Python 3.12 官方文档，整理于 2026-11-03。摘要为本项目改写，`content_kind=curated_summary`；API 名称保留原文，不复制整页文档或示例代码。原文版权归各来源权利人，引用、改编或分发原文时遵循对应网站的使用条款。

唯一运行时语料为 [`src/deepdebug/knowledge/documents.json`](../src/deepdebug/knowledge/documents.json)，随 sdist/wheel 发布；本目录维护清单，不存放第二份语料。查询仅读取该固定 JSON，不遍历仓库、不加载 benchmark 标签、不联网获取 URL。

语料读取拒绝符号链接与硬链接。从 wheel 通过 uv 安装时使用 `--link-mode copy`；安装到 `.venv` 等隐藏目录受支持。

```bash
uv run --locked deepdebug search-docs '错误解释器' --category dependency
uv run --locked deepdebug search-docs 'mat1 and mat2 shapes cannot be multiplied'
```

每条记录包含文档 ID、标题、故障类别、来源 URL、适用版本、带时区整理时间、关键词和摘要。标题、关键词和摘要合并成一份索引文本，采用 BM25 排序，固定 `k1=1.2`、`b=0.75`。IDF 使用 [Lucene 文档中的正值形式](https://lucene.apache.org/core/9_12_1/core/org/apache/lucene/search/similarities/BM25Similarity.html#idf(long,long))：

```text
idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
score(q, d) = Σ idf(t) × tf(t,d) × (k1 + 1)
               / (tf(t,d) + k1 × (1 - b + b × dl / avgdl))
```

`N` 为文档总数，`df(t)` 为包含词 t 的文档数，`tf(t,d)` 为该词在文档中的次数；`dl` 和 `avgdl` 是分词后的文档长度及平均长度。索引统计基于完整语料，可选类别过滤不重新计算统计量。查询词去重后按固定顺序累加；文档保留词频。只返回正分数结果，同分按文档 ID 排序，最多 3 条，无匹配返回空列表。`score` 为浮点排序分数，不表示诊断置信度。

分词保留完整异常名和下划线标识符；点分 API 保留完整名称及逐级后缀，例如 `torch.nn.Linear` → `torch.nn.linear`、`nn.linear`、`linear`，不额外生成 `torch`、`nn` 前缀词。英文忽略大小写；中文使用相邻双字片段，单个汉字保留。查询与文档采用相同规则。

检索实现的改动与验证结果见 [开发进度](../docs/progress.md)。

文档提供一般规则；具体故障结论仍需日志、代码和环境证据。版本标签表示整理依据，不自动判断与用户环境的兼容性。检索内容按不可信数据处理；模型循环接入后仍需验证提示注入处理。

## 来源清单

| ID | 类别 | 摘要主题与官方来源 | 适用版本 |
|---|---|---|---|
| D001 | `cuda_oom` | [CUDA 缓存分配器与显存统计](https://docs.pytorch.org/docs/2.9/notes/cuda.html#memory-management) | PyTorch 2.9 |
| D002 | `cuda_oom` | [memory_allocated 当前张量显存](https://docs.pytorch.org/docs/2.9/generated/torch.cuda.memory.memory_allocated.html) | PyTorch 2.9 |
| D003 | `cuda_oom` | [empty_cache 的释放范围](https://docs.pytorch.org/docs/2.9/generated/torch.cuda.memory.empty_cache.html) | PyTorch 2.9 |
| D004 | `device_mismatch` | [Tensor.to 返回设备或类型转换后的张量](https://docs.pytorch.org/docs/2.9/generated/torch.Tensor.to.html) | PyTorch 2.9 |
| D005 | `device_mismatch` | [Module.to 迁移参数与缓冲区](https://docs.pytorch.org/docs/2.9/generated/torch.nn.Module.html#torch.nn.Module.to) | PyTorch 2.9 |
| D006 | `device_mismatch` | [torch.tensor 创建时的设备选择](https://docs.pytorch.org/docs/2.9/generated/torch.tensor.html) | PyTorch 2.9 |
| D007 | `dependency` | [venv 隔离与解释器选择](https://docs.python.org/3.12/library/venv.html#how-venvs-work) | Python 3.12 |
| D008 | `dependency` | [sys.executable 标识当前解释器](https://docs.python.org/3.12/library/sys.html#sys.executable) | Python 3.12 |
| D009 | `dependency` | [importlib.metadata 查询分发包](https://docs.python.org/3.12/library/importlib.metadata.html#distribution-versions) | Python 3.12 |
| D010 | `path` | [pathlib 的存在性与文件类型](https://docs.python.org/3.12/library/pathlib.html#querying-file-type-and-status) | Python 3.12 |
| D011 | `path` | [os.path 相对路径与工作目录](https://docs.python.org/3.12/library/os.path.html#os.path.abspath) | Python 3.12 |
| D012 | `path` | [torch.load 的文件输入与设备映射](https://docs.pytorch.org/docs/2.9/generated/torch.load.html) | PyTorch 2.9 |
| D013 | `configuration` | [Linear 的输入特征维度](https://docs.pytorch.org/docs/2.9/generated/torch.nn.Linear.html) | PyTorch 2.9 |
| D014 | `configuration` | [reshape 的元素数量与推断维度](https://docs.pytorch.org/docs/2.9/generated/torch.reshape.html) | PyTorch 2.9 |
| D015 | `configuration` | [CrossEntropyLoss 的标签形状与类型](https://docs.pytorch.org/docs/2.9/generated/torch.nn.CrossEntropyLoss.html) | PyTorch 2.9 |
