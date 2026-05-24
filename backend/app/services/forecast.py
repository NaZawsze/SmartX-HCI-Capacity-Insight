from dataclasses import dataclass
from statistics import median


SECONDS_PER_DAY = 86_400


@dataclass(slots=True)
class ForecastResult:
    status: str
    slope_per_day: float
    current: float
    forecast_30d: float | None
    forecast_60d: float | None
    forecast_90d: float | None
    forecast_180d: float | None
    exhaustion_days: float | None = None
    exhaustion_date: str | None = None


def forecast_series(points: list[tuple[int, float]], capacity: float | None = None) -> ForecastResult:
    cleaned = _clean(points)
    if len(cleaned) < 7:
        current = cleaned[-1][1] if cleaned else 0.0
        return ForecastResult(
            status="insufficient_data",
            slope_per_day=0.0,
            current=current,
            forecast_30d=None,
            forecast_60d=None,
            forecast_90d=None,
            forecast_180d=None,
        )
    filtered = _drop_outliers(cleaned)
    slope, intercept = _linear_regression(filtered)
    current_ts, current = filtered[-1]
    f30 = max(0.0, intercept + slope * ((current_ts + 30 * SECONDS_PER_DAY) / SECONDS_PER_DAY))
    f60 = max(0.0, intercept + slope * ((current_ts + 60 * SECONDS_PER_DAY) / SECONDS_PER_DAY))
    f90 = max(0.0, intercept + slope * ((current_ts + 90 * SECONDS_PER_DAY) / SECONDS_PER_DAY))
    f180 = max(0.0, intercept + slope * ((current_ts + 180 * SECONDS_PER_DAY) / SECONDS_PER_DAY))
    exhaustion_days = None
    exhaustion_date = None
    if capacity and slope > 0 and current < capacity:
        exhaustion_days = (capacity - current) / slope
    return ForecastResult(
        status="ok",
        slope_per_day=slope,
        current=current,
        forecast_30d=f30,
        forecast_60d=f60,
        forecast_90d=f90,
        forecast_180d=f180,
        exhaustion_days=exhaustion_days,
        exhaustion_date=exhaustion_date,
    )


def _clean(points: list[tuple[int, float]]) -> list[tuple[int, float]]:
    dedup: dict[int, float] = {}
    for ts, value in points:
        if value is not None:
            dedup[int(ts)] = float(value)
    return sorted(dedup.items())


def _drop_outliers(points: list[tuple[int, float]]) -> list[tuple[int, float]]:
    if len(points) < 10:
        return points
    deltas = [abs(points[i][1] - points[i - 1][1]) for i in range(1, len(points))]
    med = median(deltas)
    if med == 0:
        return points
    filtered = [points[0]]
    for point in points[1:]:
        if abs(point[1] - filtered[-1][1]) <= med * 8:
            filtered.append(point)
    return filtered if len(filtered) >= 7 else points


def _linear_regression(points: list[tuple[int, float]]) -> tuple[float, float]:
    xs = [ts / SECONDS_PER_DAY for ts, _ in points]
    ys = [value for _, value in points]
    x_bar = sum(xs) / len(xs)
    y_bar = sum(ys) / len(ys)
    numerator = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys, strict=True))
    denominator = sum((x - x_bar) ** 2 for x in xs)
    if denominator == 0:
        return 0.0, y_bar
    slope = numerator / denominator
    intercept = y_bar - slope * x_bar
    return slope, intercept
