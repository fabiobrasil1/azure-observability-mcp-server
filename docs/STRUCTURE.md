# Proposta de estrutura de pastas e módulos

Estrutura sugerida para evoluir o servidor MCP de observabilidade sem quebrar o que já existe, e permitir adicionar **guards**, **queries reutilizáveis**, **modelos de resposta** e **auditoria**.

---

## Visão geral

```
azure-observability-mcp-server/
  README.md
  requirements.txt
  .env.example
  config.example.yaml          # (futuro) multi-workspace / service→workspace
  docs/
    MCP_OBSERVABILITY_REVIEW.md
    STRUCTURE.md
    TODOS.md
  src/
    __init__.py
    mcp_server.py              # servidor MCP (registro + call_tool + validação)
    mcp_protocol_server.py     # JSON-RPC 2.0 stdio
    mcp_stdio_server.py        # protocolo simples JSON-lines (testes)
    cli_test.py

    auth/                      # autenticação e credenciais
      __init__.py
      credentials.py           # AzureCredentials, carregar de env/config
      # (futuro) managed_identity.py

    clients/                   # clientes de APIs externas
      __init__.py
      azure_appinsights.py     # movido de azure_appinsights.py; query_kql, tabelas
      appservice_logstream.py  # movido de appservice_logstream.py

    models/                    # contratos de entrada/saída
      __init__.py
      responses.py             # normalizar resultado API → { summary, tables, metrics, evidence }
      schemas.py                # (opcional) Pydantic/dataclasses para inputs

    queries/                   # biblioteca de KQL reutilizáveis
      __init__.py
      base.py                  # helpers: table_name(.), role_column(.), take(.)
      exceptions.py            # erros recentes, top exceptions
      requests.py              # slow requests, duration percentis
      traces.py                # trace by operation, union traces/requests/deps/exceptions
      dependencies.py          # dependency_failures
      compare.py               # compare_windows (agregações por janela)

    guards/                    # validação e limites
      __init__.py
      validation.py            # validar arguments contra JSON Schema
      limits.py                # timespan_max, row_limit_default, aplicar take(.) nas queries
      # (futuro) kql_sanitize.py se houver query_raw_kql

    tools/                     # definições MCP (ToolDefinition)
      __init__.py
      logs_tools.py            # ai_errors_recent, ai_requests_slow, ai_trace_by_operation
      appservice_tools.py      # appservice_logstream_tail
      # Novas:
      # health_tools.py         # summarize_health, get_error_rate
      # correlation_tools.py   # trace_request, correlate_failures
      # metrics_tools.py       # compare_windows
      # anomaly_tools.py       # detect_anomalies
      # (opcional) query_raw_tools.py  # query_raw_kql, default OFF, com guardrails

    cache/                     # (futuro) cache de respostas
      __init__.py
      memory.py                # in-memory TTL cache

    audit/                     # (futuro) auditoria
      __init__.py
      logger.py                # log tool name, params (mascarados), workspace, row_count
```

---

## Migração gradual

- **Fase 1:** Criar `guards/`, `models/responses.py`, e usar dentro de `tools/logs_tools.py` sem mover arquivos grandes. Manter `azure_appinsights.py` e `appservice_logstream.py` na raiz de `src/` por enquanto.
- **Fase 2:** Extrair KQL para `queries/` (funções que recebem client ou config de tabelas) e chamar de `logs_tools.py`.
- **Fase 3:** Introduzir `auth/` e `clients/` quando houver config.yaml ou segundo workspace; mover `azure_appinsights.py` para `clients/`.
- **Fase 4:** Adicionar `cache/` e `audit/` quando implementar cache e auditoria.

---

## Responsabilidades por camada

| Camada    | Responsabilidade |
|-----------|-------------------|
| **auth**  | Credenciais (env/config), token Entra ID; (futuro) Managed Identity. |
| **clients** | HTTP para Azure Logs / App Insights e App Service logstream; não monta KQL. |
| **models** | Formato de resposta normalizado (summary, tables, metrics, evidence); opcionalmente schemas de input. |
| **queries** | Montagem de KQL parametrizada (tabelas, colunas, take, filtros); sem executar. |
| **guards** | Validação de argumentos (JSON Schema), limites (timespan, row_limit), e, se existir, sanitização de KQL raw. |
| **tools**  | ToolDefinition (name, description, input_schema, handler); chama guards, queries, client, models. |
| **cache**  | Opcional; cache por (tool, hash(args), timespan) com TTL. |
| **audit**  | Opcional; log estruturado de cada chamada a tool. |

Esta estrutura suporta as novas tools (summarize_health, get_error_rate, get_top_exceptions, compare_windows, trace_request, correlate_failures, dependency_failures, detect_anomalies) e mantém um único ponto de normalização de resposta e de aplicação de limites.
