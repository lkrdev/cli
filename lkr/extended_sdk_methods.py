from looker_sdk.rtl.api_methods import TQueryParams
from typing import Any, Optional, Union, cast, Dict

from looker_sdk.rtl import transport
from looker_sdk.sdk.api40.methods import Looker40SDK
from pydantic import BaseModel

__all__ = ["ExtendedLooker40SDK", "FileContent", "Directory"]


class FileContent(BaseModel):
    path: str
    content: str


class Directory(BaseModel):
    path: str


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
