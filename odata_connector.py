"""A small read-only OData v4 connector.

Example:
    connector = ODataConnector(
        "https://usstage262.dayforcehcm.com/OData/configwizard11stage/Reports",
        username=os.environ["ODATA_USERNAME"],
        password=os.environ["ODATA_PASSWORD"],
    )
    products = connector.get_entities("Products", {"$top": "10"})
"""

import base64
import json
import logging
import os
import re
from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)


logger = logging.getLogger(__name__)


def _redact_headers(
    headers: Mapping[str, str] | list[tuple[str, str]],
) -> dict[str, str]:
    sensitive_headers = {"authorization", "proxy-authorization", "cookie", "set-cookie"}
    header_items = headers.items() if hasattr(headers, "items") else headers
    return {
        name: "<redacted>" if name.lower() in sensitive_headers else value
        for name, value in header_items
    }


def _has_basic_auth_challenge(error: HTTPError) -> bool:
    challenges = error.headers.get_all("WWW-Authenticate", [])
    return any(
        re.search(r"(?:^|,)\s*Basic(?:\s|$)", challenge, re.IGNORECASE)
        for challenge in challenges
    )


def _url_origin(url: str) -> tuple[str, str, int | None]:
    parsed_url = urlsplit(url)
    default_port = 443 if parsed_url.scheme == "https" else 80
    return parsed_url.scheme, parsed_url.hostname or "", parsed_url.port or default_port


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    def __init__(
        self,
        origin: tuple[str, str, int | None],
        log_path: str,
    ) -> None:
        super().__init__()
        self.origin = origin
        self.log_path = log_path

    def redirect_request(
        self,
        request: Request,
        response: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        source_path = urlsplit(request.full_url).path
        target_path = urlsplit(new_url).path
        _write_http_log(
            self.log_path,
            {
                "event": "response",
                "url": request.full_url,
                "status": code,
                "reason": message,
                "headers": _redact_headers(headers),
                "body": response.read().decode("utf-8", errors="replace"),
            },
        )
        if _url_origin(new_url) != self.origin:
            logger.warning(
                "Blocked cross-origin HTTP %s redirect from %s to %s.",
                code,
                source_path,
                target_path,
            )
            raise HTTPError(
                new_url,
                code,
                "Cross-origin redirects are not allowed.",
                headers,
                response,
            )
        logger.warning(
            "Following HTTP %s redirect from %s to %s.",
            code,
            source_path,
            target_path,
        )
        redirected_request = super().redirect_request(
            request, response, code, message, headers, new_url
        )
        if redirected_request is not None:
            _write_http_log(
                self.log_path,
                {
                    "event": "request",
                    "method": redirected_request.get_method(),
                    "url": redirected_request.full_url,
                    "headers": _redact_headers(redirected_request.header_items()),
                    "body": "<request body omitted>",
                },
            )
        return redirected_request


def _write_http_log(log_path: str, entry: dict[str, Any]) -> None:
    entry["timestamp"] = datetime.now().astimezone().isoformat()
    separator = "=" * 80
    lines = [
        separator,
        f"{entry['event'].upper()}  {entry['timestamp']}",
    ]
    for key in ("method", "url", "status", "reason"):
        if key in entry:
            lines.append(f"{key.title()}: {entry[key]}")
    if "headers" in entry:
        lines.extend(
            [
                "Headers:",
                json.dumps(entry["headers"], ensure_ascii=False, indent=2),
            ]
        )
    if "body" in entry:
        body = entry["body"]
        try:
            body = json.dumps(
                json.loads(body),
                ensure_ascii=False,
                indent=2,
            )
        except (TypeError, json.JSONDecodeError):
            pass
        lines.extend(["Body:", body])
    lines.append(separator)
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write("\n".join(lines) + "\n\n")


class ODataConnector:
    """Read OData v4 entity collections using HTTP Basic Authentication."""

    def __init__(
        self,
        service_url: str,
        username: str,
        password: str,
        timeout: float = 30,
    ) -> None:
        parsed_url = urlsplit(service_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("service_url must be an absolute HTTP or HTTPS URL.")
        if not username or not password:
            raise ValueError("A username and password are required.")

        self.service_url = service_url.rstrip("/") + "/"
        self.username = username
        self.password = password
        self.timeout = timeout
        self._origin = _url_origin(self.service_url)
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        self.log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"odata-http-{timestamp}.log",
        )

    def iter_entities(
        self,
        entity_set: str | None = None,
        query_options: Mapping[str, str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield entities from the service URL or a collection, following next links."""
        if entity_set is not None and (
            not entity_set or entity_set.startswith("/")
        ):
            raise ValueError("entity_set must be a non-empty relative path.")

        url = (
            self.service_url.rstrip("/")
            if entity_set is None
            else urljoin(self.service_url, quote(entity_set, safe=""))
        )
        if query_options:
            url = f"{url}?{urlencode(query_options)}"

        while url:
            self._check_origin(url)
            payload = self._get_json(url)
            entities = payload.get("value")
            if not isinstance(entities, list):
                raise ValueError("The OData response must contain a 'value' array.")
            for entity in entities:
                if not isinstance(entity, dict):
                    raise ValueError("Each item in the OData 'value' array must be an object.")
                yield entity

            next_link = payload.get("@odata.nextLink")
            if next_link is not None and not isinstance(next_link, str):
                raise ValueError("The OData '@odata.nextLink' value must be a URL string.")
            url = urljoin(url, next_link) if next_link else ""

    def get_entities(
        self,
        entity_set: str | None = None,
        query_options: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return all entities from a collection as a list."""
        return list(self.iter_entities(entity_set, query_options))

    def _get_json(self, url: str) -> dict[str, Any]:
        request = Request(url, headers={"Accept": "application/json"})
        opener = build_opener(
            _SameOriginRedirectHandler(self._origin, self.log_path)
        )
        _write_http_log(
            self.log_path,
            {
                "event": "request",
                "method": request.get_method(),
                "url": request.full_url,
                "headers": _redact_headers(request.header_items()),
                "body": "<request body omitted>",
            },
        )
        try:
            try:
                response = opener.open(request, timeout=self.timeout)
            except HTTPError as error:
                error_body = error.read().decode("utf-8", errors="replace")
                _write_http_log(
                    self.log_path,
                    {
                        "event": "response",
                        "url": error.url,
                        "status": error.code,
                        "reason": error.reason,
                        "headers": _redact_headers(error.headers),
                        "body": error_body,
                    },
                )
                if error.code != 401 or not _has_basic_auth_challenge(error):
                    error.close()
                    raise RuntimeError(
                        f"OData request failed for {url}: {error}"
                    ) from error

                challenge_url = error.url
                error.close()
                self._check_origin(challenge_url)
                logger.warning(
                    "Received HTTP 401 Basic challenge for %s; resending "
                    "request with Basic Auth credentials.",
                    urlsplit(challenge_url).path,
                )
                credentials = base64.b64encode(
                    f"{self.username}:{self.password}".encode("utf-8")
                ).decode("ascii")
                authorized_request = Request(
                    challenge_url,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Basic {credentials}",
                    },
                )
                _write_http_log(
                    self.log_path,
                    {
                        "event": "request",
                        "method": authorized_request.get_method(),
                        "url": authorized_request.full_url,
                        "headers": _redact_headers(
                            authorized_request.header_items()
                        ),
                        "body": "<request body omitted>",
                    },
                )
                response = opener.open(
                    authorized_request,
                    timeout=self.timeout,
                )

            with response:
                response_body = response.read().decode("utf-8", errors="replace")
                _write_http_log(
                    self.log_path,
                    {
                        "event": "response",
                        "url": response.url,
                        "status": response.status,
                        "reason": response.reason,
                        "headers": _redact_headers(response.headers),
                        "body": response_body,
                    },
                )
                payload = json.loads(response_body)
        except HTTPError as error:
            raise RuntimeError(
                f"OData request failed for {url}: {error}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise RuntimeError(f"OData request failed for {url}: {error}") from error
        except json.JSONDecodeError as error:
            raise ValueError(
                f"OData response from {url} was not valid JSON."
            ) from error

        if not isinstance(payload, dict):
            raise ValueError("The OData response must be a JSON object.")
        return payload

    def _check_origin(self, url: str) -> None:
        if _url_origin(url) != self._origin:
            raise ValueError("OData pagination links must remain on the service origin.")


if __name__ == "__main__":
    connector = ODataConnector(
        os.environ.get(
            "ODATA_SERVICE_URL",
            "https://usstage262.dayforcehcm.com/OData/configwizard11stage/Reports",
        ),
        os.environ.get("ODATA_USERNAME", "day.doron.posner"),
        os.environ.get("ODATA_PASSWORD","1")    ,
    )
    print(f"HTTP request/response log: {connector.log_path}")
    reports = connector.get_entities()
    print(json.dumps(reports, ensure_ascii=False, indent=2))
