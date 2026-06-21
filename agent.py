import asyncio
import json
import logging
from datetime import datetime

import anthropic
import pytz
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from research import fetch_market_context

logger = logging.getLogger(__name__)

MCP_ENDPOINT = "https://agent.robinhood.com/mcp/trading"
MAX_ITERATIONS = 20  # safety cap on the agentic loop

# Frozen system prompt — never inject dynamic content here so prompt caching works.
# The current date/day is injected in the user kickoff message instead.
SYSTEM_PROMPT = """You are an autonomous trading agent managing a Robinhood brokerage account.

## Asset Universe
Stocks (top 20 by market cap):
AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, LLY, AVGO, JPM,
V, XOM, UNH, MA, JNJ, PG, COST, HD, MRK, NFLX

Crypto (top 20 on Robinhood):
BTC, ETH, SOL, DOGE, ADA, AVAX, LINK, LTC, XLM, BCH,
BNB, XRP, DOT, MATIC, UNI, ATOM, ALGO, VET, SHIB, NEAR

## Four Strategies (run all each session in this order)

### 1. DCA (Dollar-Cost Averaging)
- Execute only on Mondays
- Buy $10 of each asset in the universe (stocks + crypto)
- If today is not Monday, skip this strategy

### 2. Rules-Based Trading
- BUY signal: any asset in universe that is down 2%+ today → buy $100
- TAKE PROFIT: any held position up 5%+ from average cost basis → sell
- STOP LOSS: any held position down 8%+ from average cost basis → sell

### 3. Portfolio Rebalancing
- Target: 60% stocks / 40% crypto (by market value)
- Rebalance when actual allocation drifts more than 5% from target
- Use equal-weight within each asset class when rebalancing

### 4. AI-Driven Analysis
- Review current prices, position P&L, and the Market Intelligence block in the user message
- The Market Intelligence block contains: upcoming earnings dates and recent news headlines
- Identify up to 2 high-conviction opportunities not covered by strategies 1-3
- Favour assets with positive news sentiment or near-term catalysts (earnings beats, product launches, macro tailwinds)
- Avoid assets with negative news unless the dip is clearly short-term noise
- Provide explicit reasoning for each trade, citing the specific news or earnings catalyst

## Risk Rules (NON-NEGOTIABLE — apply before every order)
- Maximum $100 per single trade
- Maximum 3 trades per session total
- Always maintain at least 10% of total portfolio value as cash
- Query current positions and buying power BEFORE placing any order
- Skip a trade if it would push cash below the 10% floor

## Session Workflow
1. Query account: buying power, total portfolio value, all current positions
2. Get current prices for all universe assets
3. Run strategies 1-4 in order to generate trade signals
4. Apply risk rules — discard any signal that violates them
5. Execute the top approved trades (max 3, most impactful first)
6. Output a concise session summary: trades executed, capital deployed, reasoning"""


def _serialize_mcp_content(content_items: list) -> str:
    """Convert MCP tool result content to a plain string."""
    parts = []
    for item in content_items:
        if hasattr(item, "text"):
            parts.append(item.text)
        elif isinstance(item, dict) and "text" in item:
            parts.append(item["text"])
        else:
            parts.append(str(item))
    return "\n".join(parts) if parts else "OK"


async def run_session(config: dict) -> str:
    """Run one daily trading session: Claude + Robinhood MCP tools."""
    client = anthropic.Anthropic()
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)

    # Fetch earnings + news before opening the MCP connection so the data is
    # ready to inject into the kickoff message (no extra MCP round-trips needed).
    stocks = config.get("assets", {}).get("stocks", [])
    try:
        market_context = fetch_market_context(stocks)
        logger.info("Market context fetched (%d chars)", len(market_context))
    except Exception as exc:
        logger.warning("Market context fetch failed: %s", exc)
        market_context = ""

    context_block = (
        f"\n\n## Market Intelligence\n{market_context}" if market_context else ""
    )

    # Inject dynamic context (date/day + market intelligence) in the user message
    # — NOT the system prompt, so the cached system prompt prefix stays
    # byte-identical across sessions.
    kickoff = (
        f"Today is {now.strftime('%A, %Y-%m-%d')} at {now.strftime('%H:%M')} ET."
        f"{context_block}\n\n"
        "Run today's full trading session. "
        "Follow the workflow: query account → get prices → run all four strategies → "
        "apply risk rules → execute approved trades → output session summary."
    )

    async with streamablehttp_client(MCP_ENDPOINT) as (read, write, _):
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()

            tools_result = await mcp_session.list_tools()
            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": (
                        t.inputSchema
                        if isinstance(t.inputSchema, dict)
                        else {"type": "object", "properties": {}}
                    ),
                }
                for t in tools_result.tools
            ]
            logger.info("Discovered %d Robinhood MCP tools: %s",
                        len(tools), [t["name"] for t in tools])

            messages: list[dict] = [{"role": "user", "content": kickoff}]

            for iteration in range(1, MAX_ITERATIONS + 1):
                response = client.messages.create(
                    model="claude-opus-4-8",
                    max_tokens=8192,
                    thinking={"type": "adaptive"},
                    output_config={"effort": "high"},
                    # Cache the frozen system prompt — saves ~$0.03+ per session
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    tools=tools,
                    messages=messages,
                )

                usage = response.usage
                logger.debug(
                    "Turn %d | stop=%s | in=%d out=%d cache_read=%d cache_write=%d",
                    iteration,
                    response.stop_reason,
                    usage.input_tokens,
                    usage.output_tokens,
                    getattr(usage, "cache_read_input_tokens", 0),
                    getattr(usage, "cache_creation_input_tokens", 0),
                )

                messages.append({"role": "assistant", "content": response.content})

                if response.stop_reason == "end_turn":
                    summary = next(
                        (b.text for b in response.content if hasattr(b, "text")),
                        "Session complete.",
                    )
                    return summary

                if response.stop_reason != "tool_use":
                    logger.warning("Unexpected stop reason: %s", response.stop_reason)
                    break

                # Execute tool calls and collect results
                tool_results = []
                for block in response.content:
                    if not hasattr(block, "type") or block.type != "tool_use":
                        continue

                    logger.info("→ %s(%s)", block.name,
                                json.dumps(block.input, separators=(",", ":")))

                    try:
                        result = await mcp_session.call_tool(block.name, block.input)
                        content_str = _serialize_mcp_content(result.content)
                        logger.info("← %s", content_str[:300])
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": content_str,
                        })
                    except Exception as exc:
                        logger.error("Tool %s failed: %s", block.name, exc)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error calling {block.name}: {exc}",
                            "is_error": True,
                        })

                messages.append({"role": "user", "content": tool_results})

    return "Session ended (max iterations reached)."
