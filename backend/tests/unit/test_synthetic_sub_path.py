from __future__ import annotations

from bot.data.dataset import DatasetSpec, generate_bundle
from bot.data.feed import Feed
from bot.data.synthetic import SUB_STEPS, generate_price_series


def test_generate_price_series_has_sub_path_matching_ohlc():
    df, _labels = generate_price_series(seed=1, n_candles=5)
    assert "sub_path" in df.columns
    for _, row in df.iterrows():
        path = row["sub_path"]
        assert len(path) == SUB_STEPS + 1
        assert path[0] == row["open"]
        assert path[-1] == row["close"]
        assert max(path) == row["high"]
        assert min(path) == row["low"]


def test_feed_bar_at_15m_carries_sub_path_but_resampled_tf_does_not():
    spec = DatasetSpec(seed=1, n_candles_15m=20)
    bundle = generate_bundle(spec)
    price_feed = Feed(frames=bundle["price"])

    ts15 = price_feed.frames["15m"].index[0].to_pydatetime()
    bar15 = price_feed.bar_at("15m", ts15)
    assert bar15 is not None
    assert bar15.sub_path is not None
    assert len(bar15.sub_path) == SUB_STEPS + 1

    ts1h = price_feed.frames["1H"].index[0].to_pydatetime()
    bar1h = price_feed.bar_at("1H", ts1h)
    assert bar1h is not None
    assert bar1h.sub_path is None
