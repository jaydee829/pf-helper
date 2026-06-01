from pf_helper.answer.tools import get_entry_payload, search_payload
from pf_helper.models import EntryDetail, SearchHit


class FakeRetriever:
    def __init__(self, hits, details):
        self._hits, self._details = hits, details

    def search(self, query, category, limit):
        return self._hits

    def get(self, name, category):
        return self._details.get(name)


def test_search_payload_collects_sources():
    hit = SearchHit(id="spell:heal", name="Heal", category="spell", excerpt="h",
                    source_url="https://x/Heal")
    sources = {}
    out = search_payload(FakeRetriever([hit], {}), sources, "heal", "")
    assert out == [
        {"name": "Heal", "category": "spell", "source_url": "https://x/Heal", "excerpt": "h"}
    ]
    assert sources == {"Heal": "https://x/Heal"}


def test_get_entry_payload_and_miss():
    d = EntryDetail(id="spell:heal", name="Heal", category="spell", text="Heal a creature.",
                    source_url="https://x/Heal")
    sources = {}
    r = FakeRetriever([], {"Heal": d})
    assert get_entry_payload(r, sources, "Heal", "spell")["text"] == "Heal a creature."
    assert sources == {"Heal": "https://x/Heal"}
    assert get_entry_payload(r, sources, "Nope", None) is None
