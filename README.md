# AI-MCP Project

This is a Model Context Protocol (MCP) server project written in Python.

## Directory Structure

Here is a breakdown of the standard project structure created for `ai-mcp`:

```text
ai-mcp/
├── src/
│   └── ai_mcp/             # Main Python package
│       ├── __init__.py     # Package initialization and versioning
│       └── server.py       # Core MCP server implementation using FastMCP
├── venv/                   # Python virtual environment (already created)
├── pyproject.toml          # Modern Python project configuration (hatchling)
├── requirements.txt        # Basic list of project dependencies 
├── .gitignore              # Files and directories to be ignored by Git
└── README.md               # Project documentation and structure (this file)
```

## Setup & Run Instructions

Since the virtual environment (`venv`) is already created, follow these steps:

1. **Activate the virtual environment**:
   - **Windows (PowerShell)**: `.\venv\Scripts\Activate.ps1`
   - **Windows (CMD)**: `.\venv\Scripts\activate.bat`

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   *(Alternatively, you can install the project as an editable package using `pip install -e .`)*

3. **Run the MCP server**:
   You can run the server directly:
   ```bash
   python -m ai_mcp.server
   ```
   Or since we used `pyproject.toml` to define an entry point script, if you ran `pip install -e .` you can simply run:
   ```bash
   ai-mcp
   ```

## Included Example Features

The server file (`src/ai_mcp/server.py`) includes a few examples to get you started:
- **Tool**: `@mcp.tool()` `add(a, b)` - A tool that adds two numbers.
- **Resource**: `@mcp.resource()` `get_greeting(name)` - A resource that dynamically formats a greeting.
- **Prompt**: `@mcp.prompt()` `review_code(code)` - A prompt that allows clients to request a code review.
