# 构建与发布状态

## 当前公开版本

`0.1.0` 是 Windows x64 与 macOS Apple Silicon 公开 Beta。正式交付物只通过 GitHub Release 发布，不把 `dist/`、`deliverables/` 或本地构建产物提交到源码仓库。

每个版本 tag 由 `.github/workflows/build-windows.yml` 在 GitHub 托管的 Windows 2022 Runner 上重新构建，并运行：

- Ruff 代码检查与完整 pytest 测试集。
- PyInstaller 冻结和打包后启动检查。
- 内置离线 OCR 烟雾测试。
- Inno Setup 用户级安装器构建。
- 安装器与便携版 SHA-256 生成。
- GitHub Artifact Attestation 与 Release 资产上传。

Release 应同时包含安装版、免安装版、SHA-256、依赖版本清单、MIT License、第三方声明和 Windows 图文手册。Actions 临时 Artifact 仅用于调试，不视为正式发布渠道。

macOS 由 `.github/workflows/build-macos.yml` 在 Apple Silicon Runner 上构建 DMG 和 APP ZIP，执行打包后启动、OCR、签名结构、DMG 完整性和 SHA-256 检查。

## 已验证范围

- 43 项自动化测试覆盖目录扫描、内容哈希、重复材料去重、材料路由、JD 快速解析与缓存、官方院校目录核验、受限模型上下文、JSON 降级、动态 Worker、DOCX 顺序证据、Excel、人工字段持久化、材料复制、离线 OCR 与关键安全边界。
- 源码包和 wheel 可正常构建，并包含 MIT License。
- Windows 手册已重新生成，并完成 10 页渲染检查。
- 当前源码和 Git 历史未发现真实 API Key；测试只使用合成数据。

## 发布边界

- 首个公开 Windows 安装器尚未使用 Authenticode 证书，因此作为 Pre-release 发布，SmartScreen 可能显示“未知发布者”。SHA-256 和构建证明只能验证完整性，不能替代代码签名。
- DeepSeek 真实 API 端到端调用需要使用者自己的有效 Key。首次使用应先用少量合成或已获授权的样本验证账户、模型和隐私流程。
- macOS Beta 仅支持 Apple Silicon，当前为 ad-hoc 签名且未公证，Gatekeeper 会默认拦截首次启动。
- 500 份真实复杂简历的性能和召回率仍需要在合法、脱敏的基准集上持续验证；自动化结果必须由招聘人员复核。
