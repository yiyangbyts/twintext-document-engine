# TwinText 文档（中文）

TwinText for Zotero（小双对照翻译）在 Zotero 中提供 PDF 翻译、原译文对照阅读和文件导出。本页集中提供使用说明、第三方版权与许可，以及独立文档引擎的源码入口。

## 安装与使用

1. 从产品提供的下载渠道取得适合系统的 XPI，在 Zotero 的插件管理器中选择“从文件安装插件”，安装后重启 Zotero。本仓库发布的是独立引擎源码，不提供客户端安装包。
2. 打开 TwinText 设置，选择翻译服务。文档引擎负责 PDF 解析和排版，正文翻译使用所选服务；第三方服务可能需要自己的账号、凭据或本地服务。
3. 打开 PDF，点击 TwinText，选择全文、当前页或指定页范围，开始翻译。翻译状态浮动显示在 PDF 上方，生成的译文会更新到阅读窗口。
4. 根据阅读习惯调整对照方式、翻译窗口、字号、行距和字体。需要保留原文的参考文献或页眉页脚，可以启用对应的忽略选项。

### 文档引擎

| 选项 | 用途与环境 |
| --- | --- |
| BabelDOC 完整原生混排 | 在本地完成文档解析与 PDF 重建，适用于保留公式和原有版面的翻译。轻量包会检测兼容环境并在需要时自动准备；完整包附带对应平台环境。引擎由插件启动，无需手动启动 Python。 |
| 标准引擎 | 使用 Zotero 提供的 PDF.js 解析和 TwinText 阅读排版，无需安装 Python 环境。 |
| PP-DocLayoutV2 前端 WASM | 在标准解析基础上使用前端版面模型，需要下载模型，无需 Python。模型不可用时使用标准解析继续处理。 |

Mac、Windows 和 Linux 的运行环境按平台选择；Windows ARM64 完整包使用 Windows x64 兼容环境。首次环境准备、模型下载、翻译服务响应及 PDF 复杂程度会影响等待时间。

如果环境准备失败，可在设置中的“维护与诊断”检查运行环境并查看诊断记录，在“文档翻译”中修复文档引擎。卸载本产品环境只清理安装记录确认由 TwinText 安装的部分，保留外部或共享环境及已保存译文。反馈问题时请提供系统、插件版本及诊断中的错误文字，避免公开凭据或私人文档。

## 版权与许可

TwinText 尊重第三方软件及资源权利人的知识产权。产品使用的第三方组件保留其原始版权归属、许可文本和适配修改说明；使用、修改和再分发的权利与义务以各组件原许可证为准。组件名称仅用于说明技术来源，不表示官方合作或认证。

完整的[第三方版权与许可声明](THIRD-PARTY-NOTICES.md)列出产品实际使用的组件及资源。安装包中的 `content/licenses/` 保留许可材料，`content/engines/babeldoc/NOTICE.md` 保留独立引擎修改说明。GitHub 上的材料供查阅和下载，安装包中的原始告知与许可文本同时保留。

| 组件或材料 | 版本与许可 | 详细材料 |
| --- | --- | --- |
| TwinText 独立文档引擎、运行检测及源码构建代码 | Copyright © 2026 TwinText；AGPL-3.0-only | [引擎许可](LICENSE.txt)、[修改与来源说明](engine/NOTICE.md)、[运行说明](engine/README.md) |
| BabelDOC | 0.6.4；AGPL-3.0，内含代码保留相应许可 | [AGPL 原文](licenses/AGPL-3.0.txt)、[实际依赖清单](licenses/runtime/inventory.json) |
| PyMuPDF / MuPDF | 1.28.2；本运行环境采用 AGPL 版本 | [依赖及原始版权文本索引](licenses/runtime/inventory.json)、[固定版本上游源码索引](engine/upstream-sources.json) |
| PP-DocLayoutV2 模型及 ONNX 转换资源 | 模型卡声明 Apache-2.0，固定转换版本及文件摘要见资源清单 | [原模型说明](licenses/upstream/PP-DocLayoutV2-MODEL-CARD.md)、[转换资源说明](licenses/upstream/PP-DocLayoutV2-ONNX-MODEL-CARD.md)、[Apache 原文](licenses/APACHE-2.0.txt) |
| ONNX Runtime Web | 1.30.0；MIT 及随附告知 | [MIT 原文](licenses/frontend/ONNX-Runtime-Web-LICENSE-MIT)、[随附告知](licenses/frontend/ONNX-Runtime-Web-NOTICE.md) |
| Python 与运行依赖、字体和模型 | Python 3.12.11；各项分别适用 PSF、GPL、MPL、MIT、BSD、OFL 及资源许可等 | [五个平台及资源的完整清单](licenses/runtime/inventory.json)、[资源来源与版权文本摘要](licenses/upstream/sources.json) |
| uv | 0.8.22；MIT 或 Apache-2.0 | [MIT 原文](licenses/uv/LICENSE-MIT)、[Apache 原文](licenses/uv/LICENSE-APACHE) |

标准解析调用 Zotero 自带的 PDF.js，插件未重新分发 PDF.js。组件是否随包提供或安装取决于所用功能、平台和安装包类型；清单提供各平台版本、原作者告知、许可文件路径、来源和摘要。第三方组件按原许可证提供，适用原文中的担保与责任条款。

独立引擎的 TwinText 代码允许依 AGPL-3.0-only 使用、修改和再分发；对应源码的提供等要求见许可原文。公开源码包含实际适配修改，涉及参考文献、编号列表、目录、旋转页面、段落预览及错误恢复，详细说明见引擎 NOTICE。各第三方组件保留其原许可。

## 对应版本源码

打开[版本发布页](https://github.com/yiyangbyts/twintext-document-engine/releases)，选择与产品版本一致的标签，例如产品 2.0.8 对应 `v2.0.8`，下载：

- `twintext-engine-source-版本.zip`：独立引擎、适配修改、HTTP/CLI 接口、测试、依赖约束、安装与源码构建材料、许可和文件摘要清单。
- `twintext-upstream-sources.zip`：固定版本的 BabelDOC、PyMuPDF、MuPDF 和 Levenshtein 上游源码，以及版本与摘要记录。
- 对应的 `.sha256` 文件：用于核对下载内容。

安装包中的 `content/engines/babeldoc/source-distribution.json` 给出该版本的精确下载地址。引擎的 `/v1/source` 接口也提供对应地址。查阅和下载公开源码不需要 TwinText 账号、激活或付费。

引擎可以脱离 Zotero 独立运行；安装、命令行使用和测试见[引擎运行说明](engine/README.md)，HTTP 协议见[接口说明](engine/API.md)。当前源码快照的文件、摘要和版本映射见 [SOURCE-MANIFEST.json](SOURCE-MANIFEST.json)。产品客户端、账户服务及私有产品仓库历史不包含在此公开快照中；该工程目录划分本身不替代适用许可证对受许可作品及对应源码范围的要求。

后续发布将保留既有版本下载，并随版本更新对应源码、修改说明和依赖材料。
