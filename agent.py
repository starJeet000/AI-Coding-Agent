import os
import json
import time
from dotenv import load_dotenv
from groq import Groq, RateLimitError

# Load environment variables from .env file
load_dotenv()

# Initialize Groq client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Define system prompt with strict relative pathing and tool execution guardrails
SYSTEM_PROMPT = """You are an autonomous AI coding agent. 
Your task is to inspect and modify an Express.js & MongoDB application inside 'target_repo/'.

CRITICAL RULES:
1. ALWAYS use relative paths starting with 'target_repo/' (e.g., 'target_repo/app/models/note.model.js'). Never use leading slashes.
2. You MUST use the `write_file` tool to save changes to disk.
3. Keep tool calls clean and standard.

WORKFLOW:
- Use `read_file` to read existing files.
- Use `write_file` to update existing files with new functionality.
- Once files are written, output a final summary of changes made.
"""

# Tool definitions for Groq API
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at the given path. Automatically ignores node_modules and .git folders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path to list (e.g., 'target_repo/app/controllers')"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the specified relative path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative file path to read (e.g., 'target_repo/app/models/note.model.js')"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite content to a file at the specified relative path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative file path to write to (e.g., 'target_repo/app/controllers/note.controller.js')"
                    },
                    "content": {
                        "type": "string",
                        "description": "The full source code content to write into the file."
                    }
                },
                "required": ["file_path", "content"]
            }
        }
    }
]

# --- Tool Implementations ---

def list_directory(path):
    path = path.lstrip("/\\")  # Enforce relative pathing
    if not os.path.exists(path):
        return f"Error: Directory '{path}' does not exist."
    
    items = []
    for item in os.listdir(path):
        if item in ["node_modules", ".git", "__pycache__"]:
            continue
        full_path = os.path.join(path, item)
        if os.path.isdir(full_path):
            items.append(f"{item}/")
        else:
            items.append(item)
    return json.dumps(items)

def read_file(file_path):
    file_path = file_path.lstrip("/\\")  # Enforce relative pathing
    if not os.path.exists(file_path):
        return f"Error: File '{file_path}' does not exist."
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file '{file_path}': {str(e)}"

def write_file(file_path, content):
    file_path = file_path.lstrip("/\\")  # Enforce relative pathing
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote content to '{file_path}'."
    except Exception as e:
        return f"Error writing file '{file_path}': {str(e)}"

# Dispatcher mapping tool names to python functions
TOOL_MAP = {
    "list_directory": list_directory,
    "read_file": read_file,
    "write_file": write_file
}

# --- Main Agent Loop ---

def run_agent(user_prompt, max_iterations=10):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    for iteration in range(1, max_iterations + 1):
        print(f"\n--- Iteration {iteration} ---")
        
        response = None
        
        # 1. Call the Groq model with Retry & Formatting Logic
        while True:
            try:
                response = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto",
                    max_tokens=4096,
                    temperature=0.2  # Lower temperature reduces weird XML formatting attempts
                )
                break
            except RateLimitError as e:
                print("⏳ Rate limit reached. Waiting 30 seconds before retrying...")
                time.sleep(30)
            except Exception as e:
                print(f"❌ Unexpected API error occurred: {e}")
                break

        # Prevent UnboundLocalError / crash if the API request failed completely
        if response is None:
            print("⚠️ Halting execution loop due to API failure.")
            break

        response_message = response.choices[0].message
        messages.append(response_message)

        # Handle function calls if requested by the LLM
        tool_calls = response_message.tool_calls
        if tool_calls:
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                print(f"⚙️  Agent called tool: {function_name} with args: {function_args}")
                
                if function_name in TOOL_MAP:
                    tool_output = TOOL_MAP[function_name](**function_args)
                else:
                    tool_output = f"Error: Tool '{function_name}' is not supported."
                
                # Append tool execution result back to conversation history
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(tool_output)
                })
        else:
            # Agent completed task without issuing further tool calls
            print("\n✅ Agent has completed the task. Final Summary:")
            print(response_message.content)
            break

if __name__ == "__main__":
    task = """
    Improve the application so users can better organise and search their notes. 
    
    STRICT REQUIREMENTS:
    1. You MUST ONLY modify the existing `target_repo/app/models/note.model.js` and `target_repo/app/controllers/note.controller.js` files using relative paths. Do NOT create new files like `Note.js` or `NoteController.js`.
    2. Model Update: Add `tags: [String]` and `category: String` to the existing NoteSchema in `target_repo/app/models/note.model.js`. Preserve the existing `{ timestamps: true }` option.
    3. Controller Update: Modify `create` and `update` in `target_repo/app/controllers/note.controller.js` to parse and save `tags` and `category` from `req.body`.
    4. Search Logic: Modify `findAll` in `target_repo/app/controllers/note.controller.js` to accept `req.query.category` or `req.query.search` (using $or regex across title and content) to filter the notes.
    5. Maintain the existing Promise-based syntax (.then().catch()).
    """
    run_agent(task)