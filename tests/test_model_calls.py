from pathlib import Path

import pytest

from arctoken.detectors.model_calls import find_model_calls

FIXTURES = Path(__file__).parent / "fixtures"


def test_finds_every_dirty_call_site():
    result = find_model_calls(FIXTURES / "dirty" / "model_calls.py")
    assert result == [
        (9, ".chat.completions.create"),
        (16, ".messages.create"),
        (23, ".chat.completions.create"),
        (27, "model=+messages="),
        (31, ".messages.create"),
    ]


def test_clean_fixture_has_no_matches():
    result = find_model_calls(FIXTURES / "clean" / "model_calls.py")
    assert result == []


def test_raises_syntax_error_on_unparseable_file(tmp_path):
    bad_file = tmp_path / "not_python.py"
    bad_file.write_text("def broken(:\n    pass\n")
    with pytest.raises(SyntaxError) as exc_info:
        find_model_calls(bad_file)
    # The filename rides along on the raised error, so anything upstream can
    # report which file failed to parse.
    assert exc_info.value.filename == str(bad_file)


def test_preserves_encounter_order_for_calls_on_the_same_line():
    # Sorting by the whole (line, pattern) tuple would alphabetize these two
    # ties ("." < "c" < "m" means chat.completions sorts before messages),
    # reordering them ahead of the messages.create call that is actually
    # written first. Sorting by line number alone is a stable sort, so ties
    # must keep their left-to-right encounter order instead.
    result = find_model_calls(FIXTURES / "dirty" / "same_line_calls.py")
    assert result == [
        (7, ".messages.create"),
        (7, ".chat.completions.create"),
    ]


def test_file_with_a_utf8_bom_is_parsed(tmp_path):
    # CPython strips a leading BOM, so this file runs fine under python.
    # Decoding it as plain utf-8 keeps the U+FEFF and ast.parse rejects it,
    # which silently drops a real model call from the scan.
    bom_file = tmp_path / "with_bom.py"
    bom_file.write_bytes(b"\xef\xbb\xbf" + b'client.messages.create(model="m", messages=[])\n')

    assert find_model_calls(bom_file) == [(1, ".messages.create")]
