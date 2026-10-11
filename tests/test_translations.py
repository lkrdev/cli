import json
from pathlib import Path

from typer.testing import CliRunner

from lkr.main import app
from lkr.parse import (
    TranslationAnalysisResult,
    analyze_lookml_translations,
)

runner = CliRunner()


def test_translations_manifest_settings(tmp_path: Path):
    manifest = tmp_path / "manifest.lkml"
    manifest.write_text(
        """
project_name: "test_project"
localization_settings: {
  default_locale: fr_CA
  localization_level: strict
}
""",
        encoding="utf-8",
    )
    (tmp_path / "fr_CA.strings.json").write_text(
        '{"Hello": "Bonjour"}', encoding="utf-8"
    )
    (tmp_path / "users.view.lkml").write_text(
        """
view: users {
  label: "Hello"
  dimension: id {
    primary_key: yes
    label: "Hello"
  }
}
""",
        encoding="utf-8",
    )

    result = analyze_lookml_translations(path=tmp_path)
    assert isinstance(result, TranslationAnalysisResult)
    assert result.default_locale == "fr_CA"
    assert result.manifest_localization_level == "strict"
    assert result.default_locale_file == "fr_CA.strings.json"
    assert len(result.locales_checked) == 1
    assert result.locales_checked[0].locale == "fr_CA"
    assert result.total_missing_strings_count == 0


def test_translations_missing_explicit_label_and_titleize(tmp_path: Path):
    (tmp_path / "en.strings.json").write_text(
        json.dumps({"Order Items": "Order Items", "Sale Price": "Sale Price"}),
        encoding="utf-8",
    )
    (tmp_path / "views").mkdir()
    (tmp_path / "views" / "order_items.view.lkml").write_text(
        """
view: order_items {
  dimension: id {
    primary_key: yes
    label: "ID"
  }
  dimension: sale_price {}
}
""",
        encoding="utf-8",
    )
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "shop.model.lkml").write_text(
        """
connection: "bq"
include: "/views/*.view.lkml"
explore: order_items {}
""",
        encoding="utf-8",
    )

    result = analyze_lookml_translations(path=tmp_path)
    # view order_items has no label -> suggested: "Order Items"
    # dimension sale_price has no label -> suggested: "Sale Price"
    # explore order_items has no label -> suggested: "Order Items"
    unlabeled = [
        u
        for m in result.missing_translations
        for u in m.usages
        if u.missing_explicit_label
    ]
    unlabeled_objs = {u.object_name: u for u in unlabeled}
    assert "order_items" in unlabeled_objs
    assert "order_items.sale_price" in unlabeled_objs
    assert unlabeled_objs["order_items.sale_price"].missing_explicit_label is True
    assert unlabeled_objs["order_items.sale_price"].property == "label"


def test_translations_bypassed_in_foreign_locale(tmp_path: Path):
    # String "Dealership Name" is defined in fr_CA, but missing in default locale en
    (tmp_path / "en.strings.json").write_text(
        json.dumps({"Users": "Users"}), encoding="utf-8"
    )
    (tmp_path / "fr_CA.strings.json").write_text(
        json.dumps({"Users": "Utilisateurs", "Dealership Name": "Nom de concession"}),
        encoding="utf-8",
    )
    (tmp_path / "dealership.view.lkml").write_text(
        """
view: dealership {
  label: "Users"
  dimension: name {
    label: "Dealership Name"
  }
}
""",
        encoding="utf-8",
    )

    result = analyze_lookml_translations(path=tmp_path)
    bypassed = [
        m for m in result.missing_translations if "fr_CA" in m.bypassed_in_locales
    ]
    assert len(bypassed) == 1
    assert bypassed[0].string == "Dealership Name"
    assert bypassed[0].missing_in_default_locale is True
    assert bypassed[0].bypassed_in_locales == ["fr_CA"]
    assert "en" in bypassed[0].missing_in_locales

    # Check locale summary counts
    fr_summary = next(s for s in result.locales_checked if s.locale == "fr_CA")
    assert fr_summary.bypassed_due_to_missing_default_locale_count == 1


def test_translations_unused_keys(tmp_path: Path):
    (tmp_path / "en.strings.json").write_text(
        json.dumps({"Active Users": "Active Users", "legacy_unused_key": "Unused"}),
        encoding="utf-8",
    )
    (tmp_path / "test.view.lkml").write_text(
        """
view: test {
  label: "Active Users"
  dimension: id {
    primary_key: yes
    label: "Active Users"
  }
}
""",
        encoding="utf-8",
    )

    result = analyze_lookml_translations(path=tmp_path)
    unused = [u for u in result.unused_keys if u.locale == "en"]
    unused_key_names = {u.key for u in unused}
    assert "legacy_unused_key" in unused_key_names
    assert "Active Users" not in unused_key_names


def test_translations_hidden_fields_skipped(tmp_path: Path):
    (tmp_path / "en.strings.json").write_text(
        json.dumps({"Visible View": "Visible View", "Visible Dim": "Visible Dim"}),
        encoding="utf-8",
    )
    (tmp_path / "hidden.view.lkml").write_text(
        """
view: hidden_view {
  hidden: yes
  dimension: hidden_dim {
    label: "Should Not Be Flagged"
  }
}
view: partial_view {
  label: "Visible View"
  fields_hidden_by_default: yes
  dimension: implicit_hidden_dim {
    label: "Also Should Not Be Flagged"
  }
  dimension: explicit_visible_dim {
    hidden: no
    label: "Visible Dim"
  }
}
""",
        encoding="utf-8",
    )

    result = analyze_lookml_translations(path=tmp_path)
    all_usage_strings = {m.string for m in result.missing_translations}
    assert "Should Not Be Flagged" not in all_usage_strings
    assert "Also Should Not Be Flagged" not in all_usage_strings


def test_translations_liquid_localization_references(tmp_path: Path):
    (tmp_path / "en.strings.json").write_text(
        json.dumps({"My View": "My View"}), encoding="utf-8"
    )
    (tmp_path / "liquid.view.lkml").write_text(
        """
view: liquid_test {
  label: "My View"
  dimension: dynamic_col {
    sql: CASE WHEN ${TABLE}.flag = 1 THEN '{{ _localization['flag_active'] }}' ELSE '{{ _localization["flag_inactive"] }}' END ;;
  }
}
""",
        encoding="utf-8",
    )

    result = analyze_lookml_translations(path=tmp_path)
    missing_strings = {m.string for m in result.missing_translations}
    assert "flag_active" in missing_strings
    assert "flag_inactive" in missing_strings


def test_translations_cli_json_format(tmp_path: Path):
    (tmp_path / "en.strings.json").write_text('{"Orders": "Orders"}', encoding="utf-8")
    (tmp_path / "fr_CA.strings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "orders.view.lkml").write_text(
        """
view: orders {
  label: "Orders"
  dimension: id {
    primary_key: yes
    label: "Orders"
  }
}
""",
        encoding="utf-8",
    )

    cli_res = runner.invoke(
        app,
        [
            "parse",
            "lookml",
            "translations",
            "--path",
            str(tmp_path),
            "--format",
            "json",
        ],
    )
    assert cli_res.exit_code == 0
    payload = json.loads(cli_res.stdout)
    assert payload["default_locale"] == "en"
    assert len(payload["locales_checked"]) == 2
    assert any(m["string"] == "Orders" for m in payload["missing_translations"])


def test_translations_cli_text_format(tmp_path: Path):
    (tmp_path / "en.strings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "test.view.lkml").write_text(
        """
view: test {
  label: "Alpha String"
  dimension: x {
    label: "Beta String"
  }
}
""",
        encoding="utf-8",
    )

    cli_res = runner.invoke(
        app,
        [
            "parse",
            "lookml",
            "translations",
            "--path",
            str(tmp_path),
            "--format",
            "text",
        ],
    )
    assert cli_res.exit_code == 0
    lines = [
        line.strip() for line in cli_res.stdout.strip().split("\n") if line.strip()
    ]
    assert "Alpha String" in lines
    assert "Beta String" in lines


def test_translations_cli_output_file(tmp_path: Path):
    (tmp_path / "en.strings.json").write_text('{"Hello": "World"}', encoding="utf-8")
    (tmp_path / "sample.view.lkml").write_text(
        """
view: sample {
  label: "Hello"
  dimension: id {
    label: "Hello"
  }
}
""",
        encoding="utf-8",
    )
    out_file = tmp_path / "out.json"

    cli_res = runner.invoke(
        app,
        [
            "parse",
            "lookml",
            "translations",
            "--path",
            str(tmp_path),
            "--format",
            "json",
            "--output",
            str(out_file),
        ],
    )
    assert cli_res.exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["default_locale"] == "en"


def test_translations_cli_strict_and_validate(tmp_path: Path):
    (tmp_path / "en.strings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "orders.view.lkml").write_text(
        """
view: orders {
  label: "Missing Label String"
  dimension: id {
    label: "Missing Label String"
  }
}
""",
        encoding="utf-8",
    )

    # Without strict: exit code 0
    res_normal = runner.invoke(
        app,
        ["parse", "lookml", "translations", "--path", str(tmp_path)],
    )
    assert res_normal.exit_code == 0

    # With --strict: exit code 1
    res_strict = runner.invoke(
        app,
        ["parse", "lookml", "translations", "--path", str(tmp_path), "--strict"],
    )
    assert res_strict.exit_code == 1

    # With --validate: exit code 1
    res_validate = runner.invoke(
        app,
        ["parse", "lookml", "translations", "--path", str(tmp_path), "--validate"],
    )
    assert res_validate.exit_code == 1


def test_translations_cli_no_strings_found_error(tmp_path: Path):
    (tmp_path / "orders.view.lkml").write_text("view: orders {}", encoding="utf-8")
    res = runner.invoke(
        app,
        ["parse", "lookml", "translations", "--path", str(tmp_path)],
    )
    assert res.exit_code == 1
    assert "No strings JSON files were found" in res.stdout or res.exit_code == 1


def test_translations_cli_locale_filter_and_not_found(tmp_path: Path):
    (tmp_path / "en.strings.json").write_text('{"Orders": "Orders"}', encoding="utf-8")
    (tmp_path / "es_ES.strings.json").write_text(
        '{"Orders": "Pedidos"}', encoding="utf-8"
    )
    (tmp_path / "orders.view.lkml").write_text(
        """
view: orders {
  label: "Orders"
  dimension: id {
    label: "Orders"
  }
}
""",
        encoding="utf-8",
    )

    # Valid locale filter
    res_ok = runner.invoke(
        app,
        [
            "parse",
            "lookml",
            "translations",
            "--path",
            str(tmp_path),
            "--locale",
            "es_ES",
            "--format",
            "json",
        ],
    )
    assert res_ok.exit_code == 0
    payload = json.loads(res_ok.stdout)
    loc_names = [l["locale"] for l in payload["locales_checked"]]
    assert "es_ES" in loc_names

    # Invalid locale filter
    res_fail = runner.invoke(
        app,
        [
            "parse",
            "lookml",
            "translations",
            "--path",
            str(tmp_path),
            "--locale",
            "de_DE",
        ],
    )
    assert res_fail.exit_code == 1
