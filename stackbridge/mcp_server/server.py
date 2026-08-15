"""FastMCP / MCP Server implementation for StackBridge."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("stackbridge")


@mcp.tool()
def trace_endpoint(endpoint_path: str) -> str:
    """Traces an endpoint across frontend fetch calls, backend routes, and DB models."""
    return f"Tracing endpoint: {endpoint_path}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
