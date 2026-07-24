//! Integration: spawn `brain_api` + `brain_user_prompt_submit` and assert the hook
//! reaches the HTTP API and prints the context header when search returns hits.

use std::net::TcpListener;
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::json;

struct KillChild(std::process::Child);

impl Drop for KillChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn wait_for_health(base: &str, deadline: Duration) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;
    let url = format!("{}/health", base.trim_end_matches('/'));
    let start = Instant::now();
    while start.elapsed() < deadline {
        if client.get(&url).send().map(|r| r.status().is_success()).unwrap_or(false) {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(50));
    }
    Err(format!("brain_api did not become healthy within {deadline:?}"))
}

#[test]
fn user_prompt_submit_hook_hits_brain_api_and_prints_context_header() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db_path = dir.path().join("hook_it.db");

    let sock = TcpListener::bind("127.0.0.1:0").expect("bind ephemeral");
    let port = sock.local_addr().unwrap().port();
    drop(sock);

    let base = format!("http://127.0.0.1:{port}");
    let bind = format!("127.0.0.1:{port}");

    let _api = KillChild(
        Command::new(env!("CARGO_BIN_EXE_brain_api"))
            .env("BRAIN_DB_PATH", db_path.to_string_lossy().as_ref())
            .env("BRAIN_EMBEDDER", "mock")
            .env("BRAIN_API_BIND", &bind)
            .env("BRAIN_API_KEY", "")
            .env("BRAIN_API_AUTH_REQUIRED", "0")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn brain_api"),
    );

    wait_for_health(&base, Duration::from_secs(15)).expect("health");

    let client = reqwest::blocking::Client::new();
    let phrase = "HOOK_INTEGRATION_UNIQUE_PHRASE_XYZZY";
    let save_body = json!({
        "content": phrase,
        "memory_type": "decision",
        "project": "general"
    });
    let save_res = client
        .post(format!("{}/save", base.trim_end_matches('/')))
        .json(&save_body)
        .send()
        .expect("save");
    assert!(
        save_res.status().is_success(),
        "save failed: {}",
        save_res.text().unwrap_or_default()
    );

    let hook_payload = json!({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "it-session",
        "prompt": phrase,
        "cwd": "/tmp"
    });

    let out = Command::new(env!("CARGO_BIN_EXE_brain_user_prompt_submit"))
        .env("BRAIN_API_URL", &base)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .and_then(|mut child| {
            use std::io::Write;
            child
                .stdin
                .as_mut()
                .unwrap()
                .write_all(hook_payload.to_string().as_bytes())?;
            child.wait_with_output()
        })
        .expect("hook run");

    assert!(out.status.success(), "hook exited {:?}", out.status);

    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        stdout.contains("### Relevant prior context"),
        "expected context header in stdout, got: {stdout:?}"
    );
}
