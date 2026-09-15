import json
from pathlib import Path

import pytest

from jarvis.projects import ProjectResolver, load_aliases


@pytest.fixture
def root(tmp_path):
    for d in ["ShopFront/.git", "shopfront-price-collector/.git", "Acme/bill-reader/.git",
              "Acme/acme-user-catalogue/.git", "Labs/voice bot/.git", ".hidden/.git"]:
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "Ledgerly").mkdir()
    (tmp_path / "Ledgerly" / "package.json").write_text("{}")
    return tmp_path


def test_scan_includes_nested_group_projects(root):
    names = ProjectResolver(root).names()
    for n in ["ShopFront", "Ledgerly", "bill-reader", "voice bot", "Acme", "Labs"]:
        assert n in names
    assert ".hidden" not in names


def test_resolve_case_spacing_and_dashes(root):
    r = ProjectResolver(root)
    assert r.resolve("shopfront").name == "ShopFront"
    assert r.resolve("Shop Front").name == "ShopFront"
    assert r.resolve("Voice-Bot").path == root / "Labs" / "voice bot"


def test_resolve_prefix_prefers_shortest(root):
    assert ProjectResolver(root).resolve("shop").name == "ShopFront"


def test_resolve_fuzzy(root):
    assert ProjectResolver(root).resolve("ledgerli").name == "Ledgerly"


def test_resolve_alias(root, tmp_path):
    f = tmp_path / "projects.json"
    f.write_text(json.dumps({"the store": "ShopFront", "books": str(root / "Ledgerly")}, ensure_ascii=False))
    r = ProjectResolver(root, load_aliases(f))
    assert r.resolve("the store").path == root / "ShopFront"
    assert r.resolve("books").path == root / "Ledgerly"


def test_missing_alias_file_is_empty(tmp_path):
    assert load_aliases(tmp_path / "nope.json") == {}


def test_none_or_blank_is_home(root):
    r = ProjectResolver(root)
    assert r.resolve(None).path == Path.home()
    assert r.resolve("  ").name == "home"


def test_unknown_returns_none_with_suggestions(root):
    r = ProjectResolver(root)
    assert r.resolve("zzzz") is None
    assert r.suggestions("shopfrant")[0] == "ShopFront"
