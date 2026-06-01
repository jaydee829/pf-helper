import pf_helper.cli as cli


def test_bare_invocation_serves(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "_cmd_serve", lambda args: called.append("serve"))
    cli.main([])
    assert called == ["serve"]


def test_ingest_passes_refresh(monkeypatch):
    seen = {}
    import pf_helper.ingest.build as build
    monkeypatch.setattr(
        build, "run_ingest", lambda cfg, refresh=False: seen.update(refresh=refresh)
    )
    import pf_helper.config as cfgmod
    monkeypatch.setattr(cfgmod.Config, "from_env", classmethod(lambda cls: cls()))
    cli.main(["ingest", "--refresh"])
    assert seen == {"refresh": True}


def test_register_desktop_routes(monkeypatch):
    from pf_helper.install import desktop, server_cmd
    monkeypatch.setattr(server_cmd, "server_command", lambda: ["pf", "serve"])
    seen = {}
    monkeypatch.setattr(
        desktop,
        "register_desktop",
        lambda cmd: seen.setdefault("cmd", cmd) or __import__("pathlib").Path("/x"),
    )
    cli.main(["register", "--client", "desktop"])
    assert seen["cmd"] == ["pf", "serve"]


def test_print_config_outputs_json(monkeypatch, capsys):
    from pf_helper.install import server_cmd
    monkeypatch.setattr(server_cmd, "server_command", lambda: ["pf", "serve"])
    cli.main(["print-config"])
    out = capsys.readouterr().out
    assert "pf-helper" in out and "serve" in out
