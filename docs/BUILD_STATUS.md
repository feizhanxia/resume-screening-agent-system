# 当前交付状态

## 可运行交付物

- macOS Apple Silicon 安装镜像：`dist/简历筛选工作台-macOS-arm64.dmg`
- 独立应用：`dist/简历筛选工作台.app`
- DMG SHA-256：`4c86c75085c8eb2cdefb227329d3d50dc5f1cd724391634cf191e92b2f7622c4`
- 应用标识：`com.resumeagent.desktop`

DMG 已通过 `hdiutil verify`。构建产物在移除 Tesseract 的 PATH 环境下启动，成功从应用包内加载 RapidOCR、ONNX Runtime 和三个 OCR 模型，并正确识别测试图像 `Python PyTorch 123`。

## 已验证范围

- `ruff check src tests` 通过。
- 7 项 pytest 通过，包括目录扫描、包哈希、DOCX 顺序证据、60 候选人八路队列、Excel、人工字段持久化、材料复制和离线 OCR。
- GUI 四页均完成离屏渲染检查。
- API Key 未写入源码、测试、日志或安装包；项目秘密扫描无匹配。
- 当前没有使用用户曾在对话中公开的旧 Key，也没有用该 Key 发起请求。

## 发布边界

- 当前 DMG 是 arm64 架构和 ad-hoc 签名，适合本机试用与开发验收。公开分发前需要使用开发者自己的 Apple Developer ID 签名并公证。
- Windows x64 构建已补齐 PyInstaller 冻结、应用图标、版本信息、便携 ZIP、Inno Setup 用户级安装器、SHA-256、测试和打包后 OCR 自检。可在 Windows 10/11 本机运行 `deploy/build_windows.ps1`，或通过 `.github/workflows/build-windows.yml` 使用私有 GitHub Actions 的 Windows 2022 构建机。macOS 不能交叉生成或验收 Windows 可执行文件，因此当前工作区尚无真实 `.exe` 二进制。
- DeepSeek 真实 API 端到端请求未执行；首次使用时请在设置页保存一枚已轮换的新 Key，并先用少量非敏感样本验证账户模型权限。
