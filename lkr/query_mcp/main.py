import os
import sys
import json
import threading
import tempfile
from pathlib import Path
from typing import Annotated, List, Literal, Optional, Dict, Any, Set

import typer
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator, model_validator
import numpy as np

from lkr.auth_service import get_auth
from lkr.classes import LkrCtxObj
from lkr.logger import logger

try:
    import faiss
    from rank_bm25 import BM25Okapi
    from sentence_transformers import SentenceTransformer
except ImportError:
    faiss = None
    BM25Okapi = None
    SentenceTransformer = None

try:
    from google.cloud import storage
except ImportError:
    storage = None

__all__ = ["group"]

mcp = FastMCP("lkr:query-mcp")
group = typer.Typer()

# Global state for validation and searching
global_raw_fields_dict: Dict[str, Any] = {}
global_fields_docs: List[str] = []
global_fields_names: List[str] = []

# Index objects
encoder = None
faiss_index = None
bm25_index = None

ctx_lkr: LkrCtxObj | None = None

class ValidatedWriteQuery(BaseModel):
    model: str = Field(description="The name of the model")
    view: str = Field(description="The name of the explore/view")
    fields: Optional[List[str]] = Field(default=None, description="List of fields to include in the query (e.g. 'view.field')")
    pivots: Optional[List[str]] = Field(default=None, description="List of fields to pivot on")
    fill_fields: Optional[List[str]] = Field(default=None)
    filters: Optional[Dict[str, str]] = Field(default=None, description="Dictionary of filters, where keys are field names and values are filter expressions")
    sorts: Optional[List[str]] = Field(default=None)
    limit: Optional[str] = Field(default=None)
    column_limit: Optional[str] = Field(default=None)
    total: Optional[bool] = Field(default=None)
    row_total: Optional[str] = Field(default=None)
    subtotals: Optional[List[str]] = Field(default=None)
    dynamic_fields: Optional[str] = Field(default=None)
    query_timezone: Optional[str] = Field(default=None)
    filter_expression: Optional[str] = Field(default=None)
    vis_config: Optional[Dict[str, Any]] = Field(default=None)

    @field_validator('fields', 'pivots', mode="after")
    @classmethod
    def validate_field_list(cls, v):
        if not v:
            return v
        for f in v:
            if f not in global_raw_fields_dict:
                raise ValueError(f"Field '{f}' is not a valid field in the data dictionary. Please use the search_fields tool to find valid fields.")
            
            field_data = global_raw_fields_dict[f]
            category = field_data.get("category")
            if category in ("filter", "parameter"):
                raise ValueError(
                    f"Field '{f}' is of category '{category}'. "
                    f"Fields of type filter and parameter cannot be used in 'fields' or 'pivots'. "
                    f"They must only be used inside the 'filters' dictionary."
                )
        return v

    @field_validator('filters', mode="after")
    @classmethod
    def validate_filters(cls, v):
        if not v:
            return v
        for f_key in v.keys():
            if f_key not in global_raw_fields_dict:
                raise ValueError(f"Filter key '{f_key}' is not a valid field in the data dictionary.")
        return v

    @model_validator(mode="after")
    def validate_pivots_in_fields(self) -> 'ValidatedWriteQuery':
        if self.pivots:
            if not self.fields:
                raise ValueError("Pivots cannot be specified without fields.")
            fields_set = set(self.fields)
            for pivot in self.pivots:
                if pivot not in fields_set:
                    raise ValueError(f"Pivot '{pivot}' must also be included in the 'fields' list.")
        return self

def get_mcp_sdk(ctx: LkrCtxObj | typer.Context):
    sdk = get_auth(ctx).get_current_sdk(prompt_refresh_invalid_token=False)
    sdk.auth.settings.agent_tag += "-query-mcp"
    return sdk

def save_to_gcs(bucket_name: str, key: str, data: str):
    if not storage:
        logger.error("google-cloud-storage is not installed. Run 'uv pip install google-cloud-storage' or use [query-mcp-gcs]")
        return
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(key)
        blob.upload_from_string(data, content_type="application/json")
        logger.debug(f"Saved fields dict to gs://{bucket_name}/{key}")
    except Exception as e:
        logger.error(f"Failed to save to GCS: {e}")

def load_from_gcs(bucket_name: str, key: str, max_age_days: int = 7) -> Optional[str]:
    if not storage:
        return None
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(key)
        if blob.exists():
            if blob.updated:
                from datetime import datetime, timezone
                age = datetime.now(timezone.utc) - blob.updated
                if age.days >= max_age_days:
                    logger.debug(f"GCS cache gs://{bucket_name}/{key} is older than {max_age_days} days. Ignoring.")
                    return None
            logger.debug(f"Loaded fields dict from gs://{bucket_name}/{key}")
            return blob.download_as_text()
    except Exception as e:
        logger.error(f"Failed to load from GCS: {e}")
    return None

def build_indices(fields_dict: Dict[str, Any], embedding_model: str):
    global encoder, faiss_index, bm25_index, global_fields_docs, global_fields_names
    if not faiss or not SentenceTransformer or not BM25Okapi:
        logger.error("Missing required packages for indexing. Install lkr-dev-cli[query-mcp]")
        return

    typer.echo(f"Building searchable index and vectors using {embedding_model}...", err=True)
    logger.info(f"Building searchable index and vectors using {embedding_model}...")
    global_fields_docs = []
    global_fields_names = []
    
    for name, f in fields_dict.items():
        # Create a rich document for search
        label = f.get("label_short") or f.get("label") or name
        desc = f.get("description") or ""
        type_str = f.get("type") or "string"
        doc = f"{name} {label} {desc} {type_str}"
        global_fields_docs.append(doc)
        global_fields_names.append(name)
    
    tokenized_docs = [doc.lower().split() for doc in global_fields_docs]
    bm25_index = BM25Okapi(tokenized_docs)

    # Load the selected embedding model
    encoder = SentenceTransformer(embedding_model)
    doc_embeddings = encoder.encode(global_fields_docs)
    faiss_index = faiss.IndexFlatL2(doc_embeddings.shape[1])
    faiss_index.add(np.array(doc_embeddings))
    typer.echo("Finished building indices.", err=True)
    logger.info("Finished building indices.")

def fetch_and_build_fields(ctx, explores: List[str] | None, local_file_path: str | None, gcs_bucket: str | None, looker_user_id: str | None, embedding_model: str):
    global global_raw_fields_dict
    sdk = get_mcp_sdk(ctx)
    
    models_explores = []
    if explores:
        for e in explores:
            m, ex = e.split(":", 1)
            models_explores.append((m, ex))
    else:
        typer.echo("Fetching all LookML models and explores...", err=True)
        looker_models = sdk.all_lookml_models(fields="name,explores")
        for m in looker_models:
            for ex in (m.explores or []):
                models_explores.append((m.name, ex.name))

    all_fields_dict = {}
    
    typer.echo(f"Fetching fields from {len(models_explores)} model:explore pairs...", err=True)
    logger.info(f"Fetching fields from {len(models_explores)} model:explore pairs...")
    for m_name, ex_name in models_explores:
        typer.echo(f"Fetching definition for explore: {m_name}:{ex_name}...", err=True)
        try:
            explore = sdk.lookml_model_explore(m_name, ex_name, fields="fields")
            if explore.fields:
                for dim in (explore.fields.dimensions or []):
                    if dim.name:
                        all_fields_dict[dim.name] = dim.__dict__
                for meas in (explore.fields.measures or []):
                    if meas.name:
                        all_fields_dict[meas.name] = meas.__dict__
                for filt in (explore.fields.filters or []):
                    if filt.name:
                        all_fields_dict[filt.name] = filt.__dict__
                for param in (explore.fields.parameters or []):
                    if param.name:
                        all_fields_dict[param.name] = param.__dict__
        except Exception as e:
            logger.debug(f"Failed to fetch explore {m_name}:{ex_name}: {e}")
    
    global_raw_fields_dict = all_fields_dict
    
    # Save async off critical path
    if local_file_path or gcs_bucket:
        data_to_save = json.dumps(global_raw_fields_dict)
        
        def save_task():
            if local_file_path:
                try:
                    with open(local_file_path, "w") as f:
                        f.write(data_to_save)
                    logger.info(f"Saved fields to {local_file_path}")
                except Exception as e:
                    logger.error(f"Failed to save fields to local file: {e}")
            if gcs_bucket and looker_user_id:
                save_to_gcs(gcs_bucket, f"query_mcp_{looker_user_id}_fields.json", data_to_save)
                
        threading.Thread(target=save_task, daemon=True).start()

    build_indices(global_raw_fields_dict, embedding_model)


def search_fields(query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """
    Search for fields based on a natural language query or field name.
    Uses hybrid search (BM25 + FAISS) to find the most relevant fields to include in your query.
    Returns a list of field definitions.
    """
    if not encoder or not faiss_index or not bm25_index:
        return [{"error": "Search index is not initialized."}]
        
    query_vec = encoder.encode([query])
    _, vec_indices = faiss_index.search(np.array(query_vec), top_k)
    
    tokenized_query = query.lower().split()
    bm25_scores = bm25_index.get_scores(tokenized_query)
    bm25_indices = np.argsort(bm25_scores)[::-1][:top_k]
    
    # Simple Reciprocal Rank Fusion (RRF)
    # Combine vec_indices[0] and bm25_indices
    results_set = set(vec_indices[0]) | set(bm25_indices)
    
    results = []
    for i in results_set:
        if i < len(global_fields_names):
            field_name = global_fields_names[i]
            results.append(global_raw_fields_dict[field_name])
            
    return results

def run_looker_query(query: ValidatedWriteQuery | dict) -> str:
    """
    Run a Looker query based on the provided configuration.
    You must use search_fields first to find the exact field names you want to include in `fields`, `pivots`, or `filters`.
    The results will be returned in JSON_BI format.
    """
    global ctx_lkr
    if not ctx_lkr:
        return json.dumps({"error": "No Looker context found"})
        
    sdk = get_mcp_sdk(ctx_lkr)
    
    try:
        if isinstance(query, dict):
            query = ValidatedWriteQuery(**query)
            
        from looker_sdk.sdk.api40.models import WriteQuery
        wq = WriteQuery(**query.model_dump(exclude_none=True))
        
        created_query = sdk.create_query(body=wq)
        if not created_query.id:
            return json.dumps({"error": "Failed to create query, no ID returned."})
            
        result_str = sdk.run_query(query_id=created_query.id, result_format="json_bi")
        
        try:
            result_json = json.loads(result_str)
            # Extract all returned field names from metadata
            returned_fields = []
            if "metadata" in result_json and "fields" in result_json["metadata"]:
                fields_meta = result_json["metadata"]["fields"]
                for category in ["dimensions", "measures", "table_calculations", "pivots"]:
                    for f in fields_meta.get(category, []):
                        if "name" in f:
                            returned_fields.append(f["name"])
            
            # Check if requested fields are in the returned fields
            if wq.fields:
                missing = [f for f in wq.fields if f not in returned_fields]
                if missing:
                    return json.dumps({
                        "error": f"The following requested fields were not returned in the query metadata: {missing}. They may be invalid or inaccessible.",
                        "partial_result": result_json
                    })
            return result_str
        except json.JSONDecodeError:
            return result_str

    except Exception as e:
        return json.dumps({"error": str(e)})

def to_primitive(obj):
    seen = set()

    def _to_primitive(o):
        if isinstance(o, (str, int, float, bool, type(None))):
            return o
        
        obj_id = id(o)
        if obj_id in seen:
            return f"<Circular reference to {type(o).__name__}>"
        seen.add(obj_id)
        
        try:
            if isinstance(o, list):
                return [_to_primitive(item) for item in o]
            elif isinstance(o, dict):
                return {k: _to_primitive(v) for k, v in o.items()}
            else:
                try:
                    return _to_primitive(vars(o))
                except TypeError:
                    return str(o)
                except Exception:
                    return str(o)
        finally:
            seen.remove(obj_id)

    return _to_primitive(obj)

@mcp.tool()
def run_python_code(code: str) -> str:
    """
    Execute Python code safely with access to Looker SDK methods and semantic search.
    Capture the result. 
    
    AGENT HINTS:
    - Use `search_fields("query", top_k=10)` to semantically search for fields across models/explores.
    - Use `run_looker_query(payload_dict)` to validate and run a query. It accepts a dict matching WriteQuery.
    - You have full access to the Looker SDK methods as global functions (e.g. `me()`).
    - Use `dir()` and `help('method_name')` to discover available functions.
    - Return your output (avoid using print() as it may pollute the stdio stream).
    """
    import inspect
    import io
    from contextlib import redirect_stdout
    from lkr.auth_service import is_auth_expired
    import pydantic_monty
    
    try:
        global ctx_lkr
        if not ctx_lkr:
            ctx_lkr = LkrCtxObj(force_oauth=False)
        sdk = get_mcp_sdk(ctx_lkr)
        
        ALLOWED_METHODS = {
            'all_lookml_models', 
            'lookml_model', 
            'lookml_model_explore', 
            'create_query',
            'run_query'
        }
        
        external_funcs = {}
        for name, method in inspect.getmembers(sdk, predicate=inspect.ismethod):
            if name in ALLOWED_METHODS:
                # Wrap in a lambda to recursively convert output to primitives
                def make_wrapper(m):
                    def wrapper(*args, **kwargs):
                        res = m(*args, **kwargs)
                        return to_primitive(res)
                    return wrapper
                external_funcs[name] = make_wrapper(method)

        # Provide helper functions for the LLM to explore the SDK
        external_funcs['dir'] = lambda: list(external_funcs.keys())
        
        def _help(name: str) -> str:
            if name in external_funcs:
                if hasattr(sdk, name):
                    return getattr(sdk, name).__doc__ or "No docstring available."
                return f"{name} is a built-in helper function."
            return f"Function '{name}' not found."
        external_funcs['help'] = _help
        
        # Inject our custom tools
        external_funcs['search_fields'] = search_fields
        external_funcs['run_looker_query'] = run_looker_query

        m = pydantic_monty.Monty(code)
        
        # Redirect stdout to capture any print() statements
        f = io.StringIO()
        with redirect_stdout(f):
            result = m.run(external_functions=external_funcs)
        
        printed_output = f.getvalue()
        
        try:
            if result is not None:
                if isinstance(result, str):
                    output = result
                else:
                    output = json.dumps(result, indent=2, default=str)
            else:
                output = ""
        except Exception:
            output = repr(result)
            
        if printed_output:
            return f"PRINTED OUTPUT:\n{printed_output}\nRESULT:\n{output}"
        return output
    except Exception as e:
        logger.error(f"Error executing Monty: {e}")
        try:
            if is_auth_expired(e):
                return "Error: Your Looker OAuth session has expired. Please run 'lkr auth login' to re-authenticate."
        except Exception:
            pass
        return f"Error: {str(e)}"

@group.command(name="run")
def run(
    ctx: typer.Context,
    explore: Annotated[
        Optional[List[str]],
        typer.Option(
            "--explore", 
            help="Whitelisted model_name:explore_name pairs, e.g. --explore=thelook:events"
        )
    ] = None,
    local_file_path: Annotated[
        Optional[str],
        typer.Option(
            "--local-file-path",
            help="Local file path to store/load the fields JSON dictionary."
        )
    ] = None,
    gcs_bucket: Annotated[
        Optional[str],
        typer.Option(
            "--gcs-bucket",
            help="GCP Cloud Storage bucket to store/load the fields JSON dictionary."
        )
    ] = None,
    looker_user_id: Annotated[
        Optional[str],
        typer.Option(
            "--looker_user_id",
            help="Looker user ID to namespace GCS objects. If not provided, fetches from me()."
        )
    ] = None,
    max_cache_age_days: Annotated[
        int,
        typer.Option(
            "--max-cache-age-days",
            help="Maximum age of the cache in days before it is rebuilt."
        )
    ] = 7,
    embedding_model: Annotated[
        str,
        typer.Option(
            "--embedding-model",
            help="The HuggingFace sentence transformer model to use for the vector index. Good CPU options: BAAI/bge-small-en-v1.5, all-MiniLM-L6-v2, snowflake/snowflake-arctic-embed-s"
        )
    ] = "BAAI/bge-small-en-v1.5",
    debug: bool = typer.Option(False, help="Debug mode"),
):
    """
    Start the query-mcp server.
    """
    from lkr.logger import LogLevel, set_log_level
    
    global ctx_lkr, global_raw_fields_dict

    if debug:
        set_log_level(LogLevel.DEBUG)
    else:
        set_log_level(LogLevel.ERROR)

    ctx_lkr = ctx.obj.get("ctx_lkr") if ctx.obj else LkrCtxObj(force_oauth=False)
    sdk = get_mcp_sdk(ctx_lkr)
    
    if not sdk.auth.settings.base_url:
        logger.error("No current instance found")
        raise typer.Exit(1)

    if gcs_bucket and not looker_user_id:
        try:
            me = sdk.me()
            looker_user_id = str(me.id)
        except Exception as e:
            logger.error(f"Failed to fetch me() to get looker_user_id: {e}")
            
    # Critical Path: Try to load from storage first
    loaded_data = None
    if local_file_path and os.path.exists(local_file_path):
        try:
            import time
            mtime = os.path.getmtime(local_file_path)
            age_days = (time.time() - mtime) / (60 * 60 * 24)
            if age_days >= max_cache_age_days:
                logger.debug(f"Local cache {local_file_path} is older than {max_cache_age_days} days. Ignoring.")
            else:
                with open(local_file_path, "r") as f:
                    loaded_data = json.load(f)
                    logger.info(f"Loaded fields from {local_file_path}")
        except Exception as e:
            logger.error(f"Failed to load from local file: {e}")
            
    elif gcs_bucket and looker_user_id:
        gcs_data = load_from_gcs(gcs_bucket, f"query_mcp_{looker_user_id}_fields.json", max_age_days=max_cache_age_days)
        if gcs_data:
            try:
                loaded_data = json.loads(gcs_data)
                logger.info(f"Loaded fields from GCS")
            except Exception as e:
                logger.error(f"Failed to parse JSON from GCS: {e}")

    if loaded_data:
        typer.echo("Loaded field definitions from cache.", err=True)
        global_raw_fields_dict = loaded_data
        build_indices(global_raw_fields_dict, embedding_model)
    else:
        # If not loaded, fetch and build. It saves to storage off-critical path inside this function
        fetch_and_build_fields(ctx, explore, local_file_path, gcs_bucket, looker_user_id, embedding_model)
        
    typer.echo("Starting query-mcp server...", err=True)
    # Important: reroute stdout to stderr so FastMCP output isn't polluted
    sys.stdout = sys.stderr
    mcp.run()
