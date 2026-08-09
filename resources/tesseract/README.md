# Tesseract 发布资源

源码运行时会优先使用 `RESUME_AGENT_TESSERACT` 指定的程序，其次查找此资源目录，最后使用系统 PATH。冻结后的公开安装包只加载应用自身目录中的 OCR 资源，不信任目标机器的环境变量或 PATH。

正式安装包应按目标系统放入 Tesseract 5 可执行文件、依赖动态库和 `tessdata/chi_sim.traineddata`、`eng.traineddata`，并保留相应 Apache-2.0 与语言数据许可。macOS 与 Windows 资源不能互相复用，必须分别构建和验收。

本仓库不直接提交第三方 Tesseract 可执行文件。当前 Windows 构建内置 RapidOCR 与 ONNX Runtime 作为离线 OCR 后端，并保留 `tessdata/LICENSE`。新增二进制资源时，必须在 `THIRD_PARTY_NOTICES.md` 记录准确版本、上游下载地址、许可证和 SHA-256，不能提交来源不明的 DLL 或模型。
