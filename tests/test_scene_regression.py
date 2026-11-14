"""Com todas as opções novas desligadas, o desenho é idêntico ao gravado antes delas."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from scene_baseline import BASELINE, font_probe, same, scenarios, signature  # noqa: E402


def test_scenes_unchanged(qapp):
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    if abs(font_probe() - data["font_probe"]) > 0.01:
        pytest.skip("fontes do sistema diferentes das usadas para gravar a referência")
    for name, draw in scenarios():
        diff = same(signature(draw()), data["scenes"][name])
        assert diff is None, f"{name}: {diff}"
