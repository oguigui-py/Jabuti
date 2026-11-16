"""Identidade do app no macOS (ícone do Dock e nome no menu) sem dependências novas.

Rodando como ``python -m jabuti``, o processo é o executável do Python: o Dock mostra o
foguete e o menu superior diz "Python". ``QApplication.setWindowIcon`` não troca o ícone
do Dock, então aqui se fala direto com o AppKit pelo runtime do Objective-C (``libobjc``)
via ``ctypes``:

* ``set_app_name``: ``CFBundleName`` no ``infoDictionary`` do bundle principal (antes de
  criar o ``QApplication``, que é quando o menu do app é montado) e ``processName``;
* ``set_dock_icon``: ``[NSApp setApplicationIconImage:]`` com o PNG do ícone (depois de
  criar o ``QApplication``).

Tudo é opcional: fora do macOS, sem ``libobjc``/AppKit, ou com qualquer erro, as funções
devolvem ``False`` e o programa segue normalmente (nunca levantam exceção).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from pathlib import Path

from jabuti.logs import get_logger

_log = get_logger("macos")
APPKIT = "/System/Library/Frameworks/AppKit.framework/AppKit"


class _ObjC:
    """Mínimo do runtime: classes, seletores e ``objc_msgSend`` com assinatura explícita
    (obrigatório no arm64, onde a chamada variádica genérica não funciona)."""

    def __init__(self) -> None:
        path = ctypes.util.find_library("objc")
        if not path:
            raise OSError("libobjc não encontrada")
        self.lib = ctypes.cdll.LoadLibrary(path)
        ctypes.cdll.LoadLibrary(APPKIT)                  # registra NSApplication, NSImage…
        self.lib.objc_getClass.restype = ctypes.c_void_p
        self.lib.objc_getClass.argtypes = [ctypes.c_char_p]
        self.lib.sel_registerName.restype = ctypes.c_void_p
        self.lib.sel_registerName.argtypes = [ctypes.c_char_p]
        self.lib.objc_autoreleasePoolPush.restype = ctypes.c_void_p
        self.lib.objc_autoreleasePoolPop.argtypes = [ctypes.c_void_p]
        self._send = ctypes.cast(self.lib.objc_msgSend, ctypes.c_void_p).value

    def cls(self, name: str) -> int:
        c = self.lib.objc_getClass(name.encode())
        if not c:
            raise OSError(f"classe {name} indisponível")
        return c

    def send(self, obj: int | None, sel: str, *args, restype=ctypes.c_void_p, argtypes=()):  # type: ignore[no-untyped-def]
        if not obj:
            raise OSError(f"objeto nulo em {sel}")
        fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(self._send)
        return fn(obj, self.lib.sel_registerName(sel.encode()), *args)

    def string(self, text: str) -> int:
        return self.send(self.cls("NSString"), "stringWithUTF8String:", text.encode("utf-8"),
                         argtypes=(ctypes.c_char_p,))

    def pool(self):  # type: ignore[no-untyped-def]
        return self.lib.objc_autoreleasePoolPush()

    def drain(self, pool) -> None:  # type: ignore[no-untyped-def]
        self.lib.objc_autoreleasePoolPop(pool)


def _runtime() -> _ObjC | None:
    if sys.platform != "darwin":
        return None
    try:
        return _ObjC()
    except Exception as exc:  # noqa: BLE001 — AppKit ausente: segue sem ícone no Dock
        _log.info("AppKit indisponível (%s); ícone do Dock não aplicado", exc)
        return None


def set_app_name(name: str = "Jabuti") -> bool:
    """Nome no menu superior do macOS. Chamar antes de criar o ``QApplication``."""
    rt = _runtime()
    if rt is None:
        return False
    pool = None
    try:
        pool = rt.pool()
        value = rt.string(name)
        bundle = rt.send(rt.cls("NSBundle"), "mainBundle")
        ok = False
        for getter in ("localizedInfoDictionary", "infoDictionary"):
            info = rt.send(bundle, getter)
            if info and rt.send(info, "respondsToSelector:", rt.lib.sel_registerName(b"setObject:forKey:"),
                                restype=ctypes.c_bool, argtypes=(ctypes.c_void_p,)):
                rt.send(info, "setObject:forKey:", value, rt.string("CFBundleName"),
                        restype=None, argtypes=(ctypes.c_void_p, ctypes.c_void_p))
                ok = True
        process = rt.send(rt.cls("NSProcessInfo"), "processInfo")
        rt.send(process, "setProcessName:", value, restype=None, argtypes=(ctypes.c_void_p,))
        return ok
    except Exception:  # noqa: BLE001 — nunca derruba a abertura
        _log.exception("falha ao definir o nome do app no macOS")
        return False
    finally:
        if pool is not None:
            rt.drain(pool)


def set_dock_icon(png: str | Path) -> bool:
    """Ícone do Dock a partir de um PNG. Chamar depois de criar o ``QApplication``."""
    rt = _runtime()
    if rt is None:
        return False
    if not Path(png).is_file():
        _log.warning("ícone do Dock não encontrado: %s", png)
        return False
    pool = None
    try:
        pool = rt.pool()
        image = rt.send(rt.cls("NSImage"), "alloc")
        image = rt.send(image, "initWithContentsOfFile:", rt.string(str(png)), argtypes=(ctypes.c_void_p,))
        if not image:
            return False
        app = rt.send(rt.cls("NSApplication"), "sharedApplication")
        rt.send(app, "setApplicationIconImage:", image, restype=None, argtypes=(ctypes.c_void_p,))
        rt.send(image, "release", restype=None)             # o NSApp guarda a sua referência
        return True
    except Exception:  # noqa: BLE001
        _log.exception("falha ao definir o ícone do Dock")
        return False
    finally:
        if pool is not None:
            rt.drain(pool)


def bundle_name() -> str | None:
    """Diagnóstico: ``CFBundleName`` atual do bundle principal."""
    rt = _runtime()
    if rt is None:
        return None
    try:
        bundle = rt.send(rt.cls("NSBundle"), "mainBundle")
        info = rt.send(bundle, "infoDictionary")
        value = rt.send(info, "objectForKey:", rt.string("CFBundleName"), argtypes=(ctypes.c_void_p,))
        if not value:
            return None
        raw = rt.send(value, "UTF8String", restype=ctypes.c_char_p)
        return raw.decode("utf-8") if raw else None
    except Exception:  # noqa: BLE001
        return None
