# ruff: noqa: F706, F821
"""Recursively traverse folders starting from personal folder to gather all dashboards and looks."""


def get_all_items(folder_id):
    f = folder(folder_id)
    items = {"dashboards": f.get("dashboards", []), "looks": f.get("looks", [])}
    for child in folder_children(folder_id):
        child_items = get_all_items(child["id"])
        items["dashboards"].extend(child_items["dashboards"])
        items["looks"].extend(child_items["looks"])
    return items


user_data = me()
return get_all_items(user_data["personal_folder_id"])
