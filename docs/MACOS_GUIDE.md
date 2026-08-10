# macOS 使用指南

当前 macOS Beta 仅支持 Apple Silicon（M1/M2/M3/M4 等 arm64 机型）。

## 下载与安装

1. 从 GitHub Releases 下载 `ResumeScreeningAgent-macOS-arm64.dmg`。
2. 使用同一 Release 中的 `macos-SHA256.txt` 核对完整性。
3. 打开 DMG，将“简历筛选工作台”拖入 Applications。
4. 首次启动如被 Gatekeeper 拦截，进入“系统设置 → 隐私与安全性”，核对来源后选择“仍要打开”。

ZIP 是备用的免 DMG 版本：完整解压后将 `.app` 移入 Applications，不要在 ZIP 内直接运行。

## 当前签名状态

该 Beta 使用 ad-hoc 签名，未使用 Apple Developer ID，也未经过 Apple 公证。因此 Gatekeeper 会默认拦截首次启动。请只从本仓库 Release 下载，并核对 SHA-256。

API Key 保存在 macOS Keychain。原始简历、缓存、SQLite、Excel 和整理后的材料保留在本机；启用 DeepSeek 后的数据边界详见 [隐私说明](../PRIVACY.md)。
