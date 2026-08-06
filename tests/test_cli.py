from importlib.metadata import version

from arctoken.cli import main


def test_main_prints_version(capsys):
    main()
    out = capsys.readouterr().out
    assert out.strip() == version("arctoken")
