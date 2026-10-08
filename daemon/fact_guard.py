"""
daemon/fact_guard.py - Fact Guard & Hallucination Verifier for SUBrain_98
Extracts quantitative figures, metrics, and dates from generated markdown,
and cross-verifies them against raw intake text, previous note body, and user prompts.
"""

import re
from typing import List, Dict, Any, Set, Tuple


# Regex pattern to capture metrics, percentages, counts, amounts, ratings, and dates
# e.g., 24.8%, 142명, 1,840만 원, 92%, 4.8/5.0, 3주, 2026년, 10h->5h
NUMBER_TOKEN_PATTERN = re.compile(
    r'(?<!\d)('
    r'\d+(?:,\d+)*(?:\.\d+)?\s*(?:%|명|원|만\s*원|억\s*원|배|개|건|점|회|주차|주|개월|시간|h|p|점수)'
    r'|\d{4}\s*년(?:\s*\d{1,2}\s*월)?(?:\s*\d{1,2}\s*일)?'
    r'|\d{4}[-./]\d{1,2}(?:[-./]\d{1,2})?'
    r'|\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?'
    r')'
)


def normalize_figure(fig: str) -> str:
    """Normalize figure token for robust fuzzy substring matching (strip extra spaces, lowercase)."""
    fig = fig.strip().replace(" ", "").replace(",", "")
    return fig


def extract_figures(text: str) -> List[str]:
    """
    Extract all numerical metric tokens from a markdown string.
    Returns deduplicated list preserving discovery order.
    """
    if not text:
        return []

    # Exclude internal frontmatter IDs (e.g. task_id: DOC-2609-01) from false positive extraction
    cleaned_text = re.sub(r'task_id:\s*[^\n]+', '', text)
    cleaned_text = re.sub(r'aliases:\s*\[[^\n]+\]', '', cleaned_text)

    matches = NUMBER_TOKEN_PATTERN.findall(cleaned_text)
    seen: Set[str] = set()
    result: List[str] = []

    for m in matches:
        m_str = m.strip()
        # Filter out trivial bare years if too isolated or small page numbers
        if m_str and m_str not in seen:
            seen.add(m_str)
            result.append(m_str)

    return result


def extract_raw_source_text(markdown_content: str) -> str:
    """
    Extract raw text from '> [!QUOTE] 원문 맥락 창고' block in the note.
    """
    if not markdown_content:
        return ""
    
    quote_match = re.search(
        r'>\s*\[!QUOTE\][^\n]*\n((?:>.*(?:\n|$))+)',
        markdown_content,
        re.IGNORECASE
    )
    if quote_match:
        lines = quote_match.group(1).splitlines()
        cleaned_lines = [re.sub(r'^>\s?', '', line) for line in lines]
        return "\n".join(cleaned_lines)
    
    return ""


def verify_figures(
    target_text: str,
    raw_sources: List[str]
) -> Dict[str, Any]:
    """
    Verify all figures in target_text against a list of raw source texts.
    Returns:
    {
        "total_count": int,
        "verified": List[str],
        "unverified": List[str],
        "is_clean": bool,
        "warning_message": str
    }
    """
    target_figs = extract_figures(target_text)
    if not target_figs:
        return {
            "total_count": 0,
            "verified": [],
            "unverified": [],
            "is_clean": True,
            "warning_message": "정량 수치 없음 (정성 서술)"
        }

    # Build normalized corpus from all sources
    raw_corpus = " ".join(raw_sources or [])
    norm_corpus = raw_corpus.replace(" ", "").replace(",", "").lower()

    verified: List[str] = []
    unverified: List[str] = []

    for fig in target_figs:
        norm_fig = normalize_figure(fig).lower()
        # Look for raw numbers without unit as well (e.g. 142 in raw text vs 142명 in target)
        num_only = re.search(r'\d+(?:\.\d+)?', norm_fig)

        found = False
        if norm_fig in norm_corpus:
            found = True
        elif num_only and len(num_only.group(0)) >= 2 and num_only.group(0) in norm_corpus:
            found = True

        if found:
            verified.append(fig)
        else:
            unverified.append(fig)

    is_clean = len(unverified) == 0
    warning_message = ""
    if not is_clean:
        unv_preview = ", ".join(unverified[:4])
        warning_message = f"원문에 명시되지 않은 수치 {len(unverified)}건 감지 ({unv_preview})"

    return {
        "total_count": len(target_figs),
        "verified": verified,
        "unverified": unverified,
        "is_clean": is_clean,
        "warning_message": warning_message
    }
