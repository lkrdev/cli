from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from looker_sdk.sdk.api40.methods import Looker40SDK
from looker_sdk.sdk.api40.models import UpdateArtifact

from lkr.logger import logger

NAMESPACE = "lkr-dev-db-template"


class DbTemplateArtifact(BaseModel):
    template_dashboard_id: str = Field(alias="template-dashboard-id")
    folder_path: Optional[str] = Field(default=None, alias="folder-path")
    user_flag: str = Field(alias="user-flag")
    user_flag_value: str = Field(alias="user-flag-value")
    new_dashboard_id: Optional[str] = Field(default=None, alias="new-dashboard-id")
    created_at: Optional[datetime] = Field(default=None, alias="created-at")
    updated_at: Optional[datetime] = Field(default=None, alias="updated-at")
    removed_elements_from_template_dashboard_id: List[str] = Field(
        default_factory=list, alias="removed-eleemnts-from-template-dashboard id"
    )
    dashboard_query_string: Optional[str] = Field(default=None, alias="dashboard-query-string")

    class Config:
        populate_by_name = True


class ArtifactService:
    def __init__(self, sdk: Looker40SDK):
        self.sdk = sdk

    @staticmethod
    def generate_key(user_flag: str, user_flag_value: str, template_dashboard_id: str) -> str:
        return f"no-results-{user_flag}-{user_flag_value}-{template_dashboard_id}"

    def get_artifact(
        self, user_flag: str, user_flag_value: str, template_dashboard_id: str
    ) -> Optional[DbTemplateArtifact]:
        key = self.generate_key(user_flag, user_flag_value, template_dashboard_id)
        try:
            artifacts = self.sdk.artifact(namespace=NAMESPACE, key=key)
            if artifacts and len(artifacts) > 0:
                return DbTemplateArtifact.model_validate_json(artifacts[0].value)
        except Exception as e:
            logger.debug(f"No artifact found or error retrieving artifact for key '{key}': {e}")
        return None

    def save_artifact(self, artifact: DbTemplateArtifact) -> None:
        key = self.generate_key(artifact.user_flag, artifact.user_flag_value, artifact.template_dashboard_id)
        
        artifact.updated_at = datetime.now()
        if artifact.created_at is None:
            artifact.created_at = artifact.updated_at

        value_str = artifact.model_dump_json(by_alias=True)
        body = [UpdateArtifact(key=key, value=value_str)]
        
        self.sdk.update_artifacts(namespace=NAMESPACE, body=body)
        logger.info(f"Successfully saved artifact for key '{key}' in namespace '{NAMESPACE}'")

    def delete_artifact(
        self, user_flag: str, user_flag_value: str, template_dashboard_id: str
    ) -> None:
        key = self.generate_key(user_flag, user_flag_value, template_dashboard_id)
        try:
            self.sdk.delete_artifact(namespace=NAMESPACE, key=key)
            logger.info(f"Successfully deleted artifact for key '{key}' in namespace '{NAMESPACE}'")
        except Exception as e:
            logger.warning(f"Failed to delete artifact for key '{key}': {e}")
