import numpy as np
import pytest

from hallucinate import eq

RATE = 44100


def sine(freq, seconds=1.0, ch=2):
    t = np.arange(int(RATE * seconds)) / RATE
    return np.repeat((0.2 * np.sin(2 * np.pi * freq * t))[:, None], ch, axis=1).astype(np.float32)


def level(x):
    return float(np.sqrt(np.mean(x[RATE // 4:-RATE // 4] ** 2)))


def run(gains, x, chunk=4096):
    p = eq.EqProcessor()
    p.configure(RATE, x.shape[1])
    p.set_gains(gains)
    return np.concatenate([p.process(x[i:i + chunk]) for i in range(0, len(x), chunk)])


def gains_with(band, db):
    g = [0.0] * 10
    g[band] = db
    return g


@pytest.mark.parametrize("freq,band", [(125, 2), (1000, 5), (8000, 8)])
def test_band_boost_and_cut(freq, band):
    x = sine(freq)
    base = level(x)
    boosted = level(run(gains_with(band, 9), x)) / base
    cut = level(run(gains_with(band, -9), x)) / base
    assert 2.4 < boosted < 3.4  # +9 dB = 2.8x
    assert 0.25 < cut < 0.45  # -9 dB = 0.355x


def test_other_bands_unaffected_and_flat_is_transparent():
    x = sine(1000)
    assert level(run(gains_with(0, 12), x)) / level(x) == pytest.approx(1.0, abs=0.08)
    assert level(run([0.0] * 10, x)) / level(x) == pytest.approx(1.0, abs=0.03)


def test_chunking_is_seamless():
    x = sine(440, 0.5)
    g = gains_with(4, 6)
    a, b = run(g, x, 1024), run(g, x, 7000)
    assert np.allclose(a, b, atol=1e-4)


def test_mono_and_presets_valid():
    assert run(gains_with(5, 6), sine(1000, 0.3, ch=1)).shape == (int(RATE * 0.3), 1)
    assert all(len(v) == len(eq.BANDS) for v in eq.PRESETS.values())
