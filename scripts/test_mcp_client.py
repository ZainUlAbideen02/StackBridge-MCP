"""Mock MCP Client test script for StackBridge MCP Server over Stdio JSON-RPC."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "synthetic_fullstack"


async def run_mcp_client_test() -> Dict[str, Any]:
    """Connects to the StackBridge MCP server via stdio and tests all tools."""
    print("=" * 60)
    print("Starting StackBridge Mock MCP Client Test...")
    print(f"Target Fixtures Dir: {FIXTURES_DIR}")
    print("=" * 60)

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "stackbridge.mcp_server.server"],
        env=dict(os.environ),
    )

    results: Dict[str, Any] = {}

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. Initialize session
            print("\n[1/4] Initializing MCP Session...")
            init_res = await session.initialize()
            print(f"Session initialized successfully: {init_res.server_info.name} v{init_res.server_info.version}")

            # 2. List tools
            print("\n[2/4] Listing available MCP tools...")
            tools_res = await session.list_tools()
            tool_names = [t.name for t in tools_res.tools]
            print(f"Discovered {len(tool_names)} tools: {tool_names}")
            assert "trace_fullstack_path" in tool_names, "trace_fullstack_path tool missing"
            assert "get_route_contract" in tool_names, "get_route_contract tool missing"
            assert "verify_breakage" in tool_names, "verify_breakage tool missing"
            results["tools"] = tool_names

            # 3. Call trace_fullstack_path
            print("\n[3/4] Calling 'trace_fullstack_path' for BillingAccount...")
            trace_call = await session.call_tool(
                "trace_fullstack_path",
                {
                    "repo_path": str(FIXTURES_DIR),
                    "target": "backend/models.py::BillingAccount",
                },
            )
            assert trace_call.content, "Empty trace_fullstack_path response"
            trace_data = json.loads(trace_call.content[0].text)
            print(f"Trace Found: {trace_data.get('found')}")
            print(f"Full Chain: {trace_data.get('full_chain')}")
            print(f"Impacted Files: {trace_data.get('impacted_files')}")
            assert trace_data.get("found") is True
            assert len(trace_data.get("full_chain", [])) == 3
            results["trace"] = trace_data

            # 4. Call get_route_contract
            print("\n[4/4] Calling 'get_route_contract' for /api/v1/users/{user_id}/billing...")
            contract_call = await session.call_tool(
                "get_route_contract",
                {
                    "repo_path": str(FIXTURES_DIR),
                    "route_path": "/api/v1/users/{user_id}/billing",
                },
            )
            assert contract_call.content, "Empty get_route_contract response"
            contract_data = json.loads(contract_call.content[0].text)
            print(f"Route Found: {contract_data.get('found')}")
            print(f"Handler Name: {contract_data.get('handler_name')}")
            print(f"Linked Callers: {len(contract_data.get('linked_callers', []))}")
            assert contract_data.get("found") is True
            assert contract_data.get("handler_name") == "get_user_billing"
            assert len(contract_data.get("linked_callers", [])) >= 1
            results["contract"] = contract_data

            # 5. Call verify_breakage
            print("\n[Bonus] Calling 'verify_breakage' on clean repo...")
            breakage_call = await session.call_tool(
                "verify_breakage",
                {
                    "repo_path": str(FIXTURES_DIR),
                    "modified_files": {},
                },
            )
            assert breakage_call.content, "Empty verify_breakage response"
            breakage_data = json.loads(breakage_call.content[0].text)
            print(f"Breakage detected: {breakage_data.get('has_breakage')}")
            assert breakage_data.get("has_breakage") is False
            results["breakage"] = breakage_data

    print("\n" + "=" * 60)
    print("ALL MOCK MCP CLIENT TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)
    return results


def main() -> None:
    try:
        asyncio.run(run_mcp_client_test())
    except Exception as e:
        print(f"\nMock MCP Client Test Failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
