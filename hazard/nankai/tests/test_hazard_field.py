import numpy as np, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from nankai.hazard_field import pgv_to_intensity, intensity_to_pgv, GMPEField, jma_class, correlated_noise


def test_intensity_roundtrip():
    pgv = np.array([1, 5, 20, 60, 120.0])
    I = pgv_to_intensity(pgv)
    assert np.allclose(intensity_to_pgv(I), pgv, rtol=1e-6)
    assert list(jma_class(np.array([4.4, 4.5, 5.0, 5.5, 6.0, 6.5]))) == ["4", "5弱", "5強", "6弱", "6強", "7"]


def test_gmpe_decays_with_distance():
    f = GMPEField()
    lat = np.array([33.6, 34.4, 35.0, 36.5, 37.4])   # 高知付近 → 北へ離れる
    lon = np.array([133.5, 133.5, 133.5, 133.5, 133.5])
    hs = f.sample(lat, lon, randomize=False)
    assert np.all(np.diff(hs.rupture_km[1:]) > 0)
    assert np.all(np.diff(hs.pgv[1:]) < 0)
    assert 5.5 <= hs.intensity[0] <= 7.0          # 高知は 6弱以上
    assert hs.intensity[-1] < 5.0                  # 山陰沖は 5弱未満


def test_correlated_noise_is_normalized():
    rng = np.random.default_rng(0)
    lat = rng.uniform(31, 37, 3000); lon = rng.uniform(130, 139, 3000)
    z = correlated_noise(lat, lon, 25.0, rng)
    assert abs(z.mean()) < 0.2 and 0.5 < z.std() < 1.5
