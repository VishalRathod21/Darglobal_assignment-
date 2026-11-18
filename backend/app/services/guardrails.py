"""Input and output guardrails.

Defence in depth against prompt injection; no single layer is trusted:
  1. Input screening (here): obvious override attempts never reach the model.
  2. Prompt design (llm/prompts.py): retrieved text is delimited and declared untrusted.
  3. Retrieval gate (retrieval/hybrid.py): off-topic questions get no context and no LLM call.
  4. Output validation (here): citations must point at passages that were actually supplied.
"""
import re

_INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier|your) (instructions|rules|prompts?)",
    r"disregard (all |any |the )?(previous|prior|above|your) (instructions|rules)",
    r"forget (all |everything|your) (previous |prior )?(instructions|rules)?",
    r"(reveal|show|print|repeat|output|what (is|are)) (me )?(your|the) (system|initial|hidden) (prompt|instructions|message)",
    r"\bsystem prompt\b",
    r"you are now\b",
    r"act as (?!a (buyer|tenant|investor))",
    r"pretend (to be|you are)",
    r"\b(jailbreak|dan mode|developer mode)\b",
    r"</?(system|context|instructions?)>",
    r"new instructions?:",
]
_INJECTION = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.I)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CITATION = re.compile(r"\[(\d{1,2})\]")

INJECTION_REPLY = (
    "I can't follow instructions that change how I work or reveal my configuration. "
    "I'm here to answer real estate questions using DarGlobal and Wasalt information. "
    "What would you like to know?"
)
GREETING_REPLY = (
    "Hello! I'm PropIntel AI. I can answer questions about DarGlobal's developments and news, "
    "and about the Wasalt.sa property listings I have indexed. Every answer comes with its sources. "
    "What would you like to know?"
)


def sanitize_question(text: str) -> str:
    return " ".join(_CONTROL_CHARS.sub(" ", text).split())


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))


def validate_citations(answer: str, passage_count: int) -> tuple[str, list[int]]:
    """Remove citation markers that do not correspond to a supplied passage and return the
    valid passage numbers in order of first use. A model that cites [9] when it was given
    six passages is inventing a source; the marker must not reach the user."""
    used: list[int] = []

    def _replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if 1 <= number <= passage_count:
            if number not in used:
                used.append(number)
            return match.group(0)
        return ""

    cleaned = _CITATION.sub(_replace, answer)
    return re.sub(r"[ \t]+([.,;])", r"\1", cleaned).strip(), used
