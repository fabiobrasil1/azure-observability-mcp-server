# Lista concreta de TODOs — MCP Observability Server

Execute na ordem sugerida (por etapa do roadmap). Cada item é acionável (arquivo/módulo indicado quando possível).

---

## Etapa 1 — MVP semantic tools + guardrails (~2 semanas)

- [ ] **Guards: timespan e row limit**  
  - Criar `src/guards/limits.py`: constante `TIMESPAN_MAX` (ex.: `P30D`), `ROW_LIMIT_DEFAULT` (ex.: 5000).  
  - Função `parse_and_validate_timespan(timespan: str) -> timedelta` que rejeita se > TIMESPAN_MAX.  
  - Função `apply_take(query: str, limit: int) -> str` que adiciona `| take N` no final da KQL se ainda não existir.

- [ ] **Guards: validação de argumentos**  
  - Em `src/mcp_server.py` em `call_tool`: antes de `await tool.handler(**arguments)`, validar `arguments` contra `tool.input_schema` com `jsonschema.validate()`.  
  - Adicionar `jsonschema` em `requirements.txt`.  
  - Em caso de ValidationError, retornar `{ "error": "Invalid arguments", "details": ... }` em vez de chamar o handler.

- [ ] **Models: resposta normalizada**  
  - Criar `src/models/responses.py` com função `normalize_logs_response(raw_api_result: dict, row_limit: int) -> dict` que:  
    - Extrai `tables` do formato Azure (columns + rows).  
    - Trunca `rows` a `row_limit`.  
    - Gera `summary` (texto curto, ex.: "X rows in 1 table.").  
    - Retorna `{ summary, tables, evidence: { row_count, truncated } }`.  
  - Opcional: incluir `query` e `timespan` em `evidence`.

- [ ] **Aplicar take em todas as KQL**  
  - Em `src/tools/logs_tools.py`, em cada `_kql_*`: adicionar `| take {ROW_LIMIT_DEFAULT}` (ou parâmetro `limit` passado pelo handler).  
  - Handlers devem receber `limit` (default do guards) e repassar para a função KQL.

- [ ] **Handlers retornam formato normalizado**  
  - Em `logs_tools.py`, em cada handler: após `result = await logs_client.query_kql(...)`, chamar `normalize_logs_response(result, limit)` e retornar esse dicionário (incluindo `tool`, `timespan`).  
  - Manter `query` em `evidence` ou no top-level para debug.

- [ ] **Nova tool: get_top_exceptions**  
  - Em `src/tools/logs_tools.py` (ou novo `health_tools.py`):  
  - Inputs: `service_name`, `timespan`, `limit` (default 20).  
  - KQL: agrupar por exception (problemId ou outerMessage), count, order by count desc, take limit.  
  - Registrar em `build_logs_tools` (ou em nova função `build_health_tools`) e registrar no servidor.  
  - Schema JSON com `limit` (number, default 20), validar com guards.

- [ ] **Documentar defaults e limites no README**  
  - Seção "Limites e segurança": timespan máximo (P30D), row limit (5000), e que não há KQL raw exposto.

- [ ] **Corrigir schema severity**  
  - Em `_errors_recent_schema()`: alinhar com implementação — hoje handler usa `severity: int = 3`. Manter como number e documentar no README (ex.: 1=Critical, 2=Error, 3=Warning) ou trocar para string enum no schema e no handler.

---

## Etapa 2 — Correlation + compare windows (~4–6 semanas)

- [ ] **Módulo queries/**  
  - Criar `src/queries/base.py` com helpers que recebem `client` (ou config de tabelas/colunas): `table_name(base)`, `role_column()`, `timestamp_column()`, etc.  
  - Mover/extract funções KQL de `logs_tools.py` para `src/queries/exceptions.py`, `requests.py`, `traces.py`.  
  - `logs_tools.py` importa de `queries` e chama com o client.

- [ ] **Tool trace_request(request_id)**  
  - Nova tool que busca por `operation_Id` ou por request id (conforme schema Azure); retorna mesmo formato normalizado (summary + tables + evidence).  
  - Pode reutilizar lógica de ai_trace_by_operation com filtro por request.

- [ ] **Tool correlate_failures(operation_id, timespan)**  
  - Retorna falhas (exceptions + dependency failures) correlacionadas ao operation_id.  
  - Reutilizar union de trace e filtrar por tipo exception/dependency com success=false.

- [ ] **Tool compare_windows(metric, service_name, timespan_a, timespan_b)**  
  - Criar `src/queries/compare.py`: duas agregações (uma por timespan_a, uma por timespan_b) para a métrica (request_count, error_count, duration_p95, etc.).  
  - Handler em nova tool; retorno: `value_a`, `value_b`, `delta`, `percent_change`, `summary`.

- [ ] **Outputs com percentis**  
  - Em queries de requests: adicionar opção de retornar p50/p95/p99 de duration (KQL `percentiles()`).  
  - Incluir em `normalize_logs_response` ou em campo `metrics` da resposta quando a tool for de métrica.

- [ ] **Documentar env (opcional)**  
  - README: parâmetro `env` em tools que o suportarem; por enquanto pode mapear ao único workspace/app; depois config.yaml com service/env → workspace.

---

## Etapa 3 — Anomalias, cache, auditoria, testes (8–12 semanas)

- [ ] **Tool detect_anomalies(metric, service_name, timespan, sensitivity?)**  
  - Criar `src/tools/anomaly_tools.py`.  
  - Query: série temporal (bin por tempo) para a métrica; em Python: calcular média e desvio; marcar pontos onde valor > média + sensitivity * desvio.  
  - Retorno: `summary`, `anomalies[]`, `baseline`, `evidence`.

- [ ] **Cache opcional**  
  - Criar `src/cache/memory.py`: TTL cache (ex.: 60s); chave = (tool_name, hash(args), timespan).  
  - Em `call_tool` (ou no protocol server): se cache habilitado (env) e hit, retornar cached; senão executar e armazenar.  
  - Documentar env `CACHE_ENABLED`, `CACHE_TTL_SECONDS`.

- [ ] **Auditoria**  
  - Criar `src/audit/logger.py`: função `audit_log(tool_name, params_sanitized, workspace_or_app, row_count, duration_ms)`.  
  - Chamar após cada `call_tool` bem-sucedido (params sem secrets; workspace_id ou app_id).  
  - Saída: arquivo local ou stdout estruturado (JSON-lines).

- [ ] **Testes unitários**  
  - Criar `tests/` com pytest.  
  - Mock de `httpx` / Azure API em `tests/conftest.py`.  
  - Testes para: `normalize_logs_response`, `apply_take`, `parse_and_validate_timespan`, e para cada handler (com client mockado) verificando shape da saída.

- [ ] **Contract tests**  
  - Para cada tool: teste com inputs válidos (verificar presença de `summary`, `tables` ou `metrics`); teste com inputs inválidos (verificar erro estruturado).  
  - Golden files (opcional): salvar resposta esperada para uma chamada fixa e comparar (sem dados sensíveis).

- [ ] **README: troubleshooting**  
  - Seção com erros comuns: "Falha ao obter access token" (checar tenant/client/secret), "Falha na consulta KQL" (status 400/403, row limit), "Tool não registrada" (list_tools).

---

## Manutenção e opcionais

- [ ] **query_raw_kql (se for exposta)**  
  - Default OFF (env `ALLOW_RAW_KQL=false`).  
  - Guardrails: allowlist de verbos KQL (where, project, take, order by, limit, etc.); proibir `externaldata`, `invoke`, `evaluate`; row limit rígido (ex.: 1000); sanitização de strings em argumentos.  
  - Documentar riscos no README.

- [ ] **Rate limit**  
  - Opcional: por cliente (IP ou token) ou por tool; ex.: 60 req/min por tool. Implementar em middleware ou em `call_tool`.

- [ ] **Managed Identity**  
  - Documentar e, se possível, implementar auth via Managed Identity quando rodando em Azure (VM/App Service/Function).

- [ ] **config.yaml**  
  - Suporte a múltiplos ambientes: lista de workspaces/apps e mapeamento service_name + env → workspace_id/app_id.  
  - Carregar em bootstrap e passar para client ou para camada de queries.
