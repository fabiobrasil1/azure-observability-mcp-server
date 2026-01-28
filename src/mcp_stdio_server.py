"""
Servidor MCP minimalista via stdin/stdout.

Protocolo simples por linhas JSON:
- {"type": "list_tools"}
- {"type": "call_tool", "name": "...", "arguments": {...}}

Respostas:
- {"type": "list_tools_result", "tools": [...]}
- {"type": "call_tool_result", "result": {...}}
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

from src.azure_appinsights import AzureAppInsightsClient, AzureCredentials
from src.appservice_logstream import (
    AppServiceLogStreamClient,
    AppServicePublishCredentials,
)
from src.mcp_server import AzureObservabilityMCPServer


def _require_env(names: List[str]) -> None:
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        _write_json(
            {
                "type": "error",
                "message": "Variaveis de ambiente obrigatorias ausentes.",
                "missing": missing,
            }
        )
        raise SystemExit(1)


def _write_json(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


async def _handle_messages(server: AzureObservabilityMCPServer) -> None:
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break

        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _write_json({"type": "error", "message": "JSON invalido."})
            continue

        msg_type = msg.get("type")
        if msg_type == "list_tools":
            _write_json({"type": "list_tools_result", "tools": server.list_tools()})
            continue

        if msg_type == "call_tool":
            name = msg.get("name", "")
            arguments = msg.get("arguments", {})
            result = await server.call_tool(name, arguments)
            _write_json({"type": "call_tool_result", "result": result})
            continue

        _write_json({"type": "error", "message": "Tipo de mensagem desconhecido."})


async def _run() -> None:
    # Carregar variáveis de ambiente do .env
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()  # Tenta carregar do diretório atual

    # Validar variáveis obrigatórias
    _require_env(
        [
            "AZURE_TENANT_ID",
            "AZURE_CLIENT_ID",
            "AZURE_CLIENT_SECRET",
        ]
    )
    
    # Validar que temos AZURE_APP_ID OU AZURE_WORKSPACE_ID
    app_id = os.getenv("AZURE_APP_ID")
    workspace_id = os.getenv("AZURE_WORKSPACE_ID")
    
    if not app_id and not workspace_id:
        _write_json(
            {
                "type": "error",
                "message": "E necessario fornecer AZURE_APP_ID ou AZURE_WORKSPACE_ID.",
            }
        )
        raise SystemExit(1)

    credentials = AzureCredentials(
        tenant_id=os.getenv("AZURE_TENANT_ID", ""),
        client_id=os.getenv("AZURE_CLIENT_ID", ""),
        client_secret=os.getenv("AZURE_CLIENT_SECRET", ""),
    )
    logs_client = AzureAppInsightsClient(
        workspace_id=workspace_id or "",
        credentials=credentials,
        app_id=app_id,
    )
    appservice_client = _build_appservice_client()
    server = AzureObservabilityMCPServer(
        logs_client=logs_client,
        appservice_client=appservice_client,
    )
    try:
        await _handle_messages(server)
    finally:
        if appservice_client is not None:
            await appservice_client.close()
        await logs_client.close()


if __name__ == "__main__":
    asyncio.run(_run())


def _build_appservice_client() -> AppServiceLogStreamClient | None:
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
