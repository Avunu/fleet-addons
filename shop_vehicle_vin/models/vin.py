# Copyright 2026 Avunu LLC (avu.nu)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""VIN shape and check-digit rules.

Deliberately free of Odoo imports so the rules can be reasoned about (and
tested) on their own. Nothing here talks to the network -- these checks exist
to avoid spending an API round trip on a VIN that cannot be valid.
"""

# I, O and Q are excluded from VINs precisely because they look like 1 and 0.
VIN_LENGTH = 17
VIN_INVALID_LETTERS = frozenset("IOQ")

# ISO 3779 transliteration for the check-digit calculation.
_TRANSLITERATION = {
    **{str(d): d for d in range(10)},
    "A": 1,
    "B": 2,
    "C": 3,
    "D": 4,
    "E": 5,
    "F": 6,
    "G": 7,
    "H": 8,
    "J": 1,
    "K": 2,
    "L": 3,
    "M": 4,
    "N": 5,
    "P": 7,
    "R": 9,
    "S": 2,
    "T": 3,
    "U": 4,
    "V": 5,
    "W": 6,
    "X": 7,
    "Y": 8,
    "Z": 9,
}
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)
_CHECK_DIGIT_POSITION = 8  # 9th character, zero-indexed


def normalise(vin):
    """Upper-case and strip a VIN. Returns "" for anything empty."""
    return (vin or "").strip().upper().replace(" ", "").replace("-", "")


def has_valid_shape(vin):
    """True if the VIN is 17 characters drawn from the legal alphabet."""
    vin = normalise(vin)
    if len(vin) != VIN_LENGTH:
        return False
    return all(char in _TRANSLITERATION for char in vin)


def check_digit_matches(vin):
    """True if the 9th character matches the ISO 3779 check digit.

    Only meaningful for North American VINs, and even there some
    manufacturers are known not to comply -- so callers should treat a
    mismatch as a prompt to double-check, never as a hard rejection. NHTSA
    itself decodes non-compliant VINs and reports the mismatch as a notice.
    """
    vin = normalise(vin)
    if not has_valid_shape(vin):
        return False
    total = sum(
        _TRANSLITERATION[char] * weight
        for char, weight in zip(vin, _WEIGHTS, strict=False)
    )
    remainder = total % 11
    expected = "X" if remainder == 10 else str(remainder)
    return vin[_CHECK_DIGIT_POSITION] == expected


def describe_problem(vin):
    """Return a human-readable problem with `vin`, or None if it looks fine.

    Ordered most-fundamental first so the message names the thing worth
    fixing rather than a downstream symptom.
    """
    raw = normalise(vin)
    if not raw:
        return "No VIN entered."
    if len(raw) != VIN_LENGTH:
        return f"A VIN is {VIN_LENGTH} characters; this one is {len(raw)}."
    bad_letters = sorted(set(raw) & VIN_INVALID_LETTERS)
    if bad_letters:
        return (
            f"VINs never contain {', '.join(bad_letters)} -- "
            "those are usually a misread 1 or 0."
        )
    if not has_valid_shape(raw):
        illegal = sorted({char for char in raw if char not in _TRANSLITERATION})
        return f"Not a valid VIN character: {', '.join(illegal)}."
    return None
