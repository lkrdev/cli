# ruff: noqa: F821
"""Recursively traverse folders starting from personal folder to gather all dashboards and looks."""


def get_all_items(folder_id):
    if not folder_id:
        return {"dashboards": [], "looks": []}
    f = folder(folder_id)  # ty: ignore[unresolved-reference]
    if not f:
        return {"dashboards": [], "looks": []}
    items = {"dashboards": f.get("dashboards", []), "looks": f.get("looks", [])}
    children = folder_children(folder_id) or []  # ty: ignore[unresolved-reference]
    for child in children:
        child_items = get_all_items(child.get("id"))
        items["dashboards"].extend(child_items["dashboards"])
        items["looks"].extend(child_items["looks"])
    return items


def main():
    user_data = me()  # ty: ignore[unresolved-reference]
    if not user_data or not user_data.get("personal_folder_id"):
        return {"dashboards": [], "looks": []}
    return get_all_items(user_data["personal_folder_id"])


main()
