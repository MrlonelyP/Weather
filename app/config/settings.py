"""Application settings, loaded from environment variables / `.env`.

Every secret (API keys, DB password) comes from the environment only.
Nothing here contains measured data.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenMeteoModel(BaseModel):
    """One Open-Meteo weather model we collect (Data Sources WX-01..03).

    - name:      our label, stored in weather_forecast.model (e.g. "ECMWF")
    - endpoint:  model API path under https://api.open-meteo.com/v1/ (ecmwf | gfs | jma)
    - param:     value passed as `&models=` to pin one specific model
    - meta_id:   id of the model-update metadata file
                 (`/data/{meta_id}/static/meta.json`) that gives the model run
                 (initialisation) time. Open-Meteo does not return the run time
                 in the forecast response, so we read it from here.
    - extra_hourly: model specific variables (e.g. soil moisture layer names differ)
    """

    name: str
    endpoint: str
    param: str
    meta_id: str
    extra_hourly: list[str] = []


DEFAULT_OPENMETEO_MODELS = [
    OpenMeteoModel(name="ECMWF", endpoint="ecmwf", param="ecmwf_ifs", meta_id="ecmwf_ifs",
                   extra_hourly=["soil_moisture_0_to_7cm"]),
    OpenMeteoModel(name="GFS", endpoint="gfs", param="gfs_global", meta_id="ncep_gfs013",
                   extra_hourly=["soil_moisture_0_to_10cm"]),
    OpenMeteoModel(name="JMA", endpoint="jma", param="jma_gsm", meta_id="jma_gsm"),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Core -------------------------------------------------------------
    database_url: str = "postgresql+psycopg://flood:flood@localhost:5432/flood_intel"
    log_level: str = "INFO"
    display_timezone: str = "Asia/Bangkok"
    # Run the APScheduler inside the API process (convenient for dev).
    # For long-running collection run `python -m app.scheduler` as its own process.
    run_scheduler_in_api: bool = False
    # comma separated origins allowed to call the API from a browser (e.g. the Next.js dev server).
    # Not needed when the frontend proxies /api through its own server.
    cors_origins: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # --- HTTP defaults (every collector) -----------------------------------
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 3
    http_backoff_base_seconds: float = 2.0
    http_backoff_max_seconds: float = 60.0
    http_user_agent: str = "ThailandWeatherFloodIntel-Phase0/0.1"

    # --- Health -----------------------------------------------------------
    # consecutive failed runs before a job is reported UNAVAILABLE
    health_unavailable_after_failures: int = 3
    # a job is STALE when its last success is older than interval * factor
    health_stale_factor: float = 3.0

    # --- Open-Meteo (WX-01..04) -------------------------------------------
    openmeteo_enabled: bool = True
    # Optional commercial key. When set, the customer-* hosts are used.
    openmeteo_api_key: str | None = None
    openmeteo_base_url: str = "https://api.open-meteo.com/v1"
    openmeteo_customer_base_url: str = "https://customer-api.open-meteo.com/v1"
    openmeteo_historical_forecast_url: str = "https://historical-forecast-api.open-meteo.com/v1/forecast"
    openmeteo_customer_historical_forecast_url: str = (
        "https://customer-historical-forecast-api.open-meteo.com/v1/forecast"
    )
    openmeteo_meta_url_template: str = "https://api.open-meteo.com/data/{meta_id}/static/meta.json"
    openmeteo_models: list[OpenMeteoModel] = DEFAULT_OPENMETEO_MODELS
    openmeteo_forecast_days: int = 16
    openmeteo_hourly_variables: str = (
        "temperature_2m,relative_humidity_2m,precipitation,rain,precipitation_probability,"
        "pressure_msl,cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
    )
    openmeteo_poll_minutes: int = 30
    openmeteo_historical_enabled: bool = True
    openmeteo_historical_hour_utc: int = 2  # daily re-fetch of the last N days
    openmeteo_historical_lookback_days: int = 3

    # --- TMD telecom API (TMD-01..03), public -----------------------------
    tmd_enabled: bool = True
    tmd_base_url: str = "https://telecom.tmd.go.th/api/ftp"
    # Query parameter names documented as "date/country/utc" (see docs/DATA_SOURCES.md).
    tmd_param_date: str = "date"
    tmd_param_country: str = "country"
    tmd_param_utc: str = "utc"
    tmd_date_format: str = "%Y-%m-%d"
    tmd_country: str = "TH"
    tmd_synoptic_enabled: bool = True
    tmd_warning_enabled: bool = True
    tmd_metar_enabled: bool = False  # TMD-02 is P1: raw archive only, enable later
    tmd_synoptic_poll_minutes: int = 60
    tmd_synoptic_lookback_hours: int = 6  # re-request recent synoptic hours (late bulletins)
    tmd_warning_poll_minutes: int = 30
    tmd_metar_poll_minutes: int = 30
    # station metadata (coordinates); TMD's published example credentials by default
    tmd_stations_enabled: bool = True
    tmd_station_url: str = "https://data.tmd.go.th/api/Station/v1/"
    tmd_station_uid: str | None = "api"
    tmd_station_ukey: str | None = "api12345"
    # WMO block prefix(es) of stations to normalize (48 = Thailand)
    tmd_wmo_prefixes: str = "48"

    # --- RID reservoir API (RID-01..02), public ----------------------------
    rid_enabled: bool = True
    rid_dam_url: str = "https://app.rid.go.th/reservoir/api/dam/public"
    rid_medium_url: str = "https://app.rid.go.th/reservoir/api/reservoir/public"
    rid_medium_enabled: bool = False  # RID-02 is P1
    # Historical query: `{url}/{date}` with date YYYY-MM-DD (Asia/Bangkok)
    rid_date_path_format: str = "{url}/{date}"
    rid_poll_minutes: int = 180
    rid_lookback_days: int = 2

    # --- GISTDA (GIS-01..02), API key required -----------------------------
    gistda_enabled: bool = True
    gistda_api_key: str | None = None
    gistda_api_key_header: str = "API-Key"
    # GIS-01: point check "is lat/lon inside a satellite-detected flood extent"
    gistda_point_check_url: str = (
        "https://api-gateway.gistda.or.th/api/2.0/resources/gi-service/v1.0/disasters/flood-extent-1day"
    )
    gistda_point_param_lat: str = "lat"
    gistda_point_param_lon: str = "lon"
    # GIS-02: flood polygons (GeoJSON FeatureCollection). Endpoint must be taken
    # from https://disaster.gistda.or.th/services/open-api once a key is issued.
    gistda_flood_polygon_url: str | None = None
    gistda_page_limit: int = 1000
    gistda_max_pages: int = 50
    gistda_poll_minutes: int = 360

    # --- ThaiWater / HII national water API (TW-01, TW-02), public --------
    thaiwater_enabled: bool = True
    thaiwater_base_url: str = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public"
    thaiwater_waterlevel_enabled: bool = True
    thaiwater_rain_enabled: bool = True
    thaiwater_poll_minutes: int = 60
    # provinces whose station history is backfilled/refreshed for trend (TIS-1099 codes)
    thaiwater_history_provinces: str = "10,11,12,13,14,73,74"
    thaiwater_history_poll_minutes: int = 360
    thaiwater_history_hours: int = 24  # scheduled refresh window; CLI backfill can go up to 7 days

    # --- Terrain / DEM (static data, see app/config/terrain.json) ------------
    # GeoTIFF tiles live here as files (not in PostGIS); keep it on a persistent volume
    dem_data_dir: str = "data/dem"
    # datasets to download/use; both are 1 arc-second (~30 m)
    terrain_datasets: str = "copernicus_glo30,fabdem_v1_2"
    # dataset whose result is shown first. fabdem_v1_2 is bare-earth (better in towns) but
    # CC BY-NC-SA (non-commercial only); set copernicus_glo30 for a commercial deployment.
    terrain_primary_dataset: str = "fabdem_v1_2"
    terrain_download_workers: int = 4
    terrain_download_timeout_seconds: float = 600.0

    @property
    def thaiwater_history_provinces_list(self) -> list[str]:
        return [p.strip() for p in self.thaiwater_history_provinces.split(",") if p.strip()]

    @property
    def terrain_dataset_list(self) -> list[str]:
        return [d.strip() for d in self.terrain_datasets.split(",") if d.strip()]

    @property
    def openmeteo_hourly_list(self) -> list[str]:
        return [v.strip() for v in self.openmeteo_hourly_variables.split(",") if v.strip()]

    @property
    def tmd_wmo_prefix_list(self) -> list[str]:
        return [p.strip() for p in self.tmd_wmo_prefixes.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
