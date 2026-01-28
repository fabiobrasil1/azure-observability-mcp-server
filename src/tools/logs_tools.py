"""
Tools MCP de alto nivel para logs do Azure Application Insights.

Estas tools sao construidas a partir de um cliente de logs (`AzureAppInsightsClient`)
e expostas ao servidor MCP como instancias de `ToolDefinition`.
"""

from typing import Any, Dict, List

from src.azure_appinsights import AzureAppInsightsClient
from src.mcp_server import ToolDefinition


def build_logs_tools(logs_client: AzureAppInsightsClient) -> List[ToolDefinition]:
    return [
        ToolDefinition(
            name="ai_errors_recent",
            description="Lista erros/exceptions recentes de um servico.",
            input_schema=_errors_recent_schema(),
            handler=_build_errors_recent_handler(logs_client),
        ),
        ToolDefinition(
            name="ai_requests_slow",
            description="Identifica requisicoes lentas acima de um limiar.",
            input_schema=_requests_slow_schema(),
            handler=_build_requests_slow_handler(logs_client),
        ),
        ToolDefinition(
            name="ai_trace_by_operation",
            description="Inspeciona o trace completo por operation_id/trace_id.",
            input_schema=_trace_by_operation_schema(),
            handler=_build_trace_by_operation_handler(logs_client),
        ),
    ]


def _errors_recent_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "service_name": {"type": "string"},
            "timespan": {"type": "string"},
            "severity": {"type": "number"},
        },
        "required": ["service_name", "timespan"],
    }


def _requests_slow_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "service_name": {"type": "string"},
            "timespan": {"type": "string"},
            "duration_threshold_ms": {"type": "number"},
        },
        "required": ["service_name", "timespan", "duration_threshold_ms"],
    }


def _trace_by_operation_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "operation_id": {"type": "string"},
            "trace_id": {"type": "string"},
            "timespan": {"type": "string"},
        },
        "required": ["timespan"],
        "anyOf": [{"required": ["operation_id"]}, {"required": ["trace_id"]}],
    }


def _build_errors_recent_handler(logs_client: AzureAppInsightsClient):
    async def _handler(
        service_name: str,
        timespan: str,
        severity: int = 3,
    ) -> Dict[str, Any]:
        query = _kql_errors_recent(service_name, severity, logs_client)
        result = await logs_client.query_kql(query=query, timespan=timespan)
        return {
            "tool": "ai_errors_recent",
            "query": query,
            "timespan": timespan,
            "result": result,
        }

    return _handler


def _build_requests_slow_handler(logs_client: AzureAppInsightsClient):
    async def _handler(
        service_name: str,
        timespan: str,
        duration_threshold_ms: float,
    ) -> Dict[str, Any]:
        query = _kql_requests_slow(service_name, duration_threshold_ms, logs_client)
        result = await logs_client.query_kql(query=query, timespan=timespan)
        return {
            "tool": "ai_requests_slow",
            "query": query,
            "timespan": timespan,
            "result": result,
        }

    return _handler


def _build_trace_by_operation_handler(logs_client: AzureAppInsightsClient):
    async def _handler(
        timespan: str,
        operation_id: str = "",
        trace_id: str = "",
    ) -> Dict[str, Any]:
        query = _kql_trace_by_operation(operation_id, trace_id, logs_client)
        result = await logs_client.query_kql(query=query, timespan=timespan)
        return {
            "tool": "ai_trace_by_operation",
            "query": query,
            "timespan": timespan,
            "result": result,
        }

    return _handler


def _kql_errors_recent(service_name: str, severity: int, logs_client: AzureAppInsightsClient) -> str:
    table_name = logs_client._get_table_name("exceptions")
    role_name_column = logs_client._get_role_name_column()
    return (
        f"{table_name}\n"
        f'| where {role_name_column} == "{service_name}"\n'
        f"| where severityLevel >= {severity}\n"
        "| project timestamp, problemId, outerMessage, operation_Id, severityLevel\n"
        "| order by timestamp desc"
    )


def _kql_requests_slow(service_name: str, duration_threshold_ms: float, logs_client: AzureAppInsightsClient) -> str:
    table_name = logs_client._get_table_name("requests")
    role_name_column = logs_client._get_role_name_column()
    return (
        f"{table_name}\n"
        f'| where {role_name_column} == "{service_name}"\n'
        f"| where duration >= {duration_threshold_ms}ms\n"
        "| project timestamp, name, url, duration, resultCode, operation_Id\n"
        "| order by duration desc"
    )


def _kql_trace_by_operation(operation_id: str, trace_id: str, logs_client: AzureAppInsightsClient) -> str:
    if operation_id:
        filter_expr = f'operation_Id == "{operation_id}"'
    elif trace_id:
        filter_expr = f'operation_Id == "{trace_id}"'
    else:
        filter_expr = "false"

    traces_table = logs_client._get_table_name("traces")
    requests_table = logs_client._get_table_name("requests")
    dependencies_table = logs_client._get_table_name("dependencies")
    exceptions_table = logs_client._get_table_name("exceptions")

    return (
        f"union {traces_table}, {requests_table}, {dependencies_table}, {exceptions_table}\n"
        f"| where {filter_expr}\n"
        "| project timestamp, itemType, name, message, duration, resultCode, operation_Id\n"
        "| order by timestamp asc"
    )
