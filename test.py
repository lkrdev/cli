from lkr.tools.classes import UserAttributeUpdater


updater = UserAttributeUpdater(
    user_attribute="test",
    value="test",
    update_type="default",
)
print(updater.model_dump_json())







