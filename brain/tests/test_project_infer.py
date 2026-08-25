"""Tests for high-confidence project inference used in retag."""
from brain.ingest.project_infer import infer_projects, infer_unique_project


def test_unique_farmaplus_from_name():
    assert infer_unique_project("FarmaPlus scaffolding in the farmaplus repo") == "farmaplus"


def test_unique_brain_from_brain_api():
    assert infer_unique_project("brain_api launchd plist fails with exit 78") == "brain"


def test_unique_from_absolute_path():
    text = "Repo at /Users/macm1air/Documents/lechandelier-restaurant/src/app/page.tsx"
    # folder map may not have lechandelier-restaurant — alias le chandelier / lechandelier
    text2 = "Created Next app in /Users/macm1air/Documents/le-chandelier/src/app"
    assert infer_unique_project(text2) == "le_chandelier"


def test_ambiguous_returns_none():
    text = "Compared farmaplus and meddefi landing pages"
    assert infer_unique_project(text) is None
    assert infer_projects(text) == {"farmaplus", "meddefi"}


def test_no_signal_returns_none():
    assert infer_unique_project("Changed CSS height from 80px to 40px") is None


def test_sicop_health_beats_sicop():
    assert infer_unique_project("SICOP Health monorepo option for sicop-health") == "sicop-health"


def test_owelign_sakbe_alias():
    assert infer_unique_project("Sakbé Inventory API event-driven architecture") == "owelign"
