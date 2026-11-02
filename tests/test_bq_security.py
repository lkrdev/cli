import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from lkr.parse.lookml_to_api import (
    _extract_access_filter_fields,
    parse_lookml_to_api,
)
from lkr.tools.bq_security import (
    BqColumnSecurity,
    BqPermissionDeniedError,
    BqPrincipals,
    BqRowPolicy,
    BqTableSecurity,
    compile_bq_security_overlays,
    discover_bq_security,
    ensure_model_security_includes,
    sync_looker_security_attributes,
)
from lkr.tools.lookml import BigQueryAuditEvent, create_lookml_views


class _FakeResp:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> dict[str, Any]:
        return self._body


def _denied_resp(permission: str, resource: str = "projects/p") -> _FakeResp:
    return _FakeResp(
        403,
        {
            "error": {
                "code": 403,
                "message": f"Permission '{permission}' denied on resource '{resource}'.",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "IAM_PERMISSION_DENIED",
                        "metadata": {
                            "permission": permission,
                            "resource": resource,
                        },
                    }
                ],
            }
        },
    )


def test_discover_bq_security_ratchets_permissions_fail_closed() -> None:
    """Verify every GCP endpoint fails closed on 403 and surfaces the exact missing IAM permission."""
    tag_name = "projects/12345/locations/us/taxonomies/tax1/policyTags/tag_pii"
    tax_name = "projects/12345/locations/us/taxonomies/tax1"
    dp_name = "projects/fifth-inkwell/locations/us/dataPolicies/mask_email"

    base_ok: dict[tuple[str, str], dict[str, Any]] = {
        (
            "GET",
            "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing",
        ): {
            "location": "US",
            "access": [{"role": "OWNER", "specialGroup": "projectOwners"}],
        },
        (
            "POST",
            "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing:getIamPolicy",
        ): {"bindings": []},
        (
            "GET",
            "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing/tables/orders",
        ): {
            "schema": {
                "fields": [
                    {"name": "id", "type": "INT64"},
                    {
                        "name": "email",
                        "type": "STRING",
                        "policyTags": {"names": [tag_name]},
                    },
                    {
                        "name": "billing_address",
                        "type": "RECORD",
                        "fields": [
                            {
                                "name": "street",
                                "type": "STRING",
                                "policyTags": {"names": [tag_name]},
                            }
                        ],
                    },
                ]
            }
        },
        (
            "POST",
            "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing/tables/orders:getIamPolicy",
        ): {
            "bindings": [
                {
                    "role": "roles/bigquery.dataViewer",
                    "members": [
                        "group:analysts@corp.com",
                        "serviceAccount:bq-runner@fifth-inkwell.iam.gserviceaccount.com",
                    ],
                }
            ]
        },
        (
            "GET",
            "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing/tables/orders/rowAccessPolicies",
        ): {
            "rowAccessPolicies": [
                {
                    "rowAccessPolicyReference": {"policyId": "rap_us"},
                    "filterPredicate": "region = 'US'",
                    "grantees": ["group:us-sales@corp.com"],
                }
            ]
        },
        (
            "POST",
            "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing/tables/orders/rowAccessPolicies/rap_us:getIamPolicy",
        ): {"bindings": []},
        (
            "POST",
            f"https://datacatalog.googleapis.com/v1/{tax_name}:getIamPolicy",
        ): {"bindings": []},
        (
            "POST",
            f"https://datacatalog.googleapis.com/v1/{tag_name}:getIamPolicy",
        ): {
            "bindings": [
                {
                    "role": "roles/datacatalog.categoryFineGrainedReader",
                    "members": ["group:pii-readers@corp.com"],
                }
            ]
        },
        (
            "GET",
            "https://bigquerydatapolicy.googleapis.com/v1/projects/fifth-inkwell/locations/us/dataPolicies",
        ): {
            "dataPolicies": [
                {
                    "name": dp_name,
                    "dataPolicyType": "DATA_MASKING_POLICY",
                    "policyTag": "projects/fifth-inkwell/locations/US/taxonomies/tax1/policyTags/tag_pii",
                    "dataMaskingPolicy": {"predefinedExpression": "SHA256"},
                }
            ]
        },
        (
            "POST",
            f"https://bigquerydatapolicy.googleapis.com/v1/{dp_name}:getIamPolicy",
        ): {
            "bindings": [
                {
                    "role": "roles/bigquerydatapolicy.maskedReader",
                    "members": ["group:support@corp.com"],
                }
            ]
        },
    }

    expected_ratchet = [
        (
            (
                "GET",
                "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing",
            ),
            "bigquery.datasets.get",
        ),
        (
            (
                "POST",
                "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing:getIamPolicy",
            ),
            "bigquery.datasets.getIamPolicy",
        ),
        (
            (
                "GET",
                "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing/tables/orders",
            ),
            "bigquery.tables.get",
        ),
        (
            (
                "POST",
                "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing/tables/orders:getIamPolicy",
            ),
            "bigquery.tables.getIamPolicy",
        ),
        (
            (
                "GET",
                "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing/tables/orders/rowAccessPolicies",
            ),
            "bigquery.rowAccessPolicies.list",
        ),
        (
            (
                "POST",
                "https://bigquery.googleapis.com/bigquery/v2/projects/fifth-inkwell/datasets/bq_access_testing/tables/orders/rowAccessPolicies/rap_us:getIamPolicy",
            ),
            "bigquery.rowAccessPolicies.getIamPolicy",
        ),
        (
            ("POST", f"https://datacatalog.googleapis.com/v1/{tax_name}:getIamPolicy"),
            "datacatalog.taxonomies.getIamPolicy",
        ),
        (
            ("POST", f"https://datacatalog.googleapis.com/v1/{tag_name}:getIamPolicy"),
            "datacatalog.categories.getIamPolicy",
        ),
        (
            (
                "GET",
                "https://bigquerydatapolicy.googleapis.com/v1/projects/fifth-inkwell/locations/us/dataPolicies",
            ),
            "bigquerydatapolicy.dataPolicies.list",
        ),
        (
            ("POST", f"https://bigquerydatapolicy.googleapis.com/v1/{dp_name}:getIamPolicy"),
            "bigquerydatapolicy.dataPolicies.getIamPolicy",
        ),
    ]

    granted: set[tuple[str, str]] = set()
    for step_key, expected_perm in expected_ratchet:
        sess = MagicMock()
        sess.request.side_effect = lambda m, u, **_kw: (
            _FakeResp(200, base_ok[(m, u)])
            if (m, u) in granted
            else _denied_resp(
                dict(expected_ratchet)[(m, u)],
                u,
            )
        )
        with pytest.raises(BqPermissionDeniedError) as exc_info:
            discover_bq_security(
                project_id="fifth-inkwell",
                dataset_id="bq_access_testing",
                table_ids=["orders"],
                token="fake-token",
                excluded_service_accounts={
                    "bq-runner@fifth-inkwell.iam.gserviceaccount.com"
                },
                session=sess,
            )
        assert exc_info.value.permission == expected_perm
        granted.add(step_key)

    # Once all 10 permissions are granted, discovery succeeds and normalizes project-number vs project-id policyTag keys!
    sess_ok = MagicMock()
    sess_ok.request.side_effect = lambda m, u, **_kw: _FakeResp(200, base_ok[(m, u)])
    sec = discover_bq_security(
        project_id="fifth-inkwell",
        dataset_id="bq_access_testing",
        table_ids=["orders"],
        token="fake-token",
        excluded_service_accounts={"bq-runner@fifth-inkwell.iam.gserviceaccount.com"},
        session=sess_ok,
    )
    orders = sec["orders"]
    assert orders.has_custom_table_iam is True
    assert orders.table_readers.groups == {"analysts@corp.com"}
    assert "billing_address__street" in orders.columns
    assert orders.columns["email"].mask_expression == "SHA256"
    assert orders.columns["email"].unmasked_readers.groups == {"pii-readers@corp.com"}
    assert orders.columns["email"].masked_readers.groups == {"support@corp.com"}


def test_progressive_stages_zero_add_mutate_remove(tmp_path: Any) -> None:
    """Verify Stage 0 (Nothing) -> Stage 1 (Add 1-by-1) -> Stage 2 (Mutate) -> Stage 3 (Remove to 0)."""
    base_model = (
        'connection: "bq_sa"\n'
        'include: "/bronze/*.view.lkml"\n\n'
        "explore: orders {\n"
        "  join: customers {\n"
        "    type: left_outer\n"
        "    relationship: many_to_one\n"
        "    sql_on: ${orders.customer_id} = ${customers.id} ;;\n"
        "  }\n"
        "  aggregate_table: daily_rollup {\n"
        "    query: {\n"
        "      dimensions: [orders.status]\n"
        "      measures: [orders.total_amount]\n"
        "    }\n"
        "    materialization: {\n"
        "      sql_trigger_value: SELECT CURRENT_DATE() ;;\n"
        "    }\n"
        "  }\n"
        "}\n"
        "explore: customers {}\n"
    )
    project_files = {
        "ecomm.model.lkml": base_model,
        "bronze/orders.view.lkml": (
            "view: orders {\n"
            "  sql_table_name: `fifth-inkwell.bq_access_testing.orders` ;;\n"
            "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
            "  dimension: customer_id { type: number sql: ${TABLE}.customer_id ;; }\n"
            "  dimension: status { type: string sql: ${TABLE}.status ;; }\n"
            "  dimension: region { type: string sql: ${TABLE}.region ;; }\n"
            "  dimension: amount { type: number sql: ${TABLE}.amount ;; }\n"
            "  dimension: base_salary { type: number sql: ${TABLE}.base_salary ;; }\n"
            "  dimension_group: terminated {\n"
            "    type: time\n"
            "    timeframes: [raw, date, month]\n"
            "    sql: ${TABLE}.terminated_at ;;\n"
            "  }\n"
            "  measure: total_amount { type: sum sql: ${amount} ;; }\n"
            "  measure: total_base_salary { type: sum sql: ${base_salary} ;; }\n"
            "}\n"
        ),
        "bronze/customers.view.lkml": (
            "view: customers {\n"
            "  sql_table_name: `fifth-inkwell.bq_access_testing.customers` ;;\n"
            "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
            "  dimension: country { type: string sql: ${TABLE}.country ;; }\n"
            "  dimension: email { type: string sql: ${TABLE}.email ;; }\n"
            "  dimension: billing_address__street { type: string sql: ${TABLE}.billing_address.street ;; }\n"
            "  measure: email_count { type: count_distinct sql: ${email} ;; }\n"
            "}\n"
        ),
    }

    def _empty_tables() -> dict[str, BqTableSecurity]:
        return {
            "orders": BqTableSecurity(
                project_id="fifth-inkwell",
                dataset_id="bq_access_testing",
                table_id="orders",
                columns={
                    "id": BqColumnSecurity("id", "id", "INT64"),
                    "customer_id": BqColumnSecurity("customer_id", "customer_id", "INT64"),
                    "status": BqColumnSecurity("status", "status", "STRING"),
                    "region": BqColumnSecurity("region", "region", "STRING"),
                    "amount": BqColumnSecurity("amount", "amount", "NUMERIC"),
                    "base_salary": BqColumnSecurity("base_salary", "base_salary", "NUMERIC"),
                    "terminated_at": BqColumnSecurity(
                        "terminated_at", "terminated_at", "TIMESTAMP"
                    ),
                },
            ),
            "customers": BqTableSecurity(
                project_id="fifth-inkwell",
                dataset_id="bq_access_testing",
                table_id="customers",
                columns={
                    "id": BqColumnSecurity("id", "id", "INT64"),
                    "country": BqColumnSecurity("country", "country", "STRING"),
                    "email": BqColumnSecurity("email", "email", "STRING"),
                    "billing_address__street": BqColumnSecurity(
                        "billing_address.street", "billing_address__street", "STRING"
                    ),
                },
            ),
        }

    # --- Stage 0: Nothing ---
    t0 = _empty_tables()
    b0 = compile_bq_security_overlays(
        project_files=project_files,
        bq_tables=t0,
        default_dataset="bq_access_testing",
        model_name="ecomm",
    )
    assert b0.files == {}
    assert b0.attributes == {}
    assert ensure_model_security_includes(base_model, []) == base_model

    # --- Stage 1: Add Table IAM + Policy Tags + Dynamic Masking + RAPs + Aggregate Table sync ---
    t1 = _empty_tables()
    t1["orders"].has_custom_table_iam = True
    t1["orders"].table_readers = BqPrincipals(groups={"analysts@corp.com"})
    t1["customers"].has_custom_table_iam = True
    t1["customers"].table_readers = BqPrincipals(groups={"crm@corp.com"})

    tag_hr = "projects/1/locations/us/taxonomies/hr/policyTags/comp"
    tag_pii = "projects/1/locations/us/taxonomies/pii/policyTags/contact"
    t1["orders"].columns["base_salary"].policy_tag = tag_hr
    t1["orders"].columns["base_salary"].unmasked_readers = BqPrincipals(
        groups={"hr@corp.com"}
    )
    t1["orders"].columns["terminated_at"].policy_tag = tag_hr
    t1["orders"].columns["terminated_at"].unmasked_readers = BqPrincipals(
        groups={"hr@corp.com"}
    )
    t1["customers"].columns["billing_address__street"].policy_tag = tag_pii
    t1["customers"].columns["billing_address__street"].unmasked_readers = BqPrincipals(
        groups={"pii@corp.com"}
    )
    t1["customers"].columns["email"].policy_tag = tag_pii
    t1["customers"].columns["email"].unmasked_readers = BqPrincipals(
        groups={"pii@corp.com"}
    )
    t1["customers"].columns["email"].mask_expression = "SHA256"
    t1["customers"].columns["email"].masked_readers = BqPrincipals(
        groups={"support@corp.com"}
    )

    t1["orders"].row_policies = [
        BqRowPolicy(
            "rap_us", "region = 'US'", BqPrincipals(groups={"us-sales@corp.com"})
        ),
        BqRowPolicy(
            "rap_eu", "region = 'EU'", BqPrincipals(groups={"eu-sales@corp.com"})
        ),
        BqRowPolicy("rap_exec", "TRUE", BqPrincipals(groups={"execs@corp.com"})),
    ]
    t1["customers"].row_policies = [
        BqRowPolicy(
            "rap_uk", "country = 'UK'", BqPrincipals(groups={"uk-crm@corp.com"})
        ),
    ]

    b1 = compile_bq_security_overlays(
        project_files=project_files,
        bq_tables=t1,
        default_dataset="bq_access_testing",
        model_name="ecomm",
    )
    views_sec = b1.files["security/views.refinement.lkml"]
    exp_sec = b1.files["security/explores.refinement.lkml"]

    # Policy tag applied to TIMESTAMP dimension_group AND inherited by `total_base_salary` measure
    assert "dimension_group: terminated {\n    required_access_grants: [bq_tag_hr_comp]" in views_sec
    assert "measure: total_base_salary {\n    required_access_grants: [bq_tag_hr_comp]" in views_sec
    # Masked `email` gets 3-tier Liquid SHA256 + `bq_masked` tag, while `email_count` measure promotes to unmasked `bq_tag_pii_contact`!
    assert "TO_HEX(SHA256(CAST(${TABLE}.email AS STRING)))" in views_sec
    assert 'tags: ["bq_masked"]' in views_sec
    assert "measure: email_count {\n    required_access_grants: [bq_rom_bq_access_testing_customers_email, bq_tag_pii_contact]" in views_sec

    # Explore `orders` gets `access_filter`, `daily_rollup` auto-adds `orders.region`, and `left_outer` `customers` pushes RLS into `sql_on:`!
    assert "field: orders.region\n    user_attribute: bq_rls_bq_access_testing_orders_region" in exp_sec
    assert "dimensions: [orders.status, orders.region]" in exp_sec
    assert "sql_on: (${orders.customer_id} = ${customers.id}) AND (" in exp_sec
    assert "${customers.country} = 'UK'" in exp_sec

    # Attribute spec uses `advanced_filter_string` with `%,NULL` for `TRUE` bypass group
    rls_attr = b1.attributes["bq_rls_bq_access_testing_orders_region"]
    assert rls_attr.attr_type == "advanced_filter_string"
    assert rls_attr.groups["us-sales@corp.com"] == "US"
    assert rls_attr.groups["execs@corp.com"] == "%,NULL"

    # Assemble combined project & verify zero offline validation errors!
    stage1_files = {
        **project_files,
        **b1.files,
        "ecomm.model.lkml": ensure_model_security_includes(
            base_model, list(b1.files)
        ),
    }
    for rel_p, body in stage1_files.items():
        fp = tmp_path / rel_p
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(body, encoding="utf-8")
    api_res = parse_lookml_to_api(path=tmp_path)
    assert api_res.lookml_model_explores["ecomm::orders"].errors is None
    from lkr.parse.user_attributes import parse_user_attributes

    ua_res = parse_user_attributes(path=tmp_path)
    referenced_uas = {r.attribute_name for r in ua_res.attributes}
    assert referenced_uas.issubset(set(b1.attributes) | {"email"})

    # --- Stage 2: Mutate masking (`SHA256` -> `LAST_FOUR_CHARACTERS`) + multi-col RAP + `INNER JOIN` ---
    t1["customers"].columns["email"].mask_expression = "LAST_FOUR_CHARACTERS"
    t1["orders"].row_policies = [
        BqRowPolicy(
            "rap_multi",
            "region = 'US' AND amount < 1000",
            BqPrincipals(groups={"us-SMB@corp.com"}),
        )
    ]
    inner_model = base_model.replace("type: left_outer", "type: inner")
    b2 = compile_bq_security_overlays(
        project_files={**stage1_files, "ecomm.model.lkml": inner_model},
        bq_tables=t1,
        default_dataset="bq_access_testing",
        model_name="ecomm",
    )
    assert "CONCAT('XXXXX', RIGHT(CAST(${TABLE}.email AS STRING), 4))" in b2.files["security/views.refinement.lkml"]
    assert "sql_always_where:" in b2.files["security/explores.refinement.lkml"]
    assert "required_access_grants: [bq_tbl_bq_access_testing_customers, bq_tbl_bq_access_testing_orders]" in b2.files["security/explores.refinement.lkml"]

    # --- Stage 3: Remove all policies back to Stage 0 ---
    b3 = compile_bq_security_overlays(
        project_files=stage1_files,
        bq_tables=_empty_tables(),
        default_dataset="bq_access_testing",
        model_name="ecomm",
    )
    assert b3.files == {}
    assert b3.attributes == {}
    restored_model = ensure_model_security_includes(
        stage1_files["ecomm.model.lkml"], list(b3.files)
    )
    assert restored_model == base_model


def _parse_in_tmp(files: dict[str, str]) -> Any:
    from lkr.tools.bq_security import _parse_virtual_project

    return _parse_virtual_project(files)


def test_multi_table_persisted_ndt_and_sql_pdt_partial_table_access() -> None:
    """User has access to `orders` and NOT `customers`: verify shared Persisted NDT & SQL PDT scope `customers` to its columns!"""
    files = {
        "ecomm.model.lkml": (
            'connection: "bq_sa"\n'
            'include: "/*.view.lkml"\n\n'
            "explore: orders {\n"
            "  join: customers {\n"
            "    type: left_outer\n"
            "    relationship: many_to_one\n"
            "    sql_on: ${orders.customer_id} = ${customers.id} ;;\n"
            "  }\n"
            "}\n"
            "explore: order_customer_ndt {}\n"
            "explore: order_customer_pdt {}\n"
            "explore: order_inner_pdt {}\n"
            "explore: order_agg_no_rap_pdt {}\n"
        ),
        "orders.view.lkml": (
            "view: orders {\n"
            "  sql_table_name: `p.ds.orders` ;;\n"
            "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
            "  dimension: customer_id { type: number sql: ${TABLE}.customer_id ;; }\n"
            "  dimension: region { type: string sql: ${TABLE}.region ;; }\n"
            "  dimension: amount { type: number sql: ${TABLE}.amount ;; }\n"
            "  measure: total_amount { type: sum sql: ${amount} ;; }\n"
            "}\n"
        ),
        "customers.view.lkml": (
            "view: customers {\n"
            "  sql_table_name: `p.ds.customers` ;;\n"
            "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
            "  dimension: country { type: string sql: ${TABLE}.country ;; }\n"
            "  dimension: tier { type: string sql: ${TABLE}.tier ;; }\n"
            "  dimension: email { type: string sql: ${TABLE}.email ;; }\n"
            "}\n"
        ),
        # 1. Persisted Native Derived Table (`explore_source:` + `datagroup_trigger:`)
        "order_customer_ndt.view.lkml": (
            "view: order_customer_ndt {\n"
            "  derived_table: {\n"
            "    datagroup_trigger: nightly\n"
            "    explore_source: orders {\n"
            "      column: order_id { field: orders.id }\n"
            "      column: order_region { field: orders.region }\n"
            "      column: total_amount { field: orders.total_amount }\n"
            "      column: customer_country { field: customers.country }\n"
            "      column: customer_tier { field: customers.tier }\n"
            "      column: customer_email { field: customers.email }\n"
            "    }\n"
            "  }\n"
            "  dimension: order_id { primary_key: yes type: number }\n"
            "  dimension: order_region { type: string }\n"
            "  dimension: total_amount { type: number }\n"
            "  dimension: customer_country { type: string }\n"
            "  dimension: customer_tier { type: string }\n"
            "  dimension: customer_email { type: string }\n"
            "  measure: sum_revenue { type: sum sql: ${total_amount} ;; }\n"
            "  measure: tier_count { type: count_distinct sql: ${customer_tier} ;; }\n"
            "}\n"
        ),
        # 2. Persisted SQL Derived Table (`derived_table.sql` using `${view.SQL_TABLE_NAME}`)
        "order_customer_pdt.view.lkml": (
            "view: order_customer_pdt {\n"
            "  derived_table: {\n"
            "    datagroup_trigger: nightly\n"
            "    sql:\n"
            "      SELECT\n"
            "        o.id AS order_id,\n"
            "        o.region AS order_region,\n"
            "        o.amount AS amount,\n"
            "        c.country AS customer_country,\n"
            "        c.tier AS customer_tier,\n"
            "        c.email AS customer_email\n"
            "      FROM ${orders.SQL_TABLE_NAME} AS o\n"
            "      LEFT JOIN ${customers.SQL_TABLE_NAME} AS c ON o.customer_id = c.id ;;\n"
            "  }\n"
            "  dimension: order_id { primary_key: yes type: number sql: ${TABLE}.order_id ;; }\n"
            "  dimension: order_region { type: string sql: ${TABLE}.order_region ;; }\n"
            "  dimension: amount { type: number sql: ${TABLE}.amount ;; }\n"
            "  dimension: customer_country { type: string sql: ${TABLE}.customer_country ;; }\n"
            "  dimension: customer_tier { type: string sql: ${TABLE}.customer_tier ;; }\n"
            "  dimension: customer_email { type: string sql: ${TABLE}.customer_email ;; }\n"
            "  measure: sum_amount { type: sum sql: ${amount} ;; }\n"
            "  measure: tier_count { type: count_distinct sql: ${customer_tier} ;; }\n"
            "}\n"
        ),
        # 3. INNER JOIN PDT -> `customers` filters rows so whole PDT requires BOTH table grants & propagates BOTH spine `access_filter`s!
        "order_inner_pdt.view.lkml": (
            "view: order_inner_pdt {\n"
            "  derived_table: {\n"
            "    datagroup_trigger: nightly\n"
            "    sql: SELECT o.id, o.region, c.country, c.tier FROM ds.orders o INNER JOIN ds.customers c ON o.customer_id = c.id ;;\n"
            "  }\n"
            "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
            "  dimension: region { type: string sql: ${TABLE}.region ;; }\n"
            "  dimension: country { type: string sql: ${TABLE}.country ;; }\n"
            "  dimension: tier { type: string sql: ${TABLE}.tier ;; }\n"
            "}\n"
        ),
        # 4. PDT aggregating away RAP column `region` without a TRUE policy -> fail-closed `bq_rls_missing_*`!
        "order_agg_no_rap_pdt.view.lkml": (
            "view: order_agg_no_rap_pdt {\n"
            "  derived_table: {\n"
            "    datagroup_trigger: nightly\n"
            "    sql: SELECT customer_id, SUM(amount) AS total FROM ds.orders GROUP BY 1 ;;\n"
            "  }\n"
            "  dimension: customer_id { primary_key: yes type: number sql: ${TABLE}.customer_id ;; }\n"
            "  dimension: total { type: number sql: ${TABLE}.total ;; }\n"
            "}\n"
        ),
    }

    bq_tables = {
        "orders": BqTableSecurity(
            project_id="p",
            dataset_id="ds",
            table_id="orders",
            has_custom_table_iam=True,
            table_readers=BqPrincipals(groups={"order-users@corp.com"}),
            columns={
                "id": BqColumnSecurity("id", "id", "INT64"),
                "customer_id": BqColumnSecurity("customer_id", "customer_id", "INT64"),
                "region": BqColumnSecurity("region", "region", "STRING"),
                "amount": BqColumnSecurity("amount", "amount", "NUMERIC"),
            },
            row_policies=[
                BqRowPolicy(
                    "rap_us", "region = 'US'", BqPrincipals(groups={"us@corp.com"})
                )
            ],
        ),
        "customers": BqTableSecurity(
            project_id="p",
            dataset_id="ds",
            table_id="customers",
            has_custom_table_iam=True,
            table_readers=BqPrincipals(groups={"customer-users@corp.com"}),
            columns={
                "id": BqColumnSecurity("id", "id", "INT64"),
                "country": BqColumnSecurity("country", "country", "STRING"),
                "tier": BqColumnSecurity("tier", "tier", "STRING"),
                "email": BqColumnSecurity(
                    "email",
                    "email",
                    "STRING",
                    policy_tag="projects/1/locations/us/taxonomies/pii/policyTags/email",
                    unmasked_readers=BqPrincipals(groups={"pii@corp.com"}),
                    mask_expression="EMAIL_MASK",
                    masked_readers=BqPrincipals(groups={"support@corp.com"}),
                ),
            },
            row_policies=[
                BqRowPolicy(
                    "rap_uk", "country = 'UK'", BqPrincipals(groups={"uk@corp.com"})
                )
            ],
        ),
    }

    bundle = compile_bq_security_overlays(
        project_files=files,
        bq_tables=bq_tables,
        default_dataset="ds",
        model_name="ecomm",
    )
    merged = {
        **files,
        **bundle.files,
        "ecomm.model.lkml": ensure_model_security_includes(
            files["ecomm.model.lkml"], list(bundle.files)
        ),
    }
    proj = _parse_in_tmp(merged)
    m_views = proj.model["ecomm"].view
    m_exps = proj.model["ecomm"].explore

    for dt_name in ("order_customer_ndt", "order_customer_pdt"):
        v = m_views[dt_name]
        # Whole PDT/NDT view requires ONLY `bq_tbl_ds_orders` (NOT `bq_tbl_ds_customers`!)
        assert v.required_access_grants == ["bq_tbl_ds_orders"]
        # `orders`-backed fields require NO customer grants -> User A can query them cleanly!
        assert not v.dimension["order_id"].required_access_grants
        assert not v.dimension["order_region"].required_access_grants
        # `customers`-backed fields require `bq_tbl_ds_customers` + `CASE WHEN` RAP guard + masking!
        assert "bq_tbl_ds_customers" in (
            v.dimension["customer_tier"].required_access_grants or []
        )
        assert "CASE WHEN" in (v.dimension["customer_tier"].sql or "")
        assert f"${{{dt_name}.customer_country}}" in (
            v.dimension["customer_tier"].sql or ""
        )
        assert "REGEXP_REPLACE" in (v.dimension["customer_email"].sql or "")
        assert "bq_tbl_ds_customers" in (
            v.measure["tier_count"].required_access_grants or []
        )
        # Explore on the PDT/NDT automatically applies `orders.region` `access_filter` mapped to `order_region`!
        exp = m_exps[dt_name]
        assert _extract_access_filter_fields(exp.access_filter, dt_name) == [
            (f"{dt_name}.order_region", "bq_rls_ds_orders_region")
        ]

    # INNER JOIN PDT requires BOTH `orders` AND `customers` table grants on the whole PDT view AND both spine `access_filter`s!
    assert sorted(m_views["order_inner_pdt"].required_access_grants or []) == [
        "bq_tbl_ds_customers",
        "bq_tbl_ds_orders",
    ]
    assert sorted(
        _extract_access_filter_fields(
            m_exps["order_inner_pdt"].access_filter, "order_inner_pdt"
        )
    ) == [
        ("order_inner_pdt.country", "bq_rls_ds_customers_country"),
        ("order_inner_pdt.region", "bq_rls_ds_orders_region"),
    ]

    # Aggregated PDT omitting `region` fails closed with a valid registered `bq_rls_missing_*` grant!
    agg_grants = m_views["order_agg_no_rap_pdt"].required_access_grants or []
    assert any(g.startswith("bq_rls_missing_") for g in agg_grants)
    assert "bq_rls_missing_ds_orders_order_agg_no_rap_pdt" in bundle.files["security/bq_access_grants.refinement.lkml"]


def test_sync_looker_security_attributes_multi_group_union_and_cleanup() -> None:
    """Verify `UserAttributeUpdater` creates `advanced_filter_string`, unions multi-group RAP users, and cleans up removed policies."""
    from lkr.tools.bq_security import DesiredAttributeSpec

    sdk = MagicMock()
    attrs_store: dict[str, dict[str, Any]] = {}
    next_id = 10

    def _get_uas(path: str, **_kw: Any) -> list[dict[str, Any]]:
        assert path == "/user_attributes"
        return list(attrs_store.values())

    def _create_ua(body: Any) -> Any:
        nonlocal next_id
        aid = str(next_id)
        next_id += 1
        rec = {
            "id": aid,
            "name": body.name,
            "label": body.label,
            "type": body.type,
            "default_value": body.default_value,
        }
        attrs_store[aid] = rec
        return SimpleNamespace(**rec)

    def _get_ua(aid: str, *_args: Any, **_kw: Any) -> Any:
        return SimpleNamespace(**attrs_store[aid])

    def _del_ua(aid: str) -> None:
        attrs_store.pop(aid, None)

    sdk.get.side_effect = _get_uas
    sdk.create_user_attribute.side_effect = _create_ua
    sdk.user_attribute.side_effect = _get_ua
    sdk.delete_user_attribute.side_effect = _del_ua

    sdk.all_groups.return_value = [
        SimpleNamespace(id="g1", name="us-sales@corp.com"),
        SimpleNamespace(id="g2", name="eu-sales@corp.com"),
    ]
    sdk.search_groups.side_effect = lambda name, **_kw: (
        [SimpleNamespace(id="g1")]
        if "us-sales" in name
        else [SimpleNamespace(id="g2")]
        if "eu-sales" in name
        else []
    )
    # `alice@corp.com` belongs to BOTH `us-sales` and `eu-sales`!
    sdk.all_group_users.side_effect = lambda group_id, **_kw: (
        [SimpleNamespace(email="alice@corp.com"), SimpleNamespace(email="bob@corp.com")]
        if group_id == "g1"
        else [SimpleNamespace(email="alice@corp.com")]
    )
    sdk.user_for_credential.side_effect = lambda _kind, email: (
        SimpleNamespace(id="u_alice") if email == "alice@corp.com" else None
    )
    sdk.artifact.side_effect = Exception("not found")

    desired_stage1 = {
        "bq_rls_ds_orders_region": DesiredAttributeSpec(
            name="bq_rls_ds_orders_region",
            attr_type="advanced_filter_string",
            default_value="__BQ_RLS_DENY__",
            groups={"us-sales@corp.com": "US", "eu-sales@corp.com": "EU"},
        ),
        "bq_tbl_ds_orders": DesiredAttributeSpec(
            name="bq_tbl_ds_orders",
            attr_type="string",
            default_value="no",
            groups={"us-sales@corp.com": "yes"},
        ),
    }

    res1 = sync_looker_security_attributes(sdk, "ecomm_proj", desired_stage1)
    assert sorted(res1["synced_attributes"]) == [
        "bq_rls_ds_orders_region",
        "bq_tbl_ds_orders",
    ]
    # Verify `alice@corp.com` received the union `"US,EU"` user override!
    sdk.set_user_attribute_user_value.assert_called_once()
    u_call = sdk.set_user_attribute_user_value.call_args.kwargs
    assert u_call["user_id"] == "u_alice"
    assert u_call["body"].value == "US,EU"

    # Saved state artifact fed into Stage 3 removal -> deletes attributes & stale bindings!
    saved_payload = sdk.update_artifacts.call_args.kwargs["body"][0].value
    sdk.artifact.side_effect = None
    sdk.artifact.return_value = [SimpleNamespace(value=saved_payload)]

    res2 = sync_looker_security_attributes(sdk, "ecomm_proj", {})
    assert sorted(res2["deleted_attributes"]) == [
        "bq_rls_ds_orders_region",
        "bq_tbl_ds_orders",
    ]
    assert attrs_store == {}


def test_webhook_iam_suffix_and_create_lookml_views_bq_security(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify `:setIamPolicy` audit events strip the action suffix and `create_lookml_views(bq_security=True)` wires end-to-end."""
    ev = BigQueryAuditEvent.model_validate(
        {
            "protoPayload": {
                "methodName": "google.iam.v1.IAMPolicy.SetIamPolicy",
                "resourceName": "projects/fifth-inkwell/datasets/bq_access_testing/tables/orders:setIamPolicy",
            }
        }
    )
    assert ev.resolve_target() == (
        "fifth-inkwell",
        "bq_access_testing",
        "orders",
        "google.iam.v1.IAMPolicy.SetIamPolicy",
    )

    sdk = MagicMock()
    sdk.connection.return_value = SimpleNamespace(
        host="fifth-inkwell",
        database="bq_access_testing",
        username="sa@fifth-inkwell.iam.gserviceaccount.com",
    )
    remote_files: dict[str, str] = {
        "ecomm.model.lkml": 'connection: "bq_sa"\ninclude: "/bronze/*.view.lkml"\nexplore: orders {}\n',
        "bronze/orders.view.lkml": (
            "# AUTOGENERATED\nview: orders {\n"
            "  sql_table_name: `fifth-inkwell.bq_access_testing.orders` ;;\n"
            "  dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }\n"
            "}\n"
        ),
    }
    sdk.all_project_files.side_effect = lambda **_kw: [
        {"id": k} for k in remote_files
    ]
    sdk.get_file_content.side_effect = lambda project_id, file_path: remote_files[
        file_path
    ]
    sdk.update_file.side_effect = lambda project_id, file_content: remote_files.__setitem__(
        file_content.path, file_content.content
    )
    sdk.create_file.side_effect = lambda project_id, file_content: remote_files.__setitem__(
        file_content.path, file_content.content
    )
    sdk.artifact.side_effect = Exception("none")
    sdk.get.return_value = []
    sdk.create_user_attribute.return_value = SimpleNamespace(id="99")
    sdk.user_attribute.return_value = SimpleNamespace(
        id="99", name="bq_tbl_bq_access_testing_orders", label="L", type="string"
    )
    sdk.search_groups.return_value = [SimpleNamespace(id="g1")]

    monkeypatch.setattr(
        "lkr.tools.bq_security.discover_bq_security",
        lambda **_kw: {
            "orders": BqTableSecurity(
                project_id="fifth-inkwell",
                dataset_id="bq_access_testing",
                table_id="orders",
                has_custom_table_iam=True,
                table_readers=BqPrincipals(groups={"analysts@corp.com"}),
            )
        },
    )

    res = create_lookml_views(
        sdk=sdk,
        project_id="ecomm",
        connection="bq_sa",
        folder="bronze",
        event_json=ev,
        bq_security=True,
        gcp_token="tok",
    )
    assert res["status"] == "deployed"
    assert "security/bq_access_grants.refinement.lkml" in remote_files
    assert "security/views.refinement.lkml" in remote_files
    assert "# BEGIN LKR BQ SECURITY" in remote_files["ecomm.model.lkml"]


def test_offline_security_validator_catches_leaks() -> None:
    """Verify `parse_lookml_to_api` catches leaked measure grants, missing agg-table RLS dims, masked agg dims, and unguarded join RLS."""
    bad_lookml = """
    connection: "bq_sa"
    access_grant: bq_tag_comp {
      user_attribute: bq_tag_comp
      allowed_values: ["yes"]
    }
    view: orders {
      dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }
      dimension: region { type: string sql: ${TABLE}.region ;; }
      dimension: email { type: string tags: ["bq_masked"] sql: ${TABLE}.email ;; }
      dimension: salary { type: number required_access_grants: [bq_tag_comp] sql: ${TABLE}.salary ;; }
      measure: leaked_salary { type: sum sql: ${salary} ;; }
    }
    view: shipments {
      dimension: id { primary_key: yes type: number sql: ${TABLE}.id ;; }
      dimension: order_id { type: number sql: ${TABLE}.order_id ;; }
    }
    explore: orders {
      access_filter: {
        field: orders.region
        user_attribute: bq_rls_region
      }
      aggregate_table: broken_rollup {
        query: {
          dimensions: [orders.email]
          measures: [orders.leaked_salary]
        }
        materialization: { sql_trigger_value: SELECT 1 ;; }
      }
    }
    explore: shipments {
      join: orders {
        type: left_outer
        relationship: many_to_one
        sql_on: ${shipments.order_id} = ${orders.id} ;;
      }
    }
    """
    res = parse_lookml_to_api(lookml=bad_lookml)
    ord_errs = {
        e["type"]
        for e in (res.lookml_model_explores["inline::orders"].errors or [])
    }
    shp_errs = {
        e["type"]
        for e in (res.lookml_model_explores["inline::shipments"].errors or [])
    }
    assert "measure_missing_access_grants" in ord_errs
    assert "aggregate_table_missing_access_filter" in ord_errs
    assert "aggregate_table_masked_dimension" in ord_errs
    assert "unpropagated_join_rls" in shp_errs
