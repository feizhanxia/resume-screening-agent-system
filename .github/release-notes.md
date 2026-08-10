公开 Beta 提供 Windows x64 与 macOS Apple Silicon 版本。

### beta.5 更新

- JD 解析采用独立快速路径：正常只请求一次，相同 JD 复用本地缓存，异常时有限重试并在 60 秒内降级为可编辑草稿。
- 离线内置教育部官方 985、211及第二轮“双一流”高校和建设学科清单，附来源、版本与文件校验值。
- 本科院校类别仅在校名与简历原文能够精确对应时自动核验；排名、综合性大学等没有统一口径的条件继续保留为待核查。
- Windows 与 macOS 打包冒烟测试均强制检查 147 所“双一流”高校清单，避免安装包漏带资源。

### 下载选择

- `ResumeScreeningAgent-Setup-x64.exe`：推荐，用户级安装，无需管理员权限。
- `ResumeScreeningAgent-portable-x64.zip`：完整解压后运行 `ResumeScreeningAgent.exe`。
- `windows-SHA256.txt`：下载后用于核对安装包完整性。
- `ResumeScreeningAgent-macOS-arm64.dmg`：Apple Silicon 推荐安装镜像。
- `ResumeScreeningAgent-macOS-arm64.zip`：macOS `.app` 备用压缩包。
- `macos-SHA256.txt`：macOS 产物完整性校验值。

### 重要提示

本版本尚未使用 Windows Authenticode 或 Apple Developer ID 签名，SmartScreen/Gatekeeper 可能拦截首次启动。请只从本页面下载并核对 SHA-256。原始简历保留在本机；启用 DeepSeek 后，应用会在每次任务前征求确认并发送基础脱敏后的提取文本用于语义分析。

主要功能和安全改进见 [CHANGELOG](https://github.com/feizhanxia/resume-screening-agent-system/blob/main/CHANGELOG.md)，使用方法见 [Windows 指南](https://github.com/feizhanxia/resume-screening-agent-system/blob/main/docs/WINDOWS_GUIDE.md) 与 [macOS 指南](https://github.com/feizhanxia/resume-screening-agent-system/blob/main/docs/MACOS_GUIDE.md)。
