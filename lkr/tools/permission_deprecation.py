import typer
from typing import Annotated, List, Optional, Set, Dict
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel
from pydash import get
from lkr.auth_service import get_auth
from lkr.logger import logger

target_permissions = [
    "download_with_limit",
    "download_without_limit",
    "schedule_look_emails",
    "schedule_external_look_emails",
    "send_to_s3",
    "send_to_sftp",
    "send_outgoing_webhook",
    "send_to_integration",
]

class AuditRow(BaseModel):
    user_id: str
    name: str
    email: Optional[str] = None
    instance_wide: List[str]
    model_permissions: Dict[str, Optional[List[str]]] # model_name -> missing permissions. None if no 'access_data'.
    has_target_perms: bool

class DeprecationAuditResult(BaseModel):
    model_names: List[str] # The columns
    rows: List[AuditRow]

def schedule_download_deprecation(
    ctx: typer.Context,
    limit: int = 500,
    unfiltered: bool = False,
) -> Optional[DeprecationAuditResult]:
    """
    Build a audit result of users and their scheduling/downloading permissions per model.
    """
    sdk = get_auth(ctx).get_current_sdk()
    
    # 1. Query models to define columns
    logger.info("Fetching LookML models...")
    models = sdk.all_lookml_models(fields="name")
    model_names = sorted([m.name for m in models if m.name])
    
    # 2. Query all roles, permission sets, and model sets
    logger.info("Fetching roles and permissions...")
    roles = sdk.all_roles(fields="id,name,permission_set,model_set")
    
    # Pre-process roles for faster lookup
    role_map = {}
    for role in roles:
        target_perms_in_role = set()
        has_access_data = False
        is_admin = False
        
        # Check if it's the Admin role (Admin permission set)
        if role.permission_set:
            if role.permission_set.name == "Admin":
                is_admin = True
                target_perms_in_role = set(target_permissions)
                has_access_data = True
            elif role.permission_set.permissions:
                role_perms = set(role.permission_set.permissions)
                target_perms_in_role = set([p for p in target_permissions if p in role_perms])
                has_access_data = "access_data" in role_perms
        
        role_models = set()
        all_models = False
        if is_admin:
            all_models = True
        elif role.model_set:
            if role.model_set.name == "All" or (role.model_set.models and "*" in role.model_set.models):
                all_models = True
            elif role.model_set.models:
                role_models = set(role.model_set.models)
            
        role_map[str(role.id)] = {
            "target_perms": target_perms_in_role,
            "has_access_data": has_access_data,
            "models": role_models,
            "all_models": all_models
        }

    # 3. Pagination - Fetch all non-embed, active users using ThreadPoolExecutor
    all_users = []
    offset = 0
    max_workers = 10
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            logger.info(f"Fetching users batch starting at offset {offset}...")
            futures = []
            for i in range(max_workers):
                futures.append(executor.submit(
                    sdk.search_users,
                    is_disabled=False,
                    embed_user=False,
                    email="bryanweber%",
                    limit=limit,
                    offset=offset + (i * limit),
                    fields="id,first_name,last_name,role_ids,external_id,email"
                ))
            
            batch_done = False
            for future in futures:
                users = future.result()
                if not users:
                    batch_done = True
                    continue
                # Filter out embed users locally (embed users have an external_id)
                active_non_embed = [u for u in users if not getattr(u, 'external_id', None)]
                all_users.extend(active_non_embed)
                if len(users) < limit:
                    batch_done = True
            
            if batch_done:
                break
            offset += (max_workers * limit)

    if not all_users:
        return None

    # 4. Prepare Result Data
    audit_rows = []

    for user in all_users:
        user_id = user.id
        name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        
        user_role_ids = user.role_ids or []
        user_instance_perms: Set[str] = set()
        # Track permissions per model
        user_model_perms = {m: set() for m in model_names}
        # Track if user has access_data per model
        user_model_access_data = {m: False for m in model_names}
        
        for r_id in user_role_ids:
            role_info = role_map.get(str(r_id))
            if not role_info:
                continue
            
            p_set = role_info["target_perms"]
            has_ad = role_info["has_access_data"]
            
            # If the role has target perms, add them to instance wide
            user_instance_perms.update(p_set)
            
            # Update per-model tracking
            target_models = model_names if role_info["all_models"] else role_info["models"]
            for m_name in target_models:
                if m_name in model_names:
                    user_model_perms[m_name].update(p_set)
                    if has_ad:
                        user_model_access_data[m_name] = True
        
        model_results = {}
        for m_name in model_names:
            if not user_model_access_data[m_name]:
                # No access_data for this model -> N/A
                model_results[m_name] = None
            elif not user_instance_perms:
                # User has access_data but no target perms instance-wide
                model_results[m_name] = []
            else:
                # User has access_data and some target perms instance-wide
                # List missing target perms for this model
                missing = user_instance_perms - user_model_perms[m_name]
                model_results[m_name] = sorted(list(missing))
                    
        audit_rows.append(AuditRow(
            user_id=str(user_id),
            name=name,
            email=user.email,
            instance_wide=sorted(list(user_instance_perms)),
            model_permissions=model_results,
            has_target_perms=len(user_instance_perms) > 0
        ))

    # 5. Filter Results unless unfiltered is True
    if not unfiltered:
        # Only show rows where someone has a value in any one of the model_name columns.
        # Hide if all are check marks (empty list) or all are N/A (None).
        # We check if there's ANY model where the user has missing permissions (non-empty list).
        filtered_rows = [
            row for row in audit_rows
            if any(row.model_permissions[m] for m in model_names if row.model_permissions[m] is not None)
        ]
        audit_rows = filtered_rows

    return DeprecationAuditResult(
        model_names=model_names,
        rows=audit_rows
    )
