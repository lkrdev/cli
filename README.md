# lkr cli

The `lkr` cli is a tool for interacting with Looker. It combines Looker's SDK and customer logic to interact with Looker in meaninful ways. For a full list of commands, see the full [cli docs](./lkr.md)

## Usage

`uv` makes everyone's life easier. Go [install it](https://docs.astral.sh/uv/getting-started/installation/). You can start using `lkr` by running `uv run --with lkr-dev-cli lkr --help`.

Alternatively, you can install `lkr` with `pip install lkr-dev-cli` and use commands directly like `lkr <command>`.

We also have a public docker image that you can use to run `lkr` commands.

```bash
docker run -it --rm us-central1-docker.pkg.dev/lkr-dev-production/lkr-cli/cli:latest lkr --help
```


## Login

### Using OAuth2

See the [prerequisites section](#oauth2-prerequisites)

Login to `lkr`

```bash
uv run --with lkr-dev-cli lkr auth login
```

- Select a new instance
- Put the url of your Looker instance (e.g. https://acme.cloud.looker.com)
- Choose whether you want this login to use production or development mode
- Give it a name

You will be redirected to the Looker OAuth authorization page, click Allow. If you do not see an allow button, the [prerequisites](#prerequisites) were not done properly.

If everything is successful, you will see `Successfully authenticated!`. Test it with

```bash
uv run --with lkr-dev-cli lkr auth whoami
```

### Using API Key

If you provide environment variables for `LOOKERSDK_CLIENT_ID`, `LOOKERSDK_CLIENT_SECRET`, and `LOOKERSDK_BASE_URL`, `lkr` will use the API key to authenticate and the commands.  We also support command line arguments to pass in the client id, client secret, and base url.

```bash
uv run --with lkr-dev-cli  lkr --client-id <your client id> --client-secret <your client secret> --base-url <your instance url> auth whoami
```


### OAuth2 Prerequisites

If this if the first time you're using the Language Server, you'll need to register a new OAuth client to communicate with `lkr` cli.

`lkr` uses OAuth2 to authenticate to Looker and manages the authentication lifecycle for you. A Looker Admin will need to Register a new OAuth client to communicate with the Language Server:

Go to the Looker API Explorer for Register OAuth App (https://your.looker.instance/extensions/marketplace_extension_api_explorer::api-explorer/4.0/methods/Auth/register_oauth_client_app)

- Enter lkr-cli as the client_id
- Enter the following payload in the body

```json
{
  "redirect_uri": "http://localhost:8000/callback",
  "display_name": "LKR",
  "description": "lkr.dev language server, MCP and CLI",
  "enabled": true
}
```

- Check the "I Understand" box and click the Run button
- This only needs to be done once per instance


## MCP
Built into the `lkr` is an MCP server. Right now its tools are based on helping you work within an IDE. To use it a tool like [Cursor](https://www.cursor.com/), add this to your mcp.json

```
{
  "mcpServers": {
    "lkr-mcp": {
      "command": "uv",
      "args": ["run", "--with", "lkr-dev-cli", "lkr", "mcp", "run"]
    },
    "lkr-mcp-docker": {
      "command": "docker",
      "args": ["run", "--rm", "-it", "us-central1-docker.pkg.dev/lkr-dev-production/lkr-cli/cli:latest", "lkr", "mcp", "run"]
    }
  }
}
```

## Observability

The observability command provides tools for monitoring and interacting with Looker dashboard embeds. `lkr observability embed` will start a server that has endpoints for logging events from embedded dashboards. This tool is useful for monitoring the health of Looker embeds and your query times. It will spin up a chromium browser and use selinium and a simple HTML page to capture Looker's [Javascript events](https://cloud.google.com/looker/docs/embedded-javascript-events)

1. Embed user login times
2. Time to paint the dashboard `dashboard:loaded` including the login time
3. Time to finish running the dashboard `dashboard:run:complete`
4. Time for tiles to finish loading `dashboard:tile:start` and `dashboard:tile:complete` which is a proxy for your database query times

> [!NOTE]
> There are other ways in [Looker's System Activity](https://cloud.google.com/looker/docs/usage-reports-with-system-activity-explores) to view query times and dashboard load performance, but System Activity is not recommended to poll this aggresively if you are not on Elite System Activity. If you are on Elite System Activity, the data feeds for system activity is too slow for health checks. Also, Looker's system activity doesn't have a way to tie both the dashboard load and the query times together; this tool is the best proxy for both as we collect them together all within a single embedded dashboard load session.

### Primary Endpoint
- `GET /health`: Launches a headless browser to simulate embedding a dashboard, waits for a completion indicator, and logs the process for health checking. This endpoint accepts query parameters to help login users with custom attributes.

> [!IMPORTANT]
> Make sure you add the `http://host:port` to your domain allowlist in Admin Embed. [docs](https://cloud.google.com/looker/docs/embedded-javascript-events#adding_the_embed_domain_to_the_allowlist) Unless overridden, the default would be http://0.0.0.0:8080. These can also set via cli arguments. E.g., `lkr observability embed --host localhost --port 7777` or by setting the environment variables `HOST` and `PORT`. You can check the embed_domain by sending a request to the `/settings` endpoint.


For example:
- `dashboard_id`: *string* **required** - The id of the dashboard to embed
- `external_user_id`: *string* **required** - The external_user_id of the user to login. We recommend not logging in as a known user, rather a standalone healthcheck user. 
- `group_ids`: *list[string]* - The ids of the groups the user belongs to. Accepts multiple values like `&group_ids=123&group_ids=456`
- `permissions`: *list[string]* - The permissions the user has, defaults to access_data, see_user_dashboards, see_lookml_dashboards, see_looks, explore. Accepts multiple values like `&permissions=access_data&permissions=see_user_dashboards`
- `models`: *list[string]* **required** - The models the user has access to. Accepts multiple values like `&models=acme_model1&models=acme_model2`
- `session_length`: *int* - The length of the session. Defaults to 10 minutes.
- `first_name`: *string* - The first name of the user
- `last_name`: *string* - The last name of the user
- `user_timezone`: *string* - The timezone of the user
- `user_attributes`: *string* - The attributes of the user, this should be a stringified JSON like `&user_attributes={"store_id": "123"}`


### Other Endpoints

- `POST /log_event`: Receives and logs events from embedded dashboards. The embe
- `GET /settings`: Returns the current embed configuration and checks if the requesting domain is allowed. Useful for debugging why you're not receiving events
- `GET /`: Serves a static HTML file for embedding.
  

### Logging Events
`lkr observability embed` will have structured logs to stdout as well as return a JSON object with the events at the end of the request. These can be turned off with the `--quiet` flag. `lkr --quiet observability embed` will not print anything to stdout but still return the logged events in the response body.

- `lkr-observability:health_check_start`: The API has started
- `lkr-observability:health_check_timeout`: The API has timed out
- `lkr-observability:health_check_error`: The API has failed wuth an error
- `lkr-observability:dashboard:loaded`: The dashboard has loaded, based on Looker's `dashboard:loaded` event
- `lkr-observability:dashboard:run:start`: The dashboard has run started, based on Looker's `dashboard:run:start` event
- `lkr-observability:dashboard:run:complete`: The dashboard has run complete, based on Looker's `dashboard:run:complete` event
- `lkr-observability:dashboard:tile:start`: The dashboard tile has started, based on Looker's `dashboard:tile:start` event
- `lkr-observability:dashboard:tile:complete`: The dashboard tile has completed, based on Looker's `dashboard:tile:complete` event

*Payload*
- `event_type`: The type of event
- `event_at`: The time the event occurred
- `time_since_start`: The time since the session started
- `payload`: Additional data that may have been returned from the Javascript event
- `session_id`: The session id, corresponds to a single API request to `GET /health`.
- `last_event_type`: The type of the last event if there is one
- `last_event_at`: The time the last event occurred, if there is one
- `time_since_last_event`: The time since the last event, if there is one
- `external_user_id`: The external user id of the user who is running the dashboard
- `dashboard_id`: The id of the dashboard that was run

### Cloud Run + GCP Health Check example

One of the simplest ways to launch the health check is the `lkr-cli` public docker image, Cloud Run, and the GCP health check service. Here's an example; make sure to change your region and project. HEALTH_URL is an example of how to structure the query parameters for the health check.

```bash
export REGION=<your region>
export PROJECT=<your project id>

export HEALTH_URL="/health?dashboard_id=1&external_user_id=observability-embed-user&models=thelook&user_attributes={\"store_id\":\"1\"}"

gcloud run deploy lkr-observability \
  --image us-central1-docker.pkg.dev/lkr-dev-production/lkr-cli/cli:latest \
  --command lkr \
  --args observability,embed \
  --platform managed \
  --region $REGION \
  --project $PROJECT \
  --cpu 2 \
  --memory 4Gi \
  --set-env-vars LOOKERSDK_CLIENT_ID=<your client id>,LOOKERSDK_CLIENT_SECRET=<your client secret>,LOOKERSDK_BASE_URL=<your instance url> 

gcloud monitoring uptime create lkr-observability-health-check \
  --protocol https \
  --project $PROJECT \
  --resource-type="cloud-run-revision" \
  --resource-labels="project_id=${PROJECT},service_name=lkr-observability,location=${REGION}" \
  --path="${HEALTH_URL}" \
  --period="15" \
  --timeout="60"

```

### Alternative Usage
This can also be used to stress test your Looker environment as it serves an API that logs into a Looker embedded dashboard and runs queries like a user would within Chromium. If you wrote a script to repeatedly call this API with different parameters, you could use it to stress test your Looker environment and/or your database.

## User Attribute Updater (OIDC Token)

This section describes how to set up a Google Cloud Run service that can update a Looker User Attribute with an OIDC token. This is useful for services that need to authenticate to Looker as a service account.

**Setup Steps:**

1.  **Prepare Cloud Run Service:**
    *   Use the public `lkr-cli` Docker image: `us-central1-docker.pkg.dev/lkr-dev-production/lkr-cli/cli:latest`.
    *   Configure necessary environment variables: `LOOKERSDK_CLIENT_ID`, `LOOKERSDK_CLIENT_SECRET`, `LOOKERSDK_BASE_URL`, and `LOOKER_WHITELISTED_BASE_URLS`.
        *   `LOOKER_WHITELISTED_BASE_URLS` defaults to the `LOOKERSDK_BASE_URL` if not set, suitable for single-instance use. For multiple instances, provide a comma-separated list.
        *   The service also accepts `base_url`, `client_id`, and `client_secret` in the request body to override these environment variables.
    *   Set the Cloud Run command to `lkr` and arguments to `tools user-attribute-updater`.
    *   Deploy the Cloud Run service. Note the service URL upon deployment. An example `gcloud run deploy` command is provided in the "Example gcloud commands for User Attribute Updater" section below.

2.  **Create Looker User Attribute:**
    *   **Name:** `cloud_run_access_token` (or your preferred name).
    *   **Data Type:** String.
    *   **User Access:** None.
    *   **Hide values:** Yes.
    *   **Domain Allowlist:** The URL of your deployed Cloud Run service (from step 1). Looker will only allow this user attribute to be set if the request originates from this URL.

> [!NOTE]
> The user attribute name can be customized. If used with a Looker extension, follow the naming convention for scoped user attributes (e.g., `extension_name::attribute_name`) as described in the [Extension User Attributes documentation](https://www.npmjs.com/package/@looker/extension-sdk#user-attributes). For global attributes, a simple name like `cloud_run_access_token` is sufficient.

3.  **Create Cloud Scheduler Job:**
    *   **Schedule:** `0 * * * *` (runs hourly, adjust as needed).
    *   **Target Type:** HTTP.
    *   **URL:** The Cloud Run service URL (from step 1) appended with `/identity_token` (e.g., `https://your-cloud-run-url.com/identity_token`).
    *   **HTTP Method:** POST.
    *   **Headers:** `Content-Type: application/json`.
    *   **Body:** JSON payload specifying the user attribute to update. Use the name from step 2 or the `user_attribute_id` from Looker.

    ```json
    {
      "user_attribute": "cloud_run_access_token",
      "update_type": "default"
    }
    ```
    *   **Auth Header:** OIDC Token.
    *   **Service Account:** Select or create a service account to be used by the Cloud Scheduler job. This service account will be granted permission to invoke your Cloud Run service.
    *   **Audience:** The URL of the Cloud Run service (from step 1).
    *   **Max Retries:** Greater than 0 (e.g., 5).
    An example `gcloud scheduler jobs create` command is provided in the "Example gcloud commands for User Attribute Updater" section below.

4.  **Grant Permissions:**
    *   Ensure the service account used by Cloud Scheduler (from step 3) has the `Cloud Run Invoker` (roles/run.invoker) role for your Cloud Run service. This allows the scheduler to trigger the service. An example `gcloud run services add-iam-policy-binding` command is provided below.

5.  **Test:**
    *   Navigate to the Cloud Scheduler page in the Google Cloud Console.
    *   Select the job you created and click "Force Run."
    *   Check the logs of your Cloud Run service for a 200 response, indicating successful execution.

### Example gcloud commands for User Attribute Updater

This section provides the `gcloud` commands to automate the setup described above. Remember to replace placeholder values (like `<your-project-id>`, `<your-region>`, service account emails, and URLs) with your actual configuration details.

**1. Deploy Cloud Run Service:**
```bash
export REGION=<your-region> # e.g., us-central1
export PROJECT=<your-project-id>
export CLOUD_RUN_SERVICE_ACCOUNT_EMAIL=<your-cloud-run-sa-email> # Service account for the Cloud Run service itself
export LOOKERSDK_CLIENT_ID=<your-looker-client-id>
export LOOKERSDK_CLIENT_SECRET=<your-looker-client-secret>
export LOOKERSDK_BASE_URL=<https://your.looker.instance.com>
# Optional: export LOOKER_WHITELISTED_BASE_URLS=$LOOKERSDK_BASE_URL

gcloud run deploy lkr-access-token-updater \
  --image us-central1-docker.pkg.dev/lkr-dev-production/lkr-cli/cli:latest \
  --service-account "$CLOUD_RUN_SERVICE_ACCOUNT_EMAIL" \
  --command lkr \
  --args tools,user-attribute-updater \
  --platform managed \
  --region "$REGION" \
  --project "$PROJECT" \
  --cpu 1 \
  --memory 2Gi \
  --set-env-vars "LOOKERSDK_CLIENT_ID=$LOOKERSDK_CLIENT_ID,LOOKERSDK_CLIENT_SECRET=$LOOKERSDK_CLIENT_SECRET,LOOKERSDK_BASE_URL=$LOOKERSDK_BASE_URL,LOOKER_WHITELISTED_BASE_URLS=${LOOKER_WHITELISTED_BASE_URLS:-$LOOKERSDK_BASE_URL}" \
  --allow-unauthenticated # Required for OIDC from Scheduler if not further restricted by IAM
```

**2. Create Cloud Scheduler Job:**
```bash
export CLOUD_RUN_URL=$(gcloud run services describe lkr-access-token-updater --platform managed --region "$REGION" --project "$PROJECT" --format 'value(status.url)')
export SCHEDULER_SERVICE_ACCOUNT_EMAIL=<your-scheduler-sa-email> # Service account for the Scheduler job

gcloud scheduler jobs create http lkr-token-updater-scheduler \
  --schedule "0 * * * *" \
  --http-method POST \
  --uri "${CLOUD_RUN_URL}/identity_token" \
  --message-body "{\"user_attribute\": \"cloud_run_access_token\", \"update_type\": \"default\"}" \
  --oidc-service-account-email "$SCHEDULER_SERVICE_ACCOUNT_EMAIL" \
  --oidc-token-audience "$CLOUD_RUN_URL" \
  --max-retry-attempts 5 \
  --region "$REGION" \
  --project "$PROJECT" \
  --description "Periodically update Looker user attribute with OIDC token." \
  --time-zone "Etc/UTC" \
  --headers "Content-Type=application/json"
```

**3. Grant Cloud Run Invoker Role to Scheduler's Service Account:**
```bash
# Grant the Cloud Scheduler's service account permission to invoke the Cloud Run service
gcloud run services add-iam-policy-binding lkr-access-token-updater \
  --member="serviceAccount:${SCHEDULER_SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/run.invoker" \
  --region "$REGION" \
  --project "$PROJECT" \
  --platform managed
```

> [!NOTE]
> * Adjust service names (`lkr-access-token-updater`, `lkr-token-updater-scheduler`), regions, and project IDs in the commands to match your setup.
> * The Cloud Run service account (`CLOUD_RUN_SERVICE_ACCOUNT_EMAIL`) is the identity the *service runs as*. The Scheduler service account (`SCHEDULER_SERVICE_ACCOUNT_EMAIL`) is the identity the *scheduler uses to invoke the Run service*.
> * The `gcloud run deploy` command includes `--allow-unauthenticated`. This is a common setup for services invoked by Cloud Scheduler with OIDC. If you need tighter control, you can configure IAM policies more restrictively, but ensure the Scheduler's OIDC token is still accepted.

## UserAttributeUpdater `lkr-dev-cli`

Exported from the `lkr-dev-cli` package is the `UserAttributeUpdater` pydantic class. This class has all the necessary logic to update a user attribute value. 

It supports the following operations:
- Updating a default value
- Updating a group value
- Updating a user value
- Deleting a default value
- Deleting a group value
- Deleting a user value

It can also support looking up looker ids. It will lookup the following if the id is not provided:
- user_attribute_id by the name
- user_id by the email or external_user_id
- group_id by the name


### Example Usage

```python
from lkr import UserAttributeUpdater

# without credentials
updater = UserAttributeUpdater(
    user_attribute="cloud_run_access_token",
    update_type="default",
    value="123",
)


# with credentials
updater = UserAttributeUpdater(
    user_attribute="cloud_run_access_token",
    update_type="default",
    value="123",
    base_url="https://your-looker-instance.com",
    client_id="your-client-id",
    client_secret="your-client-secret",
)

updater.update_user_attribute_value()

# Getting authorization header from a FastAPI request
from fastapi import Request
from lkr import UserAttributeUpdater

@app.post("/request_authorization")
def request_authorization(request: Request):
    body = await request.json()
    updater = UserAttributeUpdater.model_validate(body)
    updater.get_request_authorization_for_value(request)
    updater.update_user_attribute_value()

@app.post("/as_body")
def as_body(request: Request, body: UserAttributeUpdater):
    body.get_request_authorization_for_value(request)
    body.update_user_attribute_value()

@app.post("/assigning_value")
def assigning_value(request: Request):
    updater = UserAttributeUpdater(
      user_attribute="cloud_run_access_token",
      update_type="default"
    )
    updater.value = request.headers.get("my_custom_header")
    updater.update_user_attribute_value()

@app.delete("/:user_attribute_name/:email")
def delete_user_attribute(user_attribute_name: str, email: str):
    updater = UserAttributeUpdater(
      user_attribute=user_attribute_name,
      update_type="user",
      email=email,
    )
    updater.delete_user_attribute_value()
```
