"""Google's desktop OAuth flow and private, project-owned Calendar configuration."""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from features.calendar_actions import CalendarBusyError, CalendarError

APP_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"
OWNED_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events.owned",
    "https://www.googleapis.com/auth/calendar.calendars.readonly",
)


def calendar_home() -> Path:
    return Path.home() / ".hermes/profiles/hw3-local/google-calendar"


@contextmanager
def configuration_lock(home: Path):
    try:
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (home / "auth.lock").open("a") as lock:
            os.chmod(lock.name, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CalendarBusyError(
                    "Google Calendar authorization or configuration is busy. Try again later."
                ) from None
            yield
    except OSError:
        raise CalendarError(
            "Cannot read or write the local Google Calendar configuration. Check directory permissions."
        ) from None


def save_json(path: Path, data: dict) -> None:
    """Atomic replacement with private permissions, including the temporary file."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".calendar-")
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        raise CalendarError(
            "Cannot save Google Calendar configuration. Completed remote operations are not automatically undone."
        ) from None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_config(home: Path | None = None) -> dict:
    directory = home if home is not None else calendar_home()
    try:
        data = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {
            "calendar_id",
            "timezone",
            "summary",
        }:
            raise ValueError
        for key, limit in (("calendar_id", 1024), ("timezone", 64), ("summary", 200)):
            value = data[key]
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > limit
                or any(ord(c) < 32 for c in value)
            ):
                raise ValueError
        if data["calendar_id"] == "primary":
            raise ValueError
        ZoneInfo(data["timezone"])
        return data
    except (OSError, ValueError, TypeError, KeyError):
        raise CalendarError(
            "Google Calendar configuration is missing or invalid. Run calendar google connect."
        ) from None


def authorize(
    client_secrets: Path,
    *,
    existing: bool = False,
    port: int = 8765,
    home: Path | None = None,
) -> None:
    """Only this explicit CLI flow opens a loopback callback; chat never requests consent."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    from oauthlib.oauth2 import OAuth2Error
    from requests import RequestException

    if type(port) is not int or not 1024 <= port <= 65535:
        raise CalendarError("The OAuth callback port must be between 1024 and 65535.")
    directory = home if home is not None else calendar_home()
    scopes = list(OWNED_SCOPES) if existing else [APP_SCOPE]
    with configuration_lock(directory):
        try:
            data = json.loads(client_secrets.read_text(encoding="utf-8"))
            config = data["installed"]
            if (
                config["auth_uri"] != "https://accounts.google.com/o/oauth2/auth"
                or config["token_uri"] != "https://oauth2.googleapis.com/token"
            ):
                raise ValueError
            if not config["client_id"] or not config["client_secret"]:
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise CalendarError(
                "Provide the desktop application OAuth client JSON downloaded from Google Cloud."
            ) from None
        try:
            flow = InstalledAppFlow.from_client_config(
                data, scopes, autogenerate_code_verifier=True
            )
            # The callback timeout does not bound the later token exchange.
            flow.oauth2session.request = partial(flow.oauth2session.request, timeout=30)
            credentials = flow.run_local_server(
                host="localhost",
                bind_addr="127.0.0.1",
                port=port,
                open_browser=False,
                timeout_seconds=300,
                authorization_prompt_message="Open this link in a browser on this computer and authorize within 5 minutes:\n{url}",
                success_message="Google Calendar authorization received. You can close this page.",
                access_type="offline",
                prompt="consent",
            )
        except (OAuth2Error, RequestException, OSError, ValueError, AttributeError):
            # OAuth exceptions may include authorization codes, tokens or account details.
            raise CalendarError(
                "Google authorization did not complete or timed out. Check the browser and callback port, then retry."
            ) from None
        if not credentials.refresh_token or not credentials.has_scopes(scopes):
            raise CalendarError(
                "Required permissions or an offline refresh token were not granted. Authorize again."
            )
        save_json(directory / "token.json", json.loads(credentials.to_json()))


class CalendarHTTP:
    """SDK-compatible transport without httplib2's implicit stale-connection replay."""

    timeout = 30

    def __init__(self, credentials):
        self.credentials = credentials

    def request(self, uri, method="GET", body=None, headers=None, **_kwargs):
        import httplib2
        from google.auth.transport.requests import AuthorizedSession
        from requests import RequestException

        # A fresh session avoids stale pooled connections across long polling gaps.
        # Requests' default adapter has zero retries; also disable Google's 401 replay.
        try:
            with AuthorizedSession(
                self.credentials, max_refresh_attempts=0, refresh_timeout=self.timeout
            ) as session:
                response = session.request(
                    method,
                    uri,
                    data=body,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=False,
                )
                return httplib2.Response(
                    {
                        **response.headers,
                        "status": str(response.status_code),
                        "reason": response.reason,
                    }
                ), response.content
        except RequestException:
            raise OSError("Google Calendar transport did not complete.") from None


def build_service(home: Path | None = None):
    """Load/refresh credentials under a lock and use Google's client with bounded I/O."""
    from google.auth.exceptions import GoogleAuthError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    directory = home if home is not None else calendar_home()
    with configuration_lock(directory):
        try:
            data = json.loads((directory / "token.json").read_text(encoding="utf-8"))
            credentials = Credentials.from_authorized_user_info(data)
            if not credentials.refresh_token or not (
                credentials.has_scopes([APP_SCOPE])
                or credentials.has_scopes(OWNED_SCOPES)
            ):
                raise ValueError
            if not credentials.valid:
                request = Request()
                credentials.refresh(
                    lambda *args, **kwargs: request(*args, **{**kwargs, "timeout": 30})
                )
                save_json(directory / "token.json", json.loads(credentials.to_json()))
        except (OSError, ValueError, TypeError, KeyError, GoogleAuthError):
            raise CalendarError(
                "Google Calendar authorization is unavailable. Run calendar google auth to authorize again."
            ) from None
    # Refresh explicitly above; never transparently replay a write after a 401.
    http = CalendarHTTP(credentials)
    return build(
        "calendar", "v3", http=http, cache_discovery=False, static_discovery=True
    )
