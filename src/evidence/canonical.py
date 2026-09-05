"""Deterministic JSON serialization.

The whole project rests on one property: hashing the same logical evidence must
produce the same bytes, on any machine, on any run, after any number of
JSON round-trips. If that fails, `verify` reports a mismatch that has nothing to
do with tampering and the demo dies on stage.

Python's `json.dumps` is not sufficient on its own. Three things break it:

  * key order is insertion order, not sorted
  * default separators inject whitespace
  * floats serialize via `repr`, whose output is shortest-round-trip and so
    depends on the exact binary value - 0.1 + 0.2 prints as 0.30000000000000004

The third is the dangerous one, because a cosine similarity is a float computed
from a model whose last bits are not stable across BLAS versions or CPUs.

We therefore quantize every float to a fixed number of decimal places before it
is ever serialized, and emit it with fixed formatting. The resulting text is
stable under re-parsing, which is the property `verify` actually needs:

    canonical(json.loads(canonical(x))) == canonical(x)

This is RFC 8785 (JCS) in spirit - sorted keys, no whitespace, UTF-8 - but with
fixed-precision numbers instead of JCS's ES6 number formatting. That is a
deliberate deviation: full ES6 formatting would preserve every last bit of a
float we explicitly do not trust to be reproducible. Tests in
tests/test_canonical.py pin the behaviour.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any

# Decimal places retained for every float in an evidence bundle.
#
# Six is far finer than any decision we make - the match threshold is compared
# at two decimals - while staying well inside the range where a float32 model
# output is reproducible across machines.
FLOAT_PRECISION = 6


class NonCanonicalizable(ValueError):
    """A value cannot be represented deterministically."""


def _quantize(value: float) -> Decimal:
    """Round a float to FLOAT_PRECISION decimal places.

    Returns a Decimal so that serialization does not route back through binary
    floating point, which is what would reintroduce the noise we just removed.
    """
    if math.isnan(value) or math.isinf(value):
        # JSON has no representation for these, and a NaN would silently make
        # every comparison false rather than raising.
        raise NonCanonicalizable(f"non-finite float in evidence: {value!r}")
    return Decimal(value).quantize(Decimal(1).scaleb(-FLOAT_PRECISION))


def _normalize(value: Any) -> Any:
    """Recursively convert a value into canonical-safe primitives."""
    # bool before int: bool is a subclass of int and must stay true/false.
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _quantize(value)
    if isinstance(value, Decimal):
        return _quantize(float(value))
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                # Silently coercing 1 and "1" to the same key would let two
                # different bundles hash identically.
                raise NonCanonicalizable(f"object keys must be strings, got {type(key).__name__}")
            out[key] = _normalize(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    raise NonCanonicalizable(f"unsupported type in evidence: {type(value).__name__}")


def _encode(value: Any) -> str:
    """Serialize normalized data, emitting Decimals as bare JSON numbers."""
    if isinstance(value, Decimal):
        # Fixed notation, always FLOAT_PRECISION decimals, so 1.0 and 1.000000
        # can never produce different bytes.
        return f"{value:.{FLOAT_PRECISION}f}"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # ensure_ascii=False keeps UTF-8 text as UTF-8, per JCS.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, dict):
        # Sorted by key so insertion order cannot change the bytes. JCS sorts
        # by UTF-16 code unit; for the ASCII keys used here that is identical
        # to Python's default string ordering.
        items = sorted(value.items(), key=lambda kv: kv[0])
        return "{" + ",".join(f"{json.dumps(k, ensure_ascii=False)}:{_encode(v)}" for k, v in items) + "}"
    raise NonCanonicalizable(f"unsupported type: {type(value).__name__}")


def canonical(value: Any) -> bytes:
    """Return the canonical UTF-8 byte serialization of `value`.

    This is the only function that should ever feed a hash.
    """
    return _encode(_normalize(value)).encode("utf-8")


def canonical_str(value: Any) -> str:
    """Canonical form as text - for logging and for writing evidence files."""
    return canonical(value).decode("utf-8")
