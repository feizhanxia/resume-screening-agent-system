# 标准 Agent Loop

## 1. 处理单位

系统的最小业务单位是 `CandidatePackage`，不是单个文件。

```text
简历根目录/
├── 张三/
│   ├── 简历.pdf
│   ├── 项目补充.docx
│   └── 证明材料/论文.pdf
├── 李四/
│   ├── CV.docx
│   └── portfolio.pdf
└── 未归属文件.pdf  → 标记未归属，不自动猜候选人
```

一个候选人目录由一个 Worker 独占处理。目录内文件可在该 Worker 的控制下并行提取，但不能分给不同候选人 Worker 独立分析。所有普通文件都进入材料清单和 `package_hash`；暂不支持解析的文件使用 `inventory_only` 状态，仍会随候选人目录一起整理复制。

核心对象：

```python
class CandidatePackage:
    candidate_id: str
    root_path: str
    relative_dir: str
    package_hash: str
    files: list[MaterialFile]

class MaterialFile:
    file_id: str
    candidate_id: str
    relative_path: str
    media_type: str
    material_role: str
    content_hash: str
    extraction_status: str
```

`material_role` 可为 `primary_resume | supplementary | certificate | portfolio | publication | other | unknown`。所有受支持文件仍在本地提取并进入覆盖审计；角色决定发送给模型的文本预算：主简历使用全文，论文和其他非主材料仅使用受限预览。

## 2. 为什么使用有界 Loop

自由 ReAct Agent 容易无限调用、重复读取或跳过材料。本系统采用固定步骤、动态决策的有界循环：模型可以解释条件和材料，但下一步允许做什么由状态机决定。

标准循环：

```text
OBSERVE → DECIDE → ACT → VALIDATE → PERSIST → NEXT/STOP
```

- `OBSERVE`：读取候选人、文件、缓存、条件和上次错误。
- `DECIDE`：纯代码策略选择唯一下一动作。
- `ACT`：调用一个标准 Tool。
- `VALIDATE`：校验输出结构、文件覆盖、证据来源和条件覆盖。
- `PERSIST`：事务写入数据库和缓存，记录事件。
- `NEXT/STOP`：继续下一步，或进入成功/待复核/失败终态。

## 3. 候选人状态机

```text
DISCOVERED
  → EXTRACTING
  → NORMALIZING
  → READY_FOR_ANALYSIS
  → ANALYZING
  → VERIFYING
  ├─ NEEDS_FACTS → RESOLVING_FACTS → VERIFYING
  ├─ RETRYABLE_ERROR → 前一安全状态
  ├─ NEEDS_REVIEW
  ├─ FAILED
  └─ COMPLETED
```

终态只有 `COMPLETED | NEEDS_REVIEW | FAILED`。加密、空白、无法 OCR、条件证据冲突等都必须形成终态和原因。

## 4. 标准 Tool 接口

首版 Tool 固定，不允许模型动态安装或执行任意代码：

| Tool | 输入 | 输出 |
|---|---|---|
| `scan_candidate_package` | 候选人目录 | 文件清单、哈希、异常 |
| `extract_pdf` | PDF 文件 | 逐页文本、页覆盖、OCR状态 |
| `extract_docx` | DOCX 文件 | 有序段落/表格、对象异常 |
| `extract_image` | PNG/JPEG/TIFF | OCR文本与图像状态 |
| `inventory_material` | 其他文件 | 元数据、哈希、仅归档状态 |
| `classify_material` | 文件名与摘要 | 材料角色 |
| `merge_candidate_dossier` | 全部文件提取结果 | 去重后的候选人档案视图 |
| `compile_criteria` | JD与要求 | 条件草案 |
| `analyze_candidate` | 档案视图与条件 | 事实、判断、证据、待查事实 |
| `resolve_fact` | 标准事实请求 | 带来源的事实或不确定 |
| `audit_candidate` | 候选人全部状态 | 覆盖缺口与终态建议 |
| `export_results` | 运行ID | Excel |
| `copy_candidate_packages` | candidate_id集合 | 复制结果与manifest |

每个 Tool 使用 pydantic 定义输入和输出，带 `tool_version`。缓存键包含工具版本，升级提取器后可以识别旧缓存。

## 5. Loop 决策表

| 当前观察 | 下一动作 |
|---|---|
| 目录尚未扫描或包哈希变化 | `scan_candidate_package` |
| 存在未提取或已变化 PDF | `extract_pdf` |
| 存在未提取或已变化 DOCX | `extract_docx` |
| 文件全部终态但档案视图过期 | `merge_candidate_dossier` |
| 档案就绪且当前条件缺少判断 | `analyze_candidate` |
| 存在可解析外部事实请求 | `resolve_fact` |
| 结果 JSON 无效且重试未超限 | 重试上一个模型 Tool |
| 条件或证据覆盖不足 | `audit_candidate` 后进入待复核或补做 |
| 所有文件和条件覆盖完整 | `COMPLETED` |

模型不能自己选择跳过文件，也不能直接把候选人标记为完成。

## 6. 有界限制

每个候选人默认：

```yaml
max_loop_steps: 20
max_analysis_calls: 2
max_audit_calls: 1
max_retries_per_tool: 2
max_fact_requests: 20
lease_seconds: 900
```

超过限制不继续消耗 API，而是进入 `NEEDS_REVIEW` 并保存最后状态。外部限流采用退避，不计入语义重试次数。

## 7. 运行伪代码

```python
async def run_candidate(candidate_id: str, run_id: str) -> FinalState:
    lease = await tasks.claim(candidate_id, run_id)
    try:
        for step_no in range(settings.max_loop_steps):
            observation = await repository.observe(candidate_id, run_id)
            action = policy.decide(observation)

            if action.type == "STOP":
                return await repository.finalize(action.final_state)

            result = await tools.execute(action)
            validated = validators.validate(action, result, observation)
            await repository.persist_event(action, validated)

        return await repository.finalize("NEEDS_REVIEW", "loop_limit")
    finally:
        await tasks.release(lease)
```

`policy.decide()` 是可测试的确定性函数；只有 `compile_criteria`、`classify_material`、`analyze_candidate` 和可选复核需要模型。

## 8. 八路调度

全局调度器维护最多八个活动候选人：

```text
Candidate Worker 1 ── 候选人A档案包
Candidate Worker 2 ── 候选人B档案包
...
Candidate Worker 8 ── 候选人H档案包
```

Worker 完成或进入待复核后立即领取下一个候选人，不按固定轮次等待。数据库写入、Excel 导出和材料复制仍由单写入器串行完成。

## 9. 证据模型

任何事实和判断必须指向具体材料：

```json
{
  "candidate_id": "cand_123",
  "criterion_id": "skill.python",
  "conclusion": "符合",
  "evidence": [
    {
      "file_id": "file_abc",
      "relative_path": "项目补充.docx",
      "locator": {"kind": "paragraph", "value": 18},
      "quote": "使用 Python 构建分子性质预测模型"
    },
    {
      "file_id": "file_def",
      "relative_path": "简历.pdf",
      "locator": {"kind": "page", "value": 2},
      "quote": "Python / PyTorch"
    }
  ]
}
```

PDF 用页码，DOCX 用段落、表格单元或对象编号。候选人级合并时保留来源，不能只保存无来源的汇总文本。

## 10. 增量规则

- 候选人目录新增材料：扫描包哈希变化，只提取新增文件，再重建档案并重算受影响判断。
- 修改单个文件：新 `file_id` 替代旧活动映射，旧结果保留历史。
- 删除材料：标记文件不再活动，重建档案并重新验证原结论是否仍有证据。
- 目录改名：根据包哈希提示可能是同一候选人，由用户确认关联。
- 同一材料出现在多个候选人目录：分别保留归属，同时标记内容重复，不能静默合并候选人。
