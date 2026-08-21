import ast
from pathlib import Path

from arctoken.project import load_project
from arctoken.walker import DEFAULT_EXCLUDES

UNPARSEABLE = "def broken(:\n    pass\n"


def test_modules_are_named_by_their_dotted_path_from_the_root(tmp_path):
    (tmp_path / "top.py").write_text("")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "inner.py").write_text("")

    project = load_project(tmp_path)

    assert [module.name for module in project.modules] == ["pkg", "pkg.inner", "top"]


def test_nested_package_init_is_named_by_its_full_dotted_path(tmp_path):
    # A single-component package never exercises the separator between parts.
    (tmp_path / "pkg" / "sub").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "sub" / "__init__.py").write_text("")

    project = load_project(tmp_path)

    assert [module.name for module in project.modules] == ["pkg", "pkg.sub"]


def test_parsed_module_carries_its_path_and_a_usable_tree(tmp_path):
    # The call graph reads both fields, so a name-only assertion would let a
    # missing tree through and surface later as a graph with no edges.
    (tmp_path / "solo.py").write_text("def handler():\n    pass\n")

    (module,) = load_project(tmp_path).modules

    assert module.path == tmp_path / "solo.py"
    assert [node.name for node in module.tree.body if isinstance(node, ast.FunctionDef)] == [
        "handler"
    ]


def test_caller_excludes_are_honoured(tmp_path):
    (tmp_path / "app.py").write_text("")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "sdk.py").write_text("")

    project = load_project(tmp_path, excludes=DEFAULT_EXCLUDES | {"vendor"})

    assert [module.name for module in project.modules] == ["app"]


def test_unparseable_module_is_skipped_and_does_not_stop_the_load(tmp_path):
    (tmp_path / "good.py").write_text("")
    (tmp_path / "broken.py").write_text(UNPARSEABLE)

    project = load_project(tmp_path)

    assert [module.name for module in project.modules] == ["good"]
    assert [(skip.path, skip.reason) for skip in project.skipped] == [
        (tmp_path / "broken.py", "unparseable")
    ]


def test_undecodable_module_is_skipped(tmp_path):
    (tmp_path / "good.py").write_text("")
    undecodable = tmp_path / "latin1.py"
    undecodable.write_bytes(b"# caf\xe9 comment\n")

    project = load_project(tmp_path)

    assert [module.name for module in project.modules] == ["good"]
    assert [(skip.path, skip.reason) for skip in project.skipped] == [(undecodable, "undecodable")]


def test_unreadable_module_is_skipped(tmp_path, monkeypatch):
    # The suite runs as root, which bypasses permission bits, so chmod cannot
    # express this. Refusing the read at the filesystem boundary can.
    (tmp_path / "good.py").write_text("")
    unreadable = tmp_path / "locked.py"
    unreadable.write_text("")
    original_read_text = Path.read_text

    def refuse_one_file(self, *args, **kwargs):
        if self == unreadable:
            raise PermissionError(13, "Permission denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", refuse_one_file)

    project = load_project(tmp_path)

    assert [module.name for module in project.modules] == ["good"]
    assert [(skip.path, skip.reason) for skip in project.skipped] == [(unreadable, "unreadable")]


def test_skipped_files_are_ordered_by_path_not_by_walk_order(tmp_path):
    # os.walk yields a directory's own files before descending, so walk order
    # here is z_broken then aaa/broken; ordering by path reverses that.
    (tmp_path / "z_broken.py").write_text(UNPARSEABLE)
    (tmp_path / "aaa").mkdir()
    (tmp_path / "aaa" / "broken.py").write_text(UNPARSEABLE)

    project = load_project(tmp_path)

    assert [skip.path for skip in project.skipped] == [
        tmp_path / "aaa" / "broken.py",
        tmp_path / "z_broken.py",
    ]


def test_module_with_a_utf8_bom_is_parsed_not_skipped(tmp_path):
    # A BOM is legal at the start of a Python file. Skipping it as unparseable
    # loses the module entirely, along with any model call inside it.
    (tmp_path / "with_bom.py").write_bytes(b"\xef\xbb\xbf" + b"def handler():\n    pass\n")

    project = load_project(tmp_path)

    (module,) = project.modules
    assert module.name == "with_bom"
    assert [node.name for node in module.tree.body if isinstance(node, ast.FunctionDef)] == [
        "handler"
    ]
    assert list(project.skipped) == []
