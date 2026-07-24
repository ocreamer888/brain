//! Native Rust MCP server (stdio): progressive-disclosure tools proxied to `brain_api`.

use std::borrow::Cow;
use std::future::Future;
use std::sync::Arc;

use rmcp::handler::server::ServerHandler;
use rmcp::model::{
    CallToolRequestParams, CallToolResult, Content, ErrorData, JsonObject, ListToolsResult,
    PaginatedRequestParams, ServerCapabilities, ServerInfo, Tool,
};
use rmcp::service::{RequestContext, RoleServer};
use rmcp::transport;
use rmcp::ServiceExt;
use serde_json::{json, Value};

/// Tool definitions for MCP clients (used by unit tests and `tools/list`).
pub fn tool_definitions() -> Vec<Tool> {
    vec![
        Tool::new(
            "search_index",
            "Layer 1: search brain index, returns compact rows with IDs.",
            schema_search_index(),
        ),
        Tool::new(
            "timeline_tool",
            "Layer 2: get chronological context around an observation ID.",
            schema_timeline(),
        ),
        Tool::new(
            "get_observations_tool",
            "Layer 3: fetch full details for observation IDs (comma-separated).",
            schema_get_observations(),
        ),
    ]
}

fn schema_search_index() -> Arc<JsonObject> {
    Arc::new(
        json!({
            "type": "object",
            "properties": {
                "query": { "type": "string" },
                "n": { "type": "integer" },
                "memory_type": { "type": "string" },
                "project": { "type": "string" }
            },
            "required": ["query"]
        })
        .as_object()
        .expect("object")
        .clone(),
    )
}

fn schema_timeline() -> Arc<JsonObject> {
    Arc::new(
        json!({
            "type": "object",
            "properties": {
                "anchor_id": { "type": "string" },
                "before": { "type": "integer" },
                "after": { "type": "integer" }
            },
            "required": ["anchor_id"]
        })
        .as_object()
        .expect("object")
        .clone(),
    )
}

fn schema_get_observations() -> Arc<JsonObject> {
    Arc::new(
        json!({
            "type": "object",
            "properties": {
                "ids": { "type": "string", "description": "Comma-separated memory IDs" }
            },
            "required": ["ids"]
        })
        .as_object()
        .expect("object")
        .clone(),
    )
}

#[derive(Debug, Clone)]
pub struct BrainMcpServer {
    api_base: String,
    api_key: String,
}

impl BrainMcpServer {
    pub fn from_env() -> Self {
        let api_base =
            std::env::var("BRAIN_API_URL").unwrap_or_else(|_| "http://127.0.0.1:8787".into());
        let api_key = std::env::var("BRAIN_API_KEY").unwrap_or_default();
        Self {
            api_base: api_base.trim_end_matches('/').to_string(),
            api_key,
        }
    }

    fn post_blocking(base: &str, api_key: &str, path: &str, body: Value) -> Result<String, ErrorData> {
        let client = reqwest::blocking::Client::new();
        let url = format!("{}{}", base.trim_end_matches('/'), path);
        let mut req = client.post(url).json(&body);
        if !api_key.is_empty() {
            req = req.header("x-api-key", api_key);
        }
        let resp = req
            .send()
            .map_err(|e| ErrorData::internal_error(e.to_string(), None))?;
        if !resp.status().is_success() {
            let status = resp.status();
            let text = resp.text().unwrap_or_default();
            return Err(ErrorData::internal_error(
                format!("HTTP {status}: {text}"),
                None,
            ));
        }
        resp.text()
            .map_err(|e| ErrorData::internal_error(e.to_string(), None))
    }

    fn dispatch_blocking(&self, name: &str, args: &JsonObject) -> Result<CallToolResult, ErrorData> {
        let base = &self.api_base;
        let key = &self.api_key;
        match name {
            "search_index" => {
                let query = args
                    .get("query")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| ErrorData::invalid_params("missing query", None))?;
                let n = args
                    .get("n")
                    .and_then(|v| v.as_u64())
                    .map(|u| u as usize)
                    .unwrap_or(10);
                let memory_type = args
                    .get("memory_type")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty());
                let project = args
                    .get("project")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty());
                let mut body = json!({ "query": query, "n": n });
                if let Some(mt) = memory_type {
                    body["memory_type"] = json!(mt);
                }
                if let Some(p) = project {
                    body["project"] = json!(p);
                }
                let text = Self::post_blocking(base, key, "/v1/search_index", body)?;
                Ok(CallToolResult::success(vec![Content::text(text)]))
            }
            "timeline_tool" => {
                let anchor_id = args
                    .get("anchor_id")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| ErrorData::invalid_params("missing anchor_id", None))?;
                let before = args
                    .get("before")
                    .and_then(|v| v.as_u64())
                    .map(|u| u as u32)
                    .unwrap_or(3);
                let after = args
                    .get("after")
                    .and_then(|v| v.as_u64())
                    .map(|u| u as u32)
                    .unwrap_or(3);
                let body = json!({
                    "anchor_id": anchor_id,
                    "before": before,
                    "after": after,
                });
                let text = Self::post_blocking(base, key, "/v1/timeline", body)?;
                Ok(CallToolResult::success(vec![Content::text(text)]))
            }
            "get_observations_tool" => {
                let ids = args
                    .get("ids")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| ErrorData::invalid_params("missing ids", None))?;
                let id_list: Vec<String> = ids
                    .split(',')
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect();
                let body = json!({ "ids": id_list });
                let text = Self::post_blocking(base, key, "/v1/get_observations", body)?;
                Ok(CallToolResult::success(vec![Content::text(text)]))
            }
            _ => Err(ErrorData::invalid_params(
                format!("unknown tool: {name}"),
                None,
            )),
        }
    }
}

impl ServerHandler for BrainMcpServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo::new(
            ServerCapabilities::builder()
                .enable_tools()
                .build(),
        )
    }

    fn call_tool(
        &self,
        request: CallToolRequestParams,
        _: RequestContext<RoleServer>,
    ) -> impl Future<Output = Result<CallToolResult, ErrorData>> + Send + '_ {
        let this = self.clone();
        let name: Cow<'static, str> = request.name.clone();
        let args = request.arguments.clone().unwrap_or_default();
        async move {
            tokio::task::spawn_blocking(move || this.dispatch_blocking(name.as_ref(), &args))
                .await
                .map_err(|e| ErrorData::internal_error(e.to_string(), None))?
        }
    }

    fn list_tools(
        &self,
        _request: Option<PaginatedRequestParams>,
        _: RequestContext<RoleServer>,
    ) -> impl Future<Output = Result<ListToolsResult, ErrorData>> + Send + '_ {
        let tools = tool_definitions();
        std::future::ready(Ok(ListToolsResult::with_all_items(tools)))
    }
}

#[tokio::main]
async fn main() {
    if let Err(e) = run().await {
        eprintln!("brain_mcp: {e}");
        std::process::exit(1);
    }
}

async fn run() -> Result<(), String> {
    let server = BrainMcpServer::from_env();
    let (stdin, stdout) = transport::stdio();
    let running = server
        .serve((stdin, stdout))
        .await
        .map_err(|e| e.to_string())?;
    running.waiting().await.map_err(|e| e.to_string())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tool_definitions_exposes_three_progressive_disclosure_tools() {
        let names: Vec<_> = tool_definitions()
            .into_iter()
            .map(|t| t.name.to_string())
            .collect();
        assert_eq!(
            names,
            vec![
                "search_index".to_string(),
                "timeline_tool".to_string(),
                "get_observations_tool".to_string(),
            ]
        );
    }
}
