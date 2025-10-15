
from strategies.registry import StrategyRegistry


def test_blend_weights_and_enable():
    reg = StrategyRegistry()
    reg.register("a", fn=lambda ctx:  1.0, weight=2.0)
    reg.register("b", fn=lambda ctx: -1.0, weight=1.0)
    score = reg.blend({})
    assert abs(score - (2*1 + 1*(-1)) / (2+1)) < 1e-9
    reg.enable("b", False)
    score2 = reg.blend({})
    assert score2 == 1.0
