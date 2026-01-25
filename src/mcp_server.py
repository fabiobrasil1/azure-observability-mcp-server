"""
Módulo principal do servidor MCP para observabilidade na Azure.

Este módulo não implementa o loop MCP (stdin/stdout) ainda, mas define o
esqueleto das estruturas centrais que serão usadas pelo servidor:

- Uma estrutura de `ToolDefinition`, que descreve cada tool MCP:
  - `name`
  - `description`
  - `input_schema` (JSON Schema)
  - `handler` (função assíncrona que executa a lógica da tool)

- A classe `AzureObservabilityMCPServer`, responsável por:
  - Registrar tools (`register_tool`)
  - Listar tools em formato serializável (`list_tools`)
  - Invocar uma tool específica (`call_tool`)

Em etapas posteriores, um outro módulo ficará responsável por:

- Implementar o loop do protocolo MCP (stdin/stdout).
- Converter mensagens MCP em chamadas a `list_tools` / `call_tool`.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Callable, Awaitable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.azure_appinsights import AzureAppInsightsClient
    from src.appservice_logstream import AppServiceLogStreamClient


ToolHandler = Callable[..., Awaitable[Dict[str, Any]]]


@dataclass
class ToolDefinition:
    """
    Representa a definição de uma tool MCP em alto nível.

    Esta estrutura é um "contrato interno" entre:
    - Os módulos de domínio (ex.: `src.tools.logs_tools`) que definem as tools.
    - O servidor MCP (`AzureObservabilityMCPServer`) que faz o roteamento.

    Attributes:
        name:
            Nome único da tool MCP, por exemplo: "ai_errors_recent".
        description:
            Descrição curta, usada por clientes MCP para exibir ajuda/contexto.
        input_schema:
            Esquema JSON (JSON Schema) que descreve os parâmetros aceitos pela
            tool. Este dicionário será exposto como `inputSchema` em `list_tools`.
        handler:
            Função assíncrona que implementa a lógica da tool. Recebe os
            parâmetros já validados como argumentos nomeados e retorna um
            dicionário serializável com o resultado.
    """

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: ToolHandler


class AzureObservabilityMCPServer:
    """
    Esqueleto do servidor MCP para observabilidade na Azure.

    Este servidor mantém um registro de tools conhecidas (por nome) e expõe
    operações de alto nível para:

    - Registrar tools (ex.: `ai_errors_recent`, `ai_requests_slow`,
      `ai_trace_by_operation`).
    - Expor um método para listar tools (`list_tools`), retornando apenas
      dados serializáveis que podem ser enviados para um cliente MCP.
    - Expor um método para invocar tools (`call_tool`), recebendo um nome
      de tool e argumentos em formato de dicionário.

    A integração com o protocolo MCP em si (leitura/escrita em stdin/stdout,
    parsing/serialização de mensagens MCP) será implementada em outro módulo
    em uma etapa posterior.
    """

    def __init__(
        self,
        logs_client: Optional["AzureAppInsightsClient"] = None,
        appservice_client: Optional["AppServiceLogStreamClient"] = None,
    ) -> None:
        # Dicionário: nome_da_tool -> ToolDefinition
        self._tools: Dict[str, ToolDefinition] = {}

        if logs_client is not None:
            from src.tools.logs_tools import build_logs_tools

            for tool_def in build_logs_tools(logs_client):
                self.register_tool(tool_def)

        if appservice_client is not None:
            from src.tools.appservice_tools import build_appservice_tools

            for tool_def in build_appservice_tools(appservice_client):
                self.register_tool(tool_def)

    def register_tool(self, tool: ToolDefinition) -> None:
        """
        Registra uma tool no servidor MCP.

        Normalmente, módulos como `src.tools.logs_tools` irão construir
        instâncias de `ToolDefinition` e chamá‑lo em um ponto de bootstrap
        da aplicação.
        """
        self._tools[tool.name] = tool

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        Retorna a lista de tools em formato serializável (para MCP).

        O formato retornado segue o contrato esperado por clientes MCP:

        - `name`: nome da tool.
        - `description`: descrição curta em texto.
        - `inputSchema`: JSON Schema descrevendo os parâmetros aceitos.

        Não são retornados detalhes de implementação como o `handler` em si.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Invoca uma tool pelo nome.

        Este método é pensado para ser chamado pela camada que lida com o
        protocolo MCP. Ela fará o parsing de uma mensagem `call_tool`,
        obterá o `name` e o dicionário de `arguments`, e então chamará este
        método.

        Responsabilidades atuais:

        - Validar se a tool existe.
        - Encaminhar a chamada para o `handler` assíncrono correspondente.

        Em etapas futuras, podemos adicionar:

        - Validação de `arguments` contra `tool.input_schema`.
        - Mapeamento consistente de erros para respostas estruturadas.
        """
        if name not in self._tools:
            return {
                "error": f"Tool '{name}' não registrada",
                "availableTools": list(self._tools.keys()),
            }

        tool = self._tools[name]
        # Aqui no futuro podemos fazer validação de `arguments` vs `tool.input_schema`
        return await tool.handler(**arguments)


if __name__ == "__main__":
    # Pequeno teste manual do esqueleto (sem MCP ainda)
    import asyncio
    import os

    from src.azure_appinsights import AzureAppInsightsClient, AzureCredentials

    missing = [
        name
        for name in [
            "AZURE_TENANT_ID",
            "AZURE_CLIENT_ID",
            "AZURE_CLIENT_SECRET",
            "AZURE_WORKSPACE_ID",
        ]
        if not os.getenv(name)
    ]
    if missing:
        print("Variaveis de ambiente obrigatorias ausentes:")
        for name in missing:
            print(f"- {name}")
        print("Defina as variaveis e rode novamente.")
        raise SystemExit(1)

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
    server = AzureObservabilityMCPServer(logs_client=logs_client)

    print("Tools registradas:")
    for tool in server.list_tools():
        print(f"- {tool['name']}: {tool['description']}")

    async def _run_demo() -> None:
        result = await server.call_tool(
            "ai_errors_recent",
            {"service_name": "example-service", "timespan": "PT1H"},
        )
        print("Resultado da chamada da tool:", result)
        await logs_client.close()

    asyncio.run(_run_demo())

