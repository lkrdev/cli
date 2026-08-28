"""Built-in Looker Code Mode examples."""

EXAMPLES = [
    [
        "Find all dashboard-related methods",
        "return [m for m in dir() if 'dashboard' in m.lower()]",
    ],
    [
        "Get the description of a specific method",
        "return help('search_dashboards')",
    ],
    [
        "Get personal folder dashboards",
        """user = me()
personal_folder = folder(user["personal_folder_id"])
return personal_folder.get("dashboards", [])""",
    ],
    [
        "Run an inline query on thelook (order_items)",
        """return run_inline_query(
    result_format="json",
    body={
        "model": "thelook",
        "view": "order_items",
        "fields": ["order_items.created_year", "users.count"],
        "filters": {"order_items.status": "Returned"},
        "sorts": ["order_items.created_year desc"],
        "limit": "500"
    }
)""",
    ],
    [
        "List personal dashboards & looks (recursive)",
        """def get_all_items(folder_id):
    f = folder(folder_id)
    items = {"dashboards": f.get("dashboards", []), "looks": f.get("looks", [])}
    for child in folder_children(folder_id):
        child_items = get_all_items(child["id"])
        items["dashboards"].extend(child_items["dashboards"])
        items["looks"].extend(child_items["looks"])
    return items

me_data = me()
return get_all_items(me_data["personal_folder_id"])""",
    ],
]
