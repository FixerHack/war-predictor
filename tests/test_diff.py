from tension_index.diff import changed_fragment, normalize


def test_normalize_ignores_cosmetic_whitespace():
    assert normalize("a  b\n\n  c  d\n") == normalize("a b\nc d")


def test_no_change_gives_empty_diff():
    assert changed_fragment("Level 2\nsame", "Level 2  \n\nsame") == ""


def test_change_is_reported():
    diff = changed_fragment(
        "Exercise increased caution.\nConsular services normal.",
        "Reconsider travel due to armed conflict.\nConsular services normal.",
    )
    assert "-Exercise increased caution." in diff
    assert "+Reconsider travel due to armed conflict." in diff
    assert "---" not in diff


def test_boilerplate_dates_are_ignored_but_content_kept():
    old = "Last updated: 1 September 2026\nStill current at: 2 September 2026\nReconsider travel"
    new = "Last updated: 30 September 2026\nStill current at: 30 September 2026\nReconsider travel"
    assert changed_fragment(old, new) == ""
    assert "Updated: ordered departure" in normalize(
        "Updated: ordered departure\nStand: 29.09.2026"
    )


def test_us_reissue_notes_are_boilerplate():
    old = "There were no changes to the advisory level or risk indicators. Advisory summary was updated.\nAdvisory summary\nExercise normal precautions in Estonia."
    new = "Reissued after periodic review with minor edits.\nAdvisory Summary\nExercise normal precautions in Estonia."
    assert changed_fragment(old, new) == ""
