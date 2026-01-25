"""
Cliente para ler o Log Stream do App Service via Kudu.
"""

import time
from dataclasses import dataclass
from typing import List, Optional

import httpx


@dataclass
class AppServicePublishCredentials:
    app_name: str
    username: str
    password: str


class AppServiceLogStreamClient:
    def __init__(self, credentials: AppServicePublishCredentials) -> None:
        self._credentials = credentials
        self._http = httpx.AsyncClient(timeout=None)

    async def close(self) -> None:
        await self._http.aclose()

    async def tail(
        self,
        duration_seconds: int = 10,
        max_lines: int = 200,
        contains: str = "",
    ) -> List[str]:
        url = (
            f"https://{self._credentials.app_name}.scm.azurewebsites.net/api/logstream"
        )
        auth = (self._credentials.username, self._credentials.password)
        start = time.time()
        lines: List[str] = []

        async with self._http.stream("GET", url, auth=auth) as response:
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Logstream HTTP {response.status_code}: {response.text}"
                )

            async for line in response.aiter_lines():
                if not line:
                    continue
                if contains and contains not in line:
                    continue
                lines.append(line)
                if max_lines and len(lines) >= max_lines:
                    break
                if duration_seconds and (time.time() - start) >= duration_seconds:
                    break

        return lines
