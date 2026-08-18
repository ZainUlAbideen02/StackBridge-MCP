"""Standalone automated Mock MCP Client for StackBridge MCP Server over Stdio JSON-RPC."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent


def send_message(proc: subprocess.Popen, msg: Dict[str, Any]) -> None:
    """Sends a JSON-RPC 2.0 message over subprocess stdin."""
    payload = json.dumps(msg) + "\n"
    if proc.stdin:
        proc.stdin.write(payload)
        proc.stdin.flush()


def receive_message(proc: subprocess.Popen, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
    """Reads a JSON-RPC 2.0 message line from subprocess stdout."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if proc.stdout is None:
            break
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
            continue
        line_str = line.strip()
        if not line_str:
            continue
        try:
            return json.loads(line_str)
        except json.JSONDecodeError:
            # Skip non-JSON output (such as startup logs or debug warnings)
            continue
    return None


def run_mock_client_test() -> Dict[str, Any]:
    """Executes full JSON-RPC 2.0 test lifecycle against stackbridge serve."""
    print("=" * 70)
    print("Starting StackBridge Mock MCP Client Automated E2E Test (JSON-RPC 2.0)")
    print(f"Working Directory: {REPO_ROOT}")
    print("=" * 70)

    cmd = [sys.executable, "-m", "stackbridge.main", "serve", "--transport", "stdio"]
    print(f"\n[1/6] Spawning MCP Server process: {' '.join(cmd)}")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        bufsize=1,
    )

    results: Dict[str, Any] = {}

    try:
        # Step 1: Send 'initialize' request
        print("\n[2/6] Sending 'initialize' JSON-RPC request...")
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "stackbridge-mock-client",
                    "version": "1.0.0",
                },
            },
        }
        send_message(proc, init_req)
        init_resp = receive_message(proc)
        assert init_resp is not None, "Did not receive response to 'initialize'"
        assert init_resp.get("id") == 1, f"Expected id 1, got {init_resp.get('id')}"
        init_res = init_resp.get("result", {})
        assert "capabilities" in init_res, "Response missing 'capabilities'"
        assert "serverInfo" in init_res or "server_info" in init_res, "Response missing server info"
        server_info = init_res.get("serverInfo") or init_res.get("server_info")
        print(f"Initialize OK: {server_info} | protocolVersion: {init_res.get('protocolVersion')}")
        results["initialize"] = init_res

        # Step 2: Send 'notifications/initialized'
        print("\n[3/6] Sending 'notifications/initialized'...")
        init_notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        send_message(proc, init_notif)

        # Step 3: Send 'tools/list' request
        print("\n[4/6] Sending 'tools/list' request...")
        list_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }
        send_message(proc, list_req)
        list_resp = receive_message(proc)
        assert list_resp is not None, "Did not receive response to 'tools/list'"
        assert list_resp.get("id") == 2, f"Expected id 2, got {list_resp.get('id')}"
        tools_res = list_resp.get("result", {})
        tools = tools_res.get("tools", [])
        tool_names = [t.get("name") for t in tools]
        print(f"Discovered {len(tool_names)} tools: {tool_names}")

        assert "trace_fullstack_path" in tool_names, "Tool 'trace_fullstack_path' missing"
        assert "verify_schema_change" in tool_names, "Tool 'verify_schema_change' missing"
        assert "get_route_contract" in tool_names, "Tool 'get_route_contract' missing"
        assert "get_stack_health" in tool_names, "Tool 'get_stack_health' missing"
        results["tools"] = tool_names

        # Step 4: Send 'tools/call' for 'trace_fullstack_path'
        print("\n[5/6] Sending 'tools/call' for 'trace_fullstack_path'...")
        trace_req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "trace_fullstack_path",
                "arguments": {
                    "symbol_or_path": "tests/fixtures/synthetic_fullstack/backend/routes.py::get_user_billing"
                },
            },
        }
        send_message(proc, trace_req)
        trace_resp = receive_message(proc)
        assert trace_resp is not None, "Did not receive response to 'trace_fullstack_path'"
        assert trace_resp.get("id") == 3, f"Expected id 3, got {trace_resp.get('id')}"
        trace_res = trace_resp.get("result", {})
        content_list = trace_res.get("content", [])
        assert len(content_list) > 0, "Empty content in trace_fullstack_path response"

        raw_text = content_list[0].get("text", "")
        print(f"Trace Content: {raw_text[:200]}...")
        trace_data = json.loads(raw_text) if raw_text.startswith("{") else {}

        # Assert result contains matched frontend components
        has_frontend = False
        if "UserProfile.tsx" in raw_text or "UserProfile" in raw_text or "frontend" in raw_text:
            has_frontend = True
        if trace_data.get("matched_frontend_components") or trace_data.get("affected_frontend"):
            has_frontend = True

        assert has_frontend, "No matched frontend components found in trace response"
        print(f"Frontend component match verified successfully! (Chains: {trace_data.get('chains') or trace_data.get('full_chain')})")
        results["trace"] = trace_data or raw_text

        # Step 5: Send 'tools/call' for 'get_stack_health'
        print("\n[6/6] Sending 'tools/call' for 'get_stack_health'...")
        health_req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "get_stack_health",
                "arguments": {},
            },
        }
        send_message(proc, health_req)
        health_resp = receive_message(proc)
        assert health_resp is not None, "Did not receive response to 'get_stack_health'"
        assert health_resp.get("id") == 4, f"Expected id 4, got {health_resp.get('id')}"
        health_res = health_resp.get("result", {})
        health_content = health_res.get("content", [])
        assert len(health_content) > 0, "Empty content in get_stack_health response"

        health_raw = health_content[0].get("text", "")
        health_stats = json.loads(health_raw) if health_raw.startswith("{") else {}
        print(f"Health Stats: {health_stats}")
        assert "status" in health_stats or "total_nodes" in health_stats or "routes_count" in health_stats, "Invalid health stats response"
        results["health"] = health_stats

    finally:
        # Step 6: Close stdin and wait for clean process termination
        print("\nClosing stdin and waiting for MCP server to exit cleanly...")
        if proc.stdin:
            try:
                proc.stdin.close()
            except Exception:
                pass

        try:
            proc.wait(timeout=5.0)
            print(f"MCP server exited with returncode: {proc.returncode}")
        except subprocess.TimeoutExpired:
            print("Process did not exit immediately, terminating...")
            proc.terminate()
            proc.wait(timeout=3.0)

    print("\n" + "=" * 70)
    print("ALL MOCK MCP CLIENT TESTS PASSED SUCCESSFULLY (Exit Code 0)!")
    print("=" * 70)
    return results


def main() -> None:
    try:
        run_mock_client_test()
        sys.exit(0)
    except AssertionError as err:
        print(f"\nAssertion Error in Mock MCP Client: {err}", file=sys.stderr)
        sys.exit(1)
    except Exception as err:
        print(f"\nUnexpected Exception in Mock MCP Client: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
