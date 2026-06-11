from typing import Any, Optional, Union, cast

from looker_sdk.rtl import transport
from looker_sdk.sdk.api40.methods import Looker40SDK

from lkr.extended_sdk_methods.classes import (
    Directory,
    FileContent,
    GenerateLookMLParameters,
    GenerateLookMLWithNewFilesResponse,
    ProjectGenerationRequest,
    ProjectGenerationSemGenInput,
    ProjectGeneratorColumn,
    ProjectGeneratorTable,
    SelectedTable,
)

__all__ = [
    "ExtendedLooker40SDK",
    "FileContent",
    "Directory",
    "ProjectGeneratorColumn",
    "ProjectGeneratorTable",
    "ProjectGenerationSemGenInput",
    "ProjectGenerationRequest",
    "GenerateLookMLParameters",
    "SelectedTable",
    "GenerateLookMLWithNewFilesResponse",
]



class ExtendedLooker40SDK(Looker40SDK):
    def _prepare_body(self, body: Any) -> Any:
        if body is None:
            return None
        if hasattr(body, "model_dump") and callable(body.model_dump):
            return body.model_dump()
        if hasattr(body, "dict") and callable(body.dict):
            return body.dict()
        if hasattr(body, "__dict__") and not isinstance(body, (dict, list, str, bytes)):
            return vars(body)
        return body

    def delete(
        self,
        path: str,
        structure: Any = None,
        query_params: Optional[Any] = None,
        transport_options: Optional[transport.TransportOptions] = None,
    ) -> Any:
        """DELETE method corrected to include query_params."""
        params = self._convert_query_params(query_params) if query_params else None
        response = self.transport.request(
            transport.HttpMethod.DELETE,
            self._path(path),
            query_params=params,
            body=None,
            authenticator=self.auth.authenticate,
            transport_options=transport_options,
        )
        return self._return(response, structure)

    def all_project_files(
        self,
        project_id: str,
        fields: Optional[str] = None,
        transport_options: Optional[transport.TransportOptions] = None,
    ) -> Any:
        """Get all files in a project."""
        project_id = self.encode_path_param(project_id)
        path = f"/projects/{project_id}/files"
        return self.get(
            path=path,
            structure=list,
            query_params=cast(Any, {"fields": fields}) if fields else None,
            transport_options=transport_options,
        )

    def get_file_content(
        self,
        project_id: str,
        file_path: str,
        transport_options: Optional[transport.TransportOptions] = None,
    ) -> str:
        """Get file content."""
        project_id = self.encode_path_param(project_id)
        path = f"/projects/{project_id}/file/content"
        query_params = self._convert_query_params(cast(Any, {"file_path": file_path}))
        return cast(
            str,
            self.get(
                path=path,
                structure=str,
                query_params=cast(Any, query_params),
                transport_options=transport_options,
            ),
        )

    def create_file(
        self,
        project_id: str,
        file_content: Union[FileContent, dict, Any],
        transport_options: Optional[transport.TransportOptions] = None,
    ) -> Any:
        """Create a new file in a project."""
        project_id = self.encode_path_param(project_id)
        path = f"/projects/{project_id}/files"
        body = self._prepare_body(file_content)
        return self.post(
            path=path,
            structure=Any,
            body=body,
            transport_options=transport_options,
        )

    def update_file(
        self,
        project_id: str,
        file_content: Union[FileContent, dict, Any],
        transport_options: Optional[transport.TransportOptions] = None,
    ) -> Any:
        """Update a file in a project."""
        project_id = self.encode_path_param(project_id)
        path = f"/projects/{project_id}/files"
        body = self._prepare_body(file_content)
        return self.put(
            path=path,
            structure=Any,
            body=body,
            transport_options=transport_options,
        )

    def delete_file(
        self,
        project_id: str,
        file_path: str,
        transport_options: Optional[transport.TransportOptions] = None,
    ) -> None:
        """Delete a file in a project."""
        project_id = self.encode_path_param(project_id)
        path = f"/projects/{project_id}/files"
        query_params = self._convert_query_params(cast(Any, {"file_path": file_path}))
        return self.delete(
            path=path,
            structure=None,
            query_params=query_params,
            transport_options=transport_options,
        )

    def create_project_directory(
        self,
        project_id: str,
        directory_path: str,
        transport_options: Optional[transport.TransportOptions] = None,
    ) -> Any:
        """Create a project directory."""
        project_id = self.encode_path_param(project_id)
        path = f"/projects/{project_id}/directories"
        body = {"path": directory_path}
        return self.post(
            path=path,
            structure=Any,
            body=body,
            transport_options=transport_options,
        )

    def delete_project_directory(
        self,
        project_id: str,
        directory_path: str,
        transport_options: Optional[transport.TransportOptions] = None,
    ) -> Any:
        """Delete a project directory."""
        project_id = self.encode_path_param(project_id)
        path = f"/projects/{project_id}/directories"
        query_params = self._convert_query_params(cast(Any, {"path": directory_path}))
        return self.delete(
            path=path,
            structure=Any,
            query_params=query_params,
            transport_options=transport_options,
        )

    def generate_lookml(
        self,
        project_id: str,
        body: Union[ProjectGenerationRequest, dict, Any],
        connection: str,
        model_name: str,
        folder_name: str,
        file_type_for_explores: str,
        generate_descriptions: Optional[bool] = None,
        generate_helper_text: Optional[bool] = None,
        prefixes: Optional[str] = None,
        transport_options: Optional[transport.TransportOptions] = None,
    ) -> str:
        """Generate LookML in a project.

        Args:
            project_id: Id of project.
            body: Generation parameters.
            connection: Name of connection.
            model_name: Name of model or Explore file to generate.
            folder_name: Path of the folder to place generated files.
            file_type_for_explores: What type of file to place Explores in, if any. Valid values are model, explore, none. Defaults to model.
            generate_descriptions: Generate descriptions for columns that have them in BigQuery. Defaults to True.
            generate_helper_text: Generate helper text for LookML.
            prefixes: Case sensitive table prefixes to be ignored when naming view files.
            transport_options: Optional transport options.

        Returns:
            str: Empty string on successful LookML generation.
        """
        project_id = self.encode_path_param(project_id)
        path = f"/projects/{project_id}/generate"
        query_params = {
            "connection": connection,
            "model_name": model_name,
            "folder_name": folder_name,
            "file_type_for_explores": file_type_for_explores,
            "generate_descriptions": generate_descriptions,
            "generate_helper_text": generate_helper_text,
            "prefixes": prefixes,
        }
        converted_params = self._convert_query_params(cast(Any, query_params))
        request_body = self._prepare_body(body)
        return cast(
            str,
            self.post(
                path=path,
                structure=str,
                query_params=cast(Any, converted_params),
                body=request_body,
                transport_options=transport_options,
            ),
        )

    def generate_lookml_with_new_files(
        self,
        project_id: str,
        body: Union[ProjectGenerationRequest, dict, Any],
        connection: str,
        model_name: str,
        folder_name: str,
        file_type_for_explores: str,
        generate_descriptions: Optional[bool] = None,
        generate_helper_text: Optional[bool] = None,
        prefixes: Optional[str] = None,
        transport_options: Optional[transport.TransportOptions] = None,
    ) -> GenerateLookMLWithNewFilesResponse:
        """Generate LookML in a project and return the API response along with newly created files.

        Args:
            project_id: Id of project.
            body: Generation parameters.
            connection: Name of connection.
            model_name: Name of model or Explore file to generate.
            folder_name: Path of the folder to place generated files.
            file_type_for_explores: What type of file to place Explores in, if any. Valid values are model, explore, none. Defaults to model.
            generate_descriptions: Generate descriptions for columns that have them in BigQuery. Defaults to True.
            generate_helper_text: Generate helper text for LookML.
            prefixes: Case sensitive table prefixes to be ignored when naming view files.
            transport_options: Optional transport options.

        Returns:
            GenerateLookMLWithNewFilesResponse: The API response from generate_lookml along with a list of newly created files.
        """
        files_before = (
            self.all_project_files(
                project_id=project_id,
                transport_options=transport_options,
            )
            or []
        )

        response = self.generate_lookml(
            project_id=project_id,
            body=body,
            connection=connection,
            model_name=model_name,
            folder_name=folder_name,
            file_type_for_explores=file_type_for_explores,
            generate_descriptions=generate_descriptions,
            generate_helper_text=generate_helper_text,
            prefixes=prefixes,
            transport_options=transport_options,
        )

        files_after = (
            self.all_project_files(
                project_id=project_id,
                transport_options=transport_options,
            )
            or []
        )

        def _get_file_id(f: Any) -> str:
            if isinstance(f, dict):
                return str(f.get("id") or f.get("path") or str(f))
            if hasattr(f, "id") and f.id is not None:
                return str(f.id)
            if hasattr(f, "path") and f.path is not None:
                return str(f.path)
            return str(f)

        before_ids = {_get_file_id(f) for f in files_before}
        new_files = [f for f in files_after if _get_file_id(f) not in before_ids]

        return GenerateLookMLWithNewFilesResponse(
            generate_lookml=response, new_files=new_files
        )
