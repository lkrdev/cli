# ruff: noqa: F821
"""Migrate a LookML dashboard to a User-Defined Dashboard (UDD).

Usage:
  uvx --from "lkr-dev-cli[codemode]" lkr-dev-cli code-mode sandbox \
    --file=skills/lkr-project-helper/scripts/migrate_dashboard_to_udd.py \
    --var dashboard_id="model_name::dashboard_name" \
    [--var space_id="1"]
"""


def main():
    dash_id = globals().get("dashboard_id", "")
    target_folder = globals().get("space_id", "1")

    if not dash_id:
        return {
            "error": "Missing dashboard_id parameter (e.g. model_name::dashboard_name)"
        }

    udd = import_lookml_dashboard(  # ty: ignore[unresolved-reference]
        lookml_dashboard_id=dash_id,
        space_id=str(target_folder),
        body={},
    )

    udd_id = (
        udd.get("id") if isinstance(udd, dict) else getattr(udd, "id", str(udd))
    )
    udd_title = (
        udd.get("title") if isinstance(udd, dict) else getattr(udd, "title", "")
    )

    return {
        "lookml_dashboard_id": dash_id,
        "udd_id": udd_id,
        "udd_title": udd_title,
        "url": f"/dashboards/{udd_id}",
    }


main()
