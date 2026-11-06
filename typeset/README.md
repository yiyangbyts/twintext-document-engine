# TwinText 排版引擎 2.2.17-public.1

本公开基线使用 Zotero 提供的 JavaScript、阅读器 PDF.js、DOM Canvas 和 ChromeWorker。排版、段落与翻译规则位于 `core/`，宿主适配器位于 `adapters/zotero/`。加载顺序见 `runtime.json`，翻译回调和文件接口见 `API.md`。

在本目录运行基础测试：

```sh
node --test test/runtime.cjs
```

构建源码包或运行真实 PDF 集成测试前，先按仓库首页的步骤生成 DocLayout 模型并核对 `ASSETS.json` 中的摘要。

```sh
python3 build-source.py --output-dir dist
node --test test/integration.cjs
```

集成测试使用 Playwright、Chrome/Chromium 和 Zotero 自带的 PDF.js。按需设置 `NODE_PATH`、`TWINTEXT_BROWSER` 及 `TWINTEXT_ZOTERO_APP`。其他平台可用 `TWINTEXT_ZOTERO_PDF_DIR` 指向 Zotero 的阅读器 PDF 资源目录。测试使用隔离环境和模拟翻译服务。

本模块按 AGPL-3.0-only 提供。第三方组件的版权和许可见 `NOTICE.md`、`LICENSE.txt` 和 `licenses/`。
