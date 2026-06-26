import pytest

from bemade_pre_commit_hooks._manifest import (
    bump_version_string,
    is_increase,
    read_version,
    set_version,
)


@pytest.mark.parametrize(
    "version,level,expected",
    [
        # full Odoo form: series 19.0 must never move
        ("19.0.1.2.3", "patch", "19.0.1.2.4"),
        ("19.0.1.2.3", "minor", "19.0.1.3.0"),
        ("19.0.1.2.3", "major", "19.0.2.0.0"),
        # short form
        ("1.0.0", "patch", "1.0.1"),
        ("1.2.3", "minor", "1.3.0"),
        ("1.2.3", "major", "2.0.0"),
    ],
)
def test_bump(version, level, expected):
    assert bump_version_string(version, level) == expected


def test_minor_needs_three_segments():
    with pytest.raises(ValueError):
        bump_version_string("19.0", "minor")


def test_major_needs_three_segments():
    with pytest.raises(ValueError):
        bump_version_string("19.0", "major")


def test_non_numeric_segment():
    with pytest.raises(ValueError):
        bump_version_string("1.0.x", "patch")


def test_read_and_set_roundtrip():
    text = "{\n 'name': 'Foo',\n 'version': '19.0.1.0.0',\n}\n"
    assert read_version(text) == "19.0.1.0.0"
    updated = set_version(text, "19.0.1.0.1")
    assert read_version(updated) == "19.0.1.0.1"
    assert "'name': 'Foo'" in updated  # nothing else touched


def test_read_double_quotes():
    assert read_version('{"version": "1.0.0"}') == "1.0.0"


def test_is_increase():
    assert is_increase("19.0.1.0.0", "19.0.1.0.1")
    assert is_increase("1.0.0", "1.0.1")
    assert not is_increase("1.0.1", "1.0.1")
    assert not is_increase("1.0.2", "1.0.1")  # a decrease is not an increase
    # zero-padding: 1.0 vs 1.0.1
    assert is_increase("1.0", "1.0.1")
