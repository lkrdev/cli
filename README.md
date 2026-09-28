# lkr cli

The `lkr` cli is a tool for interacting with Looker. It combines Looker's SDK and customer logic to interact with Looker in meaninful ways. For a full list of commands, see the full [cli docs](./lkr.md)

## Usage

`uv` makes everyone's life easier. Go [install it](https://docs.astral.sh/uv/getting-started/installation/). You can start using `lkr` without installing by running `uvx lkr-dev-cli --help`.

Alternatively, you can install `lkr` with `uv tool install "lkr-dev-cli[all]"` (or `pip install "lkr-dev-cli[all]"`) and run commands directly like `lkr <command>`.

We also have a public docker image that you can use to run `lkr` commands.

```bash
docker run -it --rm us-central1-docker.pkg.dev/lkr-dev-production/lkr-cli/cli:latest lkr --help
```

## Installing and upgrading with `uv tool`

Install `lkr` globally on your PATH to run `lkr` (or `lkr-dev-cli`) directly without `uvx`:

```bash
# Install with all optional extras (mcp, code-mode, observability, tools)
uv tool install "lkr-dev-cli[all]"

# Verify installation
lkr --help
```

Upgrade an existing installation to the latest release:

```bash
uv tool upgrade lkr-dev-cli

# Or force reinstall the latest version
uv tool install --upgrade --reinstall "lkr-dev-cli[all]"
```

## Login

### Using OAuth2

See the [prerequisites section](#oauth2-prerequisites)

Login to `lkr`

```bash
uvx lkr-dev-cli auth login
```

- Select a new instance
- Put the url of your Looker instance (e.g. https://acme.cloud.looker.com)
- Choose whether you want this login to use production or development mode
- Give it a name

You will be redirected to the Looker OAuth authorization page, click Allow. If you do not see an allow button, the [prerequisites](#oauth2-prerequisites) were not done properly.

If everything is successful, you will see `Successfully authenticated!`. Test it with

```bash
uvx lkr-dev-cli auth whoami
```

### Using API Key

If you provide environment variables for `LOOKERSDK_CLIENT_ID`, `LOOKERSDK_CLIENT_SECRET`, and `LOOKERSDK_BASE_URL`, `lkr` will use the API key to authenticate and the commands.  We also support command line arguments to pass in the client id, client secret, and base url.

```bash
uvx lkr-dev-cli --client-id <your client id> --client-secret <your client secret> --base-url <your instance url> auth whoami
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


## Code mode

Execute Python code with Looker SDK coverage inside a `Monty` sandbox. It inspects the Looker SDK for public methods and injects them into the sandbox for both Model Context Protocol (MCP) server mode and standalone CLI execution.

### Direct CLI execution (sandbox mode)
Run scripts or inline code directly against your active Looker instance:
```bash
# Execute inline Python code
uvx lkr-dev-cli code-mode sandbox --code="return me()"

# Execute a Python script file
uvx lkr-dev-cli code-mode sandbox --file=./path/to/script.py
```

### Agent skill (`lkr-code-mode`)

For AI coding agents (Gemini CLI, Claude Code, Cursor, Copilot), this repository includes an installable skill under [skills/lkr-code-mode](./skills/lkr-code-mode) (and [.agents/skills/lkr-code-mode](./.agents/skills/lkr-code-mode)) for running `lkr code-mode sandbox` non-interactively, including auth flags, CLI discovery commands, helper scripts, and Looker SDK recipes.

Install it into your agent environment with `npx skills`:

```bash
npx skills add lkrdev/cli --skill lkr-code-mode
```

For full options, MCP server configuration, and PKCE recovery, see the [Code Mode docs](./codemode.md).

## MCP
Built into the `lkr` is an MCP server. Right now its tools are based on helping you work within an IDE. To use it a tool like [Cursor](https://www.cursor.com/), add this to your mcp.json

```
{
  "mcpServers": {
    "lkr-mcp": {
      "command": "uvx",
      "args": ["lkr-dev-cli[all]", "mcp", "run"]
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

1. Create a new cloud run using the `lkr-cli` public docker image `us-central1-docker.pkg.dev/lkr-dev-production/lkr-cli/cli:latest`
2. Put in the environment variables LOOKERSDK_CLIENT_ID, LOOKERSDK_CLIENT_SECRET, LOOKERSDK_BASE_URL, LOOKER_WHITELISTED_BASE_URLS. The `LOOKER_WHITELISTED_BASE_URLS` would be the same url as the `LOOKERSDK_BASE_URL` if you are only using this for a single Looker instance. For more advanced use cases, you can set the `LOOKER_WHITELISTED_BASE_URLS` to a comma separated list of urls. The body of the request also accepts a `base_url`, `client_id`, and `client_secret` key that will override these settings. See example [gcloud command](#example-gcloud-command)
3. For the command and arguments use:
   - command: `lkr`
   - args: `tools` `user-attribute-updater`
4. Deploy the cloud run
5. Retrieve the URL of the cloud run
6. Create the user attribute 
   - Name: cloud_run_access_token 
   - Data Type: String
   - User Access: None
   - Hide values: Yes
   - Domain Allowlist: The URL of the cloud run from step 4. Looker will only allow the user attribute to be set if the request is going to this URL

> [!NOTE]
> The user attribute name can be anything you want. Typically you will be using this with an extension, so you should follow the naming convention of the type of user attribute you will be using with the extension. I would recommend using a `scoped user attributes` for this. See [Extension User Attributes](https://www.npmjs.com/package/@looker/extension-sdk#user-attributes). If you are using a `global_user_attribute`, then you can just use the name of it like `cloud_run_access_token`.

6. Create a new cloud scheduler
   - cron: `0 * * * *`
   - Target Type: Cloud Run
   - URL: The URL of the cloud run from step 4 with a path of `/identity_token`. E.g. `https://your-cloud-run-url.com/identity_token`
   - HTTP Method: POST
   - Headers: `Content-Type: application/json`
   - Body: Use the user attribute_name from  step 5, or use the user_attribute_id found in the Looker URL after you created it or are editing it

    ```json
    {
      "user_attribute": "cloud_run_access_token",
      "update_type": "default"
    }
    ```
   - Auth Header: OIDC Token
   - Service Account: Choose the service account you want to use to run the cloud scheduler
   - Audience: The URL of the cloud run
   - Max Retries: >0
7. Make sure the Service Account has the `Cloud Run Invoker` role
8. Navigate the the cloud scheduler page, select the one you just created, and click Force Run
9. Check the logs of the cloud run to see if there was a 200 response


### Example `gcloud` command
```bash
export REGION=<your region>
export PROJECT=<your project id>

gcloud run deploy lkr-access-token-updater \
  --image us-central1-docker.pkg.dev/lkr-dev-production/lkr-cli/cli:latest \
  --command lkr \
  --args tools,user-attribute-updater \
  --platform managed \
  --region $REGION \
  --project $PROJECT \
  --cpu 1 \
  --memory 2Gi \
  --set-env-vars LOOKERSDK_CLIENT_ID=<your client id>,LOOKERSDK_CLIENT_SECRET=<your client secret>,LOOKERSDK_BASE_URL=<your instance url>,LOOKER_WHITELISTED_BASE_URLS=<your instance url>
  ```

## Python SDK and library usage

When installing `lkr-dev-cli` in your Python environment, you can import tools and pre-authenticated Looker SDK clients directly into your scripts, apps, or Jupyter notebooks.

### Package import aliases (`lkr` vs `lkr_dev_cli`)
Both `lkr` and `lkr_dev_cli` are exported as identical top-level Python packages:

```python
from lkr import init_sdk, UserAttributeUpdater
# works the same as:
from lkr_dev_cli import init_sdk, UserAttributeUpdater
```

### Initializing the Looker SDK (`init_sdk`)
`init_sdk()` returns an authenticated `ExtendedLooker40SDK` instance and handles credential discovery automatically:

```python
from lkr_dev_cli import init_sdk

# Option 1: Explicit API Authentication
sdk = init_sdk(
    base_url="https://acme.cloud.looker.com",
    client_id="your-client-id",
    client_secret="your-client-secret",
    verify_ssl=True,  # optional, defaults to True
)

# Option 2: Environment Variable API Authentication
# Automatically uses LOOKERSDK_BASE_URL, LOOKERSDK_CLIENT_ID, LOOKERSDK_CLIENT_SECRET
sdk = init_sdk()

# Option 3: Database (SQLite) OAuth Login Profile
# Uses your saved active session from running `lkr auth login`
sdk = init_sdk()  # Picks the active current_instance = 1
# Or pick a specific named login profile:
sdk = init_sdk(instance_name="my_dev_instance")

# Make an API call
me = sdk.me()
print(f"Hello, {me.display_name}")
```

### UserAttributeUpdater

Exported from the package is the `UserAttributeUpdater` pydantic class. This class has all the necessary logic to update a user attribute value. 

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


### Example usage

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
    updater.get_request_authorization_for_value(request.headers.items())
    updater.update_user_attribute_value()

@app.post("/as_body")
def as_body(request: Request, body: UserAttributeUpdater):
    body.get_request_authorization_for_value(request.headers.items())
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

## Permission deprecation tool

The `schedule-download-deprecation` tool helps Looker admins check that users do not lose access to models they already use when Looker moves to model-specific permissions for scheduling and downloading.

### How it helps
Some permissions in Looker are currently granted instance-wide, and in the future may need to be granted at the model level via Model Sets. This tool audits active users and finds those who:
- Have target permissions (like `download_with_limit`, `schedule_look_emails`, etc.) instance-wide.
- Do not have those same permissions for specific models they otherwise have access to.

Admins can run this before deprecation takes effect to find and fix permission gaps.

### Usage
Run this command as a Looker Admin:

```bash
uvx lkr-dev-cli[all] tools schedule-download-deprecation
```

Options:
- `--csv` exports the results to a CSV file for large instances.
- `--unfiltered` shows all users, including those who already have all required permissions across all models.
- `--model-offset` slices the table output to show different sets of models (the table shows 5 models at a time).


## Gemini Enterprise agents (`lkr tools agents`)

Looker's UI only supports connecting one default Gemini Enterprise (Discovery Engine) app per Looker instance. `lkr tools agents` lets you publish, list, and delete Looker Conversational Analytics (CA) agents across multiple Gemini Enterprise apps, GCP projects, and locations (`global`, `us`, `eu`).

For all flags and options, see the [lkr tools agents CLI docs](./lkr.md#lkr-tools-agents) ([publish](./lkr.md#lkr-tools-agents-publish), [list](./lkr.md#lkr-tools-agents-list), [delete](./lkr.md#lkr-tools-agents-delete)).

> [!IMPORTANT]
> Before publishing an agent, make sure **Admin > Gemini in Looker > Publish to Gemini Enterprise** is enabled on your Looker instance, and that the Looker service account has IAM permissions on the target GCP project plus a Gemini Enterprise user license in **Gemini Enterprise > Manage Users** (or "Assign licenses automatically" enabled on the app).

### Finding your agent ID

To get an agent's `<agent_id>` in the Looker UI:
1. Open **Conversational Analytics** from the left navigation menu and click **Manage Agents** (or go to `https://<your-looker-instance>/conversations/agents`).
2. Click on the agent (or select **Edit** from its menu).
3. Copy the `<agent_id>` GUID from the browser URL:
   ```text
   https://<your-looker-instance>/conversations/agents/<agent_id>
   ```

### Publishing an agent

```bash
# Publish an agent to the Looker instance's default Gemini Enterprise app
uvx lkr-dev-cli tools agents publish <agent_id>

# Publish an agent to a specific (or secondary) Gemini Enterprise app
uvx lkr-dev-cli tools agents publish <agent_id> \
  --project-number <gcp_project_number> \
  --location global \
  --engine-id <gemini_enterprise_engine_id> \
  --validate
```

### Listing and reconciling published agents

`lkr tools agents list` merges records from the Looker artifact store, live Discovery Engine A2A agent cards (when `--gcp-token` is passed), and Looker's default configuration. If an agent was deleted in the Gemini Enterprise UI, `list` updates its Looker artifact state to `unpublished` (pass `--no-update-artifact` to skip writing back to the artifact store).

```bash
# List agents from Looker Artifacts and live Discovery Engine, and sync UI deletions back to Artifacts
uvx lkr-dev-cli tools agents list \
  --project-number <gcp_project_number> \
  --engine-id <gemini_enterprise_engine_id> \
  --gcp-token $(gcloud auth print-access-token)
```

### Deleting or unpublishing an agent

```bash
# Unpublish from the default Looker-configured Gemini Enterprise app
uvx lkr-dev-cli tools agents delete <agent_id>

# Delete from a secondary Gemini Enterprise app via Discovery Engine and update Looker Artifacts
uvx lkr-dev-cli tools agents delete <agent_id> \
  --project-number <gcp_project_number> \
  --location global \
  --engine-id <gemini_enterprise_engine_id> \
  --gcp-token $(gcloud auth print-access-token)
```


## Optional dependencies

The `lkr` CLI has optional extras for specific commands. You can install them individually or all at once.

### Available extras

- `mcp` enables the MCP (Model Context Protocol) server and `lkr mcp` commands.
- `observability` enables the embed monitoring server and `lkr observability` commands.
- `tools` enables the user attribute updater and `lkr tools` commands.

### Installing optional dependencies

Install all optional dependencies:
```bash
uv sync --extra all
```

Install specific extras:
```bash
# Install MCP functionality
uv sync --extra mcp

# Install observability features
uv sync --extra embed-observability

# Install user attribute updater
uv sync --extra user-attribute-updater

# Install multiple extras
uv sync --extra mcp --extra embed-observability
```

Using pip:
```bash
# Install all optional dependencies
pip install lkr-dev-cli[all]

# Install specific extras
pip install lkr-dev-cli[mcp,embed-observability,user-attribute-updater]
```
