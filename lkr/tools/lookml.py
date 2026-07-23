import os
import re
from typing import Annotated, Any

import typer

from lkr.auth_service import get_auth
from lkr.extended_sdk_methods import (
    ExtendedLooker40SDK,
    FileContent,
    ProjectCommitRequest,
)
from lkr.logger import logger

__all__ = ["lookml_group"]

lookml_group = typer.Typer(
    name="lookml",
    help="LookML synchronization and deployment tools",
    no_args_is_help=True,
)

VALID_EXTENSIONS = (
    ".lkml",
    ".lookml",
    ".json",
    ".geojson",
    ".md",
    ".gitkeep",
)


def _get_file_id(f: Any) -> str:
    if isinstance(f, dict):
        return str(f.get("id") or f.get("path") or str(f))
    if hasattr(f, "id") and f.id is not None:
        return str(f.id)
    if hasattr(f, "path") and f.path is not None:
        return str(f.path)
    return str(f)


def _resolve_project_id(
    folder_name: str | None, project_id_opt: str | None
) -> str:
    if project_id_opt:
        return project_id_opt
    if folder_name:
        return os.path.basename(os.path.abspath(folder_name.rstrip("/\\")))
    env_proj = os.getenv("LOOKER_PROJECT_NAME")
    if env_proj:
        return env_proj
    return os.path.basename(os.getcwd())


def _ensure_remote_directory(
    sdk: ExtendedLooker40SDK, project_id: str, file_path: str
) -> None:
    dir_path = os.path.dirname(file_path.replace("\\", "/"))
    if not dir_path or dir_path == "." or dir_path == "/":
        return

    parts = [p for p in dir_path.split("/") if p]
    current_path = ""
    for part in parts:
        current_path = f"{current_path}/{part}" if current_path else part
        try:
            sdk.create_project_directory(
                project_id=project_id,
                directory_path=current_path,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Directory creation notice for '{current_path}': {e}")


@lookml_group.command(name="push")
def push(
    ctx: typer.Context,
    folder_name: Annotated[
        str, typer.Argument(help="Local folder name / Looker project ID to push")
    ],
    project_id_opt: Annotated[
        str | None,
        typer.Option(
            "--project-id",
            "--project",
            help="Looker project ID to push to (if different from folder name)",
        ),
    ] = None,
    file_opt: Annotated[
        str | None,
        typer.Option(
            "--file",
            "-f",
            help="Single file relative path (or absolute path) to push",
        ),
    ] = None,
    deploy: Annotated[
        bool,
        typer.Option("--deploy", help="Commit and deploy to production after push"),
    ] = False,
    message: Annotated[
        str, typer.Option("--message", help="Commit message when deploying")
    ] = "push from lkr cli",
):
    """
    Push local files to Looker, removing files on the instance that aren't being pushed.
    If --file / -f is specified (or folder_name is a file), only that single file is pushed without deleting remote orphans.
    """
    auth = get_auth(ctx)
    sdk: ExtendedLooker40SDK = auth.get_current_sdk()

    if file_opt is None and os.path.isfile(folder_name):
        file_opt = folder_name
        folder_name = os.path.dirname(os.path.abspath(folder_name))

    project_id = _resolve_project_id(folder_name, project_id_opt)
    lookml_dir = os.path.abspath(folder_name)

    files_to_push = []
    if file_opt:
        full_path = file_opt if os.path.isabs(file_opt) else os.path.join(lookml_dir, file_opt)
        full_path = os.path.abspath(full_path)
        try:
            if os.path.commonpath([lookml_dir, full_path]) != lookml_dir:
                logger.error(f"Path traversal detected and blocked: {file_opt}")
                raise typer.Exit(1)
        except ValueError:
            logger.error(f"Path traversal detected and blocked: {file_opt}")
            raise typer.Exit(1)

        if not os.path.exists(full_path):
            logger.error(f"Local file does not exist: {full_path}")
            raise typer.Exit(1)

        filename = os.path.basename(full_path)
        if not any(filename.endswith(ext) for ext in VALID_EXTENSIONS):
            logger.error(f"Local file '{filename}' has an extension not supported by Looker.")
            raise typer.Exit(1)

        rel_path = os.path.relpath(full_path, lookml_dir).replace("\\", "/")
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        files_to_push.append({
            "path": rel_path,
            "root_name": filename,
            "content": content,
        })
    else:
        if not os.path.exists(lookml_dir):
            logger.error(f"Local folder does not exist: {lookml_dir}")
            raise typer.Exit(1)

        logger.info(f"Reading local files from {lookml_dir} for project {project_id}...")
        for root, _, files in os.walk(lookml_dir):
            if ".git" in root.split(os.sep):
                continue
            for file in files:
                if file in (".gitignore", ".DS_Store"):
                    continue
                if any(file.endswith(ext) for ext in VALID_EXTENSIONS):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, lookml_dir).replace("\\", "/")
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    files_to_push.append({
                        "path": rel_path,
                        "root_name": file,
                        "content": content,
                    })
                else:
                    logger.warning(
                        f"Local file '{file}' has an extension not supported by Looker and will be skipped."
                    )

    successfully_pushed_paths = set()
    for f in files_to_push:
        structured_path = f["path"]
        root_path = f["root_name"]
        content = f["content"]

        try:
            logger.info(f"Uploading/Overwriting remote file: {structured_path}")
            file_content = FileContent(path=structured_path, content=content)
            try:
                sdk.update_file(
                    project_id=project_id,
                    file_content=file_content,
                )
            except Exception:  # noqa: BLE001
                try:
                    sdk.create_file(
                        project_id=project_id,
                        file_content=file_content,
                    )
                except Exception:  # noqa: BLE001
                    _ensure_remote_directory(
                        sdk=sdk, project_id=project_id, file_path=structured_path
                    )
                    sdk.create_file(
                        project_id=project_id,
                        file_content=file_content,
                    )
            successfully_pushed_paths.add(structured_path)
            continue
        except Exception as struct_err:  # noqa: BLE001
            logger.debug(
                f"Structured upload notice ({struct_err}), initiating fallback to project root..."
            )

        if root_path.endswith(".model.lkml"):
            content = re.sub(
                r'include:\s*["\']/views/\*\*/\*\.view\.lkml["\']',
                'include: "/*.view.lkml"',
                content,
            )

        root_file_content = FileContent(path=root_path, content=content)
        try:
            sdk.update_file(
                project_id=project_id,
                file_content=root_file_content,
            )
        except Exception:  # noqa: BLE001
            sdk.create_file(
                project_id=project_id,
                file_content=root_file_content,
            )
        successfully_pushed_paths.add(root_path)

    if not file_opt:
        logger.info("Retrieving remote file inventory to enforce one-way mirror...")
        existing_remote = sdk.all_project_files(project_id=project_id) or []
        for rf in existing_remote:
            rf_path = _get_file_id(rf)
            if not any(rf_path.endswith(ext) for ext in VALID_EXTENSIONS):
                logger.warning(
                    f"Remote file '{rf_path}' has an extension not supported by Looker."
                )
            if (
                rf_path not in successfully_pushed_paths
                and not rf_path.endswith(".gitkeep")
                and rf_path != "manifest.lkml"
            ):
                logger.info(f"Deleting remote orphan file: {rf_path}")
                try:
                    sdk.delete_file(project_id=project_id, file_path=rf_path)
                except Exception as dpe:  # noqa: BLE001
                    logger.debug(f"Deletion notice for {rf_path}: {dpe}")

    logger.info("Push completed successfully.")

    if deploy:
        logger.info(f"Committing and deploying project {project_id} to production...")
        try:
            commit_req = ProjectCommitRequest(message=message).model_dump(
                exclude_none=True
            )
            sdk.commit(project_id=project_id, body=commit_req)
        except Exception as commit_err:  # noqa: BLE001
            logger.debug(f"Commit notice: {commit_err}")

        sdk.deploy_to_production(project_id=project_id)
        logger.info("Deployment completed successfully.")


@lookml_group.command(name="pull")
def pull(
    ctx: typer.Context,
    folder_name: Annotated[
        str, typer.Argument(help="Local folder name / Looker project ID to pull into")
    ],
    project_id_opt: Annotated[
        str | None,
        typer.Option(
            "--project-id",
            "--project",
            help="Looker project ID to pull from (if different from folder name)",
        ),
    ] = None,
    file_opt: Annotated[
        str | None,
        typer.Option(
            "--file",
            "-f",
            help="Single file relative path to pull from Looker",
        ),
    ] = None,
    deploy: Annotated[
        bool,
        typer.Option(
            "--deploy", help="Commit and deploy to production on Looker after pull"
        ),
    ] = False,
    message: Annotated[
        str, typer.Option("--message", help="Commit message when deploying")
    ] = "pull from lkr cli then commit and deploy",
):
    """
    Pull remote files from Looker to local disk, removing local files that aren't on the instance.
    If --file / -f is specified, only that single file is pulled without deleting local orphans.
    """
    auth = get_auth(ctx)
    sdk: ExtendedLooker40SDK = auth.get_current_sdk()
    project_id = _resolve_project_id(folder_name, project_id_opt)

    target_dir = os.path.abspath(folder_name)
    os.makedirs(target_dir, exist_ok=True)

    if file_opt:
        full_path = file_opt if os.path.isabs(file_opt) else os.path.join(target_dir, file_opt)
        resolved_local = os.path.abspath(full_path)
        try:
            if os.path.commonpath([target_dir, resolved_local]) != target_dir:
                logger.error(f"Path traversal detected and blocked: {file_opt}")
                raise typer.Exit(1)
        except ValueError:
            logger.error(f"Path traversal detected and blocked: {file_opt}")
            raise typer.Exit(1)

        rf_path = os.path.relpath(resolved_local, target_dir).replace("\\", "/")
        if not any(rf_path.endswith(ext) for ext in VALID_EXTENSIONS):
            logger.error(
                f"File '{rf_path}' has an extension not supported by Looker."
            )
            raise typer.Exit(1)

        try:
            content = sdk.get_file_content(project_id=project_id, file_path=rf_path)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to fetch content for remote file {rf_path}: {e}")
            raise typer.Exit(1)

        os.makedirs(os.path.dirname(resolved_local), exist_ok=True)
        with open(resolved_local, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Pulled file: {rf_path}")
    else:
        logger.info(
            f"Retrieving remote files for project {project_id} to pull into {target_dir}..."
        )
        existing_remote = sdk.all_project_files(project_id=project_id) or []

        remote_paths = set()
        for rf in existing_remote:
            rf_path = _get_file_id(rf)
            if not any(rf_path.endswith(ext) for ext in VALID_EXTENSIONS):
                logger.warning(
                    f"Remote file '{rf_path}' has an extension not supported by Looker."
                )
                continue
            if rf_path.endswith(".gitkeep"):
                continue

            local_path = os.path.join(target_dir, rf_path)
            resolved_local = os.path.abspath(local_path)
            try:
                if os.path.commonpath([target_dir, resolved_local]) != target_dir:
                    logger.warning(f"Path traversal detected and blocked: {rf_path}")
                    continue
            except ValueError:
                logger.warning(f"Path traversal detected and blocked: {rf_path}")
                continue

            try:
                content = sdk.get_file_content(project_id=project_id, file_path=rf_path)
            except Exception as e:  # noqa: BLE001
                if "not found" in str(e).lower():
                    logger.debug(
                        f"Remote file {rf_path} not found in dev workspace (likely a deleted ghost file in git tracking)."
                    )
                else:
                    logger.error(f"Failed to fetch content for remote file {rf_path}: {e}")
                continue

            remote_paths.add(rf_path)

            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Pulled file: {rf_path}")

        logger.info("Cleaning up local orphans not present on the Looker instance...")
        for root, _, files in os.walk(target_dir):
            if ".git" in root.split(os.sep):
                continue
            for file in files:
                if file in (".gitignore", ".DS_Store"):
                    continue
                if any(file.endswith(ext) for ext in VALID_EXTENSIONS):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, target_dir).replace("\\", "/")
                    if (
                        rel_path not in remote_paths
                        and not rel_path.endswith(".gitkeep")
                        and rel_path != "manifest.lkml"
                    ):
                        logger.info(f"Deleting local orphan file: {rel_path}")
                        try:
                            os.remove(full_path)
                        except Exception as err:  # noqa: BLE001
                            logger.debug(f"Local deletion notice for {rel_path}: {err}")
                else:
                    logger.warning(
                        f"Local file '{file}' has an extension not supported by Looker and will not be synchronized or deleted."
                    )

    logger.info("Pull completed successfully.")

    if deploy:
        logger.info(
            f"Committing and deploying project {project_id} to production on Looker..."
        )
        try:
            commit_req = ProjectCommitRequest(message=message).model_dump(
                exclude_none=True
            )
            sdk.commit(project_id=project_id, body=commit_req)
        except Exception as commit_err:  # noqa: BLE001
            logger.debug(f"Commit notice: {commit_err}")

        sdk.deploy_to_production(project_id=project_id)
        logger.info("Deployment completed successfully.")


@lookml_group.command(name="deploy")
def deploy_cmd(
    ctx: typer.Context,
    folder_name: Annotated[
        str | None,
        typer.Argument(help="Local folder name / Looker project ID to deploy"),
    ] = None,
    project_id: Annotated[
        str | None,
        typer.Option(
            "--project-id",
            "--project",
            help="Looker project ID to deploy (if folder_name not specified)",
        ),
    ] = None,
    message: Annotated[
        str, typer.Option("--message", help="Commit message")
    ] = "commit and deploy from lkr cli",
):
    """
    Commit dev workspace and deploy Looker project to production.
    """
    auth = get_auth(ctx)
    sdk: ExtendedLooker40SDK = auth.get_current_sdk()
    resolved_project_id = _resolve_project_id(folder_name, project_id)

    logger.info(
        f"Committing and deploying project {resolved_project_id} to production..."
    )
    try:
        commit_req = ProjectCommitRequest(message=message).model_dump(
            exclude_none=True
        )
        sdk.commit(
            project_id=resolved_project_id,
            body=commit_req,
        )
    except Exception as commit_err:  # noqa: BLE001
        logger.debug(f"Commit notice: {commit_err}")

    sdk.deploy_to_production(project_id=resolved_project_id)
    logger.info("Deployment completed successfully.")
