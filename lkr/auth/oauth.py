import errno
import http.server
import io
import os
import secrets
import select
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from typing import TypedDict, cast
from urllib.parse import parse_qs

from lkr.custom_types import NewTokenCallback
from lkr.logger import logger


def parse_auth_code_input(raw_input: str, expected_state: str | None = None) -> str:
    """Extract authorization code from a raw code string or a full OAuth callback URL."""
    cleaned = raw_input.strip()
    if not cleaned:
        raise ValueError("Authorization code cannot be empty.")

    if (
        cleaned.startswith(("http://", "https://"))
        or "code=" in cleaned
        or "error=" in cleaned
    ):
        query_str = cleaned
        if "?" in cleaned:
            query_str = cleaned.split("?", 1)[1]
        elif cleaned.startswith(("http://", "https://")):
            parsed = urllib.parse.urlparse(cleaned)
            query_str = parsed.query
        query = parse_qs(query_str)
        if "error" in query:
            err = query["error"][0]
            desc = query.get("error_description", [""])[0]
            raise ValueError(f"Looker OAuth error: {err} {desc}".strip())
        if expected_state and query.get("state", [None])[0] != expected_state:
            raise ValueError("OAuth state mismatch in callback URL.")
        if "code" not in query or not query["code"][0]:
            raise ValueError("No 'code' parameter found in the provided URL.")
        return query["code"][0]

    return cleaned


def kill_process_on_port(port: int, retries: int = 5, delay: float = 1) -> None:
    """Kill any process currently using the specified port."""
    try:
        # Try to create a socket binding to check if port is in use
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("localhost", port))
        sock.close()
        return  # Port is free, no need to kill anything
    except OSError:
        # Port is in use, try to kill the process
        if os.name == "posix":  # macOS/Linux
            subprocess.run(
                f"lsof -ti tcp:{port} | xargs kill -9",
                shell=True,
                capture_output=True,
                check=False,
            )
        elif os.name == "nt":  # Windows
            subprocess.run(
                f'for /f "tokens=5" %a in (\'netstat -aon ^| find ":{port}"\') do taskkill /F /PID %a',
                shell=True,
                capture_output=True,
                check=False,
            )
        # After killing, wait for the port to be free
        for _ in range(retries):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("localhost", port))
                sock.close()
                return
            except OSError:
                time.sleep(delay)
        raise RuntimeError(f"Port {port} is still in use after killing process.")


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        """Handle the callback from OAuth authorization"""
        parsed_url = urllib.parse.urlparse(self.path)
        logger.debug(f"OAuthCallbackHandler received GET request for path: {self.path}")

        # Ignore requests that are not the callback (e.g. /favicon.ico)
        if parsed_url.path != "/callback":
            logger.debug(f"Ignoring non-callback request: {self.path}")
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self._send_cors_headers()
        self.end_headers()

        # Parse the authorization code or error from query parameters
        query_components = parse_qs(parsed_url.query)
        logger.debug(f"OAuth callback query parameters: {query_components}")

        # Store the code in the server instance
        server = cast(OAuthCallbackServer, self.server)
        if (
            server.expected_state
            and query_components.get("state", [None])[0] != server.expected_state
        ):
            logger.error("Looker OAuth callback state mismatch.")
            self.wfile.write(
                b"OAuth Authentication Failed: State mismatch. You can close this window."
            )
        elif "code" in query_components:
            server.auth_code = query_components["code"][0]
            logger.debug(
                f"Authorization code received successfully: {server.auth_code[:5]}..."
            )
            self.wfile.write(
                b"Successfully authenticated to Looker OAuth! You can close this window."
            )
        elif "error" in query_components:
            error = query_components["error"][0]
            error_description = query_components.get("error_description", [""])[0]
            logger.error(
                f"Looker OAuth returned error: {error} - {error_description}"
            )
            self.wfile.write(
                f"OAuth Authentication Failed: {error} - {error_description}. You can close this window.".encode()
            )
        else:
            logger.warning(
                f"Callback received without 'code' or 'error' query parameters: {self.path}"
            )
            self.wfile.write(
                b"OAuth Authentication Failed: Invalid callback request. You can close this window."
            )

        server.done_event.set()

    def log_message(self, format, *args):
        """Suppress logging of requests"""


class OAuthCallbackServer(socketserver.TCPServer):
    allow_reuse_address = True

    def __init__(self, server_address, expected_state: str | None = None):
        super().__init__(server_address, OAuthCallbackHandler)
        self.auth_code: str | None = None
        self.expected_state = expected_state
        self.done_event = threading.Event()


class LoginResponse(TypedDict):
    auth_code: str | None
    code_verifier: str | None


class OAuth2PKCE:
    def __init__(
        self,
        new_token_callback: NewTokenCallback,
        use_production: bool,
        port: int | None = None,
        no_browser: bool = False,
        redirect_uri: str | None = None,
    ):
        from lkr.auth_service import DbOAuthSession

        self.auth_code: str | None = None
        self.state = secrets.token_urlsafe(16)
        self.new_token_callback: NewTokenCallback = new_token_callback
        self.auth_session: DbOAuthSession | None = None
        self.server_thread: threading.Thread | None = None
        self.server: OAuthCallbackServer | None = None
        self.port: int = port if port is not None else 8000
        self.use_production: bool = use_production
        self.no_browser: bool = no_browser
        self.redirect_uri: str | None = redirect_uri

    def cleanup(self):
        """Clean up the server and its thread."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.server_thread:
            self.server_thread.join(timeout=1.0)
            self.server_thread = None

    def _start_local_server(self) -> threading.Event:
        """Start local callback server if possible; return an event signaling callback completion."""
        done_event = threading.Event()
        try:
            kill_process_on_port(self.port)
            for _ in range(20):
                try:
                    self.server = OAuthCallbackServer(
                        ("localhost", self.port), expected_state=self.state
                    )
                    break
                except OSError as e:
                    if getattr(
                        e, "errno", None
                    ) == errno.EADDRINUSE or "Address already in use" in str(e):
                        time.sleep(1)
                    else:
                        raise
            if self.server:
                done_event = self.server.done_event
                self.server_thread = threading.Thread(
                    target=self.server.serve_forever, daemon=True
                )
                self.server_thread.start()
        except Exception as e:  # noqa: BLE001
            logger.debug(
                f"Could not start local OAuth callback server on port {self.port}: {e}. Falling back to manual code entry."
            )
        return done_event

    def _wait_for_code_or_callback(self, done_event: threading.Event) -> str | None:
        """Wait for either the localhost HTTP callback or manual authorization code paste on stdin."""
        sys.stdout.write(
            "Waiting for browser authentication, or paste the authorization code here: "
        )
        sys.stdout.flush()

        try:
            if os.name != "posix":
                raise io.UnsupportedOperation("select on stdin requires posix")
            sys.stdin.fileno()
            use_select = True
        except (OSError, ValueError, io.UnsupportedOperation):
            use_select = False

        if use_select:
            stdin_eof = False
            while not done_event.is_set():
                if stdin_eof:
                    if self.server is None:
                        break
                    done_event.wait(timeout=0.1)
                    continue
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                if ready:
                    line = sys.stdin.readline()
                    if line == "":
                        stdin_eof = True
                        continue
                    if line.strip():
                        code = parse_auth_code_input(line, expected_state=self.state)
                        self.cleanup()
                        return code
            sys.stdout.write("\n")
            sys.stdout.flush()
            auth_code = self.server.auth_code if self.server else None
            self.cleanup()
            return auth_code

        stdin_lines: list[str] = []

        def _read_stdin():
            try:
                line = sys.stdin.readline()
                if line and line.strip():
                    stdin_lines.append(line)
                    done_event.set()
            except Exception:  # noqa: BLE001
                if self.server is None:
                    done_event.set()

        threading.Thread(target=_read_stdin, daemon=True).start()
        done_event.wait()

        if stdin_lines:
            code = parse_auth_code_input(stdin_lines[0], expected_state=self.state)
            self.cleanup()
            return code

        sys.stdout.write("\n")
        sys.stdout.flush()
        auth_code = self.server.auth_code if self.server else None
        self.cleanup()
        return auth_code

    def initiate_login(self, base_url: str) -> LoginResponse:
        """
        Initiates the OAuth2 PKCE login flow by starting a local callback server,
        opening (or printing) the authorization URL, and racing the localhost callback
        against manual authorization code entry on stdin.
        """
        from lkr.auth_service import get_auth_session

        done_event = self._start_local_server()

        self.auth_session = get_auth_session(
            base_url,
            self.new_token_callback,
            use_production=self.use_production,
            port=self.port,
            redirect_uri=self.redirect_uri,
        )
        oauth_url = self.auth_session.create_auth_code_request_url(
            "cors_api", self.state
        )
        logger.debug(f"Constructed OAuth URL: {oauth_url}")
        logger.info(f"Open this URL in your browser to authenticate:\n\n  {oauth_url}\n")

        if not self.no_browser:
            try:
                webbrowser.open(oauth_url)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Failed to open browser automatically: {e}")

        self.auth_code = self._wait_for_code_or_callback(done_event)

        return LoginResponse(
            auth_code=self.auth_code,
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
