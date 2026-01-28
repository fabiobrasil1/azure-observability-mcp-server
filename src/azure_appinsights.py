"""
Cliente para consulta ao Azure Application Insights / Azure Monitor Logs.

Responsabilidades:
- Autenticacao com Azure AD (client_credentials).
- Execucao de queries KQL contra o endpoint de Logs.
- Exposicao de metodos de alto nivel usados pelas tools MCP.
"""

from dataclasses import dataclass
import time
from typing import Any, Dict, Optional

import httpx


@dataclass
class AzureCredentials:
    """
    Credenciais necessárias para autenticar na Azure.

    Em um cenário real, esses valores devem ser carregados de variáveis de
    ambiente ou de um arquivo de configuração seguro (nunca commitados em git).
    """

    tenant_id: str
    client_id: str
    client_secret: str


class AzureAppInsightsClient:
    """
    Cliente para o endpoint de logs (KQL) do Application Insights
    / Azure Monitor Logs.
    """

    def __init__(
        self,
        workspace_id: str,
        credentials: AzureCredentials,
        app_id: Optional[str] = None,
    ) -> None:
        """
        Args:
            workspace_id: ID do Log Analytics Workspace (ou equivalente).
            credentials: Credenciais da aplicação registrada no Entra ID.
            app_id: (Opcional) ID específico da aplicação no Application Insights.
        """
        self.workspace_id = workspace_id
        self.credentials = credentials
        self.app_id = app_id
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._http = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._http.aclose()

    async def query_kql(self, query: str, timespan: str) -> Dict[str, Any]:
        """
        Executa uma query KQL contra o workspace / Application Insights.

        Args:
            query: string em Kusto Query Language.
            timespan: período no formato aceito pela API (ex.: 'PT1H', 'P1D').

        Returns:
            Dicionário com o resultado da consulta (shape a definir).
        """
        token = await self._get_access_token()
        if not token:
            return {
                "error": "Falha ao obter access token do Entra ID.",
                "query": query,
                "timespan": timespan,
            }

        url = self._build_query_url()
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"query": query}
        params = {"timespan": timespan}

        response = await self._http.post(url, headers=headers, json=payload, params=params)
        if response.status_code >= 400:
            return {
                "error": "Falha na consulta KQL.",
                "status_code": response.status_code,
                "body": response.text,
                "query": query,
                "timespan": timespan,
            }

        return response.json()

    def _build_query_url(self) -> str:
        if self.app_id:
            return f"https://api.applicationinsights.io/v1/apps/{self.app_id}/query"
        return f"https://api.loganalytics.io/v1/workspaces/{self.workspace_id}/query"

    def _get_table_name(self, base_name: str) -> str:
        """
        Retorna o nome correto da tabela baseado no endpoint usado.
        
        No endpoint do Application Insights, as tabelas são: exceptions, requests, traces, dependencies
        No endpoint do Log Analytics Workspace, as tabelas têm prefixo App: AppExceptions, AppRequests, AppTraces, AppDependencies
        
        Args:
            base_name: Nome base da tabela (ex: "exceptions", "requests", "traces", "dependencies")
            
        Returns:
            Nome correto da tabela para o endpoint atual
        """
        if self.app_id:
            # Endpoint do Application Insights usa nomes sem prefixo
            return base_name
        else:
            # Endpoint do Log Analytics Workspace usa prefixo "App"
            return f"App{base_name.capitalize()}"

    def _get_role_name_column(self) -> str:
        """
        Retorna o nome correto da coluna de role name baseado no endpoint usado.
        
        No endpoint do Application Insights, a coluna é: cloud_RoleName
        No endpoint do Log Analytics Workspace, a coluna é: AppRoleName
        
        Returns:
            Nome correto da coluna para o endpoint atual
        """
        if self.app_id:
            # Endpoint do Application Insights usa cloud_RoleName
            return "cloud_RoleName"
        else:
            # Endpoint do Log Analytics Workspace usa AppRoleName
            return "AppRoleName"

    async def _get_access_token(self) -> Optional[str]:
        now = time.time()
        if self._access_token and now < (self._expires_at - 60):
            return self._access_token

        token_url = (
            f"https://login.microsoftonline.com/{self.credentials.tenant_id}"
            "/oauth2/v2.0/token"
        )
        scope = (
            "https://api.applicationinsights.io/.default"
            if self.app_id
            else "https://api.loganalytics.io/.default"
        )
        data = {
            "client_id": self.credentials.client_id,
            "client_secret": self.credentials.client_secret,
            "grant_type": "client_credentials",
            "scope": scope,
        }
        response = await self._http.post(token_url, data=data)
        if response.status_code >= 400:
            return None

        token_payload = response.json()
        self._access_token = token_payload.get("access_token")
        expires_in = token_payload.get("expires_in", 0)
        self._expires_at = now + float(expires_in)
        return self._access_token

