from resume_agent.criteria.compiler import criteria_fingerprint, heuristic_compile


def test_heuristic_criteria_and_fingerprint_are_stable():
    jd = """任职要求
● 硕士及以上学历
● 精通 Python 和 PyTorch
加分项
● 有 GNN 项目经验者优先
"""
    first = heuristic_compile(jd)
    second = heuristic_compile(jd)
    assert len(first) == 3
    assert criteria_fingerprint(first) == criteria_fingerprint(second)
    assert any(item.kind == "required" for item in first)
