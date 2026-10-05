from typing import Any

VALUE_FORMAT_MAP: dict[str, str] = {
    "usd": "$#,##0.00",
    "usd_0": "$#,##0",
    "eur": "€#,##0.00",
    "eur_0": "€#,##0",
    "gbp": "£#,##0.00",
    "gbp_0": "£#,##0",
    "decimal_0": "#,##0",
    "decimal_1": "#,##0.0",
    "decimal_2": "#,##0.00",
    "decimal_3": "#,##0.000",
    "decimal_4": "#,##0.0000",
    "percent_0": "#,##0%",
    "percent_1": "#,##0.0%",
    "percent_2": "#,##0.00%",
    "percent_3": "#,##0.000%",
    "percent_4": "#,##0.0000%",
    "id": "0",
}

DISTANCE_UNIT_FORMATS: dict[str, str] = {
    "feet": '#,##0.00" ft"',
    "kilometers": '#,##0.00" km"',
    "meters": '#,##0.00" m"',
    "miles": '#,##0.00" mi"',
    "nautical_miles": '#,##0.00" nmi"',
    "yards": '#,##0.00" yd"',
}

BUILTIN_MAP_LAYERS: dict[str, dict[str, Any]] = {
    "countries": {
        "extents_json_url": None,
        "feature_key": "world",
        "format": "",
        "max_zoom_level": None,
        "min_zoom_level": None,
        "name": "countries",
        "projection": "kavrayskiy7",
        "property_key": None,
        "property_label_key": "name",
        "url": "/data/world_noantarctica.topo-545fce41cc.json",
    },
    "us_states": {
        "extents_json_url": None,
        "feature_key": "usa",
        "format": "",
        "max_zoom_level": None,
        "min_zoom_level": None,
        "name": "us_states",
        "projection": "albersUsa",
        "property_key": None,
        "property_label_key": None,
        "url": "/data/us_states.topo-402e425f99.json",
    },
    "uk_postcode_areas": {
        "extents_json_url": None,
        "feature_key": "Areas",
        "format": "",
        "max_zoom_level": None,
        "min_zoom_level": None,
        "name": "uk_postcode_areas",
        "projection": "mercator",
        "property_key": None,
        "property_label_key": None,
        "url": "/data/uk_postcode_areas.topo-9e651b39d2.json",
    },
    "us_zipcode_tabulation_areas": {
        "extents_json_url": "https://maps-tiles-b.lookercdn.com/us_zcta510/extents.json",
        "feature_key": "tl_2016_us_zcta510geojson",
        "format": "vector_tile_region",
        "max_zoom_level": 12,
        "min_zoom_level": None,
        "name": "us_zipcode_tabulation_areas",
        "projection": None,
        "property_key": "ZCTA5CE10",
        "property_label_key": None,
        "url": "https://maps-tiles-a.lookercdn.com/us_zcta510/{z}/{x}/{y}.pbf",
    },
}

_DAYS: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)

_MONTHS: tuple[str, ...] = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

DEFAULT_ENUMS: dict[str, list[dict[str, str]]] = {
    "date_day_of_week": [{"label": d, "value": d} for d in _DAYS],
    "date_day_of_week_index": [
        {"label": f"{i} - {d}", "value": str(i)} for i, d in enumerate(_DAYS)
    ],
    "date_month_name": [{"label": m, "value": m} for m in _MONTHS],
    "date_quarter_of_year": [
        {"label": f"Q{i}", "value": f"Q{i}"} for i in range(1, 5)
    ],
    "date_fiscal_quarter_of_year": [
        {"label": f"Q{i}", "value": f"Q{i}"} for i in range(1, 5)
    ],
    "yesno": [{"label": "Yes", "value": "Yes"}, {"label": "No", "value": "No"}],
}

TIMEFRAME_INTERVALS: dict[str, dict[str, Any]] = {
    "date": {"name": "day", "count": 1},
    "date_date": {"name": "day", "count": 1},
    "date_fiscal_quarter": {"name": "month", "count": 3},
    "date_fiscal_year": {"name": "year", "count": 1},
    "date_hour": {"name": "hour", "count": 1},
    **{f"date_hour{n}": {"name": "hour", "count": n} for n in (2, 3, 4, 6, 8, 12)},
    "date_microsecond": {"name": "microsecond", "count": 1},
    "date_millisecond": {"name": "millisecond", "count": 1},
    **{
        f"date_millisecond{n}": {"name": "millisecond", "count": n}
        for n in (2, 4, 5, 8, 10, 20, 25, 40, 50, 100, 125, 200, 250, 500)
    },
    "date_minute": {"name": "minute", "count": 1},
    **{
        f"date_minute{n}": {"name": "minute", "count": n}
        for n in (2, 3, 4, 5, 6, 10, 12, 15, 20, 30)
    },
    "date_month": {"name": "month", "count": 1},
    "date_quarter": {"name": "month", "count": 3},
    "date_second": {"name": "second", "count": 1},
    "date_time": {"name": "second", "count": 1},
    "date_week": {"name": "week", "count": 1},
    "date_year": {"name": "year", "count": 1},
}

NUMERIC_DIMENSION_TYPES: frozenset[str] = frozenset(
    {
        "number",
        "int",
        "date_day_of_month",
        "date_day_of_week_index",
        "date_day_of_year",
        "date_fiscal_month_num",
        "date_hour_of_day",
        "date_month_num",
        "date_week_of_year",
        "distance",
        "duration_day",
        "duration_hour",
        "duration_minute",
        "duration_month",
        "duration_quarter",
        "duration_second",
        "duration_week",
        "duration_year",
    }
)

NON_NUMERIC_MEASURE_TYPES: frozenset[str] = frozenset(
    {"list", "string", "yesno", "zipcode", "date"}
)

RANGE_FILL_TYPES: frozenset[str] = frozenset(
    {
        "date",
        "date_date",
        "date_fiscal_quarter",
        "date_fiscal_year",
        "date_hour",
        "date_minute",
        "date_month",
        "date_quarter",
        "date_week",
        "date_year",
    }
)

ENUM_FILL_TYPES: frozenset[str] = frozenset(
    {
        "date_day_of_month",
        "date_day_of_week",
        "date_day_of_week_index",
        "date_day_of_year",
        "date_fiscal_month_num",
        "date_fiscal_quarter_of_year",
        "date_hour_of_day",
        "date_month_name",
        "date_month_num",
        "date_quarter_of_year",
        "date_time_of_day",
        "date_week_of_year",
        "tier",
        "yesno",
    }
)

SUGGESTABLE_TYPES: frozenset[str] = frozenset(
    {
        "string",
        "tier",
        "yesno",
        "zipcode",
        "unquoted",
        "date_day_of_week",
        "date_fiscal_quarter_of_year",
        "date_month_name",
        "date_quarter_of_year",
    }
)

LOWERCASE_TITLE_WORDS: frozenset[str] = frozenset(
    {"of", "in", "to", "with", "for", "and", "or", "on", "at"}
)

SQL_TO_LOOKML_DOC: dict[str, str] = {
    "queries[].views": "LookML views matching query tables (direct table matches and transitive references)",
    "queries[].views[].fields[].via": "Transitive dependency path of ${...} references in LookML DAG leading to this field",
    "queries[].views[].fields[].explores": "Explores exposing this field with active view alias and join info",
    "queries[].views[].fields[].tests": "Existing LookML tests associated with this field that must pass",
    "queries[].views[].unmodeled_db_columns": "Columns present in the database table or SQL query that have no matching field in this LookML view",
    "queries[].views[].missing_db_columns": "Physical columns referenced by this LookML view (${TABLE}.col) that do not exist in the database table",
    "queries[].explores": "All reachable explores exposing any matched fields from this query",
    "queries[].tests": "All existing LookML tests across the LookML DAG that must still pass after changes",
}

__all__ = [
    "BUILTIN_MAP_LAYERS",
    "DEFAULT_ENUMS",
    "DISTANCE_UNIT_FORMATS",
    "ENUM_FILL_TYPES",
    "LOWERCASE_TITLE_WORDS",
    "NON_NUMERIC_MEASURE_TYPES",
    "NUMERIC_DIMENSION_TYPES",
    "RANGE_FILL_TYPES",
    "SQL_TO_LOOKML_DOC",
    "SUGGESTABLE_TYPES",
    "TIMEFRAME_INTERVALS",
    "VALUE_FORMAT_MAP",
    "_DAYS",
    "_MONTHS",
]
