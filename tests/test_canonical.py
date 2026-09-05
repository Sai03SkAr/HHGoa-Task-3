"""Canonicalization must be stable, or `verify` reports false tampering."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from src.evidence.canonical import (
    FLOAT_PRECISION,
    NonCanonicalizable,
    canonical,
    canonical_str,
)


def test_key_order_does_not_change_bytes():
    a = {"zebra": 1, "alpha": 2, "middle": 3}
    b = {"middle": 3, "alpha": 2, "zebra": 1}
    assert canonical(a) == canonical(b)


def test_no_whitespace():
    out = canonical_str({"a": 1, "b": [1, 2]})
    assert out == '{"a":1,"b":[1,2]}'
    assert " " not in out


def test_round_trip_is_stable():
    """The property `verify` actually depends on.

    Evidence is written to disk as JSON, read back, and re-hashed. If parsing
    and re-canonicalizing shifted a single byte, every verification would fail.
    """
    value = {
        "cosine": 0.6123456789,
        "nested": {"score": 0.1 + 0.2, "count": 3},
        "list": [1.5, 2.0, {"deep": 0.333333333}],
    }
    once = canonical(value)
    twice = canonical(json.loads(once))
    thrice = canonical(json.loads(twice))
    assert once == twice == thrice


def test_float_noise_is_quantized_away():
    """0.1 + 0.2 must not hash differently from 0.3."""
    assert canonical({"x": 0.1 + 0.2}) == canonical({"x": 0.3})


def test_float_formatting_is_fixed_precision():
    # 1.0 and 1 are different JSON types and must stay distinguishable, but a
    # float must always render with the same number of decimals.
    assert canonical_str({"x": 1.0}) == '{"x":1.' + "0" * FLOAT_PRECISION + "}"
    assert canonical_str({"x": 1}) == '{"x":1}'


def test_bool_is_not_int():
    """bool subclasses int in Python; true must not serialize as 1."""
    assert canonical_str({"x": True}) == '{"x":true}'
    assert canonical_str({"x": 1}) == '{"x":1}'
    assert canonical({"x": True}) != canonical({"x": 1})


def test_unicode_is_preserved_as_utf8():
    out = canonical({"name": "Sai Salelkar", "city": "Goa — गोवा"})
    assert "गोवा" in out.decode("utf-8")
    # Not escaped to \uXXXX, per JCS.
    assert b"\\u0917" not in out


def test_nan_and_inf_rejected():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(NonCanonicalizable):
            canonical({"x": bad})


def test_non_string_keys_rejected():
    # Otherwise {1: "a"} and {"1": "a"} would hash identically.
    with pytest.raises(NonCanonicalizable):
        canonical({1: "a"})


def test_unsupported_type_rejected():
    with pytest.raises(NonCanonicalizable):
        canonical({"x": {1, 2, 3}})


def test_tuple_and_list_are_equivalent():
    assert canonical({"x": (1, 2)}) == canonical({"x": [1, 2]})


def test_empty_containers():
    assert canonical_str({"a": {}, "b": []}) == '{"a":{},"b":[]}'


def test_stable_across_processes():
    """Guards against anything hash-seed or dict-order dependent.

    A fresh interpreter has a different PYTHONHASHSEED, which is exactly the
    condition under which an accidental set- or hash-ordering dependency would
    surface.
    """
    payload = {"z": 0.1 + 0.2, "a": [3, 2, 1], "m": {"k": "é"}}
    script = (
        "import json,sys;"
        "sys.path.insert(0,'.');"
        "from src.evidence.canonical import canonical;"
        f"sys.stdout.buffer.write(canonical(json.loads({json.dumps(json.dumps(payload))})))"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, check=True
    ).stdout
    assert out == canonical(payload)
