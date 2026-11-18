import pytest

from app.retrieval.bm25 import BM25Index, tokenize
from app.retrieval.hybrid import reciprocal_rank_fusion
from app.retrieval.query import QueryAnalyzer
from tests.conftest import make_chunk


@pytest.fixture
def analyzer() -> QueryAnalyzer:
    return QueryAnalyzer(cities={"Riyadh", "Jeddah", "Dubai", "Ras Al Khaimah"}, property_types={"Apartment", "Villa"})


def test_rrf_rewards_agreement_between_retrievers():
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["b", "d", "a"]], k=60)
    ranked = sorted(scores, key=scores.get, reverse=True)
    assert ranked[:2] == ["b", "a"]  # in both lists
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["c"] == pytest.approx(1 / 63)  # only in one list


def test_tokenize_removes_stopwords_and_keeps_arabic():
    assert tokenize("What is the price of DG1 in Dubai?") == ["price", "dg1", "dubai"]
    assert tokenize("حي المهدية") == ["حي", "المهدية"]


def test_bm25_finds_exact_names_and_respects_filter():
    chunks = [
        make_chunk("a#0", text="DG1 residential tower in Business Bay Dubai"),
        make_chunk("b#0", text="Les Vagues by Elie Saab beachfront residences in Doha"),
        make_chunk("c#0", text="Aida clifftop community in Muscat Oman"),
    ]
    index = BM25Index(chunks)
    assert index.search("Elie Saab", 5)[0][0] == "b#0"
    assert index.search("Elie Saab", 5, allowed_ids={"a#0", "c#0"}) == []
    assert index.search("the of and", 5) == []  # only stopwords
    assert BM25Index([]).search("anything", 5) == []


def test_source_detection(analyzer):
    assert analyzer.analyze("What projects does Dar Global have?").source == "darglobal"
    assert analyzer.analyze("listings on Wasalt").source == "wasalt"
    assert analyzer.analyze("compare DarGlobal and Wasalt").source is None
    assert analyzer.analyze("luxury villas").source is None


def test_structured_filters(analyzer):
    plan = analyzer.analyze("3 bedroom apartments for sale in Riyadh under 800k SAR")
    assert (plan.city, plan.property_type, plan.purpose, plan.bedrooms, plan.max_price) == (
        "Riyadh", "Apartment", "sale", 3, 800_000.0,
    )
    where = plan.where()
    assert {"bedrooms": 3} in where["$and"] and {"price": {"$lte": 800_000.0}} in where["$and"]

    plan = analyzer.analyze("two-bed villas to rent above 1.5 million")
    assert (plan.bedrooms, plan.purpose, plan.min_price, plan.property_type) == (2, "rent", 1_500_000.0, "Villa")


def test_city_alone_is_not_a_hard_filter(analyzer):
    """A bare place name must not hide documents without city metadata (e.g. press releases)."""
    plan = analyzer.analyze("What did DarGlobal announce in Jeddah?")
    assert plan.city == "Jeddah" and not plan.has_soft_filters()
    assert plan.where() == {"source": "darglobal"}
    assert analyzer.analyze("tell me about Ras Al Khaimah").where() is None


def test_follow_up_adds_previous_question(analyzer):
    plan = analyzer.analyze("what about its amenities?", previous_user_question="Tell me about DG1 in Dubai")
    assert plan.search_text == "Tell me about DG1 in Dubai what about its amenities?"
    assert plan.question == "what about its amenities?" and plan.city == "Dubai"
    standalone = analyzer.analyze(
        "Which DarGlobal developments are located in Oman?", previous_user_question="Tell me about DG1"
    )
    assert standalone.search_text == standalone.question


def test_greeting(analyzer):
    assert analyzer.analyze("Hello!").is_greeting
    assert not analyzer.analyze("Hello, what is DG1?").is_greeting
