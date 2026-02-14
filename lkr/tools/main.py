import os
import csv
import sys
from typing import Annotated, Optional

import typer
import uvicorn
from fastapi import FastAPI, Request

from lkr.logger import structured_logger as logger
from lkr.tools.classes import AttributeUpdaterResponse, UserAttributeUpdater
from lkr.tools.permission_deprecation import schedule_download_deprecation

__all__ = ["group"]

group = typer.Typer()

if not logger:
    raise Exception("Logger is not available")


@group.command()
def user_attribute_updater(
    host: str = typer.Option(default="127.0.0.1", envvar="HOST"),
    port: int = typer.Option(default=8080, envvar="PORT"),
):
    api = FastAPI()

    @api.post("/identity_token")
    def identity_token(request: Request, body: UserAttributeUpdater):
        try:
            body.get_request_authorization_for_value(request.headers.items())
            body.update_user_attribute_value()
            raw_urls = os.getenv("LOOKER_WHITELISTED_BASE_URLS", "")
            whitelisted_base_urls = (
                [url.strip() for url in raw_urls.split(",") if url.strip()]
                if raw_urls
                else []
            )
            logger.debug(
                "identify_token_user_attribute",
                **body.model_dump(),
                whitelisted_base_urls=whitelisted_base_urls,
            )

            if body.base_url not in whitelisted_base_urls:
                raise Exception(f"Base URL {body.base_url} not whitelisted")

            return AttributeUpdaterResponse(
                success=True, message="User attribute updated"
            )
        except Exception as e:
            return AttributeUpdaterResponse(success=False, message=str(e))

    @api.delete("/value")
    def delete_user_attribute_value(request: Request, body: UserAttributeUpdater):
        try:
            body.delete_user_attribute_value()
            logger.debug(
                "user_attribute_delete",
                **body.model_dump(),
            )
            return AttributeUpdaterResponse(
                success=True, message="User attribute value deleted"
            )
        except Exception as e:
            return AttributeUpdaterResponse(success=False, message=str(e))

    @api.post("/value")
    def update_user_attribute_value(request: Request, body: UserAttributeUpdater):
        try:
            body.update_user_attribute_value()
            logger.debug(
                "user_attribute_update",
                **body.model_dump(),
            )
            return AttributeUpdaterResponse(
                success=True, message="User attribute value updated"
            )
        except Exception as e:
            return AttributeUpdaterResponse(success=False, message=str(e))

    @api.get("")
    def health():
        return {"status": "ok"}

    uvicorn.run(api, host=host, port=port)


PERMISSION_MAP = {
    "download_with_limit": "dwl",
    "download_without_limit": "dwol",
    "schedule_look_emails": "sle",
    "schedule_external_look_emails": "sele",
    "send_to_s3": "s3",
    "send_to_sftp": "sftp",
    "send_outgoing_webhook": "hook",
    "send_to_integration": "intg",
}


def get_visual_length(s: str) -> int:
    """Return the visual length of a string, accounting for double-width characters like ✅."""
    # This is a simple heuristic for common emojis used in this tool.
    # We count '✅' as width 2, while len() returns 1.
    return len(s) + s.count("✅")


def visual_ljust(s: str, width: int) -> str:
    """Left justify a string based on its visual length."""
    return s + " " * (width - get_visual_length(s))


@group.command(name="schedule-download-deprecation")
def schedule_download_deprecation_command(
    ctx: typer.Context,
    limit: Annotated[Optional[int], typer.Option(help="Search batch size")] = 500,
    model_offset: Annotated[int, typer.Option(help="Offset for model columns")] = 0,
    csv_output: Annotated[bool, typer.Option("--csv", help="Output as CSV instead of a table")] = False,
    csv_file_name: Annotated[Optional[str], typer.Option("--csv-file-name", help="Output as CSV instead of a table")] = "schedule_download_deprecation",
    unfiltered: Annotated[bool, typer.Option("--unfiltered", help="Show all rows, including those with no missing permissions")] = False,
    email: Annotated[Optional[bool], typer.Option("--email", help="Use Email instead of Name")] = False,
):
    """
    Build a table of users and their scheduling/downloading permissions per model.
    """
    result = schedule_download_deprecation(ctx, limit, unfiltered=unfiltered)
    if not result:
        typer.echo("No matching users found.")
        return

    if csv_output:
        # For CSV, we ignore pagination and truncation
        with open(csv_file_name + ".csv", "w", newline="") as f:
            writer = csv.writer(f)
            csv_headers = ["User ID", "Email" if email else "Name", "Instance Wide"] + result.model_names
            writer.writerow(csv_headers)
            
            for row in result.rows:
                instance_wide = ", ".join(row.instance_wide) if row.instance_wide else " "
                model_results = []
                for m_name in result.model_names:
                    missing = row.model_permissions.get(m_name)
                    if missing is None:
                        model_results.append("N/A")
                    elif not row.has_target_perms:
                        model_results.append(" ")
                    elif not missing:
                        model_results.append("✅")
                    else:
                        model_results.append(", ".join(missing))
                
                writer.writerow([row.user_id, row.email if email else row.name, instance_wide] + model_results)
        typer.echo(f"CSV output written to {csv_file_name}.csv")
        return

    # Slice models to only show 5 at a time
    total_models = len(result.model_names)
    visible_models = result.model_names[model_offset : model_offset + 5]
    
    # Truncate model names for display
    display_model_names = [
        (m if len(m) <= 10 else m[:7] + "...") for m in visible_models
    ]
    
    headers = ["User ID", "Email" if email else "Name", "Instance Wide"] + display_model_names
    
    # Transform Pydantic rows into visual table rows
    table_rows = []
    for row in result.rows:
        instance_wide_abbrev = [PERMISSION_MAP.get(p, p) for p in row.instance_wide]
        instance_wide_str = "\n".join(instance_wide_abbrev) if instance_wide_abbrev else " "
        model_results = []
        for m_name in visible_models:
            missing = row.model_permissions.get(m_name)
            if missing is None:
                model_results.append("N/A")
            elif not row.has_target_perms:
                model_results.append(" ")
            elif not missing:
                model_results.append("✅")
            else:
                missing_abbrev = [PERMISSION_MAP.get(p, p) for p in missing]
                model_results.append("\n".join(missing_abbrev))
        
        table_rows.append([row.user_id, row.email if email else row.name, instance_wide_str] + model_results)

    # 5. Format and echo the table
    col_widths = [
        max(get_visual_length(str(line)) for r in ([headers] + table_rows) for line in str(r[i]).split("\n"))
        for i in range(len(headers))
    ]
    
    def format_line(parts, widths):
        return " | ".join(visual_ljust(str(p), w) for p, w in zip(parts, widths))

    typer.echo(format_line(headers, col_widths))
    typer.echo("-" * (sum(col_widths) + 3 * (len(headers) - 1)))

    if not table_rows:
        typer.echo("No users found matching the criteria. 🎉")
        return
    
    for row in table_rows:
        max_lines = max(str(cell).count("\n") + 1 for cell in row)
        row_lines = [str(cell).split("\n") for cell in row]
        
        for line_idx in range(max_lines):
            line_parts = [
                rl[line_idx] if line_idx < len(rl) else ""
                for rl in row_lines
            ]
            typer.echo(format_line(line_parts, col_widths))
        typer.echo("-" * (sum(col_widths) + 3 * (len(headers) - 1)))

    typer.echo("\n" + "=" * 30)
    typer.echo("LEGEND (Shortcuts)")
    typer.echo("-" * 30)
    for full, short in PERMISSION_MAP.items():
        typer.echo(f"{short.ljust(8)} = {full}")
    typer.echo("=" * 30)

    if model_offset + 5 < total_models:
        next_offset = model_offset + 5
        typer.echo(f"\nShowing models {model_offset+1}-{min(model_offset+5, total_models)} of {total_models}.")
        typer.echo(f"Use --model-offset {next_offset} to see the next 5 models. Or use --csv for the full table.")
    elif model_offset > 0:
        typer.echo(f"\nShowing models {model_offset+1}-{total_models} of {total_models}.")


if __name__ == "__main__":
    group()
