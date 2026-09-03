from app.vertical.loader import load_vertical

EXPECTED_BANDS = {"core_ai_ml", "ai_adjacent_engineering", "data_and_analytics", "technical_non_coding"}
SPEC_FAMILIES = {
    "ml_engineer", "applied_scientist", "research_scientist", "research_engineer", "nlp_llm_engineer",
    "computer_vision_engineer", "deep_learning_engineer", "genai_engineer", "rl_engineer", "speech_audio_ml",
    "software_engineer_ai_product", "backend_engineer_ml_systems", "mlops_engineer", "ml_platform_infra",
    "data_engineer", "ml_devops_cloud", "search_recsys_engineer", "robotics_perception", "ai_security_engineer",
    "data_scientist", "data_analyst_ai", "bi_analytics_engineer", "quantitative_analyst", "decision_scientist",
    "research_analyst_ai", "ai_product_manager", "ai_solutions_architect", "forward_deployed_engineer",
    "ai_consultant", "ai_trainer_evaluator", "prompt_engineer", "ai_technical_program_manager",
    "developer_advocate_ai", "ai_policy_governance", "ai_research_assistant_lab",
}


def test_vertical_loads_all_bands_and_families():
    v = load_vertical("ai")
    assert set(v.bands) == EXPECTED_BANDS
    assert set(v.families) == SPEC_FAMILIES
    for fam in v.families.values():
        assert fam.band in v.bands
        assert fam.title_synonyms, fam.key
        assert fam.qualifying_degree_fields, fam.key
        assert "publications_expected" in fam.signals, fam.key
    assert set(v.ai_relevance_levels) == {"core", "applied", "adjacent", "incidental"}
    assert v.dashboard_default_ai_relevance == ("core", "applied", "adjacent")


def test_skill_normalization_uses_aliases_and_keeps_unknowns():
    v = load_vertical("ai")
    canonical, other = v.normalize_skills(["PyTorch", "torch", "Sklearn", "LLMs", "Underwater basket weaving", " "])
    assert canonical == ["pytorch", "scikit-learn", "large language models"]
    assert other == ["Underwater basket weaving"]
