# Azure Observability MCP Server

Servidor MCP (Model Context Protocol) para consultar e analisar logs de aplicações na Azure usando **Application Insights** e **Azure Monitor Logs**. O objetivo é expor **ferramentas semânticas** para um agente/LLM investigar saúde de serviços, erros, regressões e correlação de falhas **sem escrever KQL**.

---

## Arquitetura em alto nível

```
Cliente MCP (Cursor, Claude, etc.)  →  Servidor MCP  →  Tools (semânticas)  →  AzureAppInsightsClient  →  Azure Logs (KQL)
```

- O servidor expõe **tools** com parâmetros de alto nível (`service_name`, `timespan`, `operation_id`, etc.).
- As tools montam KQL internamente e chamam o cliente Azure; **não há tool de KQL raw exposta** por padrão (evita injeção e exfiltração).
- Autenticação: OAuth2 **client_credentials** (Entra ID). Configuração via **variáveis de ambiente**.

Documentação detalhada de diagnóstico e roadmap: **[docs/MCP_OBSERVABILITY_REVIEW.md](docs/MCP_OBSERVABILITY_REVIEW.md)**.

---

## Como configurar

### 1. Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

| Variável | Obrigatório | Descrição |
|----------|-------------|-----------|
| `AZURE_TENANT_ID` | Sim | Tenant do Entra ID (Azure AD). |
| `AZURE_CLIENT_ID` | Sim | Client ID do App Registration. |
| `AZURE_CLIENT_SECRET` | Sim | Client secret do App Registration. |
| `AZURE_WORKSPACE_ID` | Sim* | ID do Log Analytics Workspace (para API Log Analytics). |
| `AZURE_APP_ID` | Sim* | ID do Application Insights (para API Application Insights). |
| `APP_SERVICE_NAME` | Não | Nome do App Service (para logstream). |
| `APP_SERVICE_PUBLISH_USER` | Não | Usuário de publicação (Kudu). |
| `APP_SERVICE_PUBLISH_PASS` | Não | Senha de publicação (Kudu). |

\* É necessário **um dos dois**: `AZURE_WORKSPACE_ID` (Log Analytics) **ou** `AZURE_APP_ID` (Application Insights). O cliente usa escopos e endpoints diferentes conforme o que for informado.

### 2. Permissões no Azure

- Para **Application Insights**: App Registration com permissão **Application Insights Data Reader** (ou role equivalente) no recurso/Resource Group.
- Para **Log Analytics**: App Registration com permissão **Log Analytics Reader** no workspace.
- Princípio de least privilege: use um App Registration dedicado a leitura de logs, sem permissões de escrita ou de outros recursos.

### 3. Dependências

```bash
pip install -r requirements.txt
```

---

## Lista de tools e exemplos

As tools são listadas pelo método MCP `tools/list`. Abaixo: nome, descrição, parâmetros e exemplo de chamada.

### Logs (Application Insights / Log Analytics)

| Tool | Descrição | Parâmetros | Exemplo |
|------|-----------|------------|---------|
| **ai_errors_recent** | Lista erros/exceptions recentes de um serviço. | `service_name` (string), `timespan` (string, ex. PT1H, P1D), `severity` (number, opcional, default 3) | Ver abaixo |
| **ai_requests_slow** | Requisições lentas acima de um limiar. | `service_name`, `timespan`, `duration_threshold_ms` (number) | Ver abaixo |
| **ai_trace_by_operation** | Trace completo por operation_id ou trace_id. | `timespan` (obrigatório), `operation_id` ou `trace_id` (um dos dois) | Ver abaixo |

### App Service (log stream)

| Tool | Descrição | Parâmetros | Exemplo |
|------|-----------|------------|---------|
| **appservice_logstream_tail** | Lê o Log Stream do App Service em tempo real. | `duration_seconds` (number, default 10), `max_lines` (number, default 200), `contains` (string, opcional) | Ver abaixo |

### Exemplos de chamada (JSON-RPC 2.0)

**Listar tools:**

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
```

**Erros recentes (última 1h, serviço "api"):**

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"ai_errors_recent","arguments":{"service_name":"api","timespan":"PT1H"}}}
```

**Requests lentas (> 1s, última 2h):**

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ai_requests_slow","arguments":{"service_name":"api","timespan":"PT2H","duration_threshold_ms":1000}}}
```

**Trace por operation_id:**

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"ai_trace_by_operation","arguments":{"operation_id":"abc123","timespan":"PT24H"}}}
```

**Log stream (10s, até 50 linhas):**

```json
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"appservice_logstream_tail","arguments":{"duration_seconds":10,"max_lines":50}}}
```

### Formato da resposta (estado atual)

A resposta de `tools/call` é enviada como texto JSON no campo `content[0].text`. O conteúdo é um objeto com:

- **Tools de logs:** `tool`, `query`, `timespan`, `result`. O campo `result` contém o JSON bruto da API Azure (estrutura com `tables`, cada uma com `columns` e `rows`).  
  *Nota: em evolução para formato normalizado com `summary`, `tables` (truncadas) e `evidence` — ver [docs/MCP_OBSERVABILITY_REVIEW.md](docs/MCP_OBSERVABILITY_REVIEW.md) e [docs/TODOS.md](docs/TODOS.md).*

- **appservice_logstream_tail:** `tool`, `duration_seconds`, `max_lines`, `contains`, `lines` (array de strings).

---

## Limites e segurança

### Estado atual

- **KQL raw:** Não há tool que aceite KQL arbitrário; todas as queries são montadas internamente. Isso reduz risco de injeção e exfiltração.
- **Timespan:** Aceito como string (ex.: PT1H, P30D); **não há limite máximo** hoje — um agente pode pedir janelas muito grandes e sobrecarregar a API. Recomendação: aplicar limite (ex.: P30D) em próxima versão.
- **Quantidade de linhas:** As queries KQL atuais **não usam `take`**; a API pode retornar muitos milhares de linhas. Recomendação: adicionar `take` (ex.: 5000) e documentar o limite.
- **Credenciais:** Client secret em variável de ambiente; não commitar `.env`. Para produção em Azure, considerar Managed Identity no roadmap.
- **Multi-workspace:** Um único workspace ou app por processo; não há allowlist de workspaces no código.

### Recomendações (roadmap)

- Validação de argumentos contra JSON Schema em `call_tool`.
- Limite máximo de timespan (ex.: P30D) e row limit (ex.: 5000) em todas as queries.
- Respostas normalizadas (summary + tables truncadas) para uso por LLM.
- Se no futuro existir tool `query_raw_kql`: default desabilitado (env), allowlist de verbos KQL, row limit rígido, sanitização. Ver [docs/MCP_OBSERVABILITY_REVIEW.md](docs/MCP_OBSERVABILITY_REVIEW.md) e [docs/TODOS.md](docs/TODOS.md).

---

## Como rodar

### Servidor MCP (JSON-RPC 2.0 — recomendado para Cursor / Claude Desktop)

```bash
python -m src.mcp_protocol_server
```

O servidor lê stdin e escreve em stdout (uma linha JSON por mensagem). Configure o cliente MCP para usar esse comando como processo do servidor.

### Servidor MCP simples (JSON-lines, para testes)

```bash
python -m src.mcp_stdio_server
```

Exemplos de mensagens:

```json
{"type": "list_tools"}
{"type": "call_tool", "name": "ai_errors_recent", "arguments": {"service_name":"api","timespan":"PT1H"}}
```

### CLI de teste (sem cliente MCP)

```bash
python -m src.cli_test --tool ai_errors_recent --arg service_name=api --arg timespan=PT1H
```

Com argumentos em JSON:

```bash
python -m src.cli_test --tool ai_requests_slow --args-json '{"service_name":"api","timespan":"PT1H","duration_threshold_ms":500}'
```

---

## Troubleshooting

| Sintoma | Possível causa | Ação |
|--------|-----------------|------|
| "Variaveis de ambiente obrigatorias ausentes" | Faltam `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` ou `AZURE_CLIENT_SECRET`. | Preencher `.env` e garantir que seja carregado (diretório atual ou caminho do script). |
| "E necessario fornecer AZURE_APP_ID ou AZURE_WORKSPACE_ID" | Nenhum dos dois foi definido. | Definir um dos dois no `.env`. |
| "Falha ao obter access token do Entra ID" | Tenant/Client/Secret incorretos ou App Registration sem permissão. | Verificar valores no Azure Portal (App Registration, secrets, API permissions / RBAC no workspace ou no App Insights). |
| "Falha na consulta KQL" (status 400/403) | Query inválida ou sem permissão no recurso. | Verificar `result.body` na resposta; conferir permissão Log Analytics Reader / Application Insights Data Reader. |
| "Tool 'X' não registrada" | Nome da tool incorreto ou servidor sem o cliente correspondente. | Chamar `tools/list` e usar o nome exato; para logstream, configurar `APP_SERVICE_NAME` e credenciais de publicação. |
| Resposta muito grande / timeout | Query sem `take` e janela grande. | Reduzir timespan ou aguardar implementação de row limit (ver TODOS). |
| Log stream não retorna linhas | App Service pausado, credenciais Kudu erradas ou filtro `contains` excluindo tudo. | Verificar no Portal se o App está rodando; testar sem `contains`; checar usuário/senha de publicação. |

---

## Estrutura do projeto e próximos passos

- **Estrutura atual:** `src/` contém `mcp_server.py`, `mcp_protocol_server.py`, `azure_appinsights.py`, `appservice_logstream.py`, `tools/logs_tools.py`, `tools/appservice_tools.py`, `cli_test.py`.
- **Proposta de evolução** (pastas/módulos): [docs/STRUCTURE.md](docs/STRUCTURE.md) — inclusão de `guards/`, `queries/`, `models/`, `auth/`, etc.
- **Plano de execução e TODOs:** [docs/TODOS.md](docs/TODOS.md) — tarefas incrementais (guardrails, respostas normalizadas, novas tools semânticas, testes, auditoria).

Roadmap em 3 etapas (resumo):

1. **~2 semanas:** Limites (timespan, row limit), validação de argumentos, resposta normalizada, tool `get_top_exceptions`.
2. **4–6 semanas:** Correlation (trace_request, correlate_failures), `compare_windows`, percentis, módulo `queries/`.
3. **8–12 semanas:** `detect_anomalies`, cache opcional, auditoria, testes unitários e contract tests.

Detalhes completos em [docs/MCP_OBSERVABILITY_REVIEW.md](docs/MCP_OBSERVABILITY_REVIEW.md).
