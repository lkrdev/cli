import typer
from typing import Annotated, Optional

from lkr.auth_service import get_auth
from lkr.logger import logger

__all__ = ["group"]

group = typer.Typer()


@group.command(
    name="no-results",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def no_results(
    ctx: typer.Context,
    template_dashboard_id: Annotated[
        str,
        typer.Argument(help="The template dashboard ID to look up"),
    ],
    looker_user_id: Annotated[
        Optional[str],
        typer.Option("--looker-user-id", help="Looker User ID"),
    ] = None,
    email: Annotated[
        Optional[str],
        typer.Option("--email", help="Email address"),
    ] = None,
    external_group_id: Annotated[
        Optional[str],
        typer.Option("--external-group-id", help="External Group ID"),
    ] = None,
    external_user_id: Annotated[
        Optional[str],
        typer.Option("--external-user-id", help="External User ID"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Do nothing, dry run placeholder"),
    ] = False,
    folder_path: Annotated[
        Optional[str],
        typer.Option("--folder-path", help="Where the nested folder should be"),
    ] = None,
    delete: Annotated[
        bool,
        typer.Option("--delete", help="Delete the user's dashboard and the artifact item"),
    ] = False,
    dashboard_query_string: Annotated[
        Optional[str],
        typer.Option("--dashboard-query-string", help="Dashboard filter query string"),
    ] = None,
):
    """
    Lookup template dashboard and prepare db-template with no results.
    """
    provided_opts = {
        "--looker-user-id": looker_user_id,
        "--email": email,
        "--external-group-id": external_group_id,
        "--external-user-id": external_user_id,
    }
    non_null_opts = {k: v for k, v in provided_opts.items() if v is not None}

    if len(non_null_opts) == 0:
        raise typer.BadParameter(
            "At least one of --looker-user-id, --email, --external-group-id, or --external-user-id must be specified."
        )

    if looker_user_id is not None and len(non_null_opts) > 1:
        raise typer.BadParameter("Option --looker-user-id is mutually exclusive with all other options.")
    if email is not None and len(non_null_opts) > 1:
        raise typer.BadParameter("Option --email is mutually exclusive with all other options.")

    if external_group_id is not None:
        selected_opt, selected_val = "--external-group-id", external_group_id
    else:
        selected_opt, selected_val = list(non_null_opts.items())[0]

    user_flag = selected_opt.lstrip("-")

    extra_filters = {}
    it = iter(ctx.args)
    for arg in it:
        if arg.startswith("--"):
            filter_name = arg.lstrip("-")
            try:
                filter_value = next(it)
                extra_filters[filter_name] = filter_value
            except StopIteration:
                raise typer.BadParameter(f"Option '{arg}' requires a value.")

    if delete:
        logger.info(
            f"Requested delete for artifact key with {selected_opt}='{selected_val}' and template_dashboard_id='{template_dashboard_id}'"
        )
        if dry_run:
            logger.info("Dry run is active. Skipping actual delete operations.")
            return

        try:
            sdk = get_auth(ctx).get_current_sdk()
            from lkr.db_template.artifact_service import ArtifactService
            artifact_service = ArtifactService(sdk)

            artifact = artifact_service.get_artifact(
                user_flag=user_flag,
                user_flag_value=selected_val,
                template_dashboard_id=template_dashboard_id,
            )

            if not artifact:
                logger.info("No existing artifact found to delete.")
                return

            # Delete the user's dashboard if it exists
            if artifact.new_dashboard_id:
                try:
                    sdk.delete_dashboard(dashboard_id=artifact.new_dashboard_id)
                    logger.info(f"Successfully deleted dashboard: ID='{artifact.new_dashboard_id}'")
                except Exception as delete_err:
                    logger.warning(f"Failed to delete dashboard '{artifact.new_dashboard_id}' from Looker: {delete_err}")

            # Delete the artifact item
            artifact_service.delete_artifact(
                user_flag=user_flag,
                user_flag_value=selected_val,
                template_dashboard_id=template_dashboard_id,
            )
        except Exception as e:
            logger.error(f"Error in delete operation: {e}")
            raise typer.Exit(code=1)
        return

    logger.info(
        f"Looking up template dashboard '{template_dashboard_id}' with option {selected_opt}='{selected_val}'"
    )

    if dry_run:
        logger.info("Dry run is active. No operations performed.")
        return

    try:
        sdk = get_auth(ctx).get_current_sdk()
        dashboard = sdk.dashboard(dashboard_id=template_dashboard_id)
        
        title = dashboard.title or "Untitled"
        logger.info(f"Successfully retrieved dashboard: ID='{dashboard.id}', Title='{title}'")

        # Artifact and Lookup management
        from lkr.db_template.artifact_service import ArtifactService, DbTemplateArtifact
        from lkr.db_template.lookup_service import LookupService
        artifact_service = ArtifactService(sdk)

        user_flag = selected_opt.lstrip("-")
        lookup_service = LookupService(
            sdk=sdk,
            user_flag=user_flag,
            user_flag_value=selected_val,
            folder_path=folder_path,
            external_user_id=external_user_id,
        )

        artifact = artifact_service.get_artifact(
            user_flag=user_flag,
            user_flag_value=selected_val,
            template_dashboard_id=template_dashboard_id,
        )

        # Determine the effective query string (prefer CLI option, fallback to artifact)
        effective_qs = dashboard_query_string
        if effective_qs is None and artifact is not None:
            effective_qs = artifact.dashboard_query_string

        # Parse dashboard filters from the query string
        import urllib.parse
        dashboard_filters = {}
        if effective_qs:
            qs = effective_qs
            if qs.startswith("?"):
                qs = qs[1:]
            dashboard_filters = dict(urllib.parse.parse_qsl(qs))
            logger.info(f"Parsed dashboard filters from query string: {dashboard_filters}")

        for k, v in extra_filters.items():
            dashboard_filters[k] = v
            logger.info(f"Command-line flag filter '{k}' = '{v}' (overwrote or added to query string)")

        logger.info(f"Effective dashboard filters to apply: {dashboard_filters}")

        if artifact:
            logger.info(
                f"Found existing artifact: Key='{artifact_service.generate_key(user_flag, selected_val, template_dashboard_id)}', "
                f"NewDashboardID='{artifact.new_dashboard_id}', CreatedAt='{artifact.created_at}'"
            )
            # If we have a new dashboard ID and folder path changed, move it
            needs_save = False
            if artifact.new_dashboard_id:
                moved_folder_id = lookup_service.validate_folder_path(
                    dashboard_id=artifact.new_dashboard_id,
                    current_folder_path=artifact.folder_path,
                )
                if moved_folder_id:
                    artifact.folder_path = folder_path
                    needs_save = True

            if dashboard_query_string is not None and dashboard_query_string != artifact.dashboard_query_string:
                artifact.dashboard_query_string = dashboard_query_string
                needs_save = True

            if needs_save:
                artifact_service.save_artifact(artifact)
        else:
            logger.info("No existing artifact found. Templating new dashboard.")
            new_dashboard_id = lookup_service.save_new_template(
                template_dashboard_id=template_dashboard_id
            )

            artifact = DbTemplateArtifact(
                template_dashboard_id=template_dashboard_id,
                folder_path=folder_path,
                user_flag=user_flag,
                user_flag_value=selected_val,
                new_dashboard_id=new_dashboard_id,
                dashboard_query_string=dashboard_query_string,
            )
            artifact_service.save_artifact(artifact)

        # Run all templated queries as impersonated user
        try:
            sudo_user_id = lookup_service.get_sudo_user_id()
            lookup_service.run_templated_dashboard(
                template_dashboard_id=template_dashboard_id,
                dashboard_filters=dashboard_filters,
                sudo_user_id=sudo_user_id,
            )
        except Exception as run_err:
            logger.warning(f"Failed to execute templated dashboard queries: {run_err}")

    except Exception as e:
        logger.error(f"Error in no-results command: {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    group()
