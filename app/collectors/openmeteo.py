"""Open-Meteo collectors (Data Sources WX-01..WX-04).

Forecast (per model: ECMWF / GFS / JMA)
    1. read the model metadata (`/data/{meta_id}/static/meta.json`) -> model run time
    2. if that run is already stored -> nothing to do
    3. fetch the hourly forecast for all configured locations in one request
    4. read the metadata again; if the run changed during the fetch we cannot be
       sure which run the values belong to -> keep raw, skip normalization
    5. normalize: one row per (model, model_run_time, forecast_time, location)

Historical Forecast (WX-04)
    Daily re-fetch of the last N days from the Historical Forecast API. That API
    stitches successive runs into one continuous series and does not expose the
    run time, so rows are stored with product="historical_forecast" and
    model_run_time NULL (see models/weather.py).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.base import AllRequestsFailed, BaseCollector, CollectResult, HttpStatusError, SchemaMismatch
from app.config.settings import OpenMeteoModel, Settings
from app.models import ForecastRun, RawPayload, WeatherForecast
from app.services import normalizer as nz
from app.services.database import session_scope
from app.services.locations import active_locations, sync_locations
from app.services.storage import get_or_create, upsert

log = logging.getLogger(__name__)

SOURCE = "openmeteo"

# Open-Meteo variable -> (weather_forecast column, converter)
VARIABLE_MAP = {
    "temperature_2m": ("temperature_c", nz.temperature_c),
    "relative_humidity_2m": ("humidity_pct", None),
    "precipitation": ("precipitation_mm", nz.rain_mm),
    "rain": ("rain_mm", nz.rain_mm),
    "precipitation_probability": ("precip_probability_pct", None),
    "pressure_msl": ("pressure_msl_hpa", nz.pressure_hpa),
    "cloud_cover": ("cloud_cover_pct", None),
    "wind_speed_10m": ("wind_speed_kmh", nz.speed_kmh),
    "wind_direction_10m": ("wind_direction_deg", None),
    "wind_gusts_10m": ("wind_gust_kmh", nz.speed_kmh),
}
VALUE_COLUMNS = [col for col, _ in VARIABLE_MAP.values()] + ["soil_moisture_m3m3"]


def parse_meta(text: str) -> dict:
    try:
        meta = json.loads(text)
        run_time = nz.from_unix(meta["last_run_initialisation_time"])
    except (ValueError, KeyError, TypeError) as exc:
        raise SchemaMismatch(f"model metadata not understood: {exc}") from exc
    if run_time is None:
        raise SchemaMismatch("model metadata has no last_run_initialisation_time")
    return {
        "model_run_time": run_time,
        "available_at": nz.from_unix(meta.get("last_run_availability_time")),
        "temporal_resolution_seconds": int(meta["temporal_resolution_seconds"])
        if meta.get("temporal_resolution_seconds") is not None else None,
        "meta": meta,
    }


def build_rows(
    payload,
    *,
    model: str,
    product: str,
    locations: list[dict],
    model_run_time: datetime | None,
    forecast_run_id: int | None,
    raw_payload_id: int,
    soil_variable: str | None,
) -> list[dict]:
    """Turn an Open-Meteo JSON response (object or list of objects) into weather_forecast rows.

    `locations` are the requested points in request order ({"id","lat","lon"}).
    """
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(locations):
        raise SchemaMismatch(f"expected {len(locations)} location results, got {len(items)}")
    rows: list[dict] = []
    for loc, item in zip(locations, items):
        if not isinstance(item, dict) or "hourly" not in item:
            reason = item.get("reason") if isinstance(item, dict) else None
            raise SchemaMismatch(f"no 'hourly' block in response ({reason or 'unexpected structure'})")
        hourly = item["hourly"]
        units = item.get("hourly_units", {})
        times = hourly.get("time")
        if not isinstance(times, list):
            raise SchemaMismatch("hourly.time missing")
        for i, ts in enumerate(times):
            forecast_time = nz.from_unix(ts) if isinstance(ts, (int, float)) else nz.parse_datetime(ts)
            if forecast_time is None:
                continue
            if model_run_time is not None and forecast_time < model_run_time:
                continue  # hours before the run are not part of this run's forecast
            row = {
                "source": SOURCE,
                "model": model,
                "product": product,
                "forecast_run_id": forecast_run_id,
                "model_run_time": model_run_time,
                "forecast_time": forecast_time,
                "lead_time_hours": int((forecast_time - model_run_time).total_seconds() // 3600)
                if model_run_time else None,
                "location_id": loc["id"],
                "lat": loc["lat"],
                "lon": loc["lon"],
                "grid_lat": nz.to_float(item.get("latitude")),
                "grid_lon": nz.to_float(item.get("longitude")),
                "grid_elevation_m": nz.to_float(item.get("elevation")),
                "raw_payload_id": raw_payload_id,
                "soil_moisture_layer": None,
            }
            for variable, (column, converter) in VARIABLE_MAP.items():
                series = hourly.get(variable)
                value = series[i] if isinstance(series, list) and i < len(series) else None
                row[column] = nz.safe(converter, value, units.get(variable)) if converter else nz.to_float(value)
            row["soil_moisture_m3m3"] = None
            if soil_variable and isinstance(hourly.get(soil_variable), list):
                row["soil_moisture_m3m3"] = nz.to_float(hourly[soil_variable][i])
                if row["soil_moisture_m3m3"] is not None:
                    row["soil_moisture_layer"] = soil_variable.removeprefix("soil_moisture_").replace("_to_", "-")
            if all(row[c] is None for c in VALUE_COLUMNS):
                continue  # beyond the model horizon
            rows.append(row)
    return rows


class _OpenMeteoBase(BaseCollector):
    source = SOURCE
    schema_verified = True  # verified against live Open-Meteo responses 2026-09-28
    secret_params = ("apikey",)

    def configuration_status(self) -> str | None:
        return None if self.settings.openmeteo_enabled else "DISABLED"

    def _common_params(self) -> dict:
        params = {
            "timezone": "GMT",
            "timeformat": "unixtime",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        }
        if self.settings.openmeteo_api_key:
            params["apikey"] = self.settings.openmeteo_api_key
        return params

    @staticmethod
    def _locations() -> list[dict]:
        with session_scope() as session:
            sync_locations(session)
            return [{"id": l.id, "code": l.code, "lat": l.lat, "lon": l.lon} for l in active_locations(session)]

    def _hourly(self, model: OpenMeteoModel, with_extras: bool = True) -> list[str]:
        variables = list(self.settings.openmeteo_hourly_list)
        if with_extras:
            variables += [v for v in model.extra_hourly if v not in variables]
        return variables

    def _fetch_hourly(self, dataset: str, url: str, model: OpenMeteoModel, params: dict, context: dict,
                      result: CollectResult):
        """Fetch; if the request is rejected (400) because of model specific extra variables,
        retry once without them."""
        variables = self._hourly(model)
        try:
            return self.fetch(dataset, url, {**params, "hourly": ",".join(variables)},
                              context={**context, "hourly": variables}), variables
        except HttpStatusError as exc:
            if exc.status_code != 400 or not model.extra_hourly:
                raise
            result.partial_errors.append(
                f"{model.name}: HTTP 400 with extra variables {model.extra_hourly}; retried without them")
            variables = self._hourly(model, with_extras=False)
            return self.fetch(dataset, url, {**params, "hourly": ",".join(variables)},
                              context={**context, "hourly": variables}), variables


class OpenMeteoForecastCollector(_OpenMeteoBase):
    """Live forecast of one model; job `openmeteo.forecast.<MODEL>`."""

    def __init__(self, settings: Settings, model: OpenMeteoModel, fetcher=None):
        super().__init__(settings, fetcher)
        self.model = model
        self.job = f"openmeteo.forecast.{model.name}"
        self.dataset_prefixes = (f"forecast.{model.name}", f"model_meta.{model.name}")

    @property
    def interval_minutes(self) -> int:
        return self.settings.openmeteo_poll_minutes

    def _meta(self) -> tuple[dict, int]:
        url = self.settings.openmeteo_meta_url_template.format(meta_id=self.model.meta_id)
        fetched = self.fetch(f"model_meta.{self.model.name}", url)
        return parse_meta(fetched.text), fetched.raw_payload_id

    def _forecast_url(self) -> str:
        base = self.settings.openmeteo_customer_base_url if self.settings.openmeteo_api_key \
            else self.settings.openmeteo_base_url
        return f"{base.rstrip('/')}/{self.model.endpoint}"

    def collect(self) -> CollectResult:
        result = CollectResult()
        meta, meta_raw_id = self._meta()
        run_time = meta["model_run_time"]
        result.details = {"model": self.model.name, "model_run_time": run_time.isoformat()}

        with session_scope() as session:
            existing = session.execute(
                select(func.count(WeatherForecast.id))
                .join(ForecastRun, WeatherForecast.forecast_run_id == ForecastRun.id)
                .where(ForecastRun.source == SOURCE, ForecastRun.model == self.model.name,
                       ForecastRun.model_run_time == run_time)
            ).scalar_one()
        if existing:
            result.details["skipped"] = "run already stored"
            return result

        locations = self._locations()
        params = {
            **self._common_params(),
            "latitude": ",".join(f"{l['lat']:.4f}" for l in locations),
            "longitude": ",".join(f"{l['lon']:.4f}" for l in locations),
            "models": self.model.param,
            "forecast_days": self.settings.openmeteo_forecast_days,
        }
        context = {
            "model": self.model.name,
            "models_param": self.model.param,
            "meta_id": self.model.meta_id,
            "model_run_time": run_time.isoformat(),
            "available_at": meta["available_at"].isoformat() if meta["available_at"] else None,
            "temporal_resolution_seconds": meta["temporal_resolution_seconds"],
            "meta_raw_payload_id": meta_raw_id,
            "locations": locations,
        }
        fetched, _ = self._fetch_hourly(f"forecast.{self.model.name}", self._forecast_url(),
                                        self.model, params, context, result)

        meta_after, _ = self._meta()
        if meta_after["model_run_time"] != run_time:
            result.partial_errors.append(
                f"model run changed during fetch ({run_time.isoformat()} -> "
                f"{meta_after['model_run_time'].isoformat()}); raw kept, not normalized")
            with session_scope() as session:
                raw = session.get(RawPayload, fetched.raw_payload_id)
                raw.parse_status, raw.parse_error = "skipped", result.partial_errors[-1]
            return result

        result.records = self.normalize_fetched(fetched)
        return result

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        if raw.dataset.startswith("model_meta."):
            parse_meta(text)  # validates; the run itself is created with the forecast
            return 0
        ctx = raw.context or {}
        if not ctx.get("model_run_time"):
            raise SchemaMismatch("raw payload has no verified model_run_time in context")
        run_time = nz.parse_datetime(ctx["model_run_time"])
        run = get_or_create(
            session, ForecastRun,
            {"source": SOURCE, "model": ctx["model"], "model_run_time": run_time},
            {"available_at": nz.parse_datetime(ctx.get("available_at")), "fetched_at": raw.fetched_at,
             "temporal_resolution_seconds": ctx.get("temporal_resolution_seconds"),
             "meta_raw_payload_id": ctx.get("meta_raw_payload_id"),
             "meta": {"models_param": ctx.get("models_param"), "meta_id": ctx.get("meta_id")}},
        )
        soil = next((v for v in ctx.get("hourly", []) if v.startswith("soil_moisture_")), None)
        rows = build_rows(
            _json(text), model=ctx["model"], product="forecast", locations=ctx["locations"],
            model_run_time=run_time, forecast_run_id=run.id, raw_payload_id=raw.id, soil_variable=soil,
        )
        return upsert(session, WeatherForecast, rows, constraint="uq_weather_forecast_key")


class OpenMeteoHistoricalCollector(_OpenMeteoBase):
    """Historical Forecast API backfill for all models; job `openmeteo.historical_forecast`."""

    job = "openmeteo.historical_forecast"
    dataset_prefixes = ("historical_forecast",)

    @property
    def interval_minutes(self) -> int:
        return 24 * 60

    def configuration_status(self) -> str | None:
        if not self.settings.openmeteo_historical_enabled:
            return "DISABLED"
        return super().configuration_status()

    def _url(self) -> str:
        if self.settings.openmeteo_api_key:
            return self.settings.openmeteo_customer_historical_forecast_url
        return self.settings.openmeteo_historical_forecast_url

    def collect(self, start_date=None, end_date=None) -> CollectResult:
        result = CollectResult()
        today = nz.utcnow().date()
        end_date = end_date or (today - timedelta(days=1))
        start_date = start_date or (today - timedelta(days=self.settings.openmeteo_historical_lookback_days))
        locations = self._locations()
        result.details = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
        for model in self.settings.openmeteo_models:
            params = {
                **self._common_params(),
                "latitude": ",".join(f"{l['lat']:.4f}" for l in locations),
                "longitude": ",".join(f"{l['lon']:.4f}" for l in locations),
                "models": model.param,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
            context = {"model": model.name, "models_param": model.param, "locations": locations}
            try:
                fetched, _ = self._fetch_hourly(f"historical_forecast.{model.name}", self._url(),
                                                model, params, context, result)
                result.records += self.normalize_fetched(fetched, force=True)
            except SchemaMismatch as exc:
                result.parse_failures += 1
                result.partial_errors.append(f"{model.name}: {exc}")
            except Exception as exc:  # one model failing must not stop the others
                result.partial_errors.append(f"{model.name}: {exc}")
        if result.partial_errors and result.records == 0 and not result.parse_failures:
            raise AllRequestsFailed("; ".join(result.partial_errors))
        return result

    def normalize(self, session: Session, raw: RawPayload, text: str) -> int:
        ctx = raw.context or {}
        soil = next((v for v in ctx.get("hourly", []) if v.startswith("soil_moisture_")), None)
        rows = build_rows(
            _json(text), model=ctx["model"], product="historical_forecast", locations=ctx["locations"],
            model_run_time=None, forecast_run_id=None, raw_payload_id=raw.id, soil_variable=soil,
        )
        return upsert(session, WeatherForecast, rows, constraint="uq_weather_forecast_key",
                      update_columns=VALUE_COLUMNS + ["raw_payload_id", "soil_moisture_layer",
                                                      "grid_lat", "grid_lon", "grid_elevation_m"])


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise SchemaMismatch(f"response is not JSON: {exc}") from exc
