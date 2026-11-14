import pytest


@pytest.fixture(autouse=True)
def own_settings_untouched(monkeypatch, tmp_path_factory):
    """Tests never read nor write the workshop's real config.toml and library (its language, spools, gallery...)."""
    from elegoo_lab import config
    root = tmp_path_factory.mktemp("atelier")
    (root / "models").mkdir()
    monkeypatch.setattr(config, "CONFIG_FILE", root / "config.toml")
    monkeypatch.setattr(config, "MODELS_DIR", root / "models")


@pytest.fixture(autouse=True)
def no_own_spools(monkeypatch, tmp_path_factory):
    """The workshop's own spool list (models/.mes_bobines.json) must not change what tests see."""
    from elegoo_lab import catalog
    empty = tmp_path_factory.mktemp("catalogue") / ".mes_bobines.json"
    monkeypatch.setattr(catalog, "_file", lambda: empty)


@pytest.fixture
def fake_printer_env(monkeypatch):
    """Dashboard config pointing at the test double (no connection is made until the app starts)."""
    import fakeprinter
    monkeypatch.setenv("CC2_HOST", fakeprinter.SIM_HOST)
    monkeypatch.setenv("CC2_ACCESS_CODE", fakeprinter.SIM_CODE)
    monkeypatch.setenv("CC2_SERIAL", fakeprinter.SIM_SERIAL)
    fakeprinter.patch_pycentauri()
