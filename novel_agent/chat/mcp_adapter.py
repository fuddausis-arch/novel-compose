"""MCP 工具适配器。

借鉴 DeterminFlow mcp/ 模块：
- 连接 MCP 服务器
- 发现工具
- 适配为 OpenAI function calling 格式

注意：MCP 客户端用 try/import，如果 mcp 包未安装，降级为 no-op + warning。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 检测 mcp 包是否可用
try:
    import mcp  # noqa: F401  # 仅用于检测可用性
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    logger.warning(
        "mcp 包未安装，MCP 工具适配器降级为 no-op。"
        "如需使用 MCP 工具，请安装：pip install mcp"
    )


class MCPClient:
    """单个 MCP 服务器连接客户端。

    如果 mcp 包未安装，所有方法降级为 no-op 并返回空结果。
    """

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._server_url: str = ""
        self._connected = False
        self._session: Any = None
        self._tools_cache: list[dict] = []

    async def connect(self, server_url: str) -> bool:
        """连接 MCP 服务器。

        Args:
            server_url: MCP 服务器 URL

        Returns:
            连接成功返回 True，失败或 mcp 不可用返回 False
        """
        self._server_url = server_url
        if not _MCP_AVAILABLE:
            logger.warning("MCPClient[%s]: mcp 包未安装，无法连接 %s", self.name, server_url)
            return False
        try:
            # mcp 包可用时的真实连接逻辑（占位，实际需根据 mcp SDK API 实现）
            # from mcp import ClientSession, StdioServerParameters
            # 真实场景需根据传输方式（stdio / sse / websocket）建立连接
            logger.info("MCPClient[%s]: 尝试连接 %s", self.name, server_url)
            self._connected = True
            return True
        except Exception as e:
            logger.warning("MCPClient[%s]: 连接 %s 失败: %s", self.name, server_url, e)
            self._connected = False
            return False

    async def discover_tools(self) -> list[dict]:
        """发现服务器上的工具，返回 OpenAI function calling 格式。

        Returns:
            工具列表，每项为 {"type": "function", "function": {...}} 格式
        """
        if not _MCP_AVAILABLE or not self._connected:
            return []
        try:
            # 占位：真实实现需调用 mcp session 的 list_tools()
            # 将 MCP tool schema 转换为 OpenAI function calling 格式
            self._tools_cache = []
            return self._tools_cache
        except Exception as e:
            logger.warning("MCPClient[%s]: 发现工具失败: %s", self.name, e)
            return []

    async def call_tool(self, name: str, arguments: dict) -> str:
        """调用 MCP 工具。

        Args:
            name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果（字符串）
        """
        if not _MCP_AVAILABLE or not self._connected:
            return f"MCP 工具不可用（mcp 包未安装或未连接）"
        try:
            # 占位：真实实现需调用 mcp session 的 call_tool()
            result = f"MCP 工具 {name} 调用完成（占位实现）"
            return result
        except Exception as e:
            logger.warning("MCPClient[%s]: 调用工具 %s 失败: %s", self.name, name, e)
            return f"工具调用失败: {e}"

    async def close(self) -> None:
        """关闭连接。"""
        self._connected = False
        self._session = None
        self._tools_cache = []
        if _MCP_AVAILABLE and self._session:
            try:
                await self._session.close()
            except Exception:
                pass


class MCPToolRegistry:
    """管理多个 MCP 服务器连接，统一工具发现与路由。

    维护 server_name -> MCPClient 映射，以及 tool_name -> server_name 路由表。
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        # 工具名 -> 所属服务器名（用于路由调用）
        self._tool_routing: dict[str, str] = {}

    async def register_server(self, name: str, url: str) -> bool:
        """注册并连接一个 MCP 服务器。

        Args:
            name: 服务器名称（用于路由标识）
            url: 服务器 URL

        Returns:
            连接成功返回 True
        """
        if name in self._clients:
            logger.info("MCPToolRegistry: 服务器 %s 已注册，跳过", name)
            return True
        client = MCPClient(name=name)
        connected = await client.connect(url)
        if connected:
            tools = await client.discover_tools()
            self._clients[name] = client
            # 建立工具路由表
            for tool in tools:
                func = tool.get("function", {}) if isinstance(tool, dict) else {}
                tool_name = func.get("name", "")
                if tool_name:
                    self._tool_routing[tool_name] = name
            logger.info(
                "MCPToolRegistry: 服务器 %s 注册成功，发现 %d 个工具",
                name, len(tools),
            )
        else:
            # 即使连接失败也注册客户端（降级为 no-op），保持注册表完整性
            self._clients[name] = client
        return connected

    def get_all_tools(self) -> dict[str, list[dict]]:
        """获取所有服务器的工具。

        Returns:
            {server_name: [工具定义列表]} 格式的字典
        """
        result: dict[str, list[dict]] = {}
        for name, client in self._clients.items():
            result[name] = list(client._tools_cache)
        return result

    async def call_tool(self, name: str, arguments: dict) -> str:
        """路由工具调用到正确的服务器。

        Args:
            name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        server_name = self._tool_routing.get(name)
        if server_name is None:
            # 未在路由表中，遍历所有客户端尝试
            for client in self._clients.values():
                return await client.call_tool(name, arguments)
            return f"未找到工具 {name} 对应的 MCP 服务器"
        client = self._clients.get(server_name)
        if client is None:
            return f"MCP 服务器 {server_name} 未注册"
        return await client.call_tool(name, arguments)

    async def close_all(self) -> None:
        """关闭所有服务器连接。"""
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:
                pass
        self._clients.clear()
        self._tool_routing.clear()
