from pf_helper.ingest.aon_clean import clean_aon


def test_resolves_links_to_label():
    assert clean_aon("See [Aberration](/Traits.aspx?ID=1) now") == "See Aberration now"


def test_strips_title_tag_keeps_name():
    md = '<title level="1" right="Trait">[Aberration](/Traits.aspx?ID=1)</title>'
    assert clean_aon(md) == "Aberration"


def test_drops_self_closing_trait_tags():
    md = '<traits>\n<trait label="Uncommon" url="/x" />\n<trait label="Fire" url="/y" /></traits>'
    assert clean_aon(md) == ""  # traits are captured separately on the Entry


def test_row_column_layout_becomes_lines():
    md = '<row gap="medium"><column>A</column><column>B</column></row>'
    assert clean_aon(md) == "A\nB"


def test_keeps_standard_markdown_emphasis():
    md = "**Source** [Core Rulebook](/Sources.aspx?ID=1) pg. 628"
    assert clean_aon(md) == "**Source** Core Rulebook pg. 628"


def test_empty_returns_empty():
    assert clean_aon("") == ""
    assert clean_aon("   ") == ""


def test_br_becomes_newline():
    assert clean_aon("abilities.<br />**Narakaas** Speed") == "abilities.\n**Narakaas** Speed"


def test_table_cells_become_lines():
    md = (
        "<table><tr><td>Level</td><td>Feature</td></tr>"
        "<tr><td>1</td><td>Alertness</td></tr></table>"
    )
    assert clean_aon(md) == "Level\nFeature\n\n1\nAlertness"


def test_actions_cost_is_preserved():
    assert clean_aon('<actions string="Two Actions" /> command') == "[Two Actions] command"
