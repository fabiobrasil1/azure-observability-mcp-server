"""
Pacote de tools de alto nível expostas pelo servidor MCP.

Cada módulo dentro deste pacote deve expor uma função que retorna uma lista
de `ToolDefinition` (definida em `src.mcp_server`) para serem registradas
no servidor.
"""

from src.tools.logs_tools import build_logs_tools
from src.tools.appservice_tools import build_appservice_tools

__all__ = ["build_logs_tools", "build_appservice_tools"]
