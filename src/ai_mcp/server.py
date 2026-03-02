import os
import json
import logging
import requests
from pathlib import Path
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


# 設定基本的 logging (日誌紀錄)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 從專案根目錄的 .env 檔案載入環境變數
# 這是因為 Claude Desktop 啟動時的工作目錄不一定會在專案根目錄
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# 初始化 MCP 伺服器
mcp = FastMCP("Auto-Integrations-Server")

# ====================================================
# Gemini API 與成本追蹤器設定
# ====================================================
try:
    from google import genai
except ImportError:
    genai = None

COST_TRACKER_FILE = Path("gemini_cost_tracker.json")
# gemini-1.5-pro 的大概定價 (請根據實際使用的模型更新)
COST_PER_1K_INPUT = 0.00125
COST_PER_1K_OUTPUT = 0.00375
BUDGET_LIMIT = float(os.getenv("GEMINI_BUDGET_LIMIT", "10.0"))


def load_cost() -> float:
    """載入本地估算已花費的金額。"""
    if COST_TRACKER_FILE.exists():
        try:
            with open(COST_TRACKER_FILE, "r") as f:
                data = json.load(f)
                return data.get("total_spent", 0.0)
        except Exception:
            return 0.0
    return 0.0


def save_cost(spent: float):
    """儲存本地估算已花費的金額。"""
    with open(COST_TRACKER_FILE, "w") as f:
        json.dump({"total_spent": spent}, f)


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """根據 token 數量計算以美金 (USD) 計價的成本。"""
    input_cost = (input_tokens / 1000) * COST_PER_1K_INPUT
    output_cost = (output_tokens / 1000) * COST_PER_1K_OUTPUT
    return input_cost + output_cost


@mcp.tool()
def ask_ai(prompt: str) -> str:
    """
    發送提示詞 (prompt) 給 AI 模型。
    預設會優先使用本機的 Ollama 模型 (mannix/llama3.1-8b-abliterated:q6_k)。
    如果偵測到是 LeetCode 解題相關的問題，則會自動切換給 Google Gemini (gemini-2.5-pro) 處理。
    """
    prompt_lower = prompt.lower()
    is_leetcode = any(
        k in prompt_lower
        for k in ["leetcode", "leet code", "解題", "演算法", "algorithm"]
    )

    if not is_leetcode:
        try:
            logger.info(
                "Routing request to local Ollama (mannix/llama3.1-8b-abliterated:q6_k)..."
            )
            ollama_url = "http://localhost:11434/api/generate"
            payload = {
                "model": "mannix/llama3.1-8b-abliterated:q6_k",
                "prompt": prompt,
                "stream": False,
            }
            response = requests.post(ollama_url, json=payload, timeout=120)
            response.raise_for_status()
            result = response.json().get("response", "")
            return f"[Local Ollama] {result}"
        except Exception as e:
            logger.error(f"Local Ollama failed: {e}")
            return f"Error: 本機 Ollama 呼叫失敗！請確保 Ollama 已啟動，真正的原因是 -> {e}"

    logger.info("Detected LeetCode/Algorithm question! Routing to Gemini...")
    if genai is None:
        return "Error: google-genai is not installed. Please install it to use Gemini."

    # .dotenv 會將變數載入為字串，但 .env 檔案中可能包含引號 (") 或 (')，在這裡將它們去除
    paid_key = os.getenv("GEMINI_PAID_API_KEY", "").strip('"').strip("'")
    free_key = os.getenv("GEMINI_FREE_API_KEY", "").strip('"').strip("'")
    logger.info(f"Loaded paid_key: {paid_key}")
    logger.info(f"Loaded free_key: {free_key}")

    current_spent = load_cost()
    remaining_balance = max(0, BUDGET_LIMIT - current_spent)
    logger.info(f"remaining_balance: {remaining_balance}")

    # 決定要使用哪個等級 (付費或免費)
    use_paid = False

    # 如果有設定付費 API Key 且餘額足夠，就會使用付費 API
    if paid_key and remaining_balance > 0:
        use_paid = True

    def _call_gemini(api_key: str, model_name: str, count_cost: bool):
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )

        # 如果是付費版本，則估算成本
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

    # 優先嘗試使用付費版本
    if use_paid:
        try:
            logger.info(f"Using Paid Gemini API. Current spent: ${current_spent:.4f}")
            # 切換使用 gemini-2.5-pro 處理 LeetCode 相關問題
            result = _call_gemini(paid_key, "gemini-2.5-pro", count_cost=True)
            return f"[Paid Tier] {result}"
        except Exception as e:
            logger.error(f"Paid API failed: {e}")
            # 不要默默地降級，將錯誤訊息回傳給使用者以便除錯
            return f"Error: 付費專案 API 呼叫失敗！真正的原因是 -> {e}"

    # 備用方案 / 使用免費版本
    if not use_paid:
        logger.info(
            f"Skipping paid tier. paid_key length: {len(paid_key)}, remaining_balance: {remaining_balance}, env_path used: {env_path}"
        )
        # --- NEW DEBUG INFO RETURNED TO CLAUDE ---
        if not paid_key:
            return f"Error: 程式找不到付費 API Key！請檢查 .env 檔案路徑與內容。使用的讀取路徑為: {env_path}, 目前抓到的 paid_key 長度為 0"
        if remaining_balance <= 0:
            return f"Error: 預算已用盡 (剩餘 {remaining_balance})，因此放棄付費版 API。"

    if not free_key:
        return "Error: 無法執行任務。付費 API 失敗（或無額度），且並未設置備用的免費 API Key。"

    try:
        logger.info("Using Free Gemini API Fallback.")
        # 免費備用方案使用 gemini-2.0-flash，因為它提供每天 1500 次的免費請求額度
        result = _call_gemini(free_key, "gemini-2.0-flash", count_cost=False)
        return f"[Free Tier Fallback] {result}"
    except Exception as e:
        return f"Error using Gemini Free Tier: {e}"


@mcp.tool()
def check_gemini_balance() -> str:
    """檢查 Gemini 付費版 ($10 美金優惠券) 在本地估算的剩餘餘額。"""
    spent = load_cost()
    remain = BUDGET_LIMIT - spent
    if remain <= 0:
        return f"Budget Exceeded! You have spent ${spent:.4f} (Limit was ${BUDGET_LIMIT:.2f}). All requests will now fallback to the free API."
    return f"You currently have an estimated ${remain:.4f} left from your ${BUDGET_LIMIT:.2f} budget."


# ====================================================
# Telegram API 設定
# ====================================================


@mcp.tool()
def send_telegram_message(message: str) -> str:
    """透過 Telegram bot 發送訊息給自己。"""
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
# Notion API 設定
# ====================================================
try:
    from notion_client import Client as NotionClient
except ImportError:
    NotionClient = None


@mcp.tool()
def add_notion_task(title: str, content: str = "") -> str:
    """
    在你的 Notion 資料庫中新增一筆任務或筆記。
    需要在 .env 檔案中設定 NOTION_API_KEY 與 NOTION_DATABASE_ID
    """
    if NotionClient is None:
        return "Error: notion-client is not installed. Please install it."

    api_key = os.getenv("NOTION_API_KEY")
    db_id = os.getenv("NOTION_DATABASE_ID")

    if not api_key or not db_id:
        return "Error: NOTION_API_KEY or NOTION_DATABASE_ID not configured in .env"

    notion = NotionClient(auth=api_key)

    # 標準結構假設預設的 Database 模板標題欄位是 "Name"
    new_page = {
        "parent": {"database_id": db_id},
        "properties": {
            "Name": {  # Notion 資料庫中標準預設的標題欄位名稱為 'Name'
                "title": [{"text": {"content": title}}]
            }
        },
    }

    # 選擇性地附加一些頁面內容 (blocks)
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
    """執行 MCP 伺服器的主要進入點。"""
    logger.info("Starting AI Integrations MCP Server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
