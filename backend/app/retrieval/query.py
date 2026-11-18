"""Query understanding: turn a free-text question into a retrieval plan.

Deliberately rule-based. An LLM call here would be more flexible, but it would double the
number of model calls per question, and the free OpenRouter tier is capped per day. The
vocabulary (cities, property types) is learned from the indexed data, so nothing is hardcoded
to today's scrape.
"""
import re
from dataclasses import dataclass, field

_FOLLOW_UP = re.compile(
    r"\b(it|its|they|them|their|those|these|the same|same one|"
    r"the (first|second|third|last) one|which one|what about|how about)\b",
    re.I,
)
_GREETING = re.compile(r"^\s*(hi|hello|hey|salam|good (morning|afternoon|evening)|thanks|thank you)[\s!.,]*$", re.I)
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "studio": 0}


@dataclass
class QueryPlan:
    question: str  # what the user typed
    search_text: str  # what we actually retrieve with (may include follow-up context)
    is_greeting: bool = False
    source: str | None = None
    city: str | None = None
    property_type: str | None = None
    purpose: str | None = None
    bedrooms: int | None = None
    max_price: float | None = None
    min_price: float | None = None
    filters_relaxed: bool = False
    notes: list[str] = field(default_factory=list)

    def where(self, include_soft: bool = True) -> dict | None:
        """Chroma metadata filter. The source filter is 'hard' (the user named a website);
        the rest are 'soft' and get dropped if they leave too few results."""
        clauses: list[dict] = []
        if self.source:
            clauses.append({"source": self.source})
        if include_soft and self.has_soft_filters():
            if self.city:
                clauses.append({"city": self.city})
            if self.property_type:
                clauses.append({"property_type": self.property_type})
            if self.purpose:
                clauses.append({"purpose": self.purpose})
            if self.bedrooms is not None:
                clauses.append({"bedrooms": self.bedrooms})
            if self.max_price is not None:
                clauses.append({"price": {"$lte": self.max_price}})
            if self.min_price is not None:
                clauses.append({"price": {"$gte": self.min_price}})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    def has_soft_filters(self) -> bool:
        """Filtering only kicks in for constraints embeddings cannot express (numbers, sale vs
        rent). A bare city or property type is left to hybrid search, because filtering on it
        would hide documents that mention the place but carry no city metadata (press releases)."""
        return any(value is not None for value in (self.purpose, self.bedrooms, self.max_price, self.min_price))


def _parse_amount(number: str, unit: str | None) -> float:
    value = float(number.replace(",", ""))
    unit = (unit or "").lower()
    if unit in ("k", "thousand"):
        value *= 1_000
    elif unit in ("m", "mn", "million"):
        value *= 1_000_000
    return value


_AMOUNT = r"(?:sar|sr|riyals?)?\s*([\d][\d,]*(?:\.\d+)?)\s*(k|m|mn|thousand|million)?"


class QueryAnalyzer:
    def __init__(self, cities: set[str], property_types: set[str]) -> None:
        # Longest names first so "Ras Al Khaimah" wins over a shorter overlap.
        self.cities = sorted(cities, key=len, reverse=True)
        self.property_types = sorted(property_types, key=len, reverse=True)

    def analyze(self, question: str, previous_user_question: str | None = None) -> QueryPlan:
        question = " ".join(question.split())
        plan = QueryPlan(question=question, search_text=question)
        if _GREETING.match(question):
            plan.is_greeting = True
            return plan

        # Follow-up handling: short or pronoun-led questions are meaningless on their own
        # ("what about its amenities?"), so retrieval also uses the previous user question.
        if previous_user_question and (len(question.split()) <= 4 or _FOLLOW_UP.search(question)):
            plan.search_text = f"{previous_user_question} {question}"
            plan.notes.append("follow_up_context_added")

        lowered = plan.search_text.lower()
        mentions_dar = bool(re.search(r"\bdar\s?global\b", lowered))
        mentions_wasalt = "wasalt" in lowered
        if mentions_dar != mentions_wasalt:
            plan.source = "darglobal" if mentions_dar else "wasalt"

        for city in self.cities:
            if re.search(rf"\b{re.escape(city.lower())}\b", lowered):
                plan.city = city
                break
        for property_type in self.property_types:
            if re.search(rf"\b{re.escape(property_type.lower())}s?\b", lowered):
                plan.property_type = property_type
                break

        if re.search(r"\b(rent|rental|lease|to let)\b", lowered):
            plan.purpose = "rent"
        elif re.search(r"\b(buy|sale|purchase|for sale)\b", lowered):
            plan.purpose = "sale"

        bedrooms = re.search(r"\b(\d|one|two|three|four|five|six)[\s-]*(?:bed(?:room)?s?|br)\b", lowered)
        if bedrooms:
            token = bedrooms.group(1)
            plan.bedrooms = int(token) if token.isdigit() else _NUMBER_WORDS[token]

        upper = re.search(rf"\b(?:under|below|less than|up to|at most|no more than|max(?:imum)?(?: of)?|cheaper than)\s+{_AMOUNT}", lowered)
        if upper:
            plan.max_price = _parse_amount(upper.group(1), upper.group(2))
        lower = re.search(rf"\b(?:over|above|more than|at least|min(?:imum)?)\s+{_AMOUNT}", lowered)
        if lower:
            plan.min_price = _parse_amount(lower.group(1), lower.group(2))
        return plan
