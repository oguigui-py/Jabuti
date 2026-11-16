"""Ícone do Dock e nome do app no macOS: nunca levantam exceção, mesmo sem AppKit.

Nenhum teste aqui cria janela nem fala com o AppKit de verdade: o runtime é simulado."""

from __future__ import annotations

import ctypes.util

import pytest

from jabuti import macos
from jabuti.resources import JABUTI_ICON, assets_dir

ICON = assets_dir() / JABUTI_ICON


def test_noop_outside_macos(monkeypatch):
    monkeypatch.setattr(macos.sys, "platform", "linux")
    monkeypatch.setattr(macos, "_ObjC", lambda: pytest.fail("não deveria carregar o runtime"))
    assert macos.set_dock_icon(ICON) is False
    assert macos.set_app_name("Jabuti") is False
    assert macos.bundle_name() is None


@pytest.mark.parametrize("how", ["sem-libobjc", "sem-appkit"])
def test_missing_appkit_does_not_raise(monkeypatch, how):
    monkeypatch.setattr(macos.sys, "platform", "darwin")
    if how == "sem-libobjc":
        monkeypatch.setattr(ctypes.util, "find_library", lambda name: None)
    else:
        real = ctypes.cdll.LoadLibrary

        def load(path):  # type: ignore[no-untyped-def]
            if "AppKit" in str(path):
                raise OSError("AppKit não existe")
            return real(path)
        monkeypatch.setattr(macos.ctypes.cdll, "LoadLibrary", load)
    assert macos.set_dock_icon(ICON) is False
    assert macos.set_app_name("Jabuti") is False
    assert macos.bundle_name() is None


class _Broken:
    """Runtime que carrega mas falha em qualquer mensagem (AppKit diferente do esperado)."""

    lib = None

    def pool(self):  # type: ignore[no-untyped-def]
        return None

    def drain(self, pool) -> None:  # type: ignore[no-untyped-def]
        pass

    def cls(self, name):  # type: ignore[no-untyped-def]
        raise OSError(f"classe {name} indisponível")

    def string(self, text):  # type: ignore[no-untyped-def]
        raise OSError("sem NSString")

    def send(self, *a, **k):  # type: ignore[no-untyped-def]
        raise OSError("falhou")


def test_runtime_errors_are_swallowed(monkeypatch):
    monkeypatch.setattr(macos, "_runtime", lambda: _Broken())
    assert macos.set_dock_icon(ICON) is False
    assert macos.set_app_name("Jabuti") is False
    assert macos.bundle_name() is None


def test_missing_icon_file(monkeypatch, tmp_path):
    monkeypatch.setattr(macos, "_runtime", lambda: _Broken())
    assert macos.set_dock_icon(tmp_path / "nao_existe.png") is False


def test_messages_sent_for_icon(monkeypatch):
    """Com um runtime simulado, o ícone é carregado do PNG e entregue ao NSApp."""
    calls: list[str] = []

    class Fake(_Broken):
        def cls(self, name):  # type: ignore[no-untyped-def]
            return name

        def string(self, text):  # type: ignore[no-untyped-def]
            return f"@{text}"

        def send(self, obj, sel, *args, **k):  # type: ignore[no-untyped-def]
            calls.append(sel)
            return f"{obj}.{sel}"

    monkeypatch.setattr(macos, "_runtime", lambda: Fake())
    assert macos.set_dock_icon(ICON) is True
    assert calls[:2] == ["alloc", "initWithContentsOfFile:"]
    assert "sharedApplication" in calls and "setApplicationIconImage:" in calls


def test_app_calls_mac_identity_in_order(monkeypatch):
    """run(): nome antes do QApplication, ícone do Dock depois dele e antes da abertura."""
    import jabuti.app as app_mod

    order: list[str] = []
    monkeypatch.setattr(app_mod.sys, "platform", "darwin")
    monkeypatch.setattr(macos, "set_app_name", lambda name="Jabuti": order.append(f"nome:{name}") or True)
    monkeypatch.setattr(macos, "set_dock_icon", lambda p: order.append(f"dock:{p.name}") or True)

    class StopHere(Exception):
        pass

    def fake_launcher(*a, **k):  # type: ignore[no-untyped-def]
        order.append("abertura")
        raise StopHere
    monkeypatch.setattr(app_mod, "Launcher", fake_launcher)
    monkeypatch.setattr(app_mod, "splash_enabled", lambda app: False)
    monkeypatch.setattr("jabuti.views.errors.install_excepthook", lambda: None)
    with pytest.raises(StopHere):
        app_mod.run(splash=False)
    assert order == ["nome:Jabuti", f"dock:{JABUTI_ICON}", "abertura"]


def test_windows_linux_keep_window_icon(monkeypatch, qapp):
    """Fora do macOS: só o setWindowIcon (ícone não nulo), sem tocar no AppKit."""
    import jabuti.app as app_mod

    monkeypatch.setattr(app_mod.sys, "platform", "win32")
    monkeypatch.setattr(macos, "set_dock_icon", lambda p: pytest.fail("AppKit fora do macOS"))
    monkeypatch.setattr(macos, "set_app_name", lambda n="": pytest.fail("AppKit fora do macOS"))

    class StopHere(Exception):
        pass

    monkeypatch.setattr(app_mod, "Launcher", lambda *a, **k: (_ for _ in ()).throw(StopHere()))
    monkeypatch.setattr("jabuti.views.errors.install_excepthook", lambda: None)
    with pytest.raises(StopHere):
        app_mod.run(splash=False)
    assert not qapp.windowIcon().isNull() and qapp.applicationName() == "Jabuti"
