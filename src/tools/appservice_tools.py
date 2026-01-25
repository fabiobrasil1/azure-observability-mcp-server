"""
Tools MCP para consumir o Log Stream do App Service.
"""

from typing import Any, Dict, List

from src.appservice_logstream import AppServiceLogStreamClient
from src.mcp_server import ToolDefinition


def build_appservice_tools(
    logstream_client: AppServiceLogStreamClient,
) -> List[ToolDefinition]:
    return [
        ToolDefinition(
            name="appservice_logstream_tail",
            description="Le linhas do Log Stream do App Service (tempo real).",
            input_schema=_logstream_tail_schema(),
            handler=_build_logstream_tail_handler(logstream_client),
        )
    ]


def _logstream_tail_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "duration_seconds": {"type": "number"},
            "max_lines": {"type": "number"},
            "contains": {"type": "string"},
        },
        "required": [],
    }


def _build_logstream_tail_handler(logstream_client: AppServiceLogStreamClient):
    async def _handler(
        duration_seconds: int = 10,
        max_lines: int = 200,
        contains: str = "",
    ) -> Dict[str, Any]:
        lines = await logstream_client.tail(
            duration_seconds=duration_seconds,
            max_lines=max_lines,
            contains=contains,
        )
        return {
            "tool": "appservice_logstream_tail",
            "duration_seconds": duration_seconds,
            "max_lines": max_lines,
            "contains": contains,
            "lines": lines,
        }

    return _handler
