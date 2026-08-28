"""Full reference documentation and instructions for Looker Code Mode."""


def get_readme() -> str:
    return """
Looker Code Mode - Instructions & Examples

RULES & HINTS:
1. **SDK Access**: All Looker SDK methods are available as global functions (e.g., `me()`) or via the `sdk` object (e.g., `sdk.me()`).
2. **Dict Access**: Return values are dictionaries, not objects. Use `user["id"]`, not `user.id`.
3. **Discovery**: Use `dir()`, `help('pattern')`, `lookup('method_name')`, `lookup_type('TypeName')`, and `examples()` to explore the SDK.
4. **No Imports**: Do not `import looker_sdk`.
5. **Output**: Return your results instead of using `print()`.
6. **Efficiency**: Always use the `fields` parameter (e.g., `all_dashboards(fields="id,title")`) when listing many objects to prevent timeouts.
7. **Nested Folders**: Use `folder_children(id)` to get sub-folders.
8. **Injected CLI Variables**: When using `sandbox` with `--var key=value` flags, those variables are directly available in your code as top-level string constants.

EXAMPLES:

Example 1: Find all dashboard-related methods
return help('dashboard')

Example 2: Get description of a specific method
return lookup('search_dashboards')

Example 3: Lookup a type definition
return lookup_type('User')

Example 4: Search and return full details for all matches
return search_with_lookups('board_item')

Example 5: Get personal folder dashboards
user = me()
personal_folder = folder(user["personal_folder_id"])
return personal_folder.get("dashboards", [])

Example 6: Run an inline query on thelook (order_items)
return run_inline_query(
    result_format="json",
    body={
        "model": "thelook",
        "view": "order_items",
        "fields": ["order_items.created_year", "users.count"],
        "filters": {"order_items.status": "Returned"},
        "sorts": ["order_items.created_year desc"],
        "limit": "500"
    }
)

Example 7: List personal dashboards & looks (Recursive traversal)
def get_all_items(folder_id):
    f = folder(folder_id)
    items = {
        "dashboards": f.get("dashboards", []),
        "looks": f.get("looks", [])
    }
    for child in folder_children(folder_id):
        child_items = get_all_items(child["id"])
        items["dashboards"].extend(child_items["dashboards"])
        items["looks"].extend(child_items["looks"])
    return items

me_data = me()
return get_all_items(me_data["personal_folder_id"])
"""
