import http.server
import os
import secrets
import socket
import socketserver
import threading
import time
import urllib.parse
import webbrowser
from typing import Optional, TypedDict
from urllib.parse import parse_qs

from lkr.custom_types import NewTokenCallback


def kill_process_on_port(port: int, retries: int = 5, delay: float = 1) -> None:
    """Kill any process currently using the specified port."""
    try:
        # Try to create a socket binding to check if port is in use
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("localhost", port))
        sock.close()
        return  # Port is free, no need to kill anything
    except socket.error:
        # Port is in use, try to kill the process
        if os.name == "posix":  # macOS/Linux
            os.system(f"lsof -ti tcp:{port} | xargs kill -9 2>/dev/null")
        elif os.name == "nt":  # Windows
            os.system(
                f'for /f "tokens=5" %a in (\'netstat -aon ^| find ":{port}"\') do taskkill /F /PID %a 2>nul'
            )
        # After killing, wait for the port to be free
        for _ in range(retries):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("localhost", port))
                sock.close()
                return
            except socket.error:
                time.sleep(delay)
        raise RuntimeError(f"Port {port} is still in use after killing process.")


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        """Handle the callback from OAuth authorization"""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        # Parse the authorization code from query parameters
        query_components = parse_qs(urllib.parse.urlparse(self.path).query)

        # Store the code in the server instance
        if "code" in query_components:
            self.server.auth_code = query_components["code"][0]  # type: ignore

        # Display a success message to the user
        self.wfile.write(
            b"Successfully authenticated to Looker OAuth! You can close this window."
        )

        # Shutdown the server
        threading.Thread(target=self.server.shutdown).start()

    def log_message(self, format, *args):
        """Suppress logging of requests"""
        pass


class OAuthCallbackServer(socketserver.TCPServer):
    def __init__(self, server_address):
        super().__init__(server_address, OAuthCallbackHandler)
        self.auth_code: str | None = None


class LoginResponse(TypedDict):
    auth_code: Optional[str]
    code_verifier: Optional[str]


class OAuth2PKCE:
    def __init__(self, new_token_callback: NewTokenCallback, use_production: bool):
        from lkr.auth_service import DbOAuthSession

        self.auth_code: Optional[str] = None
        self.state = secrets.token_urlsafe(16)
        self.new_token_callback: NewTokenCallback = new_token_callback
        self.auth_session: DbOAuthSession | None = None
        self.server_thread: threading.Thread | None = None
        self.server: OAuthCallbackServer | None = None
        self.port: int = 8000
        self.use_production: bool = use_production

    def cleanup(self):
        """Clean up the server and its thread."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.server_thread:
            self.server_thread.join(timeout=1.0)
            self.server_thread = None

    def initiate_login(self, base_url: str) -> LoginResponse:
        """
        Initiates the OAuth2 PKCE login flow by opening the browser with the authorization URL
        and starting a local server to catch the callback.

        Returns:
            Optional[str]: The authorization code if successful, None otherwise
        """
        from lkr.auth_service import get_auth_session

        # Kill any process using port 8000
        kill_process_on_port(self.port)

        # Wait until the port is actually free and we can bind the real server (up to 20 seconds)
        server_created = False
        last_exception = None
        for _ in range(20):  # 20 x 1s = 20s
            try:
                self.server = OAuthCallbackServer(("localhost", self.port))
                server_created = True
                break
            except OSError as e:
                if getattr(e, "errno", None) == 48 or "Address already in use" in str(
                    e
                ):
                    last_exception = e
                    time.sleep(1)
                else:
                    raise
        if not server_created:
            import logging

            logging.error(
                f"Failed to bind to port {self.port} after waiting: {last_exception}"
            )
            raise RuntimeError(
                f"Failed to bind to port {self.port} after waiting: {last_exception}"
            )

        # Start the server in a separate thread
        if self.server is None:
            raise RuntimeError("Internal error: server was not created successfully.")
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()

        # Construct and open the OAuth URL
        self.auth_session = get_auth_session(
            base_url, self.new_token_callback, use_production=self.use_production
        )
        oauth_url = self.auth_session.create_auth_code_request_url(
            "cors_api", self.state
        )

        webbrowser.open(oauth_url)

        # Wait for the callback
        self.server_thread.join()

        # Get the authorization code
        if self.server is None:
            raise RuntimeError("Internal error: server was not created successfully.")
        return LoginResponse(
            auth_code=self.server.auth_code,
            code_verifier=self.auth_session.code_verifier,
        )

    def exchange_code_for_token(self):
        """
        Exchange the authorization code for access and refresh tokens.

        Args:
            base_url: The base URL of the Looker instance
            client_id: The OAuth client ID

        Returns:
            Dict containing access_token, refresh_token, token_type, and expires_in
        """
        if not self.auth_code:
            raise ValueError(
                "No authorization code available. Must call initiate_login first."
            )
        if not self.auth_session:
            raise ValueError(
                "No auth session available. Must call initiate_login first."
            )
        self.auth_session.redeem_auth_code(
            self.auth_code, self.auth_session.code_verifier
        )
        self.cleanup()
        return self.auth_session.token

    def __del__(self):
        self.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.cleanup()
