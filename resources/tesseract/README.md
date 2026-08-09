# Tesseract 发布资源

源码运行时会优先使用 `RESUME_AGENT_TESSERACT` 指定的程序，其次查找此资源目录，最后使用系统 PATH。

正式安装包应按目标系统放入 Tesseract 5 可执行文件、依赖动态库和 `tessdata/chi_sim.traineddata`、`eng.traineddata`，并保留相应 Apache-2.0 与语言数据许可。macOS 与 Windows 资源不能互相复用，必须分别构建和验收。

