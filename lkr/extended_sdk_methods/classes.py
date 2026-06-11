import warnings
from typing import Any, Optional

from pydantic import BaseModel, Field

__all__ = [
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


class FileContent(BaseModel):
    path: str
    content: str


class Directory(BaseModel):
    path: str


class ProjectGeneratorColumn(BaseModel):
    """Specification of a column to be used from a table."""

    column_name: str = Field(..., description="Name of the column. Nested columns are specified in the format foo.bar.baz")


with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)

    class ProjectGeneratorTable(BaseModel):
        """Table for which to generate LookML."""

        schema: str = Field(..., description="The fully qualified schema or dataset the table is in.")
        table_name: str = Field(..., description="Name of the table.")
        primary_key: Optional[str] = Field(None, description="Name of the column that is the primary key for this table.")
        base_view: Optional[bool] = Field(None, description="Whether to use this table as a base view in Explore. Defaults to True.")
        columns: Optional[list[ProjectGeneratorColumn]] = Field(None, description="The columns to be used from this table. None will use all columns, and an empty list will use no columns.")

    class SelectedTable(BaseModel):
        connection: str
        database: str
        schema: str
        table_name: str


class ProjectGenerationSemGenInput(BaseModel):
    """Input parameters for the semantic generation of LookML."""

    user_intention: Optional[str] = Field(None, description="A high-level description of what the user is trying to model.")
    questions: Optional[str] = Field(None, description="Specific questions the user wants to answer with the data.")
    user_instructions: Optional[str] = Field(None, description="Open-ended instructions provided by the user.")


class ProjectGenerationRequest(BaseModel):
    """Request body for LookML generation."""

    tables: Optional[list[ProjectGeneratorTable]] = Field(None, description="Tables for which to generate LookML.")
    semantic_generation_input: Optional[ProjectGenerationSemGenInput] = Field(None, description="Input parameters for the semantic generation of LookML.")


class GenerateLookMLParameters(BaseModel):
    """Parameters for the generate_lookml SDK method."""

    project_id: str = Field(..., description="Id of project.")
    body: ProjectGenerationRequest = Field(..., description="Generation request payload.")
    connection: str = Field(..., description="Name of connection.")
    model_name: str = Field(..., description="Name of model or Explore file to generate.")
    folder_name: str = Field(..., description="Path of the folder to place generated files.")
    file_type_for_explores: str = Field(..., description="What type of file to place Explores in, if any. Valid values are model, explore, none. Defaults to model.")
    generate_descriptions: Optional[bool] = Field(None, description="Generate descriptions for columns that have them in BigQuery. Defaults to True.")
    generate_helper_text: Optional[bool] = Field(None, description="Generate helper text for LookML.")
    prefixes: Optional[str] = Field(None, description="Case sensitive table prefixes to be ignored when naming view files.")


class GenerateLookMLWithNewFilesResponse(BaseModel):
    """Response body for generate_lookml_with_new_files SDK method."""

    generate_lookml: str = Field(..., description="The API response from generating LookML, typically an empty string on success.")
    new_files: list[Any] = Field(..., description="List of newly created files.")
