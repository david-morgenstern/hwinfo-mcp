"""HWiNFO MCP server package.

Exposes HWiNFO data on a Windows PC to Claude over the Model Context Protocol:
  * live sensors  -> read from HWiNFO Shared Memory (v2)
  * memory timings / full hardware report -> generated & parsed from HWiNFO reports
"""

__version__ = "0.1.0"
