from pathlib import Path


WORKFLOW = Path(".github/workflows/refresh-love-dining.yml")


def test_document_verifier_runs_as_a_module() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("      - name: Verify reviewed Love Dining documents")
    end = text.index("      - name: Verify Love Dining map pins", start)
    block = text[start:end]

    assert "python3 -m scripts.verify_love_dining_documents" in block
    assert "python3 scripts/verify_love_dining_documents.py" not in block


def test_workflow_installs_the_verifiers_pypdf_version() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "pypdf==6.16.2" in text
    assert "pypdf==6.15.0" not in text
