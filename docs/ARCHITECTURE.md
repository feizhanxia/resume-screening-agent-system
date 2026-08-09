# 总体架构

## 1. 关键结论

首版不应做成九个完全自治的 LLM Agent。最稳妥的形态是：

```text
PySide6 原生桌面 GUI
        │
        ▼
确定性 Orchestrator
  ├─ 目录扫描与文件哈希
  ├─ 条件版本与任务队列
  ├─ 八路 Worker 调度
  ├─ 重试、恢复、审计
  └─ Excel 单写入
        │
        ├───────────────┐
        ▼               ▼
本地文档/SQLite     DeepSeek API
提取文本与证据      语义提取与条件判断
```

“Agent”负责理解用户意图和动态条件；可靠性由数据库事务、唯一约束、状态机和集合核查保证。这样比让多个 Agent 自己发现文件、自己更新 Excel 更可控。

## 2. 系统组件

### 2.1 Workspace Manager

每个简历根目录对应一个本地工作区，保存配置、SQLite、缓存和输出。根目录下每个一级子目录是一名候选人的档案包，内部可以继续嵌套材料目录。原始 PDF/DOCX 不复制，数据库记录候选人目录、文件绝对路径与包内相对路径。

建议运行目录：

```text
<workspace>/
├── resume-agent.db
├── cache/
│   ├── pages/<file_id>/<page_no>.txt
│   ├── extractions/<file_id>.json
│   └── runs/<run_id>/results/<file_id>.json
├── outputs/<run_id>/简历分析.xlsx
└── logs/
```

### 2.2 Scanner

职责：先枚举根目录的一级子目录作为候选人，再递归登记候选人目录内的所有普通文件；PDF、DOCX 和已启用的图片类型进入提取队列，其他类型标记为“仅归档未解析”。记录包内相对路径、大小、修改时间、类型和 SHA-256。根目录直接出现的文件进入“未归属材料”，必须提示用户处理。

优化顺序：先比较路径、大小和修改时间；疑似变化时再计算内容哈希。内容哈希决定 `file_id`；候选人 `package_hash` 由排序后的活动文件哈希集合计算。目录改名但包哈希相同可提示为疑似同一候选人，不能自动合并。

### 2.3 Extractor

PDF 使用 pypdfium2 逐页读取和渲染，并为每一页保存：

- 页码、原始文本、字符数。
- 提取方式：原生文本或 OCR。
- 页面状态：成功、空白、图片型、失败。
- 文档页数、已覆盖页集合和错误信息。

DOCX 使用 python-docx 和底层 XML 顺序遍历段落与表格，保留文档顺序及表格文本；遇到文本框、嵌入对象或只有图片的 DOCX 时记录能力缺口并进入待复核。

标准文本优先直接提取。只有页面无有效文本、被大图覆盖或疑似模拟文字时才用 pypdfium2 渲染页面并触发本地 OCR。发布版把 Tesseract 与中英文语言数据作为应用资源一起安装，通过明确的资源路径调用；OCR 结果按页缓存，禁止同一页重复 OCR。

### 2.4 Criteria Compiler

把 JD 动态编译为条件列表：

```json
{
  "criterion_id": "education.degree.master_plus",
  "name": "硕士及以上",
  "definition": "候选人最高已取得学历为硕士或博士",
  "type": "required",
  "weight": 10,
  "version": 1,
  "required_evidence": ["education.degree", "education.status"]
}
```

硬性条件、评分项和加分项分开。任何定义变化都产生新版本和条件指纹；比较新旧指纹后，只重算新增或变化条件。

### 2.5 Analyzer

单份简历的推荐调用方式：

1. 将已缓存的逐页文本、现有结构化事实、全部启用条件放入一次请求。
2. 默认使用 `deepseek-v4-flash`、关闭思考模式，要求 JSON 输出。
3. 返回候选人事实、每项结论、置信度、证据页码、证据摘要和待查询事实。
4. 用 pydantic 验证；JSON 为空、截断或结构不合法时重试，不能直接写数据库。
5. 只有“不确定但业务价值高”的候选人进入 `deepseek-v4-pro` 思考模式复核。

不要让模型直接决定文件是否处理完成。完成状态由程序根据页覆盖、JSON 校验和条件覆盖计算。

### 2.6 Fact Resolver

学校类型、排名、论文级别等外部事实单独建模：

```text
fact_key = 实体类型 + 标准化实体名 + 属性 + 口径版本
```

例如“本科前20”必须先确定排名来源、年份和口径。没有来源时结论只能是不确定。事实缓存包含来源、查询时间、有效期和原始证据；条件变化时只重算引用该 `fact_key` 的判断。

首版提供三种来源：

1. 用户上传的可信名单或规则表。
2. 本地手工核验并冻结的事实。
3. 以后增加的按需网页查询适配器。

模型常识不能直接写成“已核验事实”。

### 2.7 Auditor

结束前执行集合级验收：

```text
目录 PDF/DOCX file_id 集合 = 数据库当前文件集合
当前文件集合 = 本次结果集合
队列数 = 成功 + 失败 + 待复核
每份当前文档均有提取终态
每份当前文档 × 每个启用条件均有判断终态
Excel 当前结果集合 = 数据库当前结果集合
```

行数一致只是一层检查，还要比较 `file_id` 集合、相对路径和内容哈希。

### 2.8 Reporter

协调器是 Excel 唯一写入者。每累计 20 份结果刷新一次，结束时完整重建机器结果区。人工字段保存在数据库独立表中，按 `file_id` 合并到导出文件，避免覆盖 HR 备注。

建议继续使用六张表：运行状态、文件清单、候选人信息、筛选条件、判断明细、当前结果。

## 3. SQLite 数据模型

不需要 PostgreSQL 或外部数据库。SQLite WAL 足够支持一个协调器、八个 Worker 和 500 份简历。

核心表：

| 表 | 作用 | 关键约束 |
|---|---|---|
| `candidates` | 候选人目录、包哈希和当前状态 | `candidate_id` 唯一 |
| `files` | 材料身份、候选人归属、类型、路径和哈希 | `file_id` 唯一 |
| `candidate_files` | 候选人与活动材料的映射 | `(candidate_id, file_id)` 唯一 |
| `pages` | 每页文本、提取方式和状态 | `(file_id, page_no)` 唯一 |
| `resume_facts` | 聚合后的候选人事实 JSON | `candidate_id` 唯一 |
| `criteria` | 动态条件及版本 | `(criterion_id, version)` 唯一 |
| `runs` | 一次筛选运行和固定参数 | `run_id` 唯一 |
| `tasks` | 候选人队列、所有权、尝试次数和租约 | `(run_id, candidate_id)` 唯一 |
| `judgments` | 候选人单条件判断及证据 | `(run_id, candidate_id, criterion_id, version)` 唯一 |
| `external_facts` | 可追溯的外部事实缓存 | `fact_key` 唯一 |
| `manual_fields` | HR 维护字段 | `candidate_id` 唯一 |

SQLite 存结构化事实，逐页长文本保存在文件缓存中，数据库记录路径和内容哈希。这样备份、迁移和全文重处理都比较简单。

## 4. 八路并行与恢复

固定参数：

```yaml
worker_count: 8
extraction_concurrency: 8
analysis_concurrency: 8
batch_size: 5
excel_flush_every: 20
max_retries_per_resume: 2
```

实现建议：

- 文档提取用 `asyncio.to_thread` 或受控线程池；OCR 确认成为 CPU 瓶颈后再换进程池。
- API 调用使用 `asyncio.Semaphore(8)`，设置连接超时、读取超时、指数退避和抖动。
- Worker 从数据库原子领取任务并取得租约；租约过期的 `processing` 任务可在重启后回收。
- 单文件只允许一个活动任务。结果写数据库事务后再标记完成。
- HTTP 429、5xx 和网络中断可重试；JSON 结构不合法属于分析重试；加密或无法读取的文档属于人工复核而非无限重试。

DeepSeek 当前账户级并发远高于 8，但系统仍固定为 8，避免本机 PDF、网络和费用瞬时放大。并发必须是配置项，不能写死在业务代码中。

## 5. 自适应查询机制

当用户提出数据库里没有的新条件时：

1. 编译并版本化新条件。
2. 检查它依赖的标准事实字段。
3. 字段已有：直接重算判断，不调用文档提取。
4. 字段没有但逐页文本完整：针对缓存文本进行定向提取。
5. 文本缓存不完整：才重新读取原始文档。
6. 需要外部事实：进入 Fact Resolver；无法核验则标记不确定。

因此数据库不会限制未来问题。它保存通用事实、原文证据和判断历史，而不是只保存某一个 JD 的最终分数。

## 6. DeepSeek 接口策略

当前使用 OpenAI 兼容接口：

```text
base_url: https://api.deepseek.com
快速模型: deepseek-v4-flash
复核模型: deepseek-v4-pro
```

旧的 `deepseek-chat` 和 `deepseek-reasoner` 已在 2026-07-24 停用，不应写进新项目。

结构化返回采用 JSON Output：设置 `response_format={"type":"json_object"}`，提示词明确包含 JSON 和完整示例，同时为输出预留足够 token。响应必须经过本地 schema 校验。

默认分析关闭思考模式以降低延迟；复核时开启思考模式并保存最终判断，不把模型思维过程写入候选人报告。首版不需要 Function Calling；按需事实查询稳定后再引入工具调用。

## 7. 推荐代码结构

```text
src/resume_agent/
├── cli.py
├── config.py
├── domain/
│   ├── models.py
│   ├── schemas.py
│   └── states.py
├── storage/
│   ├── database.py
│   ├── repositories.py
│   └── migrations/
├── scanning/
│   └── scanner.py
├── extraction/
│   ├── pdf.py
│   └── ocr.py
├── criteria/
│   └── compiler.py
├── llm/
│   ├── deepseek.py
│   ├── prompts.py
│   └── validation.py
├── workers/
│   ├── queue.py
│   └── runner.py
├── audit/
│   └── coverage.py
├── reporting/
│   └── excel.py
└── adapters/
    └── workbuddy/
```

核心包不依赖 WorkBuddy。WorkBuddy 只作为适配器启动任务、查看状态和打开结果，因此未来也可以接其他界面。

## 8. 产品边界

- 系统用于辅助排序和证据整理，不自动做最终录用决定。
- 不把性别、年龄、民族、婚育、照片等敏感属性作为评分特征。
- “不确定”是合法结果，不能强制二分类。
- 模型分数不能掩盖硬性条件证据缺失；报告必须展示依据页码和待核验项。
