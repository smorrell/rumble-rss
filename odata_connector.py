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
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)


logger = logging.getLogger(__name__)


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
    def __init__(self, origin: tuple[str, str, int | None]) -> None:
        super().__init__()
        self.origin = origin

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
        return super().redirect_request(
            request, response, code, message, headers, new_url
        )


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
        opener = build_opener(_SameOriginRedirectHandler(self._origin))
        try:
            try:
                response = opener.open(request, timeout=self.timeout)
            except HTTPError as error:
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
                response = opener.open(
                    authorized_request,
                    timeout=self.timeout,
                )

            with response:
                payload = json.load(response)
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
    reports = connector.get_entities()
    print(json.dumps(reports, ensure_ascii=False, indent=2))
