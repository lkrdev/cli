from unittest.mock import MagicMock, patch
from lkr.extended_sdk_methods.main import (
    ExtendedLooker40SDK,
    GenerateLookMLParameters,
    GenerateLookMLWithNewFilesResponse,
    ProjectGenerationRequest,
    ProjectGenerationSemGenInput,
    ProjectGeneratorColumn,
    ProjectGeneratorTable,
    SelectedTable,
    ProjectCommitRequest,
)


def test_models_instantiation():
    column = ProjectGeneratorColumn(column_name="test_col")
    assert column.column_name == "test_col"

    table = ProjectGeneratorTable(
        schema="test_schema",
        table_name="test_table",
        primary_key="id",
        base_view=True,
        columns=[column],
    )
    assert table.schema == "test_schema"
    assert table.table_name == "test_table"
    assert table.primary_key == "id"
    assert table.base_view is True
    assert table.columns == [column]

    sem_gen = ProjectGenerationSemGenInput(user_intention="Create reports")
    assert sem_gen.user_intention == "Create reports"

    request = ProjectGenerationRequest(tables=[table], semantic_generation_input=sem_gen)
    assert request.tables == [table]
    assert request.semantic_generation_input == sem_gen

    params = GenerateLookMLParameters(
        project_id="test_proj",
        body=request,
        connection="test_conn",
        model_name="test_model",
        folder_name="test_folder",
        file_type_for_explores="model",
        generate_descriptions=True,
        generate_helper_text=False,
        prefixes="tbl_,vw_",
    )
    assert params.project_id == "test_proj"
    assert params.body == request
    assert params.prefixes == "tbl_,vw_"

    selected = SelectedTable(
        connection="test_conn",
        database="test_db",
        schema="test_schema",
        table_name="test_table",
    )
    assert selected.database == "test_db"


def test_generate_lookml():
    mock_auth = MagicMock()
    mock_auth.settings.base_url = "https://example.looker.com"
    sdk = ExtendedLooker40SDK(
        auth=mock_auth,
        deserialize=MagicMock(),
        serialize=MagicMock(),
        transport=MagicMock(),
        api_version="4.0",
    )

    with patch.object(sdk, "post") as mock_post:
        mock_post.return_value = ""

        request = ProjectGenerationRequest(
            tables=[
                ProjectGeneratorTable(schema="public", table_name="users")
            ]
        )

        res = sdk.generate_lookml(
            project_id="my project",
            body=request,
            connection="my_conn",
            model_name="my_model",
            folder_name="my_folder",
            file_type_for_explores="explore",
            generate_descriptions=True,
            generate_helper_text=False,
            prefixes="tbl_",
        )

        assert res == ""

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["path"] == "/projects/my%20project/generate"
        assert kwargs["query_params"] == {
            "connection": "my_conn",
            "model_name": "my_model",
            "folder_name": "my_folder",
            "file_type_for_explores": "explore",
            "generate_descriptions": "true",
            "generate_helper_text": "false",
            "prefixes": "tbl_",
        }
        assert kwargs["body"] == request.model_dump()


def test_generate_lookml_with_new_files():
    mock_auth = MagicMock()
    mock_auth.settings.base_url = "https://example.looker.com"
    sdk = ExtendedLooker40SDK(
        auth=mock_auth,
        deserialize=MagicMock(),
        serialize=MagicMock(),
        transport=MagicMock(),
        api_version="4.0",
    )

    with patch.object(sdk, "all_project_files") as mock_all_files, patch.object(sdk, "generate_lookml") as mock_gen:
        mock_all_files.side_effect = [
            [{"id": "file1.lkml"}, {"id": "file2.lkml"}],
            [{"id": "file1.lkml"}, {"id": "file2.lkml"}, {"id": "file3.lkml"}],
        ]
        mock_gen.return_value = ""

        request = ProjectGenerationRequest(
            tables=[ProjectGeneratorTable(schema="public", table_name="users")]
        )

        result = sdk.generate_lookml_with_new_files(
            project_id="my project",
            body=request,
            connection="my_conn",
            model_name="my_model",
            folder_name="my_folder",
            file_type_for_explores="explore",
            generate_descriptions=True,
            generate_helper_text=False,
            prefixes="tbl_",
        )

        assert isinstance(result, GenerateLookMLWithNewFilesResponse)
        assert result.generate_lookml == ""
        assert result.new_files == [{"id": "file3.lkml"}]

        assert mock_all_files.call_count == 2
        mock_gen.assert_called_once_with(
            project_id="my project",
            body=request,
            connection="my_conn",
            model_name="my_model",
            folder_name="my_folder",
            file_type_for_explores="explore",
            generate_descriptions=True,
            generate_helper_text=False,
            prefixes="tbl_",
            transport_options=None,
        )

    class FakeFile:
        def __init__(self, fid):
            self.id = fid

        def __eq__(self, other):
            return self.id == other.id

    with patch.object(sdk, "all_project_files") as mock_all_files, patch.object(sdk, "generate_lookml") as mock_gen:
        mock_all_files.side_effect = [
            [FakeFile("a"), FakeFile("b")],
            [FakeFile("a"), FakeFile("b"), FakeFile("c")],
        ]
        mock_gen.return_value = "generated"

        result = sdk.generate_lookml_with_new_files(
            project_id="proj",
            body={},
            connection="c",
            model_name="m",
            folder_name="f",
            file_type_for_explores="model",
        )

        assert isinstance(result, GenerateLookMLWithNewFilesResponse)
        assert result.generate_lookml == "generated"
        assert result.new_files == [FakeFile("c")]


def test_project_commit_request_model():
    req = ProjectCommitRequest(files=["a.lkml"], message="fix bug", amend=False)
    assert req.files == ["a.lkml"]
    assert req.message == "fix bug"
    assert req.amend is False


def test_commit():
    mock_auth = MagicMock()
    mock_auth.settings.base_url = "https://example.looker.com"
    sdk = ExtendedLooker40SDK(
        auth=mock_auth,
        deserialize=MagicMock(),
        serialize=MagicMock(),
        transport=MagicMock(),
        api_version="4.0",
    )

    with patch.object(sdk, "post") as mock_post:
        mock_post.return_value = "commit hash or project"

        req = ProjectCommitRequest(files=["model.lkml"], message="initial commit")
        res = sdk.commit(project_id="test_proj", body=req)

        assert res == "commit hash or project"
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["path"] == "/projects/test_proj/commit"
        assert kwargs["body"] == req.model_dump()


def test_commit_no_body():
    mock_auth = MagicMock()
    mock_auth.settings.base_url = "https://example.looker.com"
    sdk = ExtendedLooker40SDK(
        auth=mock_auth,
        deserialize=MagicMock(),
        serialize=MagicMock(),
        transport=MagicMock(),
        api_version="4.0",
    )

    with patch.object(sdk, "post") as mock_post:
        mock_post.return_value = "commit success"

        res = sdk.commit(project_id="test_proj")

        assert res == "commit success"
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["path"] == "/projects/test_proj/commit"
        assert kwargs["body"] is None
