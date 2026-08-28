# ruff: noqa: F706, F821
"""Get current user's personal folder ID and list all dashboards inside it."""

user = me()
personal_folder_id = user["personal_folder_id"]
personal_folder = folder(personal_folder_id)

return {
    "user_id": user.get("id"),
    "user_email": user.get("email"),
    "personal_folder_id": personal_folder_id,
    "dashboards": personal_folder.get("dashboards", []),
}
