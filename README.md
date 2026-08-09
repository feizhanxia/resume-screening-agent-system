# 本地优先简历筛选智能体系统

这是一个独立于 WorkBuddy 的桌面应用项目，用于批量扫描本地 PDF/DOCX 简历、增量提取、按动态岗位条件筛选、审计覆盖率、导出 Excel，并把筛选后的候选人材料安全复制到指定目录。产品直接采用原生桌面 GUI，不依赖浏览器或本地 Web 服务。

当前目录已包含可运行的桌面应用 MVP、核心处理引擎、测试和跨平台构建脚本。

当前构建产物与验收结果见 [交付状态](docs/BUILD_STATUS.md)。

## 已实现能力

- 原生 PySide6 桌面界面：任务配置、条件确认、八路进度、结果/证据查看。
- 每个一级子目录作为一个候选人包，递归登记全部普通文件和内容哈希。
- PDF 逐页提取、图片型页面按需离线 OCR、DOCX 段落/表格顺序提取。
- 其他格式使用 `inventory_only` 终态，仍进入覆盖核查和材料复制。
- DeepSeek JSON 条件编译和候选人分析；无 Key 时安全降级为“待复核”。
- 8 个 Worker、全局 8 路提取/分析信号量、暂停、继续、取消和内容缓存。
- SQLite WAL、条件/材料指纹增量复用、覆盖审计和异常可见。
- 七张表 Excel、证据定位、结果过滤和整包材料复制/哈希校验。
- API Key 仅保存到系统钥匙串，模型请求默认脱敏联系方式。

## 源码运行

```bash
cd resume-screening-agent-system
python3.12 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
python -m resume_agent.app
```

测试：

```bash
pytest
```

也可以用诊断 CLI：

```bash
resume-agent /path/to/resumes /path/to/output --jd "岗位要求" --requirements "补充条件"
```

## 打包

- macOS：`bash deploy/build_macos.sh`
- Windows x64：在 Windows 10/11 机器运行 `powershell -ExecutionPolicy Bypass -File deploy/build_windows.ps1`

Windows 构建会执行代码检查、自动化测试和冻结程序 OCR 自检，并生成：

- `dist/ResumeScreeningAgent-portable-x64.zip`：免安装便携版。
- `dist/ResumeScreeningAgent-Setup-x64.exe`：Inno Setup 用户级安装器；需要构建机装有 Inno Setup 6。安装后的产品名和快捷方式仍显示“简历筛选工作台”。
- `dist/windows-SHA256.txt`：两个交付物的 SHA-256。

仓库同时包含 `.github/workflows/build-windows.yml`。将源码放入私有 GitHub 仓库后可手动触发 Windows 2022 构建，无需自备 Windows 电脑；工作流只上传构建产物，不保存 API Key 或简历。

两个系统必须分别构建。应用优先使用 Tesseract，并内置 RapidOCR + ONNX Runtime 作为完全离线兜底，因此目标机器无需另装 OCR。正式公开分发前仍需完成代码签名、公证或 Windows 安装器签名；签名证书不能由源码仓库代替。

## 核心设计

- 一个确定性协调器管理候选人目录、文件、条件、队列、重试和验收。
- 简历根目录下每个一级子目录代表一名候选人；目录内全部 PDF/DOCX 和补充材料共同形成候选人档案包。
- 八个 Worker 按候选人档案包并行处理；同一候选人只由一个 Worker 独占，不创建十六个 Agent。
- PDF/DOCX 原文件、提取文本、SQLite、JSON 和 Excel 全部保存在本机。
- DeepSeek API 只处理需要语义理解的文本；文件扫描、哈希、状态和覆盖率由代码计算。
- SQLite 是机器事实源，Excel 是可查看和人工维护的结果视图。
- 新条件优先使用已缓存文本和事实，不重新读取原始文档。
- 不确定、读取失败、图片型、空白和加密文件都有显式终态，不能静默漏掉。

## 推荐阅读顺序

1. [产品需求与最终技术路线](docs/PRODUCT_TECH_ROUTE.md)
2. [标准 Agent Loop](docs/AGENT_LOOP.md)
3. [总体架构](docs/ARCHITECTURE.md)
4. [分阶段开发计划](docs/IMPLEMENTATION_PLAN.md)
5. [安全与隐私](docs/SECURITY.md)
6. [Windows 图文使用手册](docs/简历筛选工作台-Windows版使用手册.docx)

## 最终使用方式

用户安装并打开应用后，通过界面依次完成：选择简历目录和输出目录、粘贴 JD 与筛选要求、确认自动拆解的条件、启动八路处理、筛选结果、导出 Excel、整理入选候选人材料。

CLI 仅保留为开发测试和故障诊断接口，不要求最终用户使用命令行。

## 推荐技术栈

- Python 3.12
- PySide6-Essentials + Qt Widgets：原生桌面 GUI
- Typer：内部诊断 CLI
- SQLite WAL + SQLAlchemy 2：本地状态与结构化数据
- pypdfium2：PDF 页数、文本和页面渲染
- python-docx：DOCX 段落、表格和文档结构读取
- pydantic：输入输出与模型 JSON 校验
- OpenAI Python SDK：调用 DeepSeek 的 OpenAI 兼容接口
- openpyxl：单写入者生成和刷新 Excel
- keyring：把 API Key 保存到系统凭据库
- pyside6-deploy/Nuitka：冻结程序；按操作系统生成安装包

如决定把产品按 AGPL 开源或购买 Artifex 商业许可，可将 PDF 引擎替换为 PyMuPDF；专有分发版本默认使用许可更宽松的 pypdfium2。
- pytest、ruff、mypy：测试与质量控制

## 密钥配置

复制 `.env.example` 为 `.env`，写入重新生成的 Key。`.env` 已被 Git 忽略，不要把真实 Key 写进源码、日志、测试样例或命令历史。

DeepSeek 官方接口地址和当前模型名称见：

- https://api-docs.deepseek.com/quick_start/pricing
- https://api-docs.deepseek.com/guides/json_mode/
- https://api-docs.deepseek.com/guides/thinking_mode
