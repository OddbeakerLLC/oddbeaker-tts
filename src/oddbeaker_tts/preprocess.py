"""
TTS Text Preprocessing

Converts LLM response text into speech-friendly text by:
- Skipping code blocks
- Summarizing tables
- Truncating long lists
- Stripping markdown formatting, emojis, URLs, HTML
- Capping long prose
"""

from __future__ import annotations

import re

# Ordered substitution table for unit expansion.
# Rules: (1) require a preceding number to avoid prose false-positives,
#        (2) specific patterns before general (fl oz before oz, mg before g, km before m).
_UNIT_SUBS: list[tuple[re.Pattern, str]] = [
    # Currency / percentage
    (re.compile(r"\$(\d+(?:\.\d+)?)"), r"\1 dollars"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*%"), r"\1 percent"),
    # Temperature (°F/°C before bare °)
    (re.compile(r"(\d+(?:\.\d+)?)\s*°\s*F\b"), r"\1 degrees Fahrenheit"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*°\s*C\b"), r"\1 degrees Celsius"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*°"), r"\1 degrees"),
    # Volume (fl oz before oz; mL before L)
    (re.compile(r"(\d+(?:\.\d+)?)\s*fl\.?\s*oz\.?", re.I), r"\1 fluid ounces"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*tbsp\.?", re.I), r"\1 tablespoons"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*tsp\.?", re.I), r"\1 teaspoons"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*m[Ll]\b"), r"\1 milliliters"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*gal\.?", re.I), r"\1 gallons"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*qt\.?\b", re.I), r"\1 quarts"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*L\b"), r"\1 liters"),
    # Weight (mg/kg before g; lbs captures lb too)
    (re.compile(r"(\d+(?:\.\d+)?)\s*mg\b", re.I), r"\1 milligrams"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*kg\b", re.I), r"\1 kilograms"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*lbs?\b", re.I), r"\1 pounds"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*oz\.?\b", re.I), r"\1 ounces"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*g\b"), r"\1 grams"),
    # Length / speed
    (re.compile(r"(\d+(?:\.\d+)?)\s*sq\.?\s*ft\.?", re.I), r"\1 square feet"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*sq\.?\s*m\b", re.I), r"\1 square meters"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*mph\b", re.I), r"\1 miles per hour"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*km/h\b", re.I), r"\1 kilometers per hour"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*kph\b", re.I), r"\1 kilometers per hour"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*mm\b", re.I), r"\1 millimeters"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*cm\b", re.I), r"\1 centimeters"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*km\b", re.I), r"\1 kilometers"),
    (re.compile(r"(\d+)'\s*(\d+)\""), r"\1 feet \2 inches"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*ft\.?\b", re.I), r"\1 feet"),
    (re.compile(r"(\d+(?:\.\d+)?)\""), r"\1 inches"),
    (re.compile(r"(\d+(?:\.\d+)?)'"), r"\1 feet"),
    (
        re.compile(
            r"(\d+(?:\.\d+)?)\s*in\.?\b(?!\s+(?:the|a|an|my|your|our|their|this|that|these|those|it|of|for|on|at|to|from|with|by|or|and)\b)"
        ),
        r"\1 inches",
    ),
    (re.compile(r"(\d+(?:\.\d+)?)\s*mi\b", re.I), r"\1 miles"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*yd\.?\b", re.I), r"\1 yards"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*m\b"), r"\1 meters"),
    # File sizes
    (re.compile(r"(\d+(?:\.\d+)?)\s*TB\b"), r"\1 terabytes"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*GB\b"), r"\1 gigabytes"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*MB\b"), r"\1 megabytes"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*KB\b"), r"\1 kilobytes"),
]


def expand_units(text: str) -> str:
    """Expand abbreviated units and symbols to their spoken form."""
    for pattern, replacement in _UNIT_SUBS:
        text = pattern.sub(replacement, text)
    return text


def clean_line_for_speech(line: str) -> str:
    """Strip markdown formatting, emojis, URLs, HTML from a single line."""
    text = line
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # Bold
    text = re.sub(r"\*([^*]+)\*", r"\1", text)  # Italic
    text = re.sub(r"#{1,6}\s+", "", text)  # Headers
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # Links [text](url)
    text = re.sub(r"https?://[^\s]+", "link", text)  # Raw URLs
    text = re.sub(r"`[^`]+`", "", text)  # Inline code
    text = re.sub(r"<[^>]+>", "", text)  # HTML tags
    text = re.sub(
        r"[\U0001F600-\U0001F64F"
        r"\U0001F300-\U0001F5FF"
        r"\U0001F680-\U0001F6FF"
        r"\U0001F1E0-\U0001F1FF"
        r"\U00002600-\U000027BF"
        r"\U00002300-\U000023FF"
        r"\U00002B50"
        r"\U0000FE0F"
        r"\U0000200D"
        r"\U000020E3"
        r"\U000E0020-\U000E007F"
        r"\U0001F900-\U0001F9FF"
        r"\U0001FA00-\U0001FA6F"
        r"\U0001FA70-\U0001FAFF"
        r"\U00002702-\U000027B0]+",
        "",
        text,
    )
    text = expand_units(text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def build_spoken_text(
    text: str, max_prose_chars: int = 800, prose_cutoff: int = 500
) -> str | None:
    """
    Convert LLM response text to speech-friendly text.

    Returns:
        Cleaned text suitable for TTS, or None if nothing to speak.
    """
    blocks = re.split(r"\n{2,}", text)
    spoken = []

    in_code_block = False
    for block in blocks:
        trimmed = block.strip()
        if not trimmed:
            continue

        lines = trimmed.split("\n")

        fence_count = trimmed.count("```")
        if in_code_block:
            if fence_count % 2 == 1:
                in_code_block = False
            continue
        if trimmed.startswith("```"):
            if fence_count % 2 == 1:
                in_code_block = True
            spoken.append("Here's a code snippet.")
            continue

        table_lines = [l for l in lines if l.strip().startswith("|")]
        if len(table_lines) >= 2:
            data_rows = [l for l in table_lines if not re.match(r"^[\s|:\-]+$", l)]
            row_count = max(len(data_rows) - 1, 0)
            spoken.append(f"Here's a table with {row_count} rows.")
            continue

        list_lines = [l for l in lines if re.match(r"^\s*(?:[-*]|\d+\.)\s", l)]
        if len(list_lines) >= 2:
            if len(list_lines) <= 3:
                items = [
                    clean_line_for_speech(re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", l))
                    for l in list_lines
                ]
                spoken.append(". ".join(items) + ".")
            else:
                first = clean_line_for_speech(
                    re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", list_lines[0])
                )
                second = clean_line_for_speech(
                    re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", list_lines[1])
                )
                spoken.append(
                    f"Here are {len(list_lines)} items, including {first}, and {second}."
                )
            continue

        prose = ". ".join(clean_line_for_speech(l) for l in lines)
        if len(prose) > max_prose_chars:
            cutoff = prose[:prose_cutoff]
            last_period = cutoff.rfind(".")
            if last_period > 100:
                spoken.append(prose[: last_period + 1])
            else:
                spoken.append(cutoff + ".")
            spoken.append("You can read the rest on screen.")
        else:
            spoken.append(prose)

    result = " ".join(spoken).strip()
    result = re.sub(r"\.{2,}", ".", result)
    result = re.sub(r"\s{2,}", " ", result)
    return result if result else None
