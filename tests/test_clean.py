from pf_helper.ingest.clean import clean_text


def test_uuid_with_label_keeps_label():
    assert (
        clean_text("Become @UUID[Compendium.pf2e.x.Item.Sickened]{Sickened 2} now")
        == "Become Sickened 2 now"
    )


def test_uuid_without_label_uses_last_segment():
    assert clean_text("See @UUID[Compendium.pf2e.conditionitems.Item.Confused]") == "See Confused"


def test_damage_renders_dice_and_type():
    assert clean_text("deals @Damage[6d6[force]] damage") == "deals 6d6 force damage"


def test_damage_persistent_multitype():
    assert clean_text("@Damage[2d6[persistent,fire]]") == "2d6 persistent fire"


def test_check_with_dc():
    assert clean_text("attempt a @Check[flat|dc:5]") == "attempt a flat check (DC 5)"


def test_check_without_dc():
    assert clean_text("a @Check[performance] check") == "a performance check check"


def test_template_renders_distance_and_shape():
    assert clean_text("a @Template[burst|distance:15] area") == "a 15-foot burst area"


def test_inline_roll_keeps_dice_drops_comment():
    assert clean_text("lasts [[/r 1d4 #rounds]] rounds") == "lasts 1d4 rounds"


def test_strips_html_tags_and_unescapes_entities():
    assert clean_text("<p>You&apos;re <strong>gripped</strong></p>") == "You're gripped"


def test_paragraphs_become_blank_line_separated():
    assert clean_text("<p>One</p><p>Two</p>") == "One\n\nTwo"


def test_list_items_become_bullet_lines():
    assert clean_text("<ul><li>A</li><li>B</li></ul>") == "- A\n- B"


def test_empty_input_returns_empty():
    assert clean_text("") == ""
    assert clean_text("   ") == ""


def test_multiple_enrichers_in_one_string():
    html = "Cast @UUID[Compendium.pf2e.x.Item.Fireball]{Fireball} to deal @Damage[6d6[fire]]"
    assert clean_text(html) == "Cast Fireball to deal 6d6 fire"


def test_damage_parenthesized_formula():
    # Real data has parenthesized/expression formulas, not just bare dice.
    assert clean_text("deals @Damage[(1d10+14)[fire]] damage") == "deals (1d10+14) fire damage"


def test_damage_expression_formula():
    assert clean_text("@Damage[floor(@item.level/2)d6[bludgeoning]]") == (
        "floor(@item.level/2)d6 bludgeoning"
    )
