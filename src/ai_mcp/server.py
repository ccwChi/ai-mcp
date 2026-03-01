import os
import json
import logging
import requests
from pathlib import Path
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize MCP server
mcp = FastMCP("Auto-Integrations-Server")

# ====================================================
# Gemini API & Cost Tracker Setup
# ====================================================
try:
    from google import genai
except ImportError:
    genai = None

COST_TRACKER_FILE = Path("gemini_cost_tracker.json")
# Approximate pricing for gemini-1.5-pro (update based on exact model used)
COST_PER_1K_INPUT = 0.00125
COST_PER_1K_OUTPUT = 0.00375
BUDGET_LIMIT = float(os.getenv("GEMINI_BUDGET_LIMIT", "10.0"))


def load_cost() -> float:
    """Load the locally estimated spent amount."""
    if COST_TRACKER_FILE.exists():
        try:
            with open(COST_TRACKER_FILE, "r") as f:
                data = json.load(f)
                return data.get("total_spent", 0.0)
        except Exception:
            return 0.0
    return 0.0


def save_cost(spent: float):
    """Save the locally estimated spent amount."""
    with open(COST_TRACKER_FILE, "w") as f:
        json.dump({"total_spent": spent}, f)


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Calculate the cost in USD based on token counts."""
    input_cost = (input_tokens / 1000) * COST_PER_1K_INPUT
    output_cost = (output_tokens / 1000) * COST_PER_1K_OUTPUT
    return input_cost + output_cost


@mcp.tool()
def ask_gemini(prompt: str) -> str:
    """
    Send a prompt to Google Gemini.
    Automatically handles checking the $10 budget limit and falling back to the free tier (gemini-2.5-pro free) if the budget is exhausted or the paid API key fails.
    """
    if genai is None:
        return "Error: google-genai is not installed. Please install it to use Gemini."

    # .dotenv loads as string but .env file may have literal quotes, strip them
    paid_key = os.getenv("GEMINI_PAID_API_KEY", "").strip('"').strip("'")
    free_key = os.getenv("GEMINI_FREE_API_KEY", "").strip('"').strip("'")

    current_spent = load_cost()
    remaining_balance = max(0, BUDGET_LIMIT - current_spent)

    # Decide which tier to use
    use_paid = False

    # We will use paid API if balance is enough and we have a key
    if paid_key and remaining_balance > 0:
        use_paid = True

    def _call_gemini(api_key: str, model_name: str, count_cost: bool):
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )

        # Estimate cost if it's the paid tier
        if count_cost and response.usage_metadata:
            in_tokens = response.usage_metadata.prompt_token_count
            out_tokens = response.usage_metadata.candidates_token_count
            cost = estimate_cost(in_tokens, out_tokens)
            new_total = load_cost() + cost
            save_cost(new_total)
            logger.info(
                f"Paid Request: {in_tokens} in, {out_tokens} out. Cost: ${cost:5f}. Total spent: ${new_total:5f}"
            )

        return response.text

    # Attempt to use paid tier first
    if use_paid:
        try:
            logger.info(f"Using Paid Gemini API. Current spent: ${current_spent:.4f}")
            # we use gemini-1.5-pro for the paid example, you can switch if needed
            result = _call_gemini(paid_key, "gemini-1.5-pro", count_cost=True)
            return f"[Paid Tier] {result}"
        except Exception as e:
            logger.warning(
                f"Paid API failed (Quota exceeded or other error): {e}. Falling back to free tier."
            )
            # Fallback to free tier on any exception
            pass

    # Fallback / Free Tier Usage
    if not free_key:
        if not use_paid:
            return "Error: No API keys are available or budget is exceeded and there is no free fallback key."
        return "Error: Paid API request failed, and no free API key is available for fallback."

    try:
        logger.info("Using Free Gemini API Fallback.")
        # Free tier fallback using gemini-2.0-flash because it provides the 1500 requests per day free limit
        result = _call_gemini(free_key, "gemini-2.0-flash", count_cost=False)
        return f"[Free Tier Fallback] {result}"
    except Exception as e:
        return f"Error using Gemini Free Tier: {e}"


@mcp.tool()
def check_gemini_balance() -> str:
    """Check the locally estimated remaining balance for the Gemini Paid ($10 coupon) tier."""
    spent = load_cost()
    remain = BUDGET_LIMIT - spent
    if remain <= 0:
        return f"Budget Exceeded! You have spent ${spent:.4f} (Limit was ${BUDGET_LIMIT:.2f}). All requests will now fallback to the free API."
    return f"You currently have an estimated ${remain:.4f} left from your ${BUDGET_LIMIT:.2f} budget."


# ====================================================
# Telegram API Setup
# ====================================================


@mcp.tool()
def send_telegram_message(message: str) -> str:
    """Send a message to yourself via Telegram bot."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        return "Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured in .env"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}

    try:
        resp = requests.post(url, json=payload)
        resp_data = resp.json()
        if resp_data.get("ok"):
            return "Telegram message sent successfully."
        else:
            return f"Telegram API Error: {resp_data.get('description')}"
    except Exception as e:
        return f"Failed to send telegram message: {e}"


# ====================================================
# Notion API Setup
# ====================================================
try:
    from notion_client import Client as NotionClient
except ImportError:
    NotionClient = None


@mcp.tool()
def add_notion_task(title: str, content: str = "") -> str:
    """
    Add a task or note to your Notion database.
    Requires NOTION_API_KEY and NOTION_DATABASE_ID in .env
    """
    if NotionClient is None:
        return "Error: notion-client is not installed. Please install it."

    api_key = os.getenv("NOTION_API_KEY")
    db_id = os.getenv("NOTION_DATABASE_ID")

    if not api_key or not db_id:
        return "Error: NOTION_API_KEY or NOTION_DATABASE_ID not configured in .env"

    notion = NotionClient(auth=api_key)

    # A standard structure assuming default Database template "Name" as title
    new_page = {
        "parent": {"database_id": db_id},
        "properties": {
            "Name": {  # The standard default title column in Notion databases is called 'Name'
                "title": [{"text": {"content": title}}]
            }
        },
    }

    # Optionally append some page content (blocks)
    if content:
        new_page["children"] = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                },
            }
        ]

    try:
        response = notion.pages.create(**new_page)
        page_url = response.get("url")
        return f"Successfully added to Notion! Page URL: {page_url}"
    except Exception as e:
        return f"Failed to add to Notion: {e}"


def main():
    """Main entrypoint for running the MCP server."""
    logger.info("Starting AI Integrations MCP Server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
