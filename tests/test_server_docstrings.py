from pf_helper import server


def test_search_docstring_mentions_source_url():
    assert "source_url" in server.search.__doc__
    assert "AON" in server.search.__doc__


def test_get_entry_docstring_mentions_source_url():
    assert "source_url" in server.get_entry.__doc__
