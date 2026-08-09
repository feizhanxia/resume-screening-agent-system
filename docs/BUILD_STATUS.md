# 当前交付状态

## 可运行交付物

- macOS Apple Silicon 安装镜像：`dist/简历筛选工作台-macOS-arm64.dmg`
- 独立应用：`dist/简历筛选工作台.app`
- DMG SHA-256：`4c86c75085c8eb2cdefb227329d3d50dc5f1cd724391634cf191e92b2f7622c4`
- 应用标识：`com.resumeagent.desktop`
- Windows x64 安装器：`deliverables/windows/resume-screening-agent-windows-x64-installer/ResumeScreeningAgent-Setup-x64.exe`
- Windows x64 便携版：`deliverables/windows/resume-screening-agent-windows-x64-portable/ResumeScreeningAgent-portable-x64.zip`
- Windows 安装器 SHA-256：`9e92b65a0d3253689652cfc355e3d53da4c7164df5fa092d6bea529300fb0a17`
- Windows 便携版 SHA-256：`5dd83d9348f57eab82b34fc4fe90f8ec9b2775c9410c88772c6ea89b357254ff`

DMG 已通过 `hdiutil verify`。构建产物在移除 Tesseract 的 PATH 环境下启动，成功从应用包内加载 RapidOCR、ONNX Runtime 和三个 OCR 模型，并正确识别测试图像 `Python PyTorch 123`。

Windows 产物由 GitHub Actions Windows 2022 x64 Runner 构建。工作流运行 `31312106240` 已通过代码检查、7 项测试、PyInstaller 冻结产物启动和离线 OCR 自检、Inno Setup 中文安装器编译及 Artifact 上传。本地下载后的两个文件与 Runner 校验值一致，便携 ZIP 通过完整性检查。

## 已验证范围

- `ruff check src tests` 通过。
- 7 项 pytest 通过，包括目录扫描、包哈希、DOCX 顺序证据、60 候选人八路队列、Excel、人工字段持久化、材料复制和离线 OCR。
- GUI 四页均完成离屏渲染检查。
- API Key 未写入源码、测试、日志或安装包；项目秘密扫描无匹配。
- 当前没有使用用户曾在对话中公开的旧 Key，也没有用该 Key 发起请求。

## 发布边界

- 当前 DMG 是 arm64 架构和 ad-hoc 签名，适合本机试用与开发验收。公开分发前需要使用开发者自己的 Apple Developer ID 签名并公证。
- Windows x64 构建已补齐 PyInstaller 冻结、应用图标、版本信息、便携 ZIP、Inno Setup 用户级安装器、SHA-256、测试和打包后 OCR 自检。可在 Windows 10/11 本机运行 `deploy/build_windows.ps1`，或通过 `.github/workflows/build-windows.yml` 使用私有 GitHub Actions 的 Windows 2022 构建机。当前安装器未使用商业代码签名证书，其他电脑首次安装时可能出现 Windows SmartScreen 提示。
- DeepSeek 真实 API 端到端请求未执行；首次使用时请在设置页保存一枚已轮换的新 Key，并先用少量非敏感样本验证账户模型权限。
