from pathlib import Path

from arctoken.walker import DEFAULT_EXCLUDES, ModelCall, SkippedFile, scan_directory

ANTHROPIC_CALL = "client.messages.create(model='claude-3', messages=[])\n"
OPENAI_CALL = "client.chat.completions.create(model='gpt-4', messages=[])\n"
UNPARSEABLE = "def broken(:\n    pass\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_unparseable_file_is_recorded_and_does_not_stop_the_walk(tmp_path):
    write(tmp_path / "a_good.py", ANTHROPIC_CALL)
    write(tmp_path / "b_broken.py", UNPARSEABLE)
    write(tmp_path / "c_good.py", OPENAI_CALL)

    result = scan_directory(tmp_path)

    assert result.matches == [
        ModelCall(tmp_path / "a_good.py", 1, ".messages.create"),
        ModelCall(tmp_path / "c_good.py", 1, ".chat.completions.create"),
    ]
    assert result.skipped == [SkippedFile(tmp_path / "b_broken.py", "unparseable")]


def test_undecodable_file_is_recorded_as_a_skip(tmp_path):
    write(tmp_path / "app.py", ANTHROPIC_CALL)
    # 0xe9 is a UTF-8 lead byte, but " comment" is not a valid continuation,
    # so this is latin-1 text that cannot be decoded as UTF-8.
    undecodable = tmp_path / "latin1.py"
    undecodable.write_bytes(b"# caf\xe9 comment\nx = 1\n")

    result = scan_directory(tmp_path)

    assert result.matches == [ModelCall(tmp_path / "app.py", 1, ".messages.create")]
    assert result.skipped == [SkippedFile(undecodable, "undecodable")]


def test_unreadable_file_is_recorded_as_a_skip(tmp_path, monkeypatch):
    # chmod cannot express "unreadable" here: the suite runs as root, which
    # bypasses permission bits entirely. Refusing the read at the filesystem
    # boundary is the only way to pin this deterministically.
    write(tmp_path / "app.py", ANTHROPIC_CALL)
    unreadable = write(tmp_path / "locked.py", ANTHROPIC_CALL)
    original_read_text = Path.read_text

    def refuse_one_file(self, *args, **kwargs):
        if self == unreadable:
            raise PermissionError(13, "Permission denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", refuse_one_file)

    result = scan_directory(tmp_path)

    assert result.matches == [ModelCall(tmp_path / "app.py", 1, ".messages.create")]
    assert result.skipped == [SkippedFile(unreadable, "unreadable")]


def test_vendored_code_under_default_excludes_contributes_no_matches(tmp_path):
    write(tmp_path / "app.py", ANTHROPIC_CALL)
    vendored = tmp_path / ".venv" / "lib" / "python3.11" / "site-packages" / "anthropic"
    write(vendored / "client.py", ANTHROPIC_CALL)

    result = scan_directory(tmp_path)

    assert result.matches == [ModelCall(tmp_path / "app.py", 1, ".messages.create")]
    assert result.skipped == []


def test_excluded_directories_are_not_recorded_as_skips(tmp_path):
    # An excluded file was never a candidate, so it is not a "skip" -- skips
    # are files we intended to parse and could not.
    write(tmp_path / "app.py", ANTHROPIC_CALL)
    write(tmp_path / "node_modules" / "pkg" / "index.py", UNPARSEABLE)

    result = scan_directory(tmp_path)

    assert result.skipped == []


def test_file_without_model_calls_contributes_nothing_and_is_not_an_error(tmp_path):
    write(tmp_path / "plain.py", "def add(a, b):\n    return a + b\n")

    result = scan_directory(tmp_path)

    assert result.matches == []
    assert result.skipped == []


def test_caller_excludes_replace_the_defaults(tmp_path):
    # "tests" is excluded by default; an empty exclude set must scan it.
    write(tmp_path / "app.py", ANTHROPIC_CALL)
    write(tmp_path / "tests" / "test_app.py", OPENAI_CALL)

    result = scan_directory(tmp_path, excludes=frozenset())

    assert result.matches == [
        ModelCall(tmp_path / "app.py", 1, ".messages.create"),
        ModelCall(tmp_path / "tests" / "test_app.py", 1, ".chat.completions.create"),
    ]


def test_caller_can_exclude_a_directory_the_defaults_allow(tmp_path):
    write(tmp_path / "app.py", ANTHROPIC_CALL)
    write(tmp_path / "vendor" / "sdk.py", ANTHROPIC_CALL)

    result = scan_directory(tmp_path, excludes=DEFAULT_EXCLUDES | {"vendor"})

    assert result.matches == [ModelCall(tmp_path / "app.py", 1, ".messages.create")]


def test_non_python_files_are_ignored(tmp_path):
    write(tmp_path / "app.py", ANTHROPIC_CALL)
    write(tmp_path / "README.md", ANTHROPIC_CALL)
    write(tmp_path / "config.json", ANTHROPIC_CALL)

    result = scan_directory(tmp_path)

    assert result.matches == [ModelCall(tmp_path / "app.py", 1, ".messages.create")]
    assert result.skipped == []
