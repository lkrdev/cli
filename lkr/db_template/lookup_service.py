from typing import Optional
from looker_sdk.sdk.api40.methods import Looker40SDK
from looker_sdk.sdk.api40.models import CreateFolder, WriteDashboard

from lkr.logger import logger


class LookupService:
    def __init__(
        self,
        sdk: Looker40SDK,
        user_flag: str,
        user_flag_value: str,
        folder_path: Optional[str] = None,
        external_user_id: Optional[str] = None,
    ):
        self.sdk = sdk
        self.user_flag = user_flag
        self.user_flag_value = user_flag_value
        self.folder_path = folder_path
        self.external_user_id = external_user_id

    def _lookup_email(self) -> str:
        """Lookup user ID by email credential."""
        users = self.sdk.search_users(email=self.user_flag_value, fields="id")
        if users and len(users) > 0:
            return str(users[0].id)

        try:
            user = self.sdk.user_for_credential(
                credential_type="email", credential_id=self.user_flag_value, fields="id"
            )
            return str(user.id)
        except Exception as e:
            raise ValueError(f"No Looker user found with email '{self.user_flag_value}': {e}")

    def get_user_id(self) -> str:
        """Get the Looker User ID matching the current user-flag and user-flag-value."""
        if self.user_flag == "looker-user-id":
            return self.user_flag_value

        elif self.user_flag == "email":
            return self._lookup_email()

        elif self.user_flag == "external-user-id":
            try:
                user = self.sdk.user_for_credential(
                    credential_type="embed", credential_id=self.user_flag_value, fields="id"
                )
                return str(user.id)
            except Exception as e:
                raise ValueError(f"No Looker user found with external-user-id '{self.user_flag_value}': {e}")

        elif self.user_flag == "external-group-id":
            return self.get_sudo_user_id()

        else:
            raise ValueError(f"Unsupported user-flag: {self.user_flag}")

    def _lookup_space(self) -> str:
        """Lookup the parent folder (space) ID associated with the user/group flag."""
        if self.user_flag in ["looker-user-id", "email", "external-user-id"]:
            user_id = self.get_user_id()
            user = self.sdk.user(
                user_id=user_id,
                fields="personal_folder_id,home_folder_id,embed_group_folder_id",
            )
            folder_id = user.personal_folder_id or user.home_folder_id
            if not folder_id:
                raise ValueError(f"Could not find personal or home folder for user ID '{user_id}'")
            return str(folder_id)

        elif self.user_flag == "external-group-id":
            groups = self.sdk.search_groups(external_group_id=self.user_flag_value, fields="id")
            if not groups:
                raise ValueError(f"No Looker group found for external-group-id '{self.user_flag_value}'")
            
            folders = self.sdk.search_folders(name=self.user_flag_value, fields="id")
            if folders and len(folders) > 0:
                return str(folders[0].id)

            raise ValueError(f"Could not find parent folder for group '{self.user_flag_value}'")

        else:
            raise ValueError(f"Unsupported user-flag: {self.user_flag}")

    def _check_and_save_folder_path(self, parent_id: str, folder_name: str) -> str:
        """Check if child folder exists under parent_id; create it if it doesn't exist, and return its ID."""
        folders = self.sdk.search_folders(parent_id=parent_id, name=folder_name, fields="id")
        if folders and len(folders) > 0:
            return str(folders[0].id)

        new_folder = self.sdk.create_folder(
            body=CreateFolder(name=folder_name, parent_id=parent_id)
        )
        logger.info(f"Created folder '{folder_name}' under parent folder ID '{parent_id}'")
        return str(new_folder.id)

    def get_folder_path_folder_id(self, create_if_missing: bool = True) -> str:
        """Traverse the folder path starting from parent folder, creating folders along the way if requested."""
        parent_id = self._lookup_space()
        if not self.folder_path:
            return parent_id

        segments = [s.strip() for s in self.folder_path.strip("/").split("/") if s.strip()]
        current_parent_id = parent_id

        for segment in segments:
            if create_if_missing:
                current_parent_id = self._check_and_save_folder_path(current_parent_id, segment)
            else:
                folders = self.sdk.search_folders(parent_id=current_parent_id, name=segment, fields="id")
                if not folders or len(folders) == 0:
                    raise ValueError(f"Folder '{segment}' not found under parent folder ID '{current_parent_id}'")
                current_parent_id = str(folders[0].id)

        return current_parent_id

    def save_new_template(self, template_dashboard_id: str) -> str:
        """Copy the template dashboard to target folder, and reassign ownership to the user context."""
        target_folder_id = self.get_folder_path_folder_id(create_if_missing=True)

        logger.info(f"Copying template dashboard '{template_dashboard_id}' to folder ID '{target_folder_id}'")
        new_dashboard = self.sdk.copy_dashboard(
            dashboard_id=template_dashboard_id, folder_id=target_folder_id
        )
        new_dashboard_id = str(new_dashboard.id)

        if self.user_flag in ["looker-user-id", "email", "external-user-id"]:
            try:
                user_id = self.get_user_id()
                # Use partial dictionary mapping to reassign user ownership via transport layer
                self.sdk.update_dashboard(
                    dashboard_id=new_dashboard_id,
                    body={"user_id": user_id},  # type: ignore
                )
                logger.info(f"Assigned dashboard '{new_dashboard_id}' ownership to user ID '{user_id}'")
            except Exception as e:
                logger.warning(f"Failed to assign ownership of dashboard '{new_dashboard_id}' to user '{user_id}': {e}")

        return new_dashboard_id

    def validate_folder_path(
        self, dashboard_id: str, current_folder_path: Optional[str]
    ) -> Optional[str]:
        """Move the dashboard to a new folder if the folder path has changed."""
        if self.folder_path == current_folder_path:
            logger.info("Folder path is unchanged. No move required.")
            return None

        logger.info(f"Folder path changed from '{current_folder_path}' to '{self.folder_path}'. Moving dashboard '{dashboard_id}'...")
        new_folder_id = self.get_folder_path_folder_id(create_if_missing=True)

        self.sdk.update_dashboard(
            dashboard_id=dashboard_id,
            body=WriteDashboard(folder_id=new_folder_id),
        )
        logger.info(f"Successfully moved dashboard '{dashboard_id}' to folder ID '{new_folder_id}'")
        return new_folder_id

    def get_sudo_user_id(self) -> str:
        """Return the User ID to be sudo'd under."""
        if self.user_flag != "external-group-id":
            return self.get_user_id()

        groups = self.sdk.search_groups(external_group_id=self.user_flag_value, fields="id")
        if not groups:
            raise ValueError(f"No Looker group found for external-group-id '{self.user_flag_value}'")
        group_id = groups[0].id

        users = self.sdk.all_group_users(group_id=group_id, fields="id")
        if not users:
            raise ValueError(
                f"No users found belonging to external group '{self.user_flag_value}' (Group ID: {group_id})"
            )
        group_user_ids = {str(u.id) for u in users}

        if self.external_user_id:
            try:
                target_user = self.sdk.user_for_credential(
                    credential_type="embed", credential_id=self.external_user_id, fields="id"
                )
                target_user_id = str(target_user.id)
            except Exception as e:
                raise ValueError(f"No Looker user found with external-user-id '{self.external_user_id}': {e}")

            if target_user_id not in group_user_ids:
                raise ValueError(
                    f"Looker user with external-user-id '{self.external_user_id}' (ID: {target_user_id}) "
                    f"does not belong to the external group '{self.user_flag_value}' (Group ID: {group_id})"
                )
            return target_user_id

        return str(users[0].id)

    def run_templated_dashboard(
        self, template_dashboard_id: str, dashboard_filters: dict[str, str], sudo_user_id: str
    ):
        """Impersonate the specified user, resolve and run all dashboard element queries with the given filters."""
        logger.info(f"Impersonating user ID '{sudo_user_id}' to run dashboard queries...")
        self.sdk.auth.login_user(sudo_id=int(sudo_user_id))

        try:
            logger.debug(f"Retrieving dashboard elements for template dashboard '{template_dashboard_id}'...")
            dashboard = self.sdk.dashboard(dashboard_id=template_dashboard_id, fields="dashboard_elements")
            elements = dashboard.dashboard_elements or []

            logger.debug(f"Found {len(elements)} dashboard elements. Starting query execution...")
            for i, element in enumerate(elements):
                if not element.result_maker or not element.result_maker.query:
                    logger.debug(f"Skipping tile {i+1}: '{element.title or 'Untitled'}' (no query definition)")
                    continue

                query = element.result_maker.query
                logger.debug(f"Processing tile {i+1}: '{element.title or 'Untitled'}' (Base Query ID: {query.id})")

                filters_dict = {}
                if query.filters:
                    filters_dict = dict(query.filters)

                filterables = element.result_maker.filterables or []
                for filterable in filterables:
                    listens = filterable.listen or []
                    for listen in listens:
                        db_filter_name = listen.dashboard_filter_name
                        query_field = listen.field
                        if db_filter_name in dashboard_filters:
                            filters_dict[query_field] = dashboard_filters[db_filter_name]
                            logger.info(
                                f"  Mapped dashboard filter '{db_filter_name}' -> field '{query_field}' with value '{dashboard_filters[db_filter_name]}'"
                            )

                query_payload = {
                    "model": query.model,
                    "view": query.view,
                    "fields": list(query.fields) if query.fields else None,
                    "pivots": list(query.pivots) if query.pivots else None,
                    "fill_fields": list(query.fill_fields) if query.fill_fields else None,
                    "filters": filters_dict,
                    "filter_expression": query.filter_expression,
                    "sorts": list(query.sorts) if query.sorts else None,
                    "limit": query.limit,
                    "column_limit": query.column_limit,
                    "total": query.total,
                    "row_total": query.row_total,
                    "subtotals": list(query.subtotals) if query.subtotals else None,
                    "vis_config": dict(query.vis_config) if query.vis_config else None,
                    "dynamic_fields": query.dynamic_fields,
                    "query_timezone": query.query_timezone,
                }

                # Clean payload of None values to prevent SDK errors
                cleaned_payload = {k: v for k, v in query_payload.items() if v is not None}

                logger.debug(f"Creating filtered query with payload: {cleaned_payload}")
                new_query = self.sdk.create_query(body=cleaned_payload)  # type: ignore
                logger.debug(f"  Created new query: ID={new_query.id}")

                logger.debug(f"  Executing query ID={new_query.id}...")
                result = self.sdk.run_query(query_id=str(new_query.id), result_format="json")
                import json
                try:
                    rows = json.loads(result)
                    row_count = len(rows) if isinstance(rows, list) else 0
                    logger.debug(f"  Query execution completed successfully. Fetched {row_count} rows.")
                except Exception as parse_err:
                    logger.warning(f"  Query succeeded but output could not be parsed as JSON: {parse_err}")

        finally:
            self.sdk.auth.logout()
            logger.info("Successfully stopped impersonating user.")

