from typing import cast
from unittest.mock import MagicMock, patch

from lkr.extended_sdk_methods.main import (
    ExtendedLooker40SDK,
    GeminiEnterpriseAgentRequest,
    GenerateLookMLParameters,
    GenerateLookMLWithNewFilesResponse,
    ProjectCommitRequest,
    ProjectGenerationRequest,
    ProjectGenerationSemGenInput,
    ProjectGeneratorColumn,
    ProjectGeneratorTable,
    SelectedTable,
)


def test_models_instantiation() -> None:
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


def test_generate_lookml() -> None:
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


def test_download_project_zip() -> None:
    mock_auth = MagicMock()
    mock_auth.settings.base_url = "https://example.looker.com"
    sdk = ExtendedLooker40SDK(
        auth=mock_auth,
        deserialize=MagicMock(),
        serialize=MagicMock(),
        transport=MagicMock(),
        api_version="4.0",
    )

    with patch.object(sdk, "get") as mock_get:
        mock_get.return_value = b"PK\x05\x06" + b"\x00" * 18
        res = sdk.download_project_zip(project_id="my project")
        assert res.startswith(b"PK")
        mock_get.assert_called_once_with(
            path="/projects/my%20project/download_zip",
            structure=bytes,
            transport_options=None,
        )

    import pydantic_monty

    from lkr.codemode.type import to_primitive

    with pydantic_monty.Monty() as m, m.checkout() as session:
        assert session.feed_run(
            'b = download_project_zip("my project"); return isinstance(b, bytes), len(b)',
            external_lookup={"download_project_zip": lambda project_id: to_primitive(b"PK\x05\x06")},
        ) == (True, 4)


def test_generate_lookml_with_new_files() -> None:
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
        def __init__(self, fid: str) -> None:
            self.id = fid

        def __eq__(self, other: object) -> bool:
            return isinstance(other, FakeFile) and self.id == other.id

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


def test_project_commit_request_model() -> None:
    req = ProjectCommitRequest(files=["a.lkml"], message="fix bug", amend=False)
    assert req.files == ["a.lkml"]
    assert req.message == "fix bug"
    assert req.amend is False


def test_commit() -> None:
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


def test_commit_no_body() -> None:
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


def test_create_developer_copy() -> None:
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
        mock_post.return_value = "copy created"

        res = sdk.create_developer_copy(project_id="test_proj")

        assert res == "copy created"
        mock_post.assert_called_once_with(
            path="/projects/test_proj/developer_copy",
            structure=str,
            transport_options=None,
        )
        assert sdk.developer_copy == sdk.create_developer_copy


def test_gemini_enterprise_agent_methods() -> None:
    mock_auth = MagicMock()
    mock_auth.settings.base_url = "https://example.looker.com"
    sdk = ExtendedLooker40SDK(
        auth=mock_auth,
        deserialize=MagicMock(),
        serialize=MagicMock(),
        transport=MagicMock(),
        api_version="4.0",
    )

    req = GeminiEnterpriseAgentRequest(
        ge_gcp_project_number="123456789012",
        ge_gcp_location="global",
        ge_engine_id="secondary-ge-app",
    )

    with patch.object(sdk, "post") as mock_post:
        mock_post.return_value = {"state": "published", "message": "ok"}
        res = sdk.publish_agent("agent-guid-1", body=req)
        assert res["state"] == "published"
        mock_post.assert_called_once_with(
            path="/internal/agents/agent-guid-1/publish",
            structure=dict,
            body=req.model_dump(),
            transport_options=None,
        )

    with patch.object(sdk, "post") as mock_post:
        mock_post.return_value = {"state": "published", "message": "ok"}
        sdk.publish_agent("agent-guid-1")
        mock_post.assert_called_once_with(
            path="/internal/agents/agent-guid-1/publish",
            structure=dict,
            body={},
            transport_options=None,
        )

    with patch.object(sdk, "get") as mock_get:
        mock_get.return_value = {"state": "published", "message": "ok"}
        res = sdk.get_published_agent("agent-guid-1")
        assert res["state"] == "published"
        mock_get.assert_called_once_with(
            path="/internal/agents/agent-guid-1/publish",
            structure=dict,
            transport_options=None,
        )

    with patch.object(sdk, "patch") as mock_patch:
        mock_patch.return_value = {"state": "published", "message": "updated"}
        res = sdk.update_published_agent("agent-guid-1")
        assert res["message"] == "updated"
        mock_patch.assert_called_once_with(
            path="/internal/agents/agent-guid-1/publish",
            structure=dict,
            body={},
            transport_options=None,
        )

    with patch.object(sdk, "patch") as mock_patch:
        mock_patch.return_value = {
            "state": "unpublished",
            "message": "AGENT_UNPUBLISHED_SUCCESSFULLY",
        }
        res = sdk.unpublish_agent("agent-guid-1")
        assert res["state"] == "unpublished"
        mock_patch.assert_called_once_with(
            path="/internal/agents/agent-guid-1/unpublish",
            structure=dict,
            body={},
            transport_options=None,
        )

    with patch.object(sdk, "post") as mock_post:
        mock_post.return_value = {"success": True, "message": None}
        res = sdk.validate_gemini_enterprise_metadata(req)
        assert res["success"] is True
        mock_post.assert_called_once_with(
            path="/gemini_enterprise/validate",
            structure=dict,
            body=req.model_dump(),
            transport_options=None,
        )

    with patch.object(sdk, "get", return_value={"term": "orders", "total_count": 1}) as mock_get:
        assert sdk.global_search_v2(term="orders", limit=10, curate=True) == {
            "term": "orders",
            "total_count": 1,
        }
        mock_get.assert_called_once_with(
            path="/global_search_v2",
            structure=dict,
            query_params={"term": "orders", "curate": "true", "limit": "10"},
            transport_options=None,
        )

    with patch.object(sdk, "run_inline_query", return_value='[{"orders.count": 42}]') as mock_riq:
        rows = sdk.execute_looker_query(
            {"model": "thelook", "view": "orders", "fields": ["orders.count"]}
        )
        assert rows == [{"orders.count": 42}]
        mock_riq.assert_called_once_with(
            "json",
            {"model": "thelook", "view": "orders", "fields": ["orders.count"]},
        )


def test_extended_sdk_monty_sandbox_parity_and_execution() -> None:
    """Enforce that every ExtendedLooker40SDK method is registered and runnable in the Monty sandbox."""
    import ast
    import json
    from pathlib import Path

    import pydantic_monty

    repo_root = Path(__file__).resolve().parent.parent
    main_py = (repo_root / "lkr/extended_sdk_methods/main.py").read_text(encoding="utf-8")
    monty_py = (repo_root / "lkr/extended_sdk_methods/_kda_monty.py").read_text(encoding="utf-8")
    build_rs = (repo_root / "lkr/codemode/wasm/build.rs").read_text(encoding="utf-8")
    lib_rs = (repo_root / "lkr/codemode/wasm/src/lib.rs").read_text(encoding="utf-8")
    swagger = json.loads((repo_root / "lkr/codemode/swagger.json").read_text(encoding="utf-8"))
    swagger_ops = {
        op["operationId"]
        for p in swagger["paths"].values()
        for op in p.values()
        if isinstance(op, dict) and "operationId" in op
    }

    # 1. No forbidden stdlib imports in lkr/extended_sdk_methods/main.py
    forbidden_imports = {"concurrent", "threading", "asyncio", "subprocess", "re", "copy", "json"}
    main_tree = ast.parse(main_py)
    for node in ast.walk(main_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_imports, (
                    f"Forbidden import '{alias.name}' in main.py; multi-step logic must live in _kda_monty.py"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_imports, (
                f"Forbidden import from '{node.module}' in main.py; multi-step logic must live in _kda_monty.py"
            )

    # 2. Preamble in _kda_monty.py must have zero imports and define all delegated Monty methods
    _, preamble = monty_py.split("# --- MONTY_KDA_PREAMBLE ---", 1)
    preamble_tree = ast.parse(preamble)
    preamble_imports = [
        n for n in ast.walk(preamble_tree) if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    assert not preamble_imports, "No import statements allowed after # --- MONTY_KDA_PREAMBLE ---"
    preamble_funcs = {
        n.name for n in preamble_tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
    }

    # 3. Every public method on ExtendedLooker40SDK must be registered in build.rs (or swagger.json),
    #    and any method delegating to _kda_monty.py must be injected by wasm/src/lib.rs
    ext_methods = [
        k for k, v in ExtendedLooker40SDK.__dict__.items() if not k.startswith("_") and callable(v)
    ]
    for m_name in ext_methods:
        assert m_name in swagger_ops or f'"{m_name}"' in build_rs, (
            f"ExtendedLooker40SDK.{m_name} is missing from lkr/codemode/wasm/build.rs"
        )
        if m_name in preamble_funcs:
            assert f'rewritten.contains("{m_name}")' in lib_rs, (
                f"Monty method '{m_name}' must be checked in lkr/codemode/wasm/src/lib.rs preamble injection"
            )

    # 4. Execute execute_looker_query directly inside pydantic_monty.Monty() across all modes
    external_lookup = {
        "run_inline_query": lambda fmt, body: (
            "SELECT products.category AS products_category, SUM(sale_price) AS order_items_total_sale_price FROM orders GROUP BY 1 LIMIT 100000"
            if fmt == "sql" and body.get("view") == "order_items"
            else (
                "SELECT products.category AS products_category, COUNT(*) AS inventory_items_count FROM inv GROUP BY 1"
                if fmt == "sql"
                else (
                    [
                        {
                            "sql_runner_query.products_category": "Accessories",
                            "sql_runner_query.order_items_total_sale_price": 300.0,
                            "sql_runner_query.inventory_items_count": 50,
                            "rev_per_unit": 6.0,
                        }
                    ]
                    if body.get("model") == "sql__slug_m"
                    else [{"products.category": "Accessories", "order_items.total_sale_price": 300.0}]
                )
            )
        ),
        "create_sql_query": lambda body=None: {"slug": "slug_m"},
        "run_sql_query": lambda slug=None, result_format="json": [
            {
                "products_category": "Accessories",
                "order_items_total_sale_price": 300.0,
                "inventory_items_count": 50,
            }
        ],
        "lookml_model_explore": lambda m, e, fields=None: {"connection_name": "bq"},
    }

    with pydantic_monty.Monty() as m, m.checkout() as session:
        res = session.feed_run(
            preamble
            + """
single = execute_looker_query({"model": "thelook", "view": "order_items", "fields": ["products.category"]})
merged = execute_looker_query({
    "source_queries": [
        {"query": {"model": "thelook", "view": "order_items", "fields": ["products.category", "order_items.total_sale_price"], "limit": "-1"}},
        {"query": {"model": "thelook", "view": "inventory_items", "fields": ["products.category", "inventory_items.count"]}},
    ],
    "table_calculations": [{"name": "rev_per_unit", "expression": "${order_items.total_sale_price} / ${inventory_items.count:total}"}],
})
return {"single": single, "merged": merged}
""",
            external_lookup=external_lookup,
        )
        assert res["single"] == [{"products.category": "Accessories", "order_items.total_sale_price": 300.0}]
        assert res["merged"] == [
            {
                "products.category": "Accessories",
                "order_items.total_sale_price": 300.0,
                "inventory_items.count": 50,
                "rev_per_unit": 6.0,
            }
        ]


def test_execute_looker_query_long_sql_aliases_and_monty() -> None:
    from pathlib import Path

    import pydantic_monty

    long_view = (
        "category_sku_price_facts_distribution_centers_inventory_items_order_items_"
        "user_click_facts_user_item_volume_facts_user_warehouse_proximity_facts_fields"
    )
    long_dim = f"{long_view}.order_line_archetype"
    long_meas = f"{long_view}.total_sale_price"
    stem = long_view.replace("_", "")[:126]
    assert len(long_dim) == 172 and len(stem) == 126

    sql_0 = (
        f"SELECT CASE WHEN t.x = 'AS' THEN 0 ELSE 1 END AS {stem}_2, "
        f"CASE WHEN t.x = 'AS' THEN 'Core' ELSE 'Other' END AS {stem}_3, "
        f"SUM(t.sale_price) AS {stem}_4 "
        f"FROM (SELECT 1 AS x, 10.0 AS sale_price) AS {stem}_1 GROUP BY 1, 2"
    )
    sql_1 = f"SELECT CASE WHEN t.x = 'AS' THEN 'Core' ELSE 'Other' END AS {stem}_2, COUNT(*) AS inventory_items_count FROM (SELECT 1 AS x) AS {stem}_1 GROUP BY 1"

    created_sql: list[dict[str, object]] = []

    def fake_riq(fmt: str, body: dict[str, object]) -> object:
        assert fmt == "sql"
        return sql_0 if body.get("view") == "order_items" else sql_1

    def fake_create_sql(body: dict[str, object]) -> dict[str, str]:
        created_sql.append(body)
        return {"slug": "slug_long"}

    def fake_run_sql(slug: str, result_format: str = "json") -> list[dict[str, object]]:
        return [{f"{stem}_3": "Core", f"{stem}_4": 300.0, "inventory_items_count": 50}]

    spec: dict[str, object] = {
        "source_queries": [
            {"query": {"model": "thelook", "view": "order_items", "fields": [long_dim, long_meas]}},
            {"query": {"model": "thelook", "view": "inventory_items", "fields": [long_dim, "inventory_items.count"]}},
        ],
        "sorts": [f"{long_dim} desc"],
    }

    mock_auth = MagicMock()
    mock_auth.settings.base_url = "https://example.looker.com"
    sdk = ExtendedLooker40SDK(
        auth=mock_auth,
        deserialize=MagicMock(),
        serialize=MagicMock(),
        transport=MagicMock(),
        api_version="4.0",
    )
    with (
        patch.object(sdk, "run_inline_query", side_effect=fake_riq),
        patch.object(sdk, "create_sql_query", side_effect=fake_create_sql),
        patch.object(sdk, "run_sql_query", side_effect=fake_run_sql),
    ):
        rows = sdk.execute_looker_query(spec)

    expected = [{long_dim: "Core", long_meas: 300.0, "inventory_items.count": 50}]
    assert rows == expected
    merged_sql = str(created_sql[0]["sql"])
    assert f"LEFT JOIN cte_1 ON cte_0.{stem}_3 = cte_1.{stem}_2" in merged_sql
    assert f"SELECT cte_0.{stem}_3 AS {stem}_3, cte_0.{stem}_4 AS {stem}_4, cte_1.inventory_items_count AS inventory_items_count" in merged_sql
    assert f"ORDER BY {stem}_3 DESC" in merged_sql

    repo_root = Path(__file__).resolve().parent.parent
    _, preamble = (repo_root / "lkr/extended_sdk_methods/_kda_monty.py").read_text(encoding="utf-8").split(
        "# --- MONTY_KDA_PREAMBLE ---", 1
    )
    with pydantic_monty.Monty() as m, m.checkout() as session:
        m_rows = session.feed_run(
            preamble + f"\nreturn execute_looker_query({spec!r})\n",
            external_lookup={
                "run_inline_query": fake_riq,
                "create_sql_query": fake_create_sql,
                "run_sql_query": fake_run_sql,
                "lookml_model_explore": lambda m_name, e_name, fields=None: {"connection_name": "bq"},
            },
        )
        assert m_rows == expected


def test_profile_fields_sdk_and_monty() -> None:
    from pathlib import Path

    import pydantic_monty

    mock_auth = MagicMock()
    mock_auth.settings.base_url = "https://example.looker.com"
    sdk = ExtendedLooker40SDK(
        auth=mock_auth,
        deserialize=MagicMock(),
        serialize=MagicMock(),
        transport=MagicMock(),
        api_version="4.0",
    )

    fake_explore = {
        "view_name": "order_items",
        "fields": {
            "dimensions": [
                {"name": "order_items.status", "view": "order_items", "type": "string", "label_short": "Status", "sql": "${TABLE}.status"},
                {"name": "order_items.sale_price", "view": "order_items", "type": "number", "label_short": "Sale Price", "value_format": "$#,##0.00", "sql": "${TABLE}.sale_price"},
                {"name": "order_items.is_delivered", "view": "order_items", "type": "yesno", "label_short": "Is Delivered", "sql": "${TABLE}.delivered_at IS NOT NULL"},
                {"name": "order_items.created_date", "view": "order_items", "type": "date_date", "is_timeframe": True, "dimension_group": "order_items.created", "sql": "${TABLE}.created_at"},
                {"name": "order_items.created_month", "view": "order_items", "type": "date_month", "is_timeframe": True, "dimension_group": "order_items.created", "sql": "${TABLE}.created_at"},
                {"name": "order_items.created_year", "view": "order_items", "type": "date_year", "is_timeframe": True, "dimension_group": "order_items.created", "sql": "${TABLE}.created_at"},
            ],
            "measures": [{"name": "order_items.total_sale_price", "view": "order_items", "type": "sum", "sql": "${sale_price}"}],
        },
    }

    def fake_riq(fmt: str, body: dict[str, object]) -> object:
        if fmt == "json":
            return [{"order_items.total_sale_price": 12500.0}]
        flds = cast("list[str]", body.get("fields", []))
        if "order_items.status" in flds and "order_items.sale_price" in flds:
            return {
                "totals_data": {
                    "_p0_rows": {"value": 100},
                    "_p0_dist": {"value": 3},
                    "_p0_null": {"value": 0},
                    "_p0_empty": {"value": 0},
                    "_p0_minlen": {"value": 7},
                    "_p0_maxlen": {"value": 10},
                    "_p0_avglen": {"value": 8.2},
                    "_p1_rows": {"value": 100},
                    "_p1_dist": {"value": 2},
                    "_p1_null": {"value": 0},
                    "_p1_true": {"value": 3},
                    "_p1_false": {"value": 97},
                    "_p2_rows": {"value": 100},
                    "_p2_dist": {"value": 45},
                    "_p2_null": {"value": 0},
                    "_p2_min": {"value": 5.0},
                    "_p2_max": {"value": 250.0},
                    "_p2_avg": {"value": 55.0},
                    "_p2_med": {"value": 25.0},
                    "_p2_sum": {"value": 5500.0},
                    "_p2_zero": {"value": 0},
                    "_p2_neg": {"value": 0},
                },
                "data": [
                    {
                        "order_items.status": {"value": "Complete"},
                        "order_items.sale_price": {"value": 25.0},
                        "order_items.is_delivered": {"value": "Yes"},
                        "_p0_rows": {"value": 60},
                    },
                    {
                        "order_items.status": {"value": "Shipped"},
                        "order_items.sale_price": {"value": 50.0},
                        "order_items.is_delivered": {"value": "No"},
                        "_p0_rows": {"value": 40},
                    },
                ],
            }
        if "order_items.created_date" in flds:
            return {
                "totals_data": {
                    "_dt_rows": {"value": 100},
                    "_dt_dist": {"value": 30},
                    "_dt_null": {"value": 0},
                    "_dt_min_d": {"value": 19723},
                    "_dt_max_d": {"value": 20088},
                },
                "subtotals_data": {
                    "1": [
                        {"order_items.created_year": {"value": 2024}, "_dt_rows": {"value": 80}},
                        {"order_items.created_year": {"value": 2025}, "_dt_rows": {"value": 20}},
                    ],
                    "2": [
                        {"order_items.created_month": {"value": "2024-11"}, "_dt_rows": {"value": 60}},
                        {"order_items.created_month": {"value": "2024-12"}, "_dt_rows": {"value": 20}},
                        {"order_items.created_month": {"value": "2025-01"}, "_dt_rows": {"value": 20}},
                    ],
                },
                "data": [
                    {"order_items.created_date": {"value": "2024-11-29"}, "_dt_rows": {"value": 50}},
                    {"order_items.created_date": {"value": "2024-11-30"}, "_dt_rows": {"value": 10}},
                ],
            }
        return {"totals_data": {}, "data": []}

    with (
        patch.object(sdk, "lookml_model_explore", return_value=fake_explore),
        patch.object(sdk, "run_inline_query", side_effect=fake_riq),
    ):
        res = sdk.profile_fields(
            body={
                "model": "agentic_thelook",
                "view": "order_items",
                "fields": [
                    "order_items.status",
                    "order_items.is_delivered",
                    "order_items.created_date",
                    "order_items.total_sale_price",
                ],
                "group_fields": True,
            }
        )
        assert res["type_buckets"] == {
            "string": ["order_items.status"],
            "number": ["order_items.sale_price"],
            "yesno": ["order_items.is_delivered"],
            "datetime": ["order_items.created_date"],
        }
        measures = cast("dict[str, dict[str, object]]", res["measures"])
        assert measures["order_items.total_sale_price"]["value"] == 12500.0
        profiles = cast("dict[str, dict[str, object]]", res["profiles"])
        p_status = profiles["order_items.status"]
        assert p_status["subtype"] == "enum"
        assert "profile:low_cardinality_enum" in cast("list[str]", p_status["suggested_tags"])
        assert any("1..15" in d for d in cast("list[str]", p_status["decisions"]))
        p_price = profiles["order_items.sale_price"]
        assert p_price["subtype"] == "currency_or_decimal"
        assert "profile:skewed_distribution" in cast("list[str]", p_price["suggested_tags"])
        assert any("profile:skewed_distribution" in d for d in cast("list[str]", p_price["decisions"]))
        p_yn = profiles["order_items.is_delivered"]
        assert p_yn["subtype"] == "rare_or_skewed_boolean"
        p_dt = profiles["order_items.created_date"]
        assert p_dt["subtype"] == "calendar_date"
        p_dt_stats = cast("dict[str, object]", p_dt["stats"])
        assert p_dt_stats["min_date"] == "2024-01-01"
        assert p_dt_stats["span_days"] == 365
        assert "profile:spiky_year" in cast("list[str]", p_dt["suggested_tags"])

        types_res = sdk.profile_fields(
            model="agentic_thelook",
            view="order_items",
            fields=["order_items.status"],
            types_only=True,
        )
        assert types_res["types_only"] is True
        type_buckets = cast("dict[str, list[str]]", types_res["type_buckets"])
        assert type_buckets["string"] == ["order_items.status"]

    repo_root = Path(__file__).resolve().parent.parent
    monty_py = (repo_root / "lkr/extended_sdk_methods/_kda_monty.py").read_text(encoding="utf-8")
    _, preamble = monty_py.split("# --- MONTY_KDA_PREAMBLE ---", 1)
    with pydantic_monty.Monty() as m, m.checkout() as session:
        m_res = session.feed_run(
            preamble
            + """
return profile_fields(
    model="agentic_thelook",
    view="order_items",
    fields=["order_items.status", "order_items.is_delivered", "order_items.created_date", "order_items.total_sale_price"],
    group_fields=True,
)
""",
            external_lookup={
                "lookml_model_explore": lambda m, e, fields=None: fake_explore,
                "run_inline_query": fake_riq,
            },
        )
        assert m_res["profiles"]["order_items.status"]["subtype"] == "enum"
        assert m_res["profiles"]["order_items.sale_price"]["subtype"] == "currency_or_decimal"
        assert m_res["profiles"]["order_items.created_date"]["stats"]["min_date"] == "2024-01-01"



