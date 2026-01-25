## Azure Observability MCP Server

Servidor MCP (Model Context Protocol) para consultar e analisar logs de aplicações .NET/Node/Java/etc. rodando na Azure, usando **Application Insights** / **Azure Monitor Logs** como fonte de dados.

O objetivo é permitir que um cliente MCP (ex.: Cursor, Claude Desktop) faça perguntas em linguagem natural sobre o comportamento das aplicações, e que este servidor traduza essas perguntas em consultas KQL e agregações de logs.

### Objetivo

- Expor, via MCP, ferramentas que permitam:
  - **Buscar logs** (traces, requests, exceptions) por período.
  - **Filtrar erros recentes** de um serviço específico.
  - **Inspecionar uma requisição** completa a partir de `operation_Id` / `traceId`.
  - (Futuro) **Combinar logs** com outras fontes de observabilidade da Azure (metrics, alerts, etc.).

---

### Arquitetura em alto nível

- **Cliente MCP (ex.: Cursor)**  
  - Envia requisições `list_tools` e `call_tool` para este servidor via protocolo MCP (stdin/stdout).

- **Servidor MCP (`AzureObservabilityMCPServer`)**
  - Mantém um registro de tools (`ToolDefinition`).
  - Responde a `list_tools` com o catálogo de tools disponíveis.
  - Encaminha `call_tool` para o handler assíncrono de cada tool.

- **Camada de domínio / tools de logs (`src/tools`)**
  - Implementa funções de alto nível como:
    - `ai_errors_recent`
    - `ai_requests_slow`
    - `ai_trace_by_operation`
    - `appservice_logstream_tail`
  - Cada função é exposta como uma **tool MCP**, com:
    - `name`
    - `description`
    - `inputSchema` (JSON Schema compatível com MCP)
    - `handler` (função async que chama o cliente de logs).

- **Cliente de logs Azure (`AzureAppInsightsClient`)**
  - Encapsula:
    - Autenticação via OAuth2 (client_credentials) com Entra ID.
    - Execução de queries KQL contra Application Insights / Log Analytics.
  - Expõe métodos de uso interno, por exemplo:
    - `query_kql(query: str, timespan: str)`
    - (Futuro) Helpers específicos, como `get_recent_errors(...)`, `get_slow_requests(...)`.

Fluxo simplificado:

```text
Cliente MCP --> Servidor MCP (this repo) --> Tools de logs --> AzureAppInsightsClient --> Azure Logs (KQL)
```

---

### Stack técnica (planejada)

- **Linguagem**: Python 3.10+
- **HTTP client**: `httpx` (async)
- **Configuração**:
  - Variáveis de ambiente (tenant, client_id, client_secret, workspace_id, etc.).
  - (Futuro) Arquivo `config.yaml` para facilitar múltiplos ambientes.
- **Autenticação Azure**: OAuth2 (client_credentials) contra Entra ID.
- **Protocolo**: MCP (Model Context Protocol) via stdin/stdout (fase posterior).

---

### Estrutura inicial (proposta)

```text
azure-observability-mcp-server/
  README.md
  requirements.txt
  .gitignore
  src/
    __init__.py
    mcp_server.py          # servidor MCP principal (registro + invocação de tools)
    azure_appinsights.py   # cliente para Application Insights / Logs (KQL)
    tools/
      __init__.py          # contrato: expor funções que retornam listas de ToolDefinition
      logs_tools.py        # tools de alto nível (erros recentes, requests lentas, trace by operation)
```

---

### Contrato das tools MCP (draft)

Cada tool MCP será representada por um `ToolDefinition` com o seguinte shape:

```python
ToolDefinition(
    name: str,
    description: str,
    input_schema: Dict[str, Any],  # JSON Schema
    handler: Callable[..., Awaitable[Dict[str, Any]]],
)
```

O método `list_tools()` do servidor MCP retornará uma lista serializável com:

- `name`: nome da tool, ex.: `"ai_errors_recent"`.
- `description`: descrição curta em texto.
- `inputSchema`: objeto JSON Schema descrevendo os campos aceitos pela tool.

O método `call_tool(name, arguments)`:

- Recebe o nome da tool e um dicionário `arguments` (já validado pelo cliente MCP).
- Localiza o `ToolDefinition` correspondente.
- Chama `await tool.handler(**arguments)`.
- Retorna um dicionário com o resultado (erro ou dados de logs agregados).

---

### Tools planejadas (primeira fase)

1. **`ai_errors_recent`**
   - **Objetivo**: listar erros/exceptions recentes de um serviço.
   - **Inputs (draft)**:
     - `service_name: string` (ex.: nome do roleName, cloud_RoleName, etc.).
     - `timespan: string` (ex.: `"PT1H"`, `"P1D"`).
     - (Opcional) `severity: string` (ex.: `"Error"`, `"Critical"`).
   - **Output (draft)**:
     - Lista de erros com timestamp, mensagem, operação, e alguns campos de contexto.

2. **`ai_requests_slow`**
   - **Objetivo**: identificar requisições lentas acima de um certo limiar.
   - **Inputs (draft)**:
     - `service_name: string`
     - `timespan: string`
     - `duration_threshold_ms: number` (ex.: `1000` para 1 segundo).
   - **Output (draft)**:
     - Lista de requisições lentas (url, duration, timestamp, statusCode, operation_Id).

3. **`ai_trace_by_operation`**
   - **Objetivo**: inspecionar o “trace completo” de uma operação.
   - **Inputs (draft)**:
     - `operation_id: string` ou `trace_id: string`.
     - `timespan: string` (para limitar o escopo da busca).
   - **Output (draft)**:
     - Estrutura agregada com:
       - Request principal.
       - Dependências (chamadas externas).
       - Exceptions associadas.
       - Logs/traces correlacionados.

4. **`appservice_logstream_tail`**
   - **Objetivo**: ler o Log Stream do App Service em tempo real.
   - **Inputs (draft)**:
     - `duration_seconds: number` (ex.: `10`)
     - `max_lines: number` (ex.: `200`)
     - `contains: string` (opcional, filtro por substring)
   - **Output (draft)**:
     - Lista de linhas de log coletadas no intervalo.

Esses contratos ainda são rascunhos (“draft”) e podem ser ajustados conforme formos testando com dados reais.

---

### Plano de implementação por fases

1. **Fase 1 — Esqueleto (status: em andamento)**
   - Definir `AzureObservabilityMCPServer` com:
     - Registro de tools (`register_tool`).
     - Listagem (`list_tools`).
     - Invocação (`call_tool`).
   - Definir esqueleto do `AzureAppInsightsClient` (sem chamada real à API).
   - Definir pacote `tools` e contrato básico para `logs_tools.py`.

2. **Fase 2 — Cliente de logs stub + tools iniciais**
   - Implementar `AzureAppInsightsClient.query_kql` ainda como stub (retorno fake), para permitir desenvolver o shape das respostas.
   - Implementar `logs_tools.py` chamando o stub e retornando estruturas de dados de alto nível.
   - Registrar as tools iniciais (`ai_errors_recent`, `ai_requests_slow`, `ai_trace_by_operation`) no servidor MCP.

3. **Fase 3 — Integração real com Azure**
   - Implementar autenticação OAuth2 client_credentials via `httpx`.
   - Implementar chamada real ao endpoint de Logs (KQL) do Application Insights / Log Analytics.
   - Ajustar as queries KQL das tools para refletir a estrutura de dados real dos workspaces.

4. **Fase 4 — Integração com um cliente MCP**
   - Implementar o loop MCP via stdin/stdout.
   - Testar o servidor plugado em um cliente MCP (Cursor / Claude Desktop).
   - Refinar descriptions, schemas e formatos de resposta com base no uso real.

5. **Fase 5 — Extensões futuras**
   - Suporte a múltiplos workspaces / subscriptions.
   - Combinar logs com métricas e alertas.
   - Adicionar ferramentas de “health overview” e “sLO/SLA checks”.

---

### Como rodar (teste local)

1) Configure as variáveis de ambiente (veja `.env.example`):

```
AZURE_TENANT_ID=...
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
AZURE_WORKSPACE_ID=...
AZURE_APP_ID=...  # opcional
APP_SERVICE_NAME=...  # opcional (para logstream)
APP_SERVICE_PUBLISH_USER=...
APP_SERVICE_PUBLISH_PASS=...
```

2) Teste rápido com o script CLI:

```bash
python -m src.cli_test --tool ai_errors_recent --arg service_name=api --arg timespan=PT1H
```

Exemplo para o logstream do App Service:

```bash
python -m src.cli_test --tool appservice_logstream_tail --arg duration_seconds=10 --arg max_lines=50
```

3) Rodar o servidor MCP via stdin/stdout (protocolo simples por JSON-lines):

```bash
python -m src.mcp_stdio_server
```

Exemplos de mensagens:

```json
{"type": "list_tools"}
{"type": "call_tool", "name": "ai_errors_recent", "arguments": {"service_name":"api","timespan":"PT1H"}}
```

