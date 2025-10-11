from services.market.indicators import OpeningRange, RollingATR, RollingRSI, RollingZScore


def test_rsi_bounds() -> None:
    rsi = RollingRSI(14)
    result = None
    for i in range(1, 40):
        result = rsi.update(float(i))
    assert result is not None and 0 <= result <= 100


def test_atr_positive() -> None:
    atr = RollingATR(14)
    result = None
    for i in range(1, 40):
        result = atr.update(i + 1.0, i + 2.0, i + 0.5)
    assert result and result > 0


def test_zscore_ready() -> None:
    zscore = RollingZScore(20)
    result = None
    for i in range(1, 30):
        result = zscore.update(float(i))
    assert result is not None


def test_orb_breakout() -> None:
    orb = OpeningRange(3)
    for high, low in [(10, 9), (11, 9.5), (11.5, 9.7)]:
        orb.update(high, low)
    assert orb.breakout(12.0) == 1
    assert orb.breakout(9.0) == -1
    assert orb.breakout(10.5) == 0
