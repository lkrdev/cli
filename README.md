# lkr cli

## Usage

`uv` makes everyone's life easier. Go [install it](https://docs.astral.sh/uv/getting-started/installation/). For a full list of commands, see the full [cli docs](./lkr.md)

## Prerequisites

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

## Login

See the [prerequisites section](#prerequisites)

Login to `lkr`

```bash
uv run --with lkr-dev-cli lkr auth login
```

- Select a new instance
- Put the url of your Looker instance (e.g. https://acme.cloud.looker.com)
- Choose whether you want this login to use production or development mode
- Give it a name

You will be redirected to the Looker OAuth authorization page, click Allow. If you do not see an allow button, the [prerequisites](#prerequisites) were not done properly.

If everything is successful, you will see `Successfully authenticated!`

## MCP
Built into the `lkr` is an MCP server. Right now its tools are based on helping you work within an IDE. To use it a tool like [Cursor](https://www.cursor.com/), add this to your mcp.json

```
{
  "mcpServers": {
    "lkr-mcp": {
      "command": "uv",
      "args": ["run", "--with", "lkr-dev-cli", "lkr", "mcp", "run"]
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
> Make sure you add the http://host:port to your domain allowlist in Admin Embed. [docs](https://cloud.google.com/looker/docs/embedded-javascript-events#adding_the_embed_domain_to_the_allowlist) Unless overridden, the default would be http://0.0.0.0:8080. These can also set via cli arguments. E.g., `lkr observability embed --host localhost --port 7777` or by setting the environment variables `HOST` and `PORT`. You can check the embed_domain by sending a request to the `/settings` endpoint.


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

### Cloud Run + GCP Health Check example

One of the simplest ways to launch the health check is the `lkr-cli` public docker image, Cloud Run, and the GCP health check service. Here's an example; make sure to change your region, models, user_attributes, and external_user_id.

```bash
export REGION=<your region>
export PROJECT=<your project id>

gcloud run deploy lkr-observability \
  --image us-central1-docker.pkg.dev/lkr-dev-production/lkr-cli/cli:latest \
  --command lkr \
  --args observability,embed \
  --platform managed \
  --region $REGION \ 
  --project $PROJECT \
  --cpu 1 \
  --memory 2Gi \
  --set-env-vars LOOKERSDK_CLIENT_ID=<your client id>,LOOKERSDK_CLIENT_SECRET=<your client secret>,LOOKERSDK_BASE_URL=<your instance url> \

export HEALTH_URL="/health?dashboard_id=1&external_user_id=embed-user-abc&models=thelook&user_attributes={\"store_id\":\"1\"}"

gcloud compute network-endpoint-groups create lkr-observability-neg \
  --region $REGION \
  --network-endpoint-type SERVERLESS \
  --cloud-run-service lkr-observability \
  --project $PROJECT

gcloud compute health-checks create http lkr-observability-health-check \
    --request-path $HEALTH_URL \
    --port 80 \
    --check-interval 5s \
    --timeout 15s \
    --unhealthy-threshold 2 \
    --healthy-threshold 2 \
    --project $PROJECT



```

### Alternative Usage
This can also be used to stress test your Looker environment as it serves an API that logs into a Looker embedded dashboard and runs queries like a user would within Chromium. If you wrote a script to repeatedly call this API with different parameters, you could use it to stress test your Looker environment and/or your database.