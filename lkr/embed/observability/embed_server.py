import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from looker_sdk.sdk.api40.methods import Looker40SDK

from lkr.embed.observability.create_sso_embed_url import create_sso_embed_url
from lkr.logging import logger, structured_logger


def log_event(prefix: str, event: str, **kwargs):
    logger.info(f"{prefix}:{event}", **kwargs)

class EmbedHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.sdk: Looker40SDK | None = None
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        # Override to disable default server logging
        pass

    def do_GET(self):
        path, *rest = self.path.split('?')
        if path =='/':
        # Serve the HTML file
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            html_path = Path(__file__).parent / 'embed_container.html'
            with open(html_path, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_response(204)
            self.end_headers()


    def do_POST(self):
        path, *rest = self.path.split('?')
        if path == '/create_sso_embed_url':
            if not self.sdk:
                self.send_response(500)
                self.end_headers()
                return
            else:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data)

                sso_url = create_sso_embed_url(self.sdk, data=data)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(sso_url).encode('utf-8'))
        if path == '/log_event':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            event_data = json.loads(post_data)
            
            # # Log the event using structlog
            # structured_logger.info(
            #     event_data['event_type'],
            #     timestamp=event_data['timestamp'],
            #     duration_ms=event_data['duration_ms'],
            #     dashboard_id=event_data['dashboard_id'],
            #     user_id=event_data['user_id'],
            #     **event_data['event_data'],
            # )
            
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

def run_server(*, sdk: Looker40SDK, port:int =3000, log_event_prefix="looker_embed_observability"):
    class EmbedHandlerWithPrefix(EmbedHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.log_event_prefix = log_event_prefix
            self.sdk = sdk
    server_address = ('', port)
    httpd = HTTPServer(server_address, EmbedHandlerWithPrefix)
    structured_logger.info(f"{log_event_prefix}:embed_server_started", port=port, embed_domain=f"http://localhost:{port}")
    httpd.serve_forever()