"""station measures: keep dual (level + rain) ThaiWater stations as river stations

ThaiWater telemetry stations often report water level and rain under one station id.
Earlier runs let the last collector decide station_kind, so a river station could be
re-labelled rain_gauge. This records what each station reports (extra.measures) from the
observations already stored and makes every station with a water level a river station.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        WITH m AS (
            SELECT station_id,
                   bool_or(water_level_m IS NOT NULL) AS lvl,
                   bool_or(rain_mm IS NOT NULL OR rain_1h_mm IS NOT NULL) AS rain
            FROM water_level_observation GROUP BY station_id)
        UPDATE water_station ws SET
            extra = coalesce(ws.extra, '{}'::jsonb) || jsonb_build_object('measures',
                (SELECT coalesce(jsonb_agg(x ORDER BY x), '[]'::jsonb) FROM unnest(ARRAY[
                    CASE WHEN m.rain THEN 'rain' END, CASE WHEN m.lvl THEN 'water_level' END]) x WHERE x IS NOT NULL)),
            station_kind = CASE WHEN m.lvl THEN 'river' ELSE ws.station_kind END
        FROM m WHERE m.station_id = ws.id AND ws.source = 'thaiwater'
    """)


def downgrade() -> None:
    op.execute("UPDATE water_station SET extra = extra - 'measures' WHERE extra ? 'measures'")
