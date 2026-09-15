from jarvis.profile import load_profile, profile_block, profile_path, remember_fact


def test_missing_profile_is_empty(tmp_path):
    assert load_profile(tmp_path) == ""
    assert profile_block(tmp_path) == ""


def test_remember_creates_file_with_header(tmp_path):
    assert remember_fact(tmp_path, "lives in Lisbon") == "lives in Lisbon"
    text = profile_path(tmp_path).read_text()
    assert text.startswith("# About the user")
    assert "- lives in Lisbon" in text


def test_remember_appends_and_skips_duplicates(tmp_path):
    remember_fact(tmp_path, "lives in Lisbon")
    remember_fact(tmp_path, "speaks Spanish and English")
    remember_fact(tmp_path, "Lives in Lisbon")
    lines = [x for x in profile_path(tmp_path).read_text().splitlines() if x.startswith("- ")]
    assert lines == ["- lives in Lisbon", "- speaks Spanish and English"]


def test_remember_cleans_input(tmp_path):
    assert remember_fact(tmp_path, "  - works   on ShopFront \n") == "works on ShopFront"
    assert remember_fact(tmp_path, "   ") == ""


def test_profile_block_contains_facts(tmp_path):
    remember_fact(tmp_path, "lives in Lisbon")
    block = profile_block(tmp_path)
    assert "don't ask again" in block and "lives in Lisbon" in block
