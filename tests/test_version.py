from typer.testing import CliRunner

from lkr.main import app

runner = CliRunner()


def test_version_option():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    # In test environment it should print "0.0.0" (default from importlib.metadata.PackageNotFoundError)
    # or the installed package version.
    assert "0.0.0" in result.stdout or "0.0." in result.stdout
