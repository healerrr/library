import hashlib
import re
import unicodedata
from difflib import SequenceMatcher


WHITESPACE_RE = re.compile(r"\s+")
NON_CONTENT_RE = re.compile(r"[^0-9a-z\u3400-\u9fff]+", re.IGNORECASE)
CHEMICAL_FIELD_RE = re.compile(
    r"(?i)(?:CAS(?:\s*(?:No\.?|号))?|分子式|Molecular\s*Formula|"
    r"分子量|Molecular\s*Weight|Mol\.?\s*Wt\.?|规格(?:参数)?|Specification|"
    r"纯度|Purity)\s*[:：]?\s*[^\n；;。]{1,100}"
)
CAS_RE = re.compile(r"(?<!\d)\d{2,7}-\d{2}-\d(?!\d)")
SPEC_RE = re.compile(r"(?<!\w)(?:≥|>|≤|<)?\s*\d{1,3}(?:\.\d+)?\s*%(?!\w)")


def clean_display_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", unicodedata.normalize("NFKC", value)).strip()


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    return NON_CONTENT_RE.sub("", value)


def content_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def strip_chemical_fields(value: str) -> tuple[str, float]:
    normalized = normalize_text(value)
    if not normalized:
        return "", 0.0

    stripped = CHEMICAL_FIELD_RE.sub(" ", value)
    stripped = CAS_RE.sub(" ", stripped)
    stripped = SPEC_RE.sub(" ", stripped)
    core = normalize_text(stripped)
    ratio = max(0.0, min(1.0, 1 - (len(core) / len(normalized))))
    return core, ratio


def embedding_text(value: str) -> str:
    core, _ = strip_chemical_fields(value)
    return core if len(core) >= 3 else normalize_text(value)


def character_ngrams(value: str, size: int = 3) -> set[str]:
    text = normalize_text(value)
    if not text:
        return set()
    if len(text) < size:
        return {text}
    return {text[index : index + size] for index in range(len(text) - size + 1)}


def jaccard_similarity(left: str, right: str, size: int = 3) -> float:
    left_set = character_ngrams(left, size)
    right_set = character_ngrams(right, size)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def lexical_similarity(left: str, right: str, chemical_discount: float) -> tuple[float, float]:
    full_score = jaccard_similarity(left, right)
    left_core, left_ratio = strip_chemical_fields(left)
    right_core, right_ratio = strip_chemical_fields(right)
    chemical_overlap = min(left_ratio, right_ratio)
    discounted_full = full_score * (1 - chemical_discount * chemical_overlap)
    core_score = jaccard_similarity(left_core, right_core) if left_core and right_core else 0.0
    return max(discounted_full, core_score), chemical_overlap


def highlight_segments(query: str, original: str, min_match: int = 3) -> list[dict]:
    if not original:
        return []

    matcher = SequenceMatcher(None, query.lower(), original.lower(), autojunk=False)
    matched_positions = [False] * len(original)
    for block in matcher.get_matching_blocks():
        if block.size < min_match:
            continue
        for index in range(block.b, min(block.b + block.size, len(original))):
            matched_positions[index] = True

    segments: list[dict] = []
    start = 0
    current = matched_positions[0]
    for index in range(1, len(original)):
        if matched_positions[index] != current:
            segments.append({"text": original[start:index], "matched": current})
            start = index
            current = matched_positions[index]
    segments.append({"text": original[start:], "matched": current})
    return segments

