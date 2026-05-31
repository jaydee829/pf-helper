import time

from pf_helper.answer.base import Answer
from pf_helper.answer.cache import AnswerCache, _content_tokens, _jaccard, _stem, normalize_question


def test_normalize_collides_phrasings():
    a = normalize_question("How does flanking work?")
    b = normalize_question("  how does Flanking work ?? ")
    c = normalize_question("how does flanking work")
    assert a == b == c == "how does flanking work"


def _cache(tmp_path):
    index = tmp_path / "pf2e.db"
    index.write_text("v1")  # stand-in index file for versioning
    return AnswerCache(tmp_path / "ask_cache.db", index, ttl_days=30, max_rows=3), index


def test_put_then_get_hit(tmp_path):
    cache, _ = _cache(tmp_path)
    cache.put("How does flanking work?", Answer("Flank text", [("Flanking", "https://x")], "agent"))
    hit = cache.get("how does flanking work")  # different phrasing, same norm
    assert hit is not None
    assert hit.text == "Flank text"
    assert hit.sources == [("Flanking", "https://x")]
    assert hit.engine == "cache"


def test_miss_returns_none(tmp_path):
    cache, _ = _cache(tmp_path)
    assert cache.get("never asked") is None


def test_index_version_busts(tmp_path):
    cache, index = _cache(tmp_path)
    cache.put("q", Answer("ans", [("n", "u")]))
    index.write_text("v2-changed-bigger")  # mtime + size change -> new version
    assert cache.get("q") is None


def test_ttl_expiry(tmp_path):
    cache, _ = _cache(tmp_path)
    cache.put("q", Answer("ans", [("n", "u")]))
    cache._conn.execute("UPDATE answers SET created_at = ?", (time.time() - 31 * 86400,))
    cache._conn.commit()
    assert cache.get("q") is None


def test_size_cap_evicts_oldest(tmp_path):
    cache, _ = _cache(tmp_path)  # max_rows=3
    for i in range(5):
        cache.put(f"q{i}", Answer(f"a{i}", [("n", "u")]))
        time.sleep(0.01)
    rows = cache._conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
    assert rows == 3
    assert cache.get("q0") is None  # oldest evicted
    assert cache.get("q4") is not None  # newest kept


def test_stem_is_crude_but_consistent():
    assert _stem("flanking") == "flank"
    assert _stem("flank") == "flank"
    assert _stem("creatures") == _stem("creatures")  # deterministic
    assert _stem("is") == "is"  # short tokens untouched


def test_content_tokens_drop_stopwords_and_framing():
    assert _content_tokens("How does flanking work?") == {"flank"}
    assert _content_tokens("When am I flanking again?") == {"flank"}
    assert _content_tokens("What is flanking?") == {"flank"}
    assert _content_tokens("What are the rules for flanking?") == {"flank"}


def test_content_tokens_keep_salient_nouns():
    assert _content_tokens("can tiny creatures flank") == {"tiny", "creature", "flank"}


def test_jaccard():
    assert _jaccard({"flank"}, {"flank"}) == 1.0
    assert _jaccard({"flank", "tiny", "creature"}, {"flank"}) == 1 / 3
    assert _jaccard(set(), set()) == 0.0
