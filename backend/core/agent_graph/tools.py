from langgraph.prebuilt import ToolNode
from backend.services.tools import tools

# Tools for LangGraph
tool_node = ToolNode(tools)
