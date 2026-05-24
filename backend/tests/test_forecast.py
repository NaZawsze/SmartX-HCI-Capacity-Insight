from app.services.forecast import SECONDS_PER_DAY, forecast_series


def test_forecast_requires_seven_points() -> None:
    result = forecast_series([(1, 10.0), (2, 11.0)])
    assert result.status == "insufficient_data"
    assert result.forecast_30d is None


def test_forecast_linear_growth() -> None:
    base = 1_700_000_000
    points = [(base + day * SECONDS_PER_DAY, 100.0 + day * 10.0) for day in range(14)]
    result = forecast_series(points, capacity=400.0)
    assert result.status == "ok"
    assert round(result.slope_per_day) == 10
    assert result.forecast_30d is not None
    assert result.exhaustion_days is not None

