"""
CLI simples para testar tools MCP manualmente.

Exemplo:
  python -m src.cli_test --tool ai_errors_recent --arg service_name=api --arg timespan=PT1H
  python -m src.cli_test --tool ai_requests_slow --args-json '{"service_name":"api","timespan":"PT1H","duration_threshold_ms":500}'
"""

import argparse
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
        print("Variaveis de ambiente obrigatorias ausentes:")
        for name in missing:
            print(f"- {name}")
        print("Defina as variaveis e rode novamente.")
        raise SystemExit(1)


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CLI de teste para tools MCP.")
    parser.add_argument("--tool", required=True, help="Nome da tool MCP.")
    parser.add_argument(
        "--args-json",
        default="",
        help="Argumentos em JSON (ex.: '{\"service_name\":\"api\",\"timespan\":\"PT1H\"}').",
    )
    parser.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Argumento key=value (pode repetir). Value pode ser JSON.",
    )
    return parser.parse_args(argv)


def _parse_kv_args(pairs: List[str]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Argumento invalido: {pair}. Use key=value.")
        key, raw = pair.split("=", 1)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        parsed[key] = value
    return parsed


async def _run(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
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
    try:
        return await server.call_tool(tool_name, arguments)
    finally:
        if appservice_client is not None:
            await appservice_client.close()
        await logs_client.close()


def main(argv: List[str]) -> int:
    args = _parse_args(argv)
    arguments: Dict[str, Any] = {}
    if args.args_json:
        arguments.update(json.loads(args.args_json))
    if args.arg:
        arguments.update(_parse_kv_args(args.arg))

    result = asyncio.run(_run(args.tool, arguments))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))


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
