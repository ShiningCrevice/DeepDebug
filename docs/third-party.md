# 第三方材料与依赖来源

本项目固定检索库保存自行整理的摘要，原文来源、适用版本与整理时间集中列于 [knowledge/README.md](../knowledge/README.md)。摘要保留 API 名称与原文链接，不复制整页官方文档。benchmark 的固定最小程序与人工情境由开发流程编写；真实采集和 synthetic 标记见案例清单。

## 干净复现环境的依赖声明

下表来自提交 `0de383e` 的独立环境安装元数据，范围为基础、开发和 UI 依赖。字段优先取 License-Expression，其次取许可证分类或 License 首行；这是包作者声明的记录，完整许可文本随各包分发。精确解析结果见 uv.lock。

| 包 | 版本 | 元数据中的许可声明 |
|---|---|---|
| altair | 6.3.0 | BSD License |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.16.0 | MIT |
| attrs | 26.1.0 | MIT |
| certifi | 2026.10.23 | Mozilla Public License 2.0 (MPL 2.0) |
| charset-normalizer | 3.5.3 | MIT |
| click | 8.5.1 | BSD-3-Clause |
| h11 | 0.16.0 | MIT License |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD License |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| itsdangerous | 2.2.0 | BSD License |
| Jinja2 | 3.1.6 | BSD License |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| narwhals | 2.29.0 | MIT |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pandas | 3.1.1 | BSD-3-Clause |
| pillow | 13.0.0 | MIT-CMU |
| pluggy | 1.7.0 | MIT License |
| protobuf | 7.36.2 | 3-Clause BSD License |
| pyarrow | 26.0.1 | Apache-2.0 |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| pydeck | 0.9.3 | Apache License 2.0 |
| Pygments | 2.21.0 | BSD-2-Clause |
| pytest | 8.4.2 | MIT License |
| python-dateutil | 4.0.0 | BSD-3-Clause |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-multipart | 0.0.34 | Apache-2.0 |
| referencing | 0.37.0 | MIT |
| requests | 2.34.2 | Apache Software License |
| rpds-py | 2026.9.1 | MIT |
| ruff | 0.17.3 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| streamlit | 1.67.0 | Apache-2.0 |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| tzdata | 2026.6 | Apache-2.0 |
| urllib3 | 2.8.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| watchdog | 7.1.1 | Apache-2.0 |
| websockets | 17.4 | BSD-3-Clause |

## 可选采集环境

capture 依赖组不参与基础安装。它包含 PyTorch 2.9.1 与 NumPy；Linux/Windows 的 PyTorch CUDA wheel 来自锁文件指定的官方 cu128 源。PyTorch 及其打包的 CUDA 组件具有各自许可文件，使用时保留分发包内的声明。采集环境的具体依赖以用户选择的解释器为准，不用基础环境清单代替。

## 项目许可证

项目采用 [MIT License](../LICENSE)，版权署名为“2026 ShiningCrevice”。构建包携带许可证正文与 MIT 元数据；第三方依赖和官方文档保留各自许可。

## 本地媒体排版

报告 PDF 嵌入本机 Droid Sans Fallback 与 DejaVu 字体子集；视频字幕使用同源字体。Droid 的声明为 Google Corp. 版权、Apache-2.0；DejaVu 保留 Bitstream Vera 许可，DejaVu 的修改部分为公有领域。原声明来自系统字体包，副本与 Apache-2.0 正文随本地媒体目录的 `licenses/` 提供。媒体制作工具版本记录在同目录 `media-tools.json`；这些工具未加入产品依赖。
