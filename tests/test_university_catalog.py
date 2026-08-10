from resume_agent.domain.models import (
    AnalysisResult,
    CandidateFacts,
    Conclusion,
    Criterion,
    Evidence,
    Judgment,
)
from resume_agent.facts.universities import (
    UniversityCatalog,
    apply_university_resolutions,
)


def _criterion(definition: str = "本科院校为985或211高校") -> Criterion:
    return Criterion(
        criterion_id="education.school-tier",
        name="本科院校层次",
        definition=definition,
        kind="required",
        weight=15,
        requires_external_fact=True,
    )


def _analysis(school: str, quote: str | None = None) -> AnalysisResult:
    evidence = (
        [
            Evidence(
                file_id="resume",
                relative_path="简历.pdf",
                locator_kind="page",
                locator_value="1",
                quote=quote,
            )
        ]
        if quote
        else []
    )
    return AnalysisResult(
        candidate_id="candidate",
        facts=CandidateFacts(undergraduate_school=school),
        judgments=[
            Judgment(
                criterion_id="education.school-tier",
                conclusion="uncertain",
                confidence=0.5,
                reason="需要外部核验",
                evidence=evidence,
                needs_external_fact=True,
            )
        ],
        recommendation="review",
        model="test",
    )


def test_official_university_catalog_counts_and_categories():
    catalog = UniversityCatalog.load_default()

    assert catalog.payload.counts == {
        "985_official": 39,
        "211_official": 112,
        "double_first_class_institutions": 147,
    }
    assert len(catalog.payload.institutions) == 147
    assert sum("985" in item.categories for item in catalog.payload.institutions) == 39
    # The three umbrella institutions in the official 211 table expand to six current entities.
    assert sum("211" in item.categories for item in catalog.payload.institutions) == 115
    tsinghua = catalog.resolve("清华大学")
    assert tsinghua.status == "matched"
    assert tsinghua.categories == ["985", "211", "double_first_class"]
    assert catalog.resolve("湘潭大学").categories == ["double_first_class"]


def test_catalog_resolves_safe_aliases_renames_and_campuses():
    catalog = UniversityCatalog.load_default()

    assert catalog.resolve("北大").standard_name == "北京大学"
    assert catalog.resolve("哈尔滨工业大学（深圳校区）").standard_name == "哈尔滨工业大学"
    assert catalog.resolve("国防科学技术大学").standard_name == "国防科技大学"
    assert catalog.resolve("第二军医大学").standard_name == "海军军医大学"
    assert catalog.resolve("中国石油大学").categories == ["211", "double_first_class"]
    assert catalog.resolve("中国地质大学").categories == ["211", "double_first_class"]
    assert catalog.resolve("中国矿业大学（北京）").categories == [
        "211",
        "double_first_class",
    ]


def test_resolver_matches_and_recalculates_required_result():
    catalog = UniversityCatalog.load_default()
    criterion = _criterion()
    result = _analysis("哈工大", "本科：哈尔滨工业大学（深圳校区），计算机科学与技术")

    resolved = apply_university_resolutions(result, [criterion], catalog)

    assert resolved == 1
    assert result.judgments[0].conclusion == Conclusion.MATCH
    assert not result.judgments[0].needs_external_fact
    assert "2022-second-round-v1" in result.judgments[0].reason
    assert result.score == 100
    assert result.recommendation == "recommended"


def test_resolver_rejects_known_or_formal_nonmember_school():
    catalog = UniversityCatalog.load_default()
    criterion = _criterion("本科院校为985高校")

    known = _analysis("湘潭大学", "本科毕业于湘潭大学")
    assert apply_university_resolutions(known, [criterion], catalog) == 1
    assert known.judgments[0].conclusion == Conclusion.NO_MATCH
    assert known.recommendation == "not_recommended"

    formal = _analysis("深圳大学", "本科毕业于深圳大学")
    assert apply_university_resolutions(formal, [criterion], catalog) == 1
    assert formal.judgments[0].conclusion == Conclusion.NO_MATCH


def test_resolver_keeps_ambiguous_or_unsupported_conditions_uncertain():
    catalog = UniversityCatalog.load_default()

    missing_evidence = _analysis("北京大学")
    assert apply_university_resolutions(missing_evidence, [_criterion()], catalog) == 0
    assert missing_evidence.judgments[0].needs_external_fact

    abbreviation = _analysis("深大", "本科毕业于深大")
    assert apply_university_resolutions(abbreviation, [_criterion()], catalog) == 0
    assert abbreviation.judgments[0].conclusion == Conclusion.UNCERTAIN

    discipline = _analysis("北京大学", "本科毕业于北京大学")
    criterion = _criterion("本科专业须属于双一流学科")
    assert apply_university_resolutions(discipline, [criterion], catalog) == 0
    assert discipline.judgments[0].needs_external_fact

    ranking = _analysis("北京大学", "本科毕业于北京大学")
    criterion = _criterion("本科院校须为排名前20或985高校")
    assert apply_university_resolutions(ranking, [criterion], catalog) == 0
    assert ranking.judgments[0].needs_external_fact
