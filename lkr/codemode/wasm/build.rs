use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::Path;

#[derive(Serialize, Deserialize, Clone)]
struct ParamMeta {
    name: String,
    location: String,
    required: bool,
    type_str: String,
}

#[derive(Serialize, Deserialize, Clone)]
struct FieldMeta {
    name: String,
    type_str: String,
}

#[derive(Serialize, Deserialize, Clone)]
struct OperationMeta {
    name: String,
    http_method: String,
    path: String,
    doc: String,
    params: Vec<ParamMeta>,
    return_type: String,
    output_fields: Vec<FieldMeta>,
}

#[derive(Serialize, Deserialize, Clone)]
struct PropMeta {
    #[serde(rename = "type", skip_serializing_if = "String::is_empty", default)]
    prop_type: String,
    #[serde(skip_serializing_if = "String::is_empty", default)]
    description: String,
    #[serde(rename = "$ref", skip_serializing_if = "String::is_empty", default)]
    ref_path: String,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    items: Option<Box<PropMeta>>,
}

#[derive(Serialize, Deserialize)]
struct SdkMetadata {
    operations: BTreeMap<String, OperationMeta>,
    definitions: BTreeMap<String, BTreeMap<String, PropMeta>>,
}

fn swagger_type_to_py(
    prop: &Value,
    write_defs: &BTreeMap<String, BTreeMap<String, PropMeta>>,
    is_body: bool,
) -> String {
    if let Some(r) = prop.get("$ref").and_then(|v| v.as_str()) {
        let base = r.rsplit('/').next().unwrap_or("Any");
        if is_body {
            let write_name = format!("Write{base}");
            if write_defs.contains_key(&write_name) {
                return write_name;
            }
        }
        return base.to_string();
    }
    if let Some(schema) = prop.get("schema") {
        return swagger_type_to_py(schema, write_defs, is_body);
    }
    match prop.get("type").and_then(|v| v.as_str()).unwrap_or("") {
        "string" => "str".to_string(),
        "integer" => "int".to_string(),
        "number" => "float".to_string(),
        "boolean" => "bool".to_string(),
        "array" => {
            let inner = prop
                .get("items")
                .map(|it| swagger_type_to_py(it, write_defs, is_body))
                .unwrap_or_else(|| "Any".to_string());
            format!("Sequence[{inner}]")
        }
        "object" => " MutableMapping[str, Any]".trim().to_string(),
        _ => "Any".to_string(),
    }
}

fn convert_prop(v: &Value) -> PropMeta {
    let prop_type = v
        .get("type")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    let description = v
        .get("description")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    let ref_path = v
        .get("$ref")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    let items = v.get("items").map(|it| Box::new(convert_prop(it)));
    PropMeta {
        prop_type,
        description,
        ref_path,
        items,
    }
}

fn prop_meta_to_py(p: &PropMeta) -> String {
    if !p.ref_path.is_empty() {
        return p.ref_path.rsplit('/').next().unwrap_or("Any").to_string();
    }
    match p.prop_type.as_str() {
        "string" => "str".to_string(),
        "integer" => "int".to_string(),
        "number" | "float" => "float".to_string(),
        "boolean" => "bool".to_string(),
        "array" => {
            let inner = p
                .items
                .as_ref()
                .map(|it| prop_meta_to_py(it))
                .unwrap_or_else(|| "Any".to_string());
            format!("Sequence[{inner}]")
        }
        "object" => "dict[str, Any]".to_string(),
        _ => "Any".to_string(),
    }
}

fn main() {
    let manifest_dir = env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR not set");
    let swagger_path = Path::new(&manifest_dir).join("../swagger.json");
    println!("cargo:rerun-if-changed={}", swagger_path.display());
    let swagger_str = fs::read_to_string(&swagger_path).expect("Failed to read ../swagger.json");
    let swagger: Value = serde_json::from_str(&swagger_str).expect("Invalid JSON in swagger.json");

    let mut definitions: BTreeMap<String, BTreeMap<String, PropMeta>> = BTreeMap::new();
    let mut write_defs: BTreeMap<String, BTreeMap<String, PropMeta>> = BTreeMap::new();

    if let Some(defs) = swagger.get("definitions").and_then(|v| v.as_object()) {
        for (name, def_obj) in defs {
            let mut prop_map = BTreeMap::new();
            let mut writable_map = BTreeMap::new();
            let mut has_readonly = false;
            let mut has_writable = false;

            if let Some(props) = def_obj.get("properties").and_then(|v| v.as_object()) {
                for (pname, pval) in props {
                    let pm = convert_prop(pval);
                    let is_ro = pval
                        .get("readOnly")
                        .and_then(|b| b.as_bool())
                        .unwrap_or(false);
                    if is_ro {
                        has_readonly = true;
                    } else {
                        has_writable = true;
                        writable_map.insert(pname.clone(), pm.clone());
                    }
                    prop_map.insert(pname.clone(), pm);
                }
            }
            definitions.insert(name.clone(), prop_map);
            if (has_readonly && has_writable) || name == "DashboardBase" || name == "McpTools" {
                write_defs.insert(format!("Write{name}"), writable_map);
            }
        }
    }

    for (k, v) in &write_defs {
        definitions.insert(k.clone(), v.clone());
    }

    // Add extended SDK model definitions from lkr/extended_sdk_methods/classes.py
    let ext_models: Value = json!({
        "FileContent": {
            "path": { "type": "string" },
            "content": { "type": "string" }
        },
        "Directory": {
            "path": { "type": "string" }
        },
        "ProjectGeneratorColumn": {
            "column_name": { "type": "string", "description": "Name of the column. Nested columns are specified in the format foo.bar.baz" }
        },
        "ProjectGeneratorTable": {
            "schema": { "type": "string", "description": "The fully qualified schema or dataset the table is in." },
            "table_name": { "type": "string", "description": "Name of the table." },
            "primary_key": { "type": "string", "description": "Name of the column that is the primary key for this table." },
            "base_view": { "type": "boolean", "description": "Whether to use this table as a base view in Explore. Defaults to True." },
            "columns": { "type": "array", "description": "The columns to be used from this table. None will use all columns, and an empty list will use no columns.", "items": { "$ref": "#/definitions/ProjectGeneratorColumn" } }
        },
        "SelectedTable": {
            "connection": { "type": "string" },
            "database": { "type": "string" },
            "schema": { "type": "string" },
            "table_name": { "type": "string" }
        },
        "ProjectGenerationSemGenInput": {
            "user_intention": { "type": "string", "description": "A high-level description of what the user is trying to model." },
            "questions": { "type": "string", "description": "Specific questions the user wants to answer with the data." },
            "user_instructions": { "type": "string", "description": "Open-ended instructions provided by the user." }
        },
        "ProjectGenerationRequest": {
            "tables": { "type": "array", "description": "Tables for which to generate LookML.", "items": { "$ref": "#/definitions/ProjectGeneratorTable" } },
            "semantic_generation_input": { "$ref": "#/definitions/ProjectGenerationSemGenInput", "description": "Input parameters for the semantic generation of LookML." }
        },
        "GenerateLookMLParameters": {
            "project_id": { "type": "string", "description": "Id of project." },
            "body": { "$ref": "#/definitions/ProjectGenerationRequest", "description": "Generation request payload." },
            "connection": { "type": "string", "description": "Name of connection." },
            "model_name": { "type": "string", "description": "Name of model or Explore file to generate." },
            "folder_name": { "type": "string", "description": "Path of the folder to place generated files." },
            "file_type_for_explores": { "type": "string", "description": "What type of file to place Explores in, if any. Valid values are model, explore, none. Defaults to model." },
            "generate_descriptions": { "type": "boolean", "description": "Generate descriptions for columns that have them in BigQuery. Defaults to True." },
            "generate_helper_text": { "type": "boolean", "description": "Generate helper text for LookML." },
            "prefixes": { "type": "string", "description": "Case sensitive table prefixes to be ignored when naming view files." }
        },
        "GenerateLookMLWithNewFilesResponse": {
            "generate_lookml": { "type": "string", "description": "The API response from generating LookML, typically an empty string on success." },
            "new_files": { "type": "array", "description": "List of newly created files.", "items": { "type": "string" } }
        },
        "ProjectCommitRequest": {
            "files": { "type": "array", "description": "List of files to commit. If omitted or passed as None, Looker automatically stages and commits all modified, newly added, and deleted LookML files in the project's current development workspace.", "items": { "type": "string" } },
            "message": { "type": "string", "description": "Commit message" },
            "amend": { "type": "boolean", "description": "Amend the last commit" }
        },
        "GeminiEnterpriseAgentRequest": {
            "ge_gcp_project_number": { "type": "string", "description": "Google Cloud Project Number for Gemini Enterprise" },
            "ge_gcp_location": { "type": "string", "description": "Google Cloud Location for Gemini Enterprise (e.g., global, us, eu)" },
            "ge_engine_id": { "type": "string", "description": "Gemini Enterprise Engine ID" }
        }
    });

    if let Some(obj) = ext_models.as_object() {
        for (tname, props_val) in obj {
            let mut pmap = BTreeMap::new();
            if let Some(pobj) = props_val.as_object() {
                for (pname, pv) in pobj {
                    pmap.insert(pname.clone(), convert_prop(pv));
                }
            }
            definitions.insert(tname.clone(), pmap);
        }
    }

    let mut operations: BTreeMap<String, OperationMeta> = BTreeMap::new();

    if let Some(paths) = swagger.get("paths").and_then(|v| v.as_object()) {
        for (path, path_item) in paths {
            let Some(path_obj) = path_item.as_object() else {
                continue;
            };
            for (verb, op) in path_obj {
                let Some(op_obj) = op.as_object() else {
                    continue;
                };
                let Some(op_id) = op_obj.get("operationId").and_then(|v| v.as_str()) else {
                    continue;
                };
                let summary = op_obj.get("summary").and_then(|v| v.as_str()).unwrap_or("");
                let mut desc = op_obj
                    .get("description")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if desc.starts_with("###") {
                    desc = desc.trim_start_matches('#').trim();
                }
                let doc = match (summary.is_empty(), desc.is_empty()) {
                    (false, false) => format!("{summary}\n{desc}"),
                    (false, true) => summary.to_string(),
                    (true, false) => desc.to_string(),
                    (true, true) => String::new(),
                };

                let mut req_params = Vec::new();
                let mut opt_params = Vec::new();
                if let Some(params) = op_obj.get("parameters").and_then(|v| v.as_array()) {
                    for p in params {
                        let name = p
                            .get("name")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                        let location = p
                            .get("in")
                            .and_then(|v| v.as_str())
                            .unwrap_or("query")
                            .to_string();
                        let required = p.get("required").and_then(|v| v.as_bool()).unwrap_or(false);
                        let base_t = swagger_type_to_py(p, &write_defs, location == "body");
                        let type_str = if required {
                            base_t
                        } else {
                            format!("Optional[{base_t}]")
                        };
                        let pm = ParamMeta {
                            name,
                            location,
                            required,
                            type_str,
                        };
                        if required {
                            req_params.push(pm);
                        } else {
                            opt_params.push(pm);
                        }
                    }
                }
                req_params.extend(opt_params);
                req_params.push(ParamMeta {
                    name: "transport_options".to_string(),
                    location: "options".to_string(),
                    required: false,
                    type_str: "Optional[TransportOptions]".to_string(),
                });

                let mut return_type = "None".to_string();
                let mut output_fields = Vec::new();
                if let Some(responses) = op_obj.get("responses").and_then(|v| v.as_object()) {
                    let resp = responses
                        .get("200")
                        .or_else(|| responses.get("201"))
                        .or_else(|| responses.get("202"))
                        .or_else(|| responses.get("204"));
                    if let Some(r_obj) = resp {
                        if let Some(schema) = r_obj.get("schema") {
                            return_type = swagger_type_to_py(schema, &write_defs, false);
                            let model_ref =
                                schema.get("$ref").and_then(|v| v.as_str()).or_else(|| {
                                    schema
                                        .get("items")
                                        .and_then(|it| it.get("$ref"))
                                        .and_then(|v| v.as_str())
                                });
                            if let Some(r) = model_ref {
                                let mname = r.rsplit('/').next().unwrap_or("");
                                if let Some(props) = definitions.get(mname) {
                                    for (fname, fmeta) in props {
                                        output_fields.push(FieldMeta {
                                            name: fname.clone(),
                                            type_str: format!(
                                                "Optional[{}]",
                                                prop_meta_to_py(fmeta)
                                            ),
                                        });
                                    }
                                }
                            }
                        }
                    }
                }

                operations.insert(
                    op_id.to_string(),
                    OperationMeta {
                        name: op_id.to_string(),
                        http_method: verb.to_uppercase(),
                        path: path.clone(),
                        doc,
                        params: req_params,
                        return_type,
                        output_fields,
                    },
                );
            }
        }
    }

    // Add / override ExtendedLooker40SDK custom methods
    let extended_ops = vec![
        OperationMeta {
            name: "all_project_files".to_string(),
            http_method: "GET".to_string(),
            path: "/projects/{project_id}/files".to_string(),
            doc: "Get all files in a project.".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "fields".into(), location: "query".into(), required: false, type_str: "str | None".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "Any".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "get_file_content".to_string(),
            http_method: "GET".to_string(),
            path: "/projects/{project_id}/file/content".to_string(),
            doc: "Get file content.".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "file_path".into(), location: "query".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "str".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "create_file".to_string(),
            http_method: "POST".to_string(),
            path: "/projects/{project_id}/files".to_string(),
            doc: "Create a new file in a project.".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "file_content".into(), location: "body".into(), required: true, type_str: "FileContent | dict | Any".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "Any".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "update_file".to_string(),
            http_method: "PUT".to_string(),
            path: "/projects/{project_id}/files".to_string(),
            doc: "Update a file in a project.".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "file_content".into(), location: "body".into(), required: true, type_str: "FileContent | dict | Any".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "Any".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "delete_file".to_string(),
            http_method: "DELETE".to_string(),
            path: "/projects/{project_id}/files".to_string(),
            doc: "Delete a file in a project.".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "file_path".into(), location: "query".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "None".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "create_project_directory".to_string(),
            http_method: "POST".to_string(),
            path: "/projects/{project_id}/directories".to_string(),
            doc: "Create a project directory.".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "directory_path".into(), location: "custom".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "Any".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "delete_project_directory".to_string(),
            http_method: "DELETE".to_string(),
            path: "/projects/{project_id}/directories".to_string(),
            doc: "Delete a project directory.".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "directory_path".into(), location: "custom".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "Any".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "generate_lookml".to_string(),
            http_method: "POST".to_string(),
            path: "/projects/{project_id}/generate".to_string(),
            doc: "Generate LookML in a project.".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "body".into(), location: "body".into(), required: true, type_str: "ProjectGenerationRequest | dict | Any".into() },
                ParamMeta { name: "connection".into(), location: "query".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "model_name".into(), location: "query".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "folder_name".into(), location: "query".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "file_type_for_explores".into(), location: "query".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "generate_descriptions".into(), location: "query".into(), required: false, type_str: "bool | None".into() },
                ParamMeta { name: "generate_helper_text".into(), location: "query".into(), required: false, type_str: "bool | None".into() },
                ParamMeta { name: "prefixes".into(), location: "query".into(), required: false, type_str: "str | None".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "str".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "generate_lookml_with_new_files".to_string(),
            http_method: "CUSTOM".to_string(),
            path: "/projects/{project_id}/generate".to_string(),
            doc: "Generate LookML in a project and return the API response along with newly created files.".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "body".into(), location: "body".into(), required: true, type_str: "ProjectGenerationRequest | dict | Any".into() },
                ParamMeta { name: "connection".into(), location: "query".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "model_name".into(), location: "query".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "folder_name".into(), location: "query".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "file_type_for_explores".into(), location: "query".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "generate_descriptions".into(), location: "query".into(), required: false, type_str: "bool | None".into() },
                ParamMeta { name: "generate_helper_text".into(), location: "query".into(), required: false, type_str: "bool | None".into() },
                ParamMeta { name: "prefixes".into(), location: "query".into(), required: false, type_str: "str | None".into() },
                ParamMeta { name: "add_autogenerated_header".into(), location: "custom".into(), required: false, type_str: "bool".into() },
                ParamMeta { name: "allow_update_without_header".into(), location: "custom".into(), required: false, type_str: "bool".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "GenerateLookMLWithNewFilesResponse".to_string(),
            output_fields: vec![
                FieldMeta { name: "generate_lookml".into(), type_str: "str".into() },
                FieldMeta { name: "new_files".into(), type_str: "list[Any]".into() },
            ],
        },
        OperationMeta {
            name: "commit".to_string(),
            http_method: "POST".to_string(),
            path: "/projects/{project_id}/commit".to_string(),
            doc: "Commit changes to the project's git repository.\n\nIf you do not specify an array of files in the body (or pass None),\nLooker automatically stages and commits all modified, newly added,\nand deleted LookML files in the project's current development workspace.".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "body".into(), location: "body".into(), required: false, type_str: "ProjectCommitRequest | dict | Any | None".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "str".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "publish_agent".to_string(),
            http_method: "POST".to_string(),
            path: "/internal/agents/{agent_id}/publish".to_string(),
            doc: "Publish a Looker Conversational Analytics agent to Gemini Enterprise.".to_string(),
            params: vec![
                ParamMeta { name: "agent_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "body".into(), location: "body".into(), required: false, type_str: "GeminiEnterpriseAgentRequest | dict[str, Any] | Any | None".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "dict[str, Any]".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "get_published_agent".to_string(),
            http_method: "GET".to_string(),
            path: "/internal/agents/{agent_id}/publish".to_string(),
            doc: "Fetch published agent details from the default Gemini Enterprise app.".to_string(),
            params: vec![
                ParamMeta { name: "agent_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "dict[str, Any]".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "update_published_agent".to_string(),
            http_method: "PATCH".to_string(),
            path: "/internal/agents/{agent_id}/publish".to_string(),
            doc: "Update an agent across all published Gemini Enterprise apps.".to_string(),
            params: vec![
                ParamMeta { name: "agent_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "dict[str, Any]".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "unpublish_agent".to_string(),
            http_method: "PATCH".to_string(),
            path: "/internal/agents/{agent_id}/unpublish".to_string(),
            doc: "Unpublish an agent from the default configured Gemini Enterprise app.".to_string(),
            params: vec![
                ParamMeta { name: "agent_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "dict[str, Any]".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "validate_gemini_enterprise_metadata".to_string(),
            http_method: "POST".to_string(),
            path: "/gemini_enterprise/validate".to_string(),
            doc: "Validate Gemini Enterprise GCP project, location, and engine configuration.".to_string(),
            params: vec![
                ParamMeta { name: "body".into(), location: "body".into(), required: true, type_str: "GeminiEnterpriseAgentRequest | dict[str, Any] | Any".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "dict[str, Any]".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "get_gemini_enablement".to_string(),
            http_method: "GET".to_string(),
            path: "/gemini_enablement".to_string(),
            doc: "Fetch Gemini in Looker configuration, including ai_ge_service_account_email.".to_string(),
            params: vec![
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "TransportOptions | None".into() },
            ],
            return_type: "dict[str, Any]".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "create_ci_run".to_string(),
            http_method: "POST".to_string(),
            path: "/projects/{project_id}/ci/run".to_string(),
            doc: "Create a Continuous Integration run".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "body".into(), location: "body".into(), required: true, type_str: "CreateCIRunRequest".into() },
                ParamMeta { name: "fields".into(), location: "query".into(), required: false, type_str: "Optional[str]".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "Optional[TransportOptions]".into() },
            ],
            return_type: "CreateCIRunResponse".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "get_ci_run".to_string(),
            http_method: "GET".to_string(),
            path: "/projects/{project_id}/ci/runs/{run_id}".to_string(),
            doc: "Fetch Continuous Integration run".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "run_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "fields".into(), location: "query".into(), required: false, type_str: "Optional[str]".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "Optional[TransportOptions]".into() },
            ],
            return_type: "ProjectRun".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "create_git_diagnostic_report".to_string(),
            http_method: "POST".to_string(),
            path: "/projects/{project_id}/git_diagnostic_report".to_string(),
            doc: "Initiate Git Diagnosis".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "body".into(), location: "body".into(), required: true, type_str: "WriteGitDiagnosticReport".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "Optional[TransportOptions]".into() },
            ],
            return_type: "GitDiagnosticReport".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "get_git_diagnostic_report".to_string(),
            http_method: "GET".to_string(),
            path: "/projects/{project_id}/git_diagnostic_report/{report_id}".to_string(),
            doc: "Get Live Git Diagnosis".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "report_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "Optional[TransportOptions]".into() },
            ],
            return_type: "GitDiagnosticReport".to_string(),
            output_fields: vec![],
        },
        OperationMeta {
            name: "repair_git_diagnostic_report".to_string(),
            http_method: "POST".to_string(),
            path: "/projects/{project_id}/git_diagnostic_report/{report_id}/repair".to_string(),
            doc: "Repair Git Configuration".to_string(),
            params: vec![
                ParamMeta { name: "project_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "report_id".into(), location: "path".into(), required: true, type_str: "str".into() },
                ParamMeta { name: "body".into(), location: "body".into(), required: true, type_str: "WriteGitDiagnosticReport".into() },
                ParamMeta { name: "transport_options".into(), location: "options".into(), required: false, type_str: "Optional[TransportOptions]".into() },
            ],
            return_type: "GitDiagnosticReport".to_string(),
            output_fields: vec![],
        },
    ];

    for name in ["create_developer_copy", "developer_copy"] {
        operations.insert(
            name.into(),
            OperationMeta {
                name: name.into(),
                http_method: "POST".into(),
                path: "/projects/{project_id}/developer_copy".into(),
                doc: "Create/initialize a developer workspace copy for a Looker project.".into(),
                params: vec![
                    ParamMeta {
                        name: "project_id".into(),
                        location: "path".into(),
                        required: true,
                        type_str: "str".into(),
                    },
                    ParamMeta {
                        name: "transport_options".into(),
                        location: "options".into(),
                        required: false,
                        type_str: "TransportOptions | None".into(),
                    },
                ],
                return_type: "str".into(),
                output_fields: vec![],
            },
        );
    }

    for (m, has_body) in [
        ("get", false),
        ("post", true),
        ("put", true),
        ("patch", true),
        ("delete", false),
    ] {
        let upper = m.to_uppercase();
        let mut params = vec![
            ParamMeta {
                name: "path".into(),
                location: "raw_path".into(),
                required: true,
                type_str: "str".into(),
            },
            ParamMeta {
                name: "structure".into(),
                location: "ignore".into(),
                required: false,
                type_str: "Any".into(),
            },
            ParamMeta {
                name: "query_params".into(),
                location: "raw_query".into(),
                required: false,
                type_str: "Optional[MutableMapping[str, Any]]".into(),
            },
        ];
        if has_body {
            params.push(ParamMeta {
                name: "body".into(),
                location: "body".into(),
                required: false,
                type_str: "Any".into(),
            });
        }
        params.push(ParamMeta {
            name: "transport_options".into(),
            location: "options".into(),
            required: false,
            type_str: "Optional[TransportOptions]".into(),
        });
        operations.insert(
            m.into(),
            OperationMeta {
                name: m.into(),
                http_method: format!("RAW_{upper}"),
                path: "{path}".into(),
                doc: format!("{upper} method"),
                params,
                return_type: "Any".into(),
                output_fields: vec![],
            },
        );
    }

    for op in extended_ops {
        operations.insert(op.name.clone(), op);
    }

    let out_dir = env::var("OUT_DIR").expect("OUT_DIR not set");
    let out_path = Path::new(&out_dir).join("sdk_metadata.json");
    let meta = SdkMetadata {
        operations,
        definitions,
    };
    let json_bytes = serde_json::to_vec(&meta).expect("Failed to serialize metadata");
    fs::write(out_path, json_bytes).expect("Failed to write sdk_metadata.json");
}
