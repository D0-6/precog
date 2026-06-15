# collectors/splunk_collector.py
import httpx
import asyncio
import logging
import urllib.parse
from config import SPLUNK_MCP_URL, SPLUNK_TOKEN
from models.schemas import SplunkSignals

logger = logging.getLogger(__name__)

# Runtime configuration overridable via /api/configure
_RUNTIME_CONFIG = {
    "url": SPLUNK_MCP_URL,
    "token": SPLUNK_TOKEN,
    "index": "*",
    "service_field": "Component",
    # AI model and response speed — overridable from Settings UI
    "ai_model": "",               # Empty = use MODEL_CHAIN[0] from config.py
    "ai_response_speed": "balanced",
    "mcp_polling_interval": 10,
}

def get_runtime_config():
    return dict(_RUNTIME_CONFIG)

def update_runtime_config(updates: dict):
    _RUNTIME_CONFIG.update(updates)

class SplunkCollector:

    def __init__(self):
        # JWT tokens use 'Bearer', not 'Splunk' prefix
        self._auth = f"Bearer {_RUNTIME_CONFIG.get('token', SPLUNK_TOKEN)}"

    async def run_query(self, spl: str) -> dict:
        """
        Execute any SPL query via Splunk REST API.
        Uses the correct 3-step Splunk REST flow:
          1. POST /services/search/jobs      → get sid
          2. Poll GET /services/search/jobs/{sid} until done
          3. GET /services/search/jobs/{sid}/results?output_mode=json
        """
        # 1. Try MCP first (fast path, 6-second timeout)
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
            import json

            mcp_base = _RUNTIME_CONFIG.get("url", SPLUNK_MCP_URL)
            if not mcp_base:
                return {"results": []}
            mcp_url = f"{mcp_base}/services/mcp"
            mcp_headers = {"Authorization": self._auth}

            async def _mcp_call():
                async with sse_client(url=mcp_url, headers=mcp_headers) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        clean = " ".join(spl.split())
                        query = clean if clean.lower().startswith("search ") else f"search {clean}"
                        result = await session.call_tool(
                            "splunk_search",
                            arguments={"query": query, "earliest_time": "-7d", "latest_time": "now"}
                        )
                        if result and hasattr(result, "content") and result.content:
                            return json.loads(result.content[0].text)
                        return None

            data = await asyncio.wait_for(_mcp_call(), timeout=6.0)
            if data is not None:
                logger.info("Splunk MCP call succeeded")
                return data
        except Exception as e:
            logger.debug(f"MCP unavailable ({type(e).__name__}), using REST API")

        # 2. Splunk REST API fallback
        base_url = _RUNTIME_CONFIG.get("url", SPLUNK_MCP_URL)
        if not base_url:
            return {"results": []}
        base = base_url.rstrip("/")
        headers = {
            "Authorization": self._auth,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # Clean SPL — collapse newlines/extra spaces
        clean_spl = " ".join(spl.split())
        search_str = clean_spl if clean_spl.lower().startswith("search ") else f"search {clean_spl}"

        try:
            async with httpx.AsyncClient(timeout=25, verify=False) as client:
                # Use oneshot to get results immediately in the response, bypassing polling
                body = urllib.parse.urlencode({
                    "search": search_str,
                    "earliest_time": "-7d",
                    "latest_time": "now",
                    "output_mode": "json",
                    "exec_mode": "oneshot"
                })
                resp = await client.post(f"{base}/services/search/jobs", headers=headers, content=body.encode())

                if resp.status_code >= 400:
                    logger.warning(f"Splunk oneshot query failed {resp.status_code}: {resp.text[:300]}")
                    return {"results": []}

                return resp.json()


        except Exception as e:
            logger.warning(f"Splunk REST query failed: {e}")
            return {"results": []}

    async def discover_services(self) -> list[str]:
        """Dynamically find all unique services in the configured index."""
        index = _RUNTIME_CONFIG.get("index", "*")
        spl = (
            f"search index={index} earliest=-15m | "
            f"eval precog_service=coalesce(Component, service, sourcetype, host, source) | "
            f"where isnotnull(precog_service) AND precog_service!=\"\" | "
            f"stats count by precog_service | "
            f"fields precog_service"
        )
        
        try:
            data = await self.run_query(spl)
            rows = data.get("results", [])
            services = [r.get("precog_service") for r in rows if r.get("precog_service")]
            if services:
                logger.info(f"Discovered {len(services)} services via dynamic precog_service: {services}")
                return services
            return []
        except Exception as e:
            logger.warning(f"Failed to discover services in Splunk: {e}")
            return []

    async def discover_schema(self, service: str) -> list[str]:
        """Dynamically discover all available fields for this service."""
        index = _RUNTIME_CONFIG.get("index", "*")
        spl = (
            f'search index={index} '
            f'(Component="{service}" OR service="{service}" OR sourcetype="{service}" OR host="{service}" OR source="{service}") | '
            f"fieldsummary | fields field"
        )
        
        try:
            data = await self.run_query(spl)
            rows = data.get("results", [])
            fields = [r.get("field") for r in rows if r.get("field") and not r.get("field").startswith("_")]
            return fields
        except Exception as e:
            logger.warning(f"Failed to discover schema for {service}: {e}")
            return []

    async def get_dynamic_telemetry(self, service: str) -> list[dict]:
        """Fetch raw sample logs containing all arbitrary fields."""
        index = _RUNTIME_CONFIG.get("index", "*")
        spl = (
            f'search index={index} '
            f'(Component="{service}" OR service="{service}" OR sourcetype="{service}" OR host="{service}" OR source="{service}") | '
            f"head 50"
        )
        
        try:
            data = await self.run_query(spl)
            return data.get("results", [])
        except Exception as e:
            logger.warning(f"Failed to get dynamic telemetry for {service}: {e}")
            return []

    async def collect_all(self, service: str) -> SplunkSignals:
        """Collect schema and generic raw telemetry."""
        fields, sample_logs = await asyncio.gather(
            self.discover_schema(service),
            self.get_dynamic_telemetry(service),
            return_exceptions=True
        )
        
        fields = fields if not isinstance(fields, Exception) else []
        sample_logs = sample_logs if not isinstance(sample_logs, Exception) else []
        
        # Build an optional anomaly summary if a level field exists
        ai_summary = "No textual anomalies calculated."
        lvl_field = _RUNTIME_CONFIG.get("level_field", "level")
        err_val = _RUNTIME_CONFIG.get("error_val", "ERROR")
        msg_field = _RUNTIME_CONFIG.get("message_field", "message")
        
        if lvl_field in fields and msg_field in fields:
            try:
                index = _RUNTIME_CONFIG.get("index", "*")
                spl = (
                    f'search index={index} {lvl_field}="{err_val}" '
                    f'(Component="{service}" OR service="{service}" OR sourcetype="{service}" OR host="{service}" OR source="{service}") | '
                    f'stats count by {msg_field} | '
                    f'sort -count | head 3'
                )
                data = await self.run_query(spl)
                rows = data.get("results", [])
                if rows:
                    top_errors = "; ".join(f"{r.get(msg_field,'?')} (x{r.get('count','?')})" for r in rows)
                    ai_summary = f"Top {err_val} messages: {top_errors}"
            except Exception:
                pass
                
        return SplunkSignals(
            discovered_fields=fields,
            sample_logs=sample_logs,
            anomaly_summary=ai_summary
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _extract_float(self, data: dict, key: str, default: float) -> float:
        try:
            rows = data.get("results", [{}])
            return float(rows[0].get(key, default)) if rows else default
        except Exception:
            return default

    def _extract_str(self, data: dict, key: str, default: str) -> str:
        try:
            rows = data.get("results", [{}])
            return str(rows[0].get(key, default)) if rows else default
        except Exception:
            return default

    def _extract_int(self, data: dict, key: str, default: int) -> int:
        try:
            rows = data.get("results", [{}])
            return int(rows[0].get(key, default)) if rows else default
        except Exception:
            return default
