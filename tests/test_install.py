import sys

from pf_helper.install.server_cmd import server_command


def test_server_command_prefers_installed_script():
    assert server_command(which=lambda n: "/usr/bin/pf-helper") == ["/usr/bin/pf-helper", "serve"]


def test_server_command_falls_back_to_module():
    assert server_command(which=lambda n: None) == [sys.executable, "-m", "pf_helper", "serve"]
