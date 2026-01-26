"""
Servidor MCP oficial usando JSON-RPC 2.0 via stdin/stdout.

Implementa o protocolo MCP (Model Context Protocol) conforme especificação oficial:
- JSON-RPC 2.0
- Transporte via stdio
- Métodos: tools/list, tools/call
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from src.azure_appinsights import AzureAppInsightsClient, AzureCredentials
from src.appservice_logstream import (
    AppServiceLogStreamClient,
    AppServicePublishCredentials,
)
from src.mcp_server import AzureObservabilityMCPServer


class MCPProtocolServer:
    """
    Servidor MCP que implementa JSON-RPC 2.0 via stdin/stdout.
    """

    def __init__(self, server: AzureObservabilityMCPServer) -> None:
        self._server = server

    def _write_jsonrpc_response(
        self, id: Optional[int], result: Any = None, error: Optional[Dict[str, Any]] = None
    ) -> None:
        """Escreve uma resposta JSON-RPC 2.0."""
        response: Dict[str, Any] = {"jsonrpc": "2.0"}
        if id is not None:
            response["id"] = id
        if error is not None:
            response["error"] = error
        else:
            response["result"] = result

        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    async def _handle_request(self, request: Dict[str, Any]) -> None:
        """Processa uma requisição JSON-RPC 2.0."""
        request_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        try:
            if method == "tools/list":
                tools = self._server.list_tools()
                self._write_jsonrpc_response(request_id, result={"tools": tools})

            elif method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                result = await self._server.call_tool(tool_name, arguments)
                self._write_jsonrpc_response(
                    request_id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, indent=2, ensure_ascii=False),
                            }
                        ]
                    },
                )

            elif method == "initialize":
                self._write_jsonrpc_response(
                    request_id,
                    result={
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {
                            "name": "azure-observability-mcp-server",
                            "version": "0.1.0",
                        },
                    },
                )

            else:
                self._write_jsonrpc_response(
                    request_id,
                    error={"code": -32601, "message": f"Method not found: {method}"},
                )

        except Exception as e:
            self._write_jsonrpc_response(
                request_id,
                error={"code": -32603, "message": f"Internal error: {str(e)}"},
            )

    async def run(self) -> None:
        """Loop principal do servidor MCP."""
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break

            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                self._write_jsonrpc_response(
                    None,
                    error={"code": -32700, "message": "Parse error"},
                )
                continue

            if "method" in request:
                await self._handle_request(request)


def _require_env(names: List[str]) -> None:
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32000,
                        "message": "Variaveis de ambiente obrigatorias ausentes.",
                        "data": {"missing": missing},
                    },
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)


def _build_appservice_client() -> Optional[AppServiceLogStreamClient]:
    if not (
        os.getenv("APP_SERVICE_NAME")
        and os.getenv("APP_SERVICE_PUBLISH_USER")
        and os.getenv("APP_SERVICE_PUBLISH_PASS")
    ):
        return None

    credentials = AppServicePublishCredentials(
        app_name=os.getenv("APP_SERVICE_NAME", ""),
        username=os.getenv("APP_SERVICE_PUBLISH_USER", ""),
        password=os.getenv("APP_SERVICE_PUBLISH_PASS", ""),
    )
    return AppServiceLogStreamClient(credentials)


async def _run() -> None:
    # Carregar variáveis de ambiente do .env
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()  # Tenta carregar do diretório atual

    _require_env(
        [
            "AZURE_TENANT_ID",
            "AZURE_CLIENT_ID",
            "AZURE_CLIENT_SECRET",
            "AZURE_WORKSPACE_ID",
        ]
    )

    credentials = AzureCredentials(
        tenant_id=os.getenv("AZURE_TENANT_ID", ""),
        client_id=os.getenv("AZURE_CLIENT_ID", ""),
        client_secret=os.getenv("AZURE_CLIENT_SECRET", ""),
    )
    logs_client = AzureAppInsightsClient(
        workspace_id=os.getenv("AZURE_WORKSPACE_ID", ""),
        credentials=credentials,
        app_id=os.getenv("AZURE_APP_ID"),
    )
    appservice_client = _build_appservice_client()
    server = AzureObservabilityMCPServer(
        logs_client=logs_client,
        appservice_client=appservice_client,
    )

    mcp_server = MCPProtocolServer(server)

    try:
        await mcp_server.run()
    finally:
        if appservice_client is not None:
            await appservice_client.close()
        await logs_client.close()


if __name__ == "__main__":
    asyncio.run(_run())
