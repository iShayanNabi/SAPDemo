"""Obligation extraction.

An obligation is a sentence that imposes a duty: it carries ``shall``,
``must``, ``agrees to`` or one of the other configured duty verbs. The sentence
is kept **verbatim** as its own evidence, because a paraphrased obligation is
an obligation nobody can rely on.

The owing party is attributed only when the sentence actually names a party or
a role. When it does not, ``party`` stays ``None`` rather than being guessed -
"the supplier shall" and "the parties shall" mean very different things to
whoever has to act on the list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.modules.contract_assistant.clauses import SourceReference
from app.modules.contract_assistant.segmentation import DocumentIndex
from app.modules.contract_assistant.thresholds import ContractAssistantConfig

logger = get_logger(__name__)

__all__ = ["Obligation", "extract_obligations"]

#: Sentence splitter. Abbreviations common in contracts are protected so
#: "Sec. 4.2" or "e.g. the Supplier" does not split a sentence in half.
_PROTECTED = (
    ("No.", "No\x01"),
    ("Sec.", "Sec\x01"),
    ("Art.", "Art\x01"),
    ("e.g.", "e\x01g\x01"),
    ("i.e.", "i\x01e\x01"),
    ("Inc.", "Inc\x01"),
    ("Ltd.", "Ltd\x01"),
    ("etc.", "etc\x01"),
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")
_WHITESPACE = re.compile(r"\s+")


@dataclass
class Obligation:
    """One duty found in the contract."""

    obligation_id: str
    text: str
    party: str | None
    party_role: str | None
    duty_type: str
    is_prohibition: bool
    clause_type: str | None
    reference: SourceReference

    def to_dict(self) -> dict[str, Any]:
        return {
            "obligation_id": self.obligation_id,
            "text": self.text,
            "party": self.party,
            "party_role": self.party_role,
            "duty_type": self.duty_type,
            "is_prohibition": self.is_prohibition,
            "clause_type": self.clause_type,
            "page_number": self.reference.page_number,
            "section_heading": self.reference.section_heading,
            "excerpt": self.reference.excerpt,
            "confidence": round(float(self.reference.confidence), 3),
            "reference": self.reference.to_dict(),
        }


def extract_obligations(
    index: DocumentIndex,
    config: ContractAssistantConfig,
    *,
    party_names: list[str] | None = None,
    clause_spans: dict[str, list[tuple[int, int]]] | None = None,
) -> list[Obligation]:
    """Extract the duty sentences from an indexed contract.

    Args:
        index: The indexed document.
        config: The validated module configuration.
        party_names: Party names already extracted from the document, used to
            attribute an obligation to a named entity.
        clause_spans: Optional ``clause_type -> [(start, end)]`` map, used to
            say which clause an obligation belongs to.
    """
    settings = config.obligations
    obligations: list[Obligation] = []
    seen: set[str] = set()

    for start, sentence in _iter_sentences(index):
        if len(sentence) > settings.max_chars:
            sentence = sentence[: settings.max_chars].rstrip() + "…"
        if len(sentence.split()) < settings.min_words:
            continue
        if not any(pattern.search(sentence) for pattern in settings.modals):
            continue

        key = sentence.lower()[:160]
        if key in seen:
            continue
        seen.add(key)

        section = index.section_for(start)
        page_number = index.page_for(start)
        party, role = _attribute(sentence, config, party_names or [])
        reference = SourceReference(
            page_number=page_number,
            section_heading=section.label if section else None,
            section_number=section.number if section else None,
            excerpt=sentence,
            # An obligation is a literal quotation of the document, so the only
            # uncertainty left is whether the sentence really is a duty. A
            # sentence naming its party is the stronger signal.
            confidence=config.confidence.score(
                heading_match=section is not None,
                primary_hits=1,
                secondary_hits=1 if party else 0,
                value_extracted=False,
                scattered=False,
            ),
            char_offset=start,
        )
        obligations.append(
            Obligation(
                obligation_id=f"OB-{len(obligations) + 1:03d}",
                text=sentence,
                party=party,
                party_role=role,
                duty_type=_duty_type(sentence, config),
                is_prohibition=any(
                    pattern.search(sentence) for pattern in settings.negatives
                ),
                clause_type=_clause_for(start, clause_spans or {}),
                reference=reference,
            )
        )
        if len(obligations) >= settings.max_obligations:
            logger.info(
                "Obligation extraction stopped at the configured limit of %d",
                settings.max_obligations,
            )
            break

    return obligations


def _iter_sentences(index: DocumentIndex):
    """Yield ``(offset, sentence)`` pairs, one section at a time.

    Splitting section by section is what keeps a heading out of the obligation
    beneath it. PDF extraction discards blank lines, so ``3. TERMINATION`` and
    the sentence that follows it arrive as one run of text; without the section
    boundary every obligation would be quoted with its heading glued to the
    front.
    """
    for start, end in _blocks(index):
        block = index.text[start:end]
        # The heading line itself is not a sentence.
        newline = block.find("\n")
        if newline != -1 and index.section_for(start) is not None:
            start, block = start + newline + 1, block[newline + 1 :]

        protected = block
        for original, placeholder in _PROTECTED:
            protected = protected.replace(original, placeholder)

        cursor = start
        for raw in _SENTENCE_SPLIT.split(protected):
            offset = cursor
            cursor += len(raw) + 1
            restored = raw
            for original, placeholder in _PROTECTED:
                restored = restored.replace(placeholder, original)
            sentence = _WHITESPACE.sub(" ", restored).strip()
            if sentence:
                yield offset, sentence


def _blocks(index: DocumentIndex) -> list[tuple[int, int]]:
    """The document split into the text before the first section, then sections."""
    if not index.sections:
        return [(0, len(index.text))]
    spans = [(section.start, section.end) for section in index.sections]
    first_start = spans[0][0]
    if first_start > 0:
        spans.insert(0, (0, first_start))
    return spans


def _attribute(
    sentence: str, config: ContractAssistantConfig, party_names: list[str]
) -> tuple[str | None, str | None]:
    """Work out which party owes a duty, or return ``(None, None)``."""
    lowered = sentence.lower()

    # A named party wins: it is the least ambiguous attribution available.
    for name in party_names:
        if name and name.lower() in lowered:
            role = _role_for_name(lowered, name, config)
            return name, role

    for role, patterns in config.document.roles.items():
        if any(pattern.search(sentence) for pattern in patterns):
            return None, role

    if re.search(r"\bthe\s+parties\b|\beach\s+party\b|\bboth\s+parties\b", lowered):
        return None, "both"
    return None, None


def _role_for_name(
    lowered: str, name: str, config: ContractAssistantConfig
) -> str | None:
    """Return the role a named party plays in this sentence, when stated."""
    for role, patterns in config.document.roles.items():
        if any(pattern.search(lowered) for pattern in patterns):
            return role
    return None


def _duty_type(sentence: str, config: ContractAssistantConfig) -> str:
    """Classify the duty against the configured duty-type vocabulary."""
    best: tuple[int, str] = (0, "general")
    for name, patterns in config.obligations.duty_types.items():
        hits = sum(1 for pattern in patterns if pattern.search(sentence))
        if hits > best[0]:
            best = (hits, name)
    return best[1]


def _clause_for(offset: int, clause_spans: dict[str, list[tuple[int, int]]]) -> str | None:
    """Return the clause type whose span contains ``offset``."""
    for clause_type, spans in clause_spans.items():
        for start, end in spans:
            if start <= offset < end:
                return clause_type
    return None
