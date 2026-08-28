# ruff: noqa: F821
"""Get current user's personal folder ID and list all dashboards inside it."""


def main():
    user = me()  # ty: ignore[unresolved-reference]
    if not user:
        return {"error": "Unable to retrieve current user metadata."}

    personal_folder_id = user.get("personal_folder_id")
    if not personal_folder_id:
        return {"error": "User does not have a personal folder configured."}

    personal_folder = folder(personal_folder_id)  # ty: ignore[unresolved-reference]
    if not personal_folder:
        return {"error": f"Unable to retrieve folder with ID {personal_folder_id}."}

    return {
        "user_id": user.get("id"),
        "user_email": user.get("email"),
        "personal_folder_id": personal_folder_id,
        "dashboards": personal_folder.get("dashboards", []),
    }


main()
