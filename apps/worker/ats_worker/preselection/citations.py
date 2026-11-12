"""Lossless, provider-free source block indexing for bounded citations."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Literal


CITATION_INDEX_VERSION = "source-block-index-v1"
MAX_CITATION_BLOCK_CHARS = 1000
CitationSource = Literal["jd", "candidate_context"]
SectionKind = Literal["duty", "qualification", "unknown"]
HeadingStrength = Literal["required", "preferred", "unknown"]


class CitationIndexError(ValueError):
    """A source index or citation reference is malformed."""


@dataclass(frozen=True)
class CitationBlock:
    source: CitationSource
    id: str
    start: int
    end: int
    text: str
    section_kind: SectionKind
    heading_strength: HeadingStrength
    citable: bool


@dataclass(frozen=True)
class CitationIndex:
    """Lossless bounded blocks with local-only spans and section provenance."""

    job_description: str
    candidate_context: str
    jd_blocks: tuple[CitationBlock, ...]
    candidate_context_blocks: tuple[CitationBlock, ...]
    version: str = CITATION_INDEX_VERSION

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.version != CITATION_INDEX_VERSION:
            raise CitationIndexError("citation index version is unsupported")
        if type(self.job_description) is not str or type(self.candidate_context) is not str:
            raise CitationIndexError("citation source text must be strings")
        self._validate_source("jd", self.job_description, self.jd_blocks)
        self._validate_source("candidate_context", self.candidate_context, self.candidate_context_blocks)

    @staticmethod
    def _validate_source(
        source: CitationSource,
        source_text: str,
        blocks: tuple[CitationBlock, ...],
    ) -> None:
        if type(blocks) is not tuple:
            raise CitationIndexError("citation blocks must be an immutable tuple")
        prefix = "J" if source == "jd" else "C"
        cursor = 0
        for index, block in enumerate(blocks):
            if type(block) is not CitationBlock:
                raise CitationIndexError("citation block has an invalid type")
            if (
                block.source != source
                or type(block.id) is not str
                or block.id != f"{prefix}{index:04d}"
                or type(block.text) is not str
                or type(block.section_kind) is not str
                or type(block.heading_strength) is not str
                or type(block.start) is not int
                or type(block.end) is not int
                or block.start != cursor
                or block.end <= block.start
                or block.end - block.start != len(block.text)
                or block.end - block.start > MAX_CITATION_BLOCK_CHARS
                or type(block.citable) is not bool
                or block.section_kind not in {"duty", "qualification", "unknown"}
                or block.heading_strength not in {"required", "preferred", "unknown"}
                or source_text[block.start:block.end] != block.text
                or (block.citable and not block.text.strip())
            ):
                raise CitationIndexError("citation block does not match its exact source span")
            cursor = block.end
        if cursor != len(source_text) or "".join(block.text for block in blocks) != source_text:
            raise CitationIndexError("citation blocks do not reconstruct the complete source")

    def blocks_for(self, source: CitationSource) -> tuple[CitationBlock, ...]:
        if source == "jd":
            return self.jd_blocks
        if source == "candidate_context":
            return self.candidate_context_blocks
        raise CitationIndexError("citation source is unsupported")

    def citable_blocks_for(self, source: CitationSource) -> tuple[CitationBlock, ...]:
        return tuple(block for block in self.blocks_for(source) if block.citable)

    def citable_ids_for(self, source: CitationSource) -> tuple[str, ...]:
        return tuple(block.id for block in self.citable_blocks_for(source))

    def lookup(self, source: CitationSource, block_id: str) -> CitationBlock:
        if type(block_id) is not str:
            raise CitationIndexError("citation ID is invalid")
        for block in self.blocks_for(source):
            if block.id == block_id:
                return block
        raise CitationIndexError("citation ID is not present in the selected source")

    def resolve(self, source: CitationSource, block_id: str) -> CitationBlock:
        block = self.lookup(source, block_id)
        if not block.citable:
            raise CitationIndexError("citation ID refers to a noncitable source block")
        return block

    def model_blocks(self, source: CitationSource) -> list[dict[str, str]]:
        """Return exact lossless source blocks; citation IDs are filtered separately."""
        return [
            {"id": block.id, "section": block.section_kind, "text": block.text}
            for block in self.blocks_for(source)
        ]


_DUTY_HEADINGS = frozenset({
    "responsibilities",
    "key responsibilities",
    "primary responsibilities",
    "primary duties and responsibilities",
    "essential duties",
    "what youll do",
    "what you will do",
    "what you will work on",
    "your impact",
    "your core responsibilities",
    "role overview",
    "position summary",
    "the role",
    "about the role",
    "job overview",
    "in this role you will",
})
_QUALIFICATION_HEADINGS = frozenset({
    "qualifications",
    "minimum qualifications",
    "preferred qualifications",
    "required qualifications",
    "requirements",
    "minimum requirements",
    "what were looking for",
    "what we look for",
    "what youll bring",
    "what you will bring",
    "who you are",
    "skills and experience",
    "successful characteristics skills",
    "core technical proficiency",
    "experience background",
    "position qualifications",
    "basic qualifications",
    "preferred skills and experience",
    "required qualifications skills",
})
_UNKNOWN_HEADINGS = frozenset({
    "job description",
    "company",
    "company overview",
    "about",
    "about us",
    "about the company",
    "our company",
    "who we are",
    "benefits",
    "benefits and perks",
    "perks",
    "what we offer",
})


def _heading_text(line: str) -> str:
    heading = line.strip()
    heading = re.sub(r"^\s{0,3}#{1,6}\s*", "", heading)
    heading = re.sub(r"^\s*>\s*", "", heading)
    heading = re.sub(r"^(?:\*\*|__|~~|`{1,3}|\*|_)+", "", heading)
    heading = re.sub(r"(?:\*\*|__|~~|`{1,3}|\*|_)+$", "", heading)
    heading = heading.rstrip("\r\n").strip()
    normalized: list[str] = []
    for char in heading.casefold():
        if char in {"'", "’", "‘", "ʼ"}:
            continue
        if unicodedata.category(char).startswith("P"):
            normalized.append(" ")
        else:
            normalized.append(char)
    return " ".join("".join(normalized).split())


def _heading_metadata(line: str) -> tuple[SectionKind, HeadingStrength] | None:
    normalized = _heading_text(line)
    if normalized in _DUTY_HEADINGS:
        return "duty", "unknown"
    if normalized in _QUALIFICATION_HEADINGS:
        if normalized.startswith(("required ", "minimum ", "basic ")):
            strength: HeadingStrength = "required"
        elif normalized.startswith("preferred "):
            strength = "preferred"
        else:
            strength = "unknown"
        return "qualification", strength
    is_generic_unknown = (
        normalized in _UNKNOWN_HEADINGS
        or (
            not line.rstrip("\r\n").strip().endswith((".", "?", "!", ";"))
            and normalized.startswith(("about ", "company ", "our company ", "benefits ", "perks "))
        )
    )
    if is_generic_unknown:
        return "unknown", "unknown"
    visible_line = line.rstrip("\r\n").strip()
    has_letters = any(char.isalpha() for char in visible_line)
    explicit_heading_marker = (
        re.match(r"^#{1,6}", visible_line) is not None
        or visible_line.startswith("> ")
        or visible_line.endswith(":")
        or (
            visible_line.startswith(("**", "__", "~~", "`"))
            and visible_line.endswith(("**", "__", "~~", "`"))
        )
        or (
            has_letters
            and len(visible_line.split()) >= 2
            and visible_line == visible_line.upper()
            and not visible_line.endswith((".", "?", "!", ";"))
        )
    )
    if explicit_heading_marker:
        return "unknown", "unknown"
    return None


def _line_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        end = cursor + len(line)
        spans.append((cursor, end))
        cursor = end
    if cursor < len(text):
        spans.append((cursor, len(text)))
    return spans


def _split_ranges(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split a source span at whitespace where possible, preserving each character."""
    ranges: list[tuple[int, int]] = []
    cursor = start
    while end - cursor > MAX_CITATION_BLOCK_CHARS:
        limit = cursor + MAX_CITATION_BLOCK_CHARS
        boundary = max(
            (index for index in range(cursor + 1, limit) if text[index].isspace()),
            default=-1,
        )
        next_cursor = boundary + 1 if boundary > cursor else limit
        ranges.append((cursor, next_cursor))
        cursor = next_cursor
    if cursor < end:
        ranges.append((cursor, end))
    return ranges


def _make_blocks(
    source: CitationSource,
    text: str,
    *,
    candidate_background_span: tuple[int, int] | None = None,
) -> tuple[CitationBlock, ...]:
    prefix = "J" if source == "jd" else "C"
    blocks: list[CitationBlock] = []
    pending_start: int | None = None
    pending_end: int | None = None
    pending_kind: SectionKind = "unknown"
    pending_strength: HeadingStrength = "unknown"
    section_kind: SectionKind = "unknown"
    heading_strength: HeadingStrength = "unknown"

    def flush_pending() -> None:
        nonlocal pending_start, pending_end
        if pending_start is None or pending_end is None:
            return
        block_text = text[pending_start:pending_end]
        blocks.append(CitationBlock(
            source,
            f"{prefix}{len(blocks):04d}",
            pending_start,
            pending_end,
            block_text,
            pending_kind,
            pending_strength,
            True,
        ))
        pending_start = None
        pending_end = None

    def append_non_citable(start: int, end: int, kind: SectionKind, strength: HeadingStrength) -> None:
        for chunk_start, chunk_end in _split_ranges(text, start, end):
            blocks.append(CitationBlock(
                source,
                f"{prefix}{len(blocks):04d}",
                chunk_start,
                chunk_end,
                text[chunk_start:chunk_end],
                kind,
                strength,
                False,
            ))

    def append_citable(start: int, end: int, kind: SectionKind, strength: HeadingStrength) -> None:
        nonlocal pending_start, pending_end, pending_kind, pending_strength
        chunk_text = text[start:end]
        if not chunk_text.strip():
            flush_pending()
            append_non_citable(start, end, kind, strength)
        elif pending_start is not None and (
            pending_end == start
            and pending_kind == kind
            and pending_strength == strength
            and end - pending_start <= MAX_CITATION_BLOCK_CHARS
        ):
            pending_end = end
        else:
            flush_pending()
            pending_start = start
            pending_end = end
            pending_kind = kind
            pending_strength = strength

    for line_start, line_end in _line_spans(text):
        line = text[line_start:line_end]
        if source == "jd":
            heading = _heading_metadata(line)
        else:
            heading = None
        if heading is not None:
            flush_pending()
            section_kind, heading_strength = heading
            append_non_citable(line_start, line_end, section_kind, heading_strength)
            continue

        if source == "candidate_context":
            background_start, background_end = candidate_background_span or (-1, -1)
            candidate_citable = (
                line_start >= background_start
                and line_end <= background_end
                and background_start >= 0
            )
        else:
            candidate_citable = True

        if not line.strip() or not candidate_citable:
            flush_pending()
            append_non_citable(line_start, line_end, section_kind, heading_strength)
            continue

        for chunk_start, chunk_end in _split_ranges(text, line_start, line_end):
            if candidate_citable:
                append_citable(chunk_start, chunk_end, section_kind, heading_strength)
            else:
                flush_pending()
                append_non_citable(chunk_start, chunk_end, section_kind, heading_strength)
        flush_pending()

    flush_pending()
    return tuple(blocks)


def _candidate_background_span(text: str) -> tuple[int, int] | None:
    """Find the canonical rendered-profile BACKGROUND body conservatively."""
    spans = _line_spans(text)
    if len(spans) < 3:
        return None
    first = text[spans[0][0]:spans[0][1]].strip()
    second = text[spans[1][0]:spans[1][1]].strip()
    if re.fullmatch(r"AS OF \d{4}-\d{2}-\d{2}", first) is None or second != "BACKGROUND":
        return None
    search_lines = [
        (start, end)
        for start, end in spans[2:]
        if text[start:end].strip() == "SEARCH"
    ]
    # A source paragraph equal to SEARCH makes the body/header boundary ambiguous.
    if len(search_lines) != 1:
        return None
    search_start, _search_end = search_lines[0]
    background_start = spans[1][1]
    if background_start > search_start:
        return None
    return background_start, search_start


def build_citation_index(job_description: str, candidate_context: str) -> CitationIndex:
    """Index whole source strings losslessly; no provider, file or runtime access."""
    if type(job_description) is not str or type(candidate_context) is not str:
        raise CitationIndexError("citation sources must be strings")
    return CitationIndex(
        job_description,
        candidate_context,
        _make_blocks("jd", job_description),
        _make_blocks(
            "candidate_context",
            candidate_context,
            candidate_background_span=_candidate_background_span(candidate_context),
        ),
    )
