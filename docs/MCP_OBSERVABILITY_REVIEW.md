# Revisão: MCP de Observabilidade Azure

Documento de diagnóstico e roadmap para elevar o servidor MCP a um **MCP de observabilidade de alto valor**, com ferramentas semânticas (intenções) em vez de ser apenas um proxy de KQL.

---

## 1. Inventário do servidor MCP atual

### 1.1 Tools expostas hoje

| Tool | Fonte | Inputs | Outputs (shape atual) |
|------|--------|--------|------------------------|
| **ai_errors_recent** | `src/tools/logs_tools.py` | `service_name` (string), `timespan` (string), `severity` (number, default 3) | `{ tool, query, timespan, result }` — `result` é o JSON bruto da API Azure (tables/rows) |
| **ai_requests_slow** | `src/tools/logs_tools.py` | `service_name`, `timespan`, `duration_threshold_ms` (number) | Idem: `{ tool, query, timespan, result }` |
| **ai_trace_by_operation** | `src/tools/logs_tools.py` | `timespan` (required), `operation_id` ou `trace_id` (um dos dois) | Idem |
| **appservice_logstream_tail** | `src/tools/appservice_tools.py` | `duration_seconds` (number, default 10), `max_lines` (number, default 200), `contains` (string, optional) | `{ tool, duration_seconds, max_lines, contains, lines }` — lista de strings |

**Detalhes de código:**

- **Schemas:** `_errors_recent_schema()`, `_requests_slow_schema()`, `_trace_by_operation_schema()` em `logs_tools.py` (linhas 37–71). Em `ai_errors_recent` o schema declara `severity` como `"type": "number"` (linha 43), enquanto o README fala em string (ex.: "Error", "Critical") — inconsistência.
- **Handlers:** Cada handler chama `logs_client.query_kql(query, timespan)` e devolve o payload bruto da API dentro de `result`. Não há normalização (summary, tables, metrics, time_series, evidence).
- **KQL:** As queries são construídas em funções privadas `_kql_errors_recent`, `_kql_requests_slow`, `_kql_trace_by_operation` (logs_tools.py 128–208). Não há `take`/limit nas queries — risco de respostas muito grandes.

### 1.2 KQL raw e funções de alto nível

- **KQL raw:** Não existe tool `query_raw_kql` exposta ao MCP. O único ponto de entrada para KQL é interno: `AzureAppInsightsClient.query_kql(query, timespan)` usado pelas tools. Ou seja, hoje não há risco de usuário/agente injetar KQL arbitrário via MCP.
- **Funções de alto nível:** As três tools de logs são de “alto nível” no sentido de que recebem parâmetros semânticos (service_name, timespan, duration_threshold_ms, operation_id/trace_id) e montam a KQL internamente. Não há camada semântica explícita (service/env → workspace/app, tradutor intenção→KQL, biblioteca de queries reutilizáveis).

### 1.3 Autenticação e configuração

- **Auth:** Client credentials (OAuth2) contra Entra ID. Implementação em `azure_appinsights.py`: `_get_access_token()` (linhas 229–259), scope `https://api.applicationinsights.io/.default` ou `https://api.loganalytics.io/.default` conforme `app_id` ou workspace.
- **Onde ficam as configs:** Apenas variáveis de ambiente. Arquivo `.env.example`: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_WORKSPACE_ID`, `AZURE_APP_ID`. Para App Service logstream: `APP_SERVICE_NAME`, `APP_SERVICE_PUBLISH_USER`, `APP_SERVICE_PUBLISH_PASS`. Não há `config.yaml` nem Managed Identity — README menciona config.yaml como “futuro”.
- **Referência no código:** Bootstrap em `mcp_protocol_server.py` (`_run()`, linhas 161–220), `mcp_server.py` (`if __name__ == "__main__"`), `cli_test.py` e `mcp_stdio_server.py` — todos leem env e instanciam `AzureAppInsightsClient` e opcionalmente `AppServiceLogStreamClient`.

### 1.4 Multi-tenant / multi-workspace / multi-app

- **Estado atual:** Um único workspace ou um único app por processo. O servidor é instanciado com um único `AzureAppInsightsClient(workspace_id=..., app_id=...)`. Não há:
  - Múltiplos workspaces ou app_ids.
  - Noção de “ambiente” (dev/staging/prod) ou mapeamento service/env → workspace/app.
  - Configuração por arquivo (ex.: allowlist de workspaces).

### 1.5 Estrutura das respostas

- **Formato:** As tools de logs retornam `{ tool, query, timespan, result }` (ou equivalente). `result` é o retorno direto de `response.json()` da API Azure (ver `azure_appinsights.py` linhas 83–93): estrutura típica com `tables` (cada uma com `columns` e `rows`), sem campos adicionais como `summary`, `metrics`, `time_series`, `evidence`.
- **Protocolo MCP:** Em `mcp_protocol_server.py` (linhas 64–74), o resultado da tool é serializado como um único bloco de texto: `json.dumps(result, indent=2)` dentro de `content[0].text`. Ou seja: JSON bruto (incluindo tabelas grandes) é enviado ao agente — não há resumo curto nem evidências separadas, e não é otimizado para consumo por LLM.

---

## 2. Avaliação contra checklist “MCP bem definido”

### 2.A) Contrato de tools

| Critério | Estado | Evidência |
|----------|--------|-----------|
| Inputs tipados, validação, defaults, limites | Parcial | Schemas JSON existem; não há validação em runtime em `call_tool` (mcp_server.py 164: “Aqui no futuro podemos fazer validação”).
| Defaults | Parcial | `severity=3`, `operation_id=""`, `trace_id=""`, `duration_seconds=10`, `max_lines=200` nos handlers; não documentados nos schemas (sem `default` no JSON Schema).
| Limites (time_window máx., row limit) | Não | Nenhum `take` nas KQL; nenhum cap de timespan (ex.: máx. P30D); `max_lines` só no logstream.
| Outputs normalizados | Não | Sem estrutura estável `{ summary, tables, metrics, time_series, evidence }`; retorno é bruto da API.
| Nomenclatura e versionamento | Parcial | Nomes consistentes (ai_*); sem versão de API/tools no servidor (apenas serverInfo.version "0.1.0"). |

### 2.B) Camada semântica

| Critério | Estado | Evidência |
|----------|--------|-----------|
| Mapeamento service/env → workspace/app/table | Não | Só um workspace/app por processo; `service_name` é usado como filtro literal em KQL (cloud_RoleName/AppRoleName), não como chave de mapeamento.
| Tradutor intenção → KQL | Parcial | As tools já traduzem “erros recentes”, “requests lentas”, “trace por operation” em KQL; não há camada explícita reutilizável nem mais intenções (health, error_rate, compare_windows, anomalies).
| Biblioteca de queries reutilizáveis | Parcial | Queries em funções privadas em `logs_tools.py`; não há módulo dedicado `/queries` nem templates parametrizados.

### 2.C) Observabilidade de verdade

| Critério | Estado | Evidência |
|----------|--------|-----------|
| Requests, dependencies, exceptions, traces | Parcial | requests (slow), exceptions (recent), traces (union em trace_by_operation); dependencies entram na union mas não há tool dedicada (ex.: dependency_failures).
| Correlation (operation_Id, request_Id, traceparent) | Parcial | ai_trace_by_operation correlaciona por operation_id/trace_id; não há tool “trace_request(request_id)” nem “correlate_failures(operation_id)” explícitas.
| Comparação temporal (antes/depois), baseline, percentis | Não | Nenhuma tool compare_windows; nenhum cálculo de p50/p95/p99.
| Detecção de anomalia e explicações | Não | Nenhuma tool detect_anomalies; nenhuma heurística.

### 2.D) Segurança e governança

| Critério | Estado | Evidência |
|----------|--------|-----------|
| Least privilege, allowlist workspaces, RBAC | Parcial | Depende do App Registration no Azure; não há allowlist no código.
| Sanitização de query / KQL raw | N/A | Não há tool de KQL raw; se for adicionada, não há sanitização nem guardrails.
| Prevenção data exfiltration | Não | Sem limit de linhas nas KQL; sem auditoria do que foi consultado.
| Rate limits, timeouts, caching | Parcial | httpx timeout 30s no client (azure_appinsights.py 54); sem rate limit por cliente; sem cache.

### 2.E) UX do agente

| Critério | Estado | Evidência |
|----------|--------|-----------|
| Erros compreensíveis | Parcial | Erros da API retornados em `result.error` e body; não há mensagens padronizadas nem códigos de erro semânticos.
| Sugestões de próxima ação (next best tool) | Não | Respostas não incluem `suggested_next_tools` ou equivalente.
| Respostas LLM-friendly | Não | Resposta é JSON grande (tabelas completas); sem summary curto nem evidências destacadas.

### 2.F) Testes e confiabilidade

| Critério | Estado | Evidência |
|----------|--------|-----------|
| Testes unitários/integrados (mocks Azure) | Não | Nenhum arquivo de teste encontrado (glob test* vazio).
| Contract tests (inputs/outputs) | Não | Não há.
| Exemplos (golden files) e docs | Parcial | README com exemplos de chamada JSON-RPC; sem golden responses nem doc por tool.

---

## 3. Gap analysis

### 3.1 O que já está OK

- Três tools semânticas de logs: erros recentes, requests lentas, trace por operation_id/trace_id.
- Suporte a Application Insights (app_id) e Log Analytics (workspace_id) com colunas/tabelas corretas (`_get_table_name`, `_get_role_name_column`, etc.).
- Autenticação OAuth2 client_credentials funcionando; config via env.
- Servidor MCP JSON-RPC 2.0 com tools/list e tools/call; CLI de teste para invocar tools.
- Sem tool de KQL raw exposta — superfície de ataque menor.

### 3.2 O que falta (priorizado por impacto)

**Alto impacto (essencial para “MCP de observabilidade”):**

1. **Outputs normalizados e LLM-friendly:** Resposta estável com `summary`, `tables` (com limit), `metrics`, `evidence`, e texto curto para o agente.
2. **Limites e validação:** time_window máximo (ex.: P30D), row limit (take N) em todas as KQL, validação de arguments contra schema em `call_tool`.
3. **Novas tools semânticas:**  
   - `summarize_health(service, env, time_window)`  
   - `get_error_rate(service, env, time_window, group_by?)`  
   - `get_top_exceptions(service, env, time_window, limit)`  
   - `compare_windows(metric, service, env, window_a, window_b)`  
   - `trace_request(request_id)` / `correlate_failures(operation_id)` (pode ser alias/evolução de ai_trace_by_operation)  
   - `dependency_failures(service, env, time_window)`
4. **Camada semântica:** Mapeamento service/env → workspace (ou app); pelo menos um config (yaml/env) com lista de serviços e workspace_id/app_id por ambiente.

**Médio impacto:**

5. **Detecção de anomalias:** Tool `detect_anomalies(metric, service, env, time_window, sensitivity)` mesmo com heurística simples (ex.: desvio vs média).
6. **Percentis e baseline:** p50/p95/p99 para duration e uso em compare_windows.
7. **Erros e sugestões:** Mensagens de erro padronizadas; campo opcional `suggested_next_tools` na resposta.
8. **Guardrails se houver query_raw_kql:** Se for exposta, default desabilitado (env), allowlist de verbos KQL, row limit rígido, sanitização (ex.: sem `externaldata`, `invoke`).

**Menor impacto (governança e escala):**

9. **Rate limit / throttling** por cliente ou por tool.
10. **Cache** (ex.: por query+timespan) com TTL curto.
11. **Auditoria:** Log (local ou enviado) do que foi consultado (tool, params, workspace/app, row count).
12. **Testes:** Unitários com mocks do Azure; contract tests das tools; golden files para exemplos.

### 3.3 Riscos técnicos e de segurança

- **Respostas muito grandes:** KQL sem `take` pode devolver dezenas de milhares de linhas → timeout, memória, e péssima UX para o LLM. **Risco imediato.**
- **Timespan ilimitado:** Um agente pode pedir P365D e sobrecarregar a API e o contexto. **Risco médio.**
- **Credenciais em env:** Client secret em variável de ambiente é padrão, mas sensível; documentar uso de Managed Identity (e depois suportar) reduz risco. **Risco conhecido.**
- **Se no futuro existir `query_raw_kql`:** Sem guardrails seria **perigoso** (injeção, data exfiltration, custo). Manter default desabilitado e guardrails fortes.

---

## 4. Plano de execução incremental

### Etapa 1 — MVP semantic tools + guardrails (≈2 semanas)

**Objetivos:**

- Limites em todas as queries (timespan máx., row limit) e validação básica de argumentos.
- Resposta normalizada (summary + tables truncadas + evidências) para as tools atuais.
- Uma nova tool de “health” simples e uma de “top exceptions” para validar o padrão.

**Mudanças de código:**

- **Novos/alterados:**  
  - `src/guards/` (ou `src/validation/`): validação de timespan (ex.: máx. P30D), row_limit (ex.: 5000), e aplicação de `take` nas KQL.  
  - `src/models/responses.py` (ou similar): função que transforma resultado bruto da API em `{ summary, tables, metrics, evidence }`.  
  - `src/tools/logs_tools.py`: usar guards, aplicar take nas KQL, mapear resultado para formato normalizado.  
  - `src/mcp_server.py`: validar arguments contra input_schema (jsonschema) antes de chamar handler.
- **Novas tools (assinaturas):**  
  - `get_top_exceptions(service_name, timespan, limit=20)` → summary + tabela de top exceptions com count.  
  - (Opcional) `summarize_health(service_name, timespan)` → contagens de requests/errors/duration média (sem compare_windows ainda).

**Critérios de aceite:**

- Nenhuma query executa sem `take` (default 1000 ou 5000).
- Timespan rejeitado se > P30D (ou configurável).
- Resposta de cada tool inclui `summary` (texto curto) e `tables` (com no máximo N linhas).
- Definition of done: CLI e JSON-RPC retornam esse formato; README atualizado com exemplo.

**Exemplo de chamada e resposta esperada:**

```json
// Chamada
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_top_exceptions","arguments":{"service_name":"api","timespan":"PT1H","limit":10}}}

// Resposta esperada (estrutura)
{
  "summary": "Top 10 exceptions in the last 1 hour for service 'api'.",
  "tables": [{"columns": [...], "rows": [...]}],
  "evidence": {"row_count": 10, "truncated": false},
  "tool": "get_top_exceptions"
}
```

---

### Etapa 2 — Correlation + compare windows + melhores outputs (4–6 semanas)

**Objetivos:**

- Tools de correlação explícitas: `trace_request(request_id)`, `correlate_failures(operation_id)` (pode reutilizar/encapsular ai_trace_by_operation).
- Tool `compare_windows(metric, service, env, window_a, window_b)` para comparação temporal.
- Outputs com percentis (p50, p95, p99) onde fizer sentido (ex.: duration).
- Documentar “env” no contrato (mesmo que no início env seja opcional e mapeie ao único workspace).

**Mudanças de código:**

- **Arquivos/módulos:**  
  - `src/queries/`: mover/extract KQL para módulo (ex.: `queries/exceptions.py`, `queries/requests.py`, `queries/compare.py`).  
  - `src/tools/logs_tools.py` ou `src/tools/correlation_tools.py`: novas tools trace_request, correlate_failures.  
  - `src/tools/metrics_tools.py` (ou em logs_tools): compare_windows; queries que agregam por janela e retornam métricas.
- **Novas tools (assinaturas):**  
  - `trace_request(request_id, timespan)` → mesmo formato normalizado (summary + tables + evidence).  
  - `correlate_failures(operation_id, timespan)` → falhas correlacionadas ao operation.  
  - `compare_windows(metric, service_name, timespan_a, timespan_b)` → metric = "request_count" | "error_count" | "duration_p95" etc.; retorno com valor_a, valor_b, delta, percent_change.

**Critérios de aceite:**

- compare_windows retorna delta e percent_change para a métrica escolhida.
- Respostas de trace/correlation incluem summary + evidências (requests, dependencies, exceptions).
- Definição de “env” em README e, se possível, em config (mapeamento para workspace/app).

**Exemplo:**

```json
// compare_windows
{"name":"compare_windows","arguments":{"metric":"error_count","service_name":"api","timespan_a":"PT1H","timespan_b":"PT2H"}}
// Resposta: summary, value_a, value_b, delta, percent_change, evidence
```

---

### Etapa 3 — Anomalias, caching, auditoria, contract tests (8–12 semanas)

**Objetivos:**

- Tool `detect_anomalies(metric, service, env, time_window, sensitivity)` com heurística (ex.: pontos além de N desvios da média).
- Cache opcional (em memória ou Redis) por (tool, args hash, timespan) com TTL curto (ex.: 60s).
- Auditoria: log estruturado (tool, params, workspace/app, row_count, duration_ms).
- Testes: unitários com mocks do Azure; contract tests (inputs válidos/inválidos, shape da saída).

**Mudanças de código:**

- **Arquivos/módulos:**  
  - `src/tools/anomaly_tools.py`: detect_anomalies; uso de queries de série temporal + cálculo heurístico.  
  - `src/cache/`: wrapper de cache (interface única; implementação in-memory primeiro).  
  - `src/audit/`: logger de auditoria chamado após cada call_tool.  
  - `tests/`: pytest, mocks de httpx/Azure, contract tests por tool.
- **Novas tools:**  
  - `detect_anomalies(metric, service_name, timespan, sensitivity?)` → summary, anomalies[], baseline, evidence.

**Critérios de aceite:**

- detect_anomalies retorna lista de anomalias com timestamp e valor.
- Auditoria registra todas as chamadas a tools (sem dados sensíveis nos params, se necessário mascarar).
- Pelo menos 80% cobertura nas tools críticas; contract tests para get_error_rate, get_top_exceptions, compare_windows.

**Exemplo:**

```json
// detect_anomalies
{"name":"detect_anomalies","arguments":{"metric":"request_count","service_name":"api","timespan":"P1D","sensitivity":2}}
// Resposta: summary, anomalies: [{time, value, deviation}], baseline, evidence
```

---

## 5. Resumo dos entregáveis sugeridos

- **README “MCP Observability Server” reescrito:** configuração, lista de tools com exemplos, limites e segurança, troubleshooting (ver arquivo README proposto).
- **Proposta de estrutura de pastas:** (ver `docs/STRUCTURE.md`).
- **Lista concreta de TODOs:** (ver `docs/TODOS.md`).

Referências de código usadas nesta análise:

- Tools e schemas: `src/tools/logs_tools.py`, `src/tools/appservice_tools.py`
- Cliente e auth: `src/azure_appinsights.py`
- Servidor e call_tool: `src/mcp_server.py`, `src/mcp_protocol_server.py`
- Config: `.env.example`, bootstrap em `mcp_protocol_server.py`, `cli_test.py`
