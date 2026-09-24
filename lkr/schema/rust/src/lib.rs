use pyo3::prelude::*;
use rayon::prelude::*;
use regex::Regex;
use serde_json::{Map, Value};
use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

pub type ValidationOutcome = (bool, Vec<String>, Vec<String>, Option<String>);

static FIELD_REF_RE: OnceLock<Regex> = OnceLock::new();
static SORT_ITEM_RE: OnceLock<Regex> = OnceLock::new();

fn field_ref_regex() -> &'static Regex {
    FIELD_REF_RE.get_or_init(|| Regex::new(r"\$\{([^}]*)\}").unwrap())
}

fn sort_item_regex() -> &'static Regex {
    SORT_ITEM_RE.get_or_init(|| {
        Regex::new(r"^([A-Za-z0-9_.]+)(?:\s+(?:asc|desc))?(?:\s+\d+)?$").unwrap()
    })
}

fn read_only_query_keys() -> &'static HashSet<&'static str> {
    static KEYS: OnceLock<HashSet<&'static str>> = OnceLock::new();
    KEYS.get_or_init(|| {
        HashSet::from([
            "can",
            "id",
            "slug",
            "client_id",
            "share_url",
            "expanded_share_url",
            "url",
            "has_table_calculations",
            "filter_config",
            "visible_ui_sections",
        ])
    })
}

fn allowed_custom_measure_types() -> &'static HashSet<&'static str> {
    static TYPES: OnceLock<HashSet<&'static str>> = OnceLock::new();
    TYPES.get_or_init(|| {
        HashSet::from([
            "average",
            "average_distinct",
            "count",
            "count_distinct",
            "list",
            "max",
            "median",
            "median_distinct",
            "min",
            "number",
            "percent_of_previous",
            "percent_of_total",
            "percentile",
            "percentile_distinct",
            "running_total",
            "sum",
            "sum_distinct",
            "string",
            "yesno",
            "date",
        ])
    })
}

#[derive(Clone)]
enum CompiledFilterRule {
    Enum {
        allowed: HashSet<String>,
        allowed_repr: String,
    },
    Pattern {
        regex: Regex,
        pattern_str: String,
    },
    AnyString,
}

#[pyclass]
pub struct RustExploreValidator {
    expected_model: Option<String>,
    expected_view: Option<String>,
    default_body_limit: String,
    default_top_limit: i64,
    base_fields_set: HashSet<String>,
    base_pivots_set: HashSet<String>,
    schema_all_ref_fields: HashSet<String>,
    measure_only_set: HashSet<String>,
    filter_rules: HashMap<String, CompiledFilterRule>,
    allowed_top_keys: HashSet<String>,
    allowed_body_keys: HashSet<String>,
    allowed_result_formats: HashSet<String>,
}

impl RustExploreValidator {
    fn compile_filter_prop(
        prop_schema: &Value,
        defs_regexes: &HashMap<String, (Regex, String)>,
    ) -> CompiledFilterRule {
        if let Some(ref_str) = prop_schema.get("$ref").and_then(|v| v.as_str()) {
            if let Some(def_name) = ref_str.strip_prefix("#/$defs/") {
                if let Some((re, pat)) = defs_regexes.get(def_name) {
                    return CompiledFilterRule::Pattern {
                        regex: re.clone(),
                        pattern_str: pat.clone(),
                    };
                }
            }
        }
        if let Some(enum_arr) = prop_schema.get("enum").and_then(|v| v.as_array()) {
            let mut allowed = HashSet::new();
            let mut repr_items = Vec::new();
            for item in enum_arr {
                if let Some(s) = item.as_str() {
                    allowed.insert(s.to_string());
                    repr_items.push(format!("'{}'", s));
                }
            }
            return CompiledFilterRule::Enum {
                allowed,
                allowed_repr: format!("[{}]", repr_items.join(", ")),
            };
        }
        if let Some(pat_str) = prop_schema.get("pattern").and_then(|v| v.as_str()) {
            if let Ok(re) = Regex::new(&format!("^(?:{})$", pat_str)) {
                return CompiledFilterRule::Pattern {
                    regex: re,
                    pattern_str: pat_str.to_string(),
                };
            }
        }
        CompiledFilterRule::AnyString
    }

    fn sanitize_body(body_map: &Map<String, Value>) -> Map<String, Value> {
        let ro_keys = read_only_query_keys();
        let mut cleaned = Map::new();
        for (k, v) in body_map {
            if ro_keys.contains(k.as_str()) || v.is_null() {
                continue;
            }
            if (k == "limit" || k == "column_limit") && v.is_i64() {
                cleaned.insert(k.clone(), Value::String(v.as_i64().unwrap().to_string()));
            } else {
                cleaned.insert(k.clone(), v.clone());
            }
        }
        cleaned
    }

    fn validate_expression_refs(
        expr: &str,
        valid_fields: &HashSet<String>,
        disallowed_table_calcs: Option<&HashSet<String>>,
        self_field_name: Option<&str>,
        path: &str,
        errors: &mut Vec<String>,
    ) {
        for cap in field_ref_regex().captures_iter(expr) {
            let raw_inner = cap.get(1).map(|m| m.as_str()).unwrap_or("").trim();
            if raw_inner.is_empty() {
                errors.push(format!(
                    "{}: empty field reference '${{}}' is not allowed",
                    path
                ));
                continue;
            }
            let normalized_ref = raw_inner
                .strip_suffix(":row_total")
                .or_else(|| raw_inner.strip_suffix(":total"))
                .unwrap_or(raw_inner)
                .trim();

            if let Some(self_name) = self_field_name {
                if normalized_ref == self_name {
                    errors.push(format!(
                        "{}: dynamic field '{}' cannot reference itself in '${{{}}}'",
                        path, self_name, raw_inner
                    ));
                    continue;
                }
            }
            if let Some(tc_set) = disallowed_table_calcs {
                if tc_set.contains(normalized_ref) {
                    errors.push(format!(
                        "{}: SQL expression cannot reference post-query table_calculation '${{{}}}'",
                        path, raw_inner
                    ));
                    continue;
                }
            }
            if !valid_fields.contains(normalized_ref) {
                errors.push(format!(
                    "{}: referenced field '${{{}}}' is not a valid visible explore field or dynamic_field .name",
                    path, raw_inner
                ));
            }
        }
    }

    fn validate_filter_map(
        &self,
        filters_obj: &Map<String, Value>,
        path: &str,
        errors: &mut Vec<String>,
    ) {
        for (k, v) in filters_obj {
            let prop_path = format!("{}.{}", path, k);
            let Some(rule) = self.filter_rules.get(k) else {
                errors.push(format!(
                    "{}: unknown or hidden field '{}' is not allowed",
                    prop_path, k
                ));
                continue;
            };
            if v.is_null() {
                continue;
            }
            let Some(s) = v.as_str() else {
                errors.push(format!("{}: expected string filter expression", prop_path));
                continue;
            };
            match rule {
                CompiledFilterRule::Enum {
                    allowed,
                    allowed_repr,
                } => {
                    if !allowed.contains(s) {
                        errors.push(format!(
                            "{}: value '{}' is not in allowed values {}",
                            prop_path, s, allowed_repr
                        ));
                    }
                }
                CompiledFilterRule::Pattern { regex, pattern_str } => {
                    if !regex.is_match(s) {
                        errors.push(format!(
                            "{}: value '{}' does not match filter expression pattern '{}'",
                            prop_path, s, pattern_str
                        ));
                    }
                }
                CompiledFilterRule::AnyString => {}
            }
        }
    }

    fn validate_single_value(&self, raw_val: Value) -> ValidationOutcome {
        let mut root_obj = match raw_val {
            Value::Object(obj) => obj,
            _ => {
                return (
                    false,
                    vec!["$: expected query payload to be a JSON object".to_string()],
                    Vec::new(),
                    None,
                );
            }
        };

        let mut payload: Map<String, Value> = Map::new();
        if let Some(body_val) = root_obj.remove("body") {
            payload = root_obj;
            payload
                .entry("result_format".to_string())
                .or_insert_with(|| Value::String("json".to_string()));
            let Some(body_map) = body_val.as_object() else {
                return (
                    false,
                    vec!["$.body: expected object".to_string()],
                    Vec::new(),
                    None,
                );
            };
            payload.insert("body".to_string(), Value::Object(Self::sanitize_body(body_map)));
        } else {
            payload.insert(
                "result_format".to_string(),
                Value::String("json".to_string()),
            );
            payload.insert("body".to_string(), Value::Object(Self::sanitize_body(&root_obj)));
        }

        payload
            .entry("limit".to_string())
            .or_insert_with(|| Value::Number(self.default_top_limit.into()));

        let body = payload.get_mut("body").unwrap().as_object_mut().unwrap();
        if !body.contains_key("model") {
            if let Some(ref m) = self.expected_model {
                body.insert("model".to_string(), Value::String(m.clone()));
            }
        }
        if !body.contains_key("view") {
            if let Some(ref v) = self.expected_view {
                body.insert("view".to_string(), Value::String(v.clone()));
            }
        }
        body.entry("limit".to_string())
            .or_insert_with(|| Value::String(self.default_body_limit.clone()));

        let mut errors: Vec<String> = Vec::new();
        let mut warnings: Vec<String> = Vec::new();
        let mut dim_like_dynamic: Vec<String> = Vec::new();
        let mut non_dim_like_dynamic: Vec<String> = Vec::new();
        let mut table_calc_names: HashSet<String> = HashSet::new();
        let mut parsed_dyn_items: Vec<Value> = Vec::new();

        // Step 1: Parse and validate dynamic_fields
        let mut dyn_parse_ok = false;
        if let Some(raw_dyn) = body.get("dynamic_fields") {
            if let Some(dyn_str) = raw_dyn.as_str() {
                match serde_json::from_str::<Value>(dyn_str) {
                    Ok(Value::Array(arr)) => {
                        parsed_dyn_items = arr;
                        dyn_parse_ok = true;
                    }
                    Ok(_) => {
                        errors.push(
                            "$.body.dynamic_fields: JSON string must decode to a JSON array"
                                .to_string(),
                        );
                    }
                    Err(e) => {
                        errors.push(format!(
                            "$.body.dynamic_fields: invalid JSON string ({})",
                            e
                        ));
                    }
                }
            } else if let Some(arr) = raw_dyn.as_array() {
                parsed_dyn_items = arr.clone();
                dyn_parse_ok = true;
            } else if !raw_dyn.is_null() {
                errors.push(
                    "$.body.dynamic_fields: expected array or JSON-encoded array string"
                        .to_string(),
                );
            }

            if dyn_parse_ok {
                for item in &parsed_dyn_items {
                    if let Some(obj) = item.as_object() {
                        if let Some(d) = obj.get("dimension").and_then(|v| v.as_str()) {
                            if !d.is_empty() {
                                dim_like_dynamic.push(d.to_string());
                            }
                        } else if let Some(m) = obj.get("measure").and_then(|v| v.as_str()) {
                            if !m.is_empty() {
                                non_dim_like_dynamic.push(m.to_string());
                            }
                        } else if let Some(tc) =
                            obj.get("table_calculation").and_then(|v| v.as_str())
                        {
                            if !tc.is_empty() {
                                non_dim_like_dynamic.push(tc.to_string());
                                table_calc_names.insert(tc.to_string());
                            }
                        }
                    }
                }
            }
        }

        let mut all_ref_fields = self.schema_all_ref_fields.clone();
        let mut all_valid_fields = self.base_fields_set.clone();
        let mut all_valid_pivots = self.base_pivots_set.clone();
        for d in &dim_like_dynamic {
            all_ref_fields.insert(d.clone());
            all_valid_fields.insert(d.clone());
            all_valid_pivots.insert(d.clone());
        }
        for nd in &non_dim_like_dynamic {
            all_ref_fields.insert(nd.clone());
            all_valid_fields.insert(nd.clone());
        }
        let non_dim_dyn_set: HashSet<&str> =
            non_dim_like_dynamic.iter().map(|s| s.as_str()).collect();

        if dyn_parse_ok {
            for (idx, item) in parsed_dyn_items.iter().enumerate() {
                let item_path = format!("$.body.dynamic_fields[{}]", idx);
                let Some(obj) = item.as_object() else {
                    errors.push(format!("{}: expected object", item_path));
                    continue;
                };
                let dim_name = obj
                    .get("dimension")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty());
                let meas_name = obj
                    .get("measure")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty());
                let tc_name = obj
                    .get("table_calculation")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty());

                let has_dim = dim_name.is_some();
                let has_meas = meas_name.is_some();
                let has_tc = tc_name.is_some();

                let kind_count = (has_dim as u8) + (has_meas as u8) + (has_tc as u8);
                if kind_count != 1 {
                    errors.push(format!(
                        "{}: value must match exactly one dynamic field kind (CustomDimension, CustomMeasure, or TableCalculation)",
                        item_path
                    ));
                    continue;
                }

                let self_name = dim_name.or(meas_name).or(tc_name);

                if has_dim {
                    let has_expr = obj
                        .get("expression")
                        .and_then(|v| v.as_str())
                        .is_some_and(|s| !s.is_empty());
                    let has_calc = obj
                        .get("calculation_type")
                        .and_then(|v| v.as_str())
                        .is_some_and(|s| !s.is_empty())
                        && obj.get("args").is_some_and(|v| v.is_array());
                    let has_based_on = obj
                        .get("based_on")
                        .and_then(|v| v.as_str())
                        .is_some_and(|s| !s.is_empty());
                    if !has_expr && !has_calc && !has_based_on {
                        errors.push(format!(
                            "{}: CustomDimension must specify 'expression', 'based_on', or 'calculation_type' + 'args'",
                            item_path
                        ));
                    }
                    if let Some(bo) = obj.get("based_on").and_then(|v| v.as_str()) {
                        if !all_ref_fields.contains(bo) {
                            errors.push(format!(
                                "{}.based_on: '{}' is not a valid visible explore field or dynamic_field .name",
                                item_path, bo
                            ));
                        }
                    }
                } else if has_meas {
                    let has_based_on = obj
                        .get("based_on")
                        .and_then(|v| v.as_str())
                        .is_some_and(|s| !s.is_empty());
                    let has_expr = obj
                        .get("expression")
                        .and_then(|v| v.as_str())
                        .is_some_and(|s| !s.is_empty());
                    if let Some(mtype) = obj.get("type").and_then(|v| v.as_str()) {
                        if !allowed_custom_measure_types().contains(mtype) {
                            errors.push(format!(
                                "{}.type: value '{}' is not in allowed custom measure types",
                                item_path, mtype
                            ));
                        }
                    }
                    if !has_based_on && !has_expr {
                        errors.push(format!(
                            "{}: CustomMeasure must specify 'based_on' or 'expression'",
                            item_path
                        ));
                    }
                    if let Some(bo) = obj.get("based_on").and_then(|v| v.as_str()) {
                        if !all_ref_fields.contains(bo) {
                            errors.push(format!(
                                "{}.based_on: '{}' is not a valid visible explore field or dynamic_field .name",
                                item_path, bo
                            ));
                        }
                    }
                    if let Some(filters_val) = obj.get("filters") {
                        if let Some(f_obj) = filters_val.as_object() {
                            self.validate_filter_map(
                                f_obj,
                                &format!("{}.filters", item_path),
                                &mut errors,
                            );
                        } else if !filters_val.is_null() {
                            errors.push(format!("{}.filters: expected object", item_path));
                        }
                    }
                } else if has_tc {
                    let has_expr = obj
                        .get("expression")
                        .and_then(|v| v.as_str())
                        .is_some_and(|s| !s.is_empty());
                    let has_calc = obj
                        .get("calculation_type")
                        .and_then(|v| v.as_str())
                        .is_some_and(|s| !s.is_empty())
                        && obj.get("args").is_some_and(|v| v.is_array());
                    if !has_expr && !has_calc {
                        errors.push(format!(
                            "{}: TableCalculation must specify either 'expression' or 'calculation_type' + 'args'",
                            item_path
                        ));
                    }
                    for ref_key in ["based_on", "source_field"] {
                        if let Some(ref_val) = obj.get(ref_key).and_then(|v| v.as_str()) {
                            if !all_ref_fields.contains(ref_val) {
                                errors.push(format!(
                                    "{}.{}: '{}' is not a valid visible explore field or dynamic_field .name",
                                    item_path, ref_key, ref_val
                                ));
                            }
                        }
                    }
                    if let Some(args_arr) = obj.get("args").and_then(|v| v.as_array()) {
                        for (a_idx, a_val) in args_arr.iter().enumerate() {
                            if let Some(s) = a_val.as_str() {
                                if !all_ref_fields.contains(s) {
                                    errors.push(format!(
                                        "{}.args[{}]: '{}' is not a valid visible explore field or dynamic_field .name",
                                        item_path, a_idx, s
                                    ));
                                }
                            }
                        }
                    }
                }

                let disallowed_tcs = if has_tc {
                    None
                } else {
                    Some(&table_calc_names)
                };
                for expr_key in ["expression", "filter_expression"] {
                    if let Some(expr_str) = obj.get(expr_key).and_then(|v| v.as_str()) {
                        if !expr_str.is_empty() {
                            Self::validate_expression_refs(
                                expr_str,
                                &all_ref_fields,
                                disallowed_tcs,
                                self_name,
                                &format!("{}.{}", item_path, expr_key),
                                &mut errors,
                            );
                        }
                    }
                }
            }
        }

        // Step 2: Validate model and view
        if let Some(ref expected_m) = self.expected_model {
            let actual_m = body.get("model").and_then(|v| v.as_str());
            if actual_m != Some(expected_m.as_str()) {
                errors.push(format!(
                    "$.body.model: expected const '{}', got {:?}",
                    expected_m,
                    body.get("model")
                ));
            }
        }
        if let Some(ref expected_v) = self.expected_view {
            let actual_v = body.get("view").and_then(|v| v.as_str());
            if actual_v != Some(expected_v.as_str()) {
                errors.push(format!(
                    "$.body.view: expected const '{}', got {:?}",
                    expected_v,
                    body.get("view")
                ));
            }
        }

        // Step 3: Validate fields
        if let Some(fields_val) = body.get("fields") {
            if let Some(arr) = fields_val.as_array() {
                for (idx, item) in arr.iter().enumerate() {
                    let Some(s) = item.as_str() else {
                        errors.push(format!("$.body.fields[{}]: expected string", idx));
                        continue;
                    };
                    if !all_valid_fields.contains(s) {
                        errors.push(format!(
                            "$.body.fields[{}]: '{}' is not a valid visible dimension, measure, or dynamic_field .name",
                            idx, s
                        ));
                    }
                }
            } else if !fields_val.is_null() {
                errors.push("$.body.fields: expected array".to_string());
            }
        }

        // Step 4: Validate pivots
        if let Some(pivots_val) = body.get("pivots") {
            if let Some(arr) = pivots_val.as_array() {
                for (idx, item) in arr.iter().enumerate() {
                    let Some(s) = item.as_str() else {
                        errors.push(format!("$.body.pivots[{}]: expected string", idx));
                        continue;
                    };
                    if !all_valid_pivots.contains(s) {
                        if self.measure_only_set.contains(s) {
                            errors.push(format!(
                                "$.body.pivots[{}]: measure '{}' cannot be used as a pivot (pivots must be dimensions or dimension_like dynamic_fields)",
                                idx, s
                            ));
                        } else if non_dim_dyn_set.contains(s) {
                            errors.push(format!(
                                "$.body.pivots[{}]: dynamic_field '{}' is a measure or table_calculation and cannot be used as a pivot",
                                idx, s
                            ));
                        } else {
                            errors.push(format!(
                                "$.body.pivots[{}]: '{}' is not a valid visible dimension or dimension_like dynamic_field .name",
                                idx, s
                            ));
                        }
                    }
                }
            } else if !pivots_val.is_null() {
                errors.push("$.body.pivots: expected array".to_string());
            }
        }

        // Warning check: column_limit without pivots
        if body.get("column_limit").is_some_and(|v| !v.is_null())
            && body
                .get("pivots")
                .and_then(|v| v.as_array())
                .is_none_or(|arr| arr.is_empty())
        {
            warnings.push(
                "$.body.column_limit: 'column_limit' is set without 'pivots' (column_limit only applies to pivoted queries)"
                    .to_string(),
            );
        }

        // Step 5: Validate filters
        if let Some(filters_val) = body.get("filters") {
            if let Some(f_obj) = filters_val.as_object() {
                self.validate_filter_map(f_obj, "$.body.filters", &mut errors);
            } else if !filters_val.is_null() {
                errors.push("$.body.filters: expected object".to_string());
            }
        }

        // Step 6: Validate sorts
        if let Some(sorts_val) = body.get("sorts") {
            if let Some(arr) = sorts_val.as_array() {
                let re = sort_item_regex();
                for (idx, item) in arr.iter().enumerate() {
                    let Some(sort_expr) = item.as_str() else {
                        errors.push(format!("$.body.sorts[{}]: expected string", idx));
                        continue;
                    };
                    if sort_expr == "__UNSORTED__" {
                        continue;
                    }
                    let Some(cap) = re.captures(sort_expr) else {
                        errors.push(format!(
                            "$.body.sorts[{}]: invalid sort expression '{}' (expected '<field>', '<field> desc', '<field> 0', or '__UNSORTED__')",
                            idx, sort_expr
                        ));
                        continue;
                    };
                    let sort_field = cap.get(1).unwrap().as_str();
                    let base_dim = sort_field.strip_suffix("__sort_");
                    if !all_valid_fields.contains(sort_field)
                        && !base_dim.is_some_and(|bd| all_valid_pivots.contains(bd))
                    {
                        errors.push(format!(
                            "$.body.sorts[{}]: unknown or hidden sort field '{}'",
                            idx, sort_field
                        ));
                    }
                }
            } else if !sorts_val.is_null() {
                errors.push("$.body.sorts: expected array".to_string());
            }
        }

        // Step 7: Validate fill_fields and subtotals
        if let Some(fill_val) = body.get("fill_fields") {
            if let Some(arr) = fill_val.as_array() {
                for (idx, item) in arr.iter().enumerate() {
                    let Some(s) = item.as_str() else {
                        errors.push(format!(
                            "$.body.fill_fields[{}]: must be a non-hidden dimension or dimension_like dynamic field",
                            idx
                        ));
                        continue;
                    };
                    if !all_valid_pivots.contains(s) {
                        errors.push(format!(
                            "$.body.fill_fields[{}]: '{}' must be a non-hidden dimension or dimension_like dynamic field",
                            idx, s
                        ));
                    }
                }
            } else if !fill_val.is_null() {
                errors.push("$.body.fill_fields: expected array".to_string());
            }
        }

        if let Some(sub_val) = body.get("subtotals") {
            if let Some(arr) = sub_val.as_array() {
                for (idx, item) in arr.iter().enumerate() {
                    let Some(s) = item.as_str() else {
                        errors.push(format!(
                            "$.body.subtotals[{}]: must be a non-hidden dimension or dimension_like dynamic field",
                            idx
                        ));
                        continue;
                    };
                    if !all_valid_pivots.contains(s) {
                        errors.push(format!(
                            "$.body.subtotals[{}]: '{}' must be a non-hidden dimension or dimension_like dynamic field",
                            idx, s
                        ));
                    }
                }
            } else if !sub_val.is_null() {
                errors.push("$.body.subtotals: expected array of dimensions".to_string());
            }
        }

        // Step 8: Validate other properties & filter_expression
        if let Some(fe_val) = body.get("filter_expression") {
            if let Some(fe_str) = fe_val.as_str() {
                Self::validate_expression_refs(
                    fe_str,
                    &all_ref_fields,
                    Some(&table_calc_names),
                    None,
                    "$.body.filter_expression",
                    &mut errors,
                );
            } else if !fe_val.is_null() {
                errors.push("$.body.filter_expression: expected string".to_string());
            }
        }

        for k in body.keys() {
            if !self.allowed_body_keys.contains(k) {
                errors.push(format!(
                    "$.body.{}: unknown or hidden field '{}' is not allowed",
                    k, k
                ));
            }
        }
        for (k, v) in &payload {
            if k == "body" {
                continue;
            }
            if !self.allowed_top_keys.contains(k) {
                errors.push(format!("$.{}: unknown property '{}' is not allowed", k, k));
            } else if k == "result_format" {
                if let Some(rf) = v.as_str() {
                    if !self.allowed_result_formats.is_empty()
                        && !self.allowed_result_formats.contains(rf)
                    {
                        errors.push(format!(
                            "$.result_format: value '{}' is not in allowed values",
                            rf
                        ));
                    }
                }
            }
        }

        let is_valid = errors.is_empty();
        let normalized_json = if is_valid {
            let mut norm_payload = payload;
            let norm_body = norm_payload.get_mut("body").unwrap().as_object_mut().unwrap();
            if let Some(dyn_val) = norm_body.get("dynamic_fields") {
                if dyn_val.is_array() {
                    if let Ok(serialized) = serde_json::to_string(dyn_val) {
                        norm_body.insert("dynamic_fields".to_string(), Value::String(serialized));
                    }
                }
            }
            serde_json::to_string(&Value::Object(norm_payload)).ok()
        } else {
            None
        };

        (is_valid, errors, warnings, normalized_json)
    }
}

#[pymethods]
impl RustExploreValidator {
    #[new]
    pub fn from_schema_json(schema_json: &str) -> PyResult<Self> {
        let schema: Value = serde_json::from_str(schema_json).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Invalid schema JSON: {}", e))
        })?;

        let mut defs_regexes: HashMap<String, (Regex, String)> = HashMap::new();
        if let Some(defs_obj) = schema.get("$defs").and_then(|v| v.as_object()) {
            for (def_name, def_val) in defs_obj {
                if let Some(pat_str) = def_val.get("pattern").and_then(|v| v.as_str()) {
                    if let Ok(re) = Regex::new(&format!("^(?:{})$", pat_str)) {
                        defs_regexes.insert(def_name.clone(), (re, pat_str.to_string()));
                    }
                }
            }
        }

        let top_props = schema
            .get("properties")
            .and_then(|v| v.as_object())
            .cloned()
            .unwrap_or_default();

        let allowed_top_keys: HashSet<String> = top_props.keys().cloned().collect();
        let allowed_result_formats: HashSet<String> = top_props
            .get("result_format")
            .and_then(|v| v.get("enum"))
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        let default_top_limit = top_props
            .get("limit")
            .and_then(|v| v.get("default"))
            .and_then(|v| v.as_i64())
            .unwrap_or(500);

        let body_props = top_props
            .get("body")
            .and_then(|v| v.get("properties"))
            .and_then(|v| v.as_object())
            .cloned()
            .unwrap_or_default();

        let allowed_body_keys: HashSet<String> = body_props.keys().cloned().collect();

        let expected_model = body_props
            .get("model")
            .and_then(|v| v.get("const"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let expected_view = body_props
            .get("view")
            .and_then(|v| v.get("const"))
            .and_then(|v| v.as_str())
            .map(|s| s.to_string());

        let default_body_limit = body_props
            .get("limit")
            .and_then(|v| v.get("default"))
            .and_then(|v| v.as_str())
            .unwrap_or("500")
            .to_string();

        let base_fields_set: HashSet<String> = body_props
            .get("fields")
            .and_then(|v| v.get("items"))
            .and_then(|v| v.get("enum"))
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        let base_pivots_set: HashSet<String> = body_props
            .get("pivots")
            .and_then(|v| v.get("items"))
            .and_then(|v| v.get("enum"))
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        let measure_only_set: HashSet<String> = base_fields_set
            .difference(&base_pivots_set)
            .cloned()
            .collect();

        let mut filter_rules: HashMap<String, CompiledFilterRule> = HashMap::new();
        if let Some(filter_props) = body_props
            .get("filters")
            .and_then(|v| v.get("properties"))
            .and_then(|v| v.as_object())
        {
            for (field_name, prop_schema) in filter_props {
                let rule = Self::compile_filter_prop(prop_schema, &defs_regexes);
                filter_rules.insert(field_name.clone(), rule);
            }
        }

        let mut schema_all_ref_fields = base_fields_set.clone();
        for k in filter_rules.keys() {
            schema_all_ref_fields.insert(k.clone());
        }

        Ok(Self {
            expected_model,
            expected_view,
            default_body_limit,
            default_top_limit,
            base_fields_set,
            base_pivots_set,
            schema_all_ref_fields,
            measure_only_set,
            filter_rules,
            allowed_top_keys,
            allowed_body_keys,
            allowed_result_formats,
        })
    }

    pub fn validate_json(&self, query_json: &str) -> PyResult<ValidationOutcome> {
        let val: Value = serde_json::from_str(query_json).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Invalid query JSON: {}", e))
        })?;
        Ok(self.validate_single_value(val))
    }

    pub fn validate_batch_json(
        &self,
        py: Python<'_>,
        queries_json: Vec<String>,
    ) -> PyResult<Vec<ValidationOutcome>> {
        let results = py.allow_threads(|| {
            queries_json
                .par_iter()
                .map(|q_str| match serde_json::from_str::<Value>(q_str) {
                    Ok(val) => self.validate_single_value(val),
                    Err(e) => (
                        false,
                        vec![format!("Invalid query JSON: {}", e)],
                        Vec::new(),
                        None,
                    ),
                })
                .collect()
        });
        Ok(results)
    }
}

#[pymodule]
fn _schema_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustExploreValidator>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sample_schema() -> String {
        json!({
            "$defs": {
                "StringFilterExpression": { "type": "string" },
                "NumberFilterExpression": { "type": "string", "pattern": "^-?\\d+$" }
            },
            "properties": {
                "result_format": { "type": "string", "enum": ["json", "csv"] },
                "limit": { "type": "integer", "default": 500 },
                "body": {
                    "type": "object",
                    "properties": {
                        "model": { "type": "string", "const": "thelook" },
                        "view": { "type": "string", "const": "order_items" },
                        "fields": { "type": "array", "items": { "type": "string", "enum": ["order_items.status", "order_items.total_sale_price"] } },
                        "pivots": { "type": "array", "items": { "type": "string", "enum": ["order_items.status"] } },
                        "filters": {
                            "type": "object",
                            "properties": {
                                "order_items.status": { "$ref": "#/$defs/StringFilterExpression" },
                                "order_items.total_sale_price": { "$ref": "#/$defs/NumberFilterExpression" }
                            }
                        },
                        "sorts": { "type": "array" },
                        "limit": { "type": "string", "default": "500" },
                        "column_limit": { "type": "string" },
                        "subtotals": { "type": "array" },
                        "dynamic_fields": { "type": "array" },
                        "filter_expression": { "type": "string" }
                    }
                }
            }
        })
        .to_string()
    }

    #[test]
    fn test_sanitize_body_strips_read_only_and_coerces_limits() {
        let mut raw = Map::new();
        raw.insert("id".to_string(), json!(123));
        raw.insert("slug".to_string(), json!("abc"));
        raw.insert("client_id".to_string(), json!("cid"));
        raw.insert("limit".to_string(), json!(100));
        raw.insert("column_limit".to_string(), json!(50));
        raw.insert("model".to_string(), json!("thelook"));

        let cleaned = RustExploreValidator::sanitize_body(&raw);
        assert!(!cleaned.contains_key("id"));
        assert!(!cleaned.contains_key("slug"));
        assert!(!cleaned.contains_key("client_id"));
        assert_eq!(cleaned.get("limit"), Some(&json!("100")));
        assert_eq!(cleaned.get("column_limit"), Some(&json!("50")));
        assert_eq!(cleaned.get("model"), Some(&json!("thelook")));
    }

    #[test]
    fn test_validate_single_value_and_edge_cases() {
        let val = RustExploreValidator::from_schema_json(&sample_schema()).unwrap();

        // Non-object root payload
        let (ok, errs, _, _) = val.validate_single_value(json!(["not_an_object"]));
        assert!(!ok);
        assert!(errs[0].contains("expected query payload to be a JSON object"));

        // Non-object body payload
        let (ok, errs, _, _) = val.validate_single_value(json!({"body": "not_an_object"}));
        assert!(!ok);
        assert!(errs[0].contains("$.body: expected object"));

        // CustomMeasure with non-object filters rejected
        let (ok, errs, _, _) = val.validate_single_value(json!({
            "body": {
                "model": "thelook",
                "view": "order_items",
                "fields": ["cm1"],
                "dynamic_fields": [{
                    "measure": "cm1",
                    "based_on": "order_items.total_sale_price",
                    "filters": "invalid_non_object"
                }]
            }
        }));
        assert!(!ok);
        assert!(errs.iter().any(|e| e.contains(".filters: expected object")));

        // column_limit without pivots emits warning and remains valid
        let (ok, errs, warns, _) = val.validate_single_value(json!({
            "body": {
                "model": "thelook",
                "view": "order_items",
                "fields": ["order_items.status"],
                "column_limit": "50"
            }
        }));
        assert!(ok, "errs: {:?}", errs);
        assert_eq!(warns.len(), 1);
        assert!(warns[0].contains("$.body.column_limit"));
    }
}

