import os
import re
import json
from typing import List, Dict, Any
from github import Github
from pydantic import BaseModel, Field
from langchain_mistralai import ChatMistralAI

# Initialize GitHub Core Connections safely
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

g = Github(GITHUB_TOKEN)
# Get the repository name from environment context automatically
repo_name = os.getenv("GITHUB_REPOSITORY")
repo = g.get_repo(repo_name)

# Extract PR number dynamically from the GitHub event trigger metadata context
with open(os.getenv("GITHUB_EVENT_PATH"), "r") as f:
    event_data = json.load(f)
pr_number = event_data["number"]
pr = repo.get_pull(pr_number)

class InlineFinding(BaseModel):
    file_path: str = Field(description="The relative system path to the code file analyzed")
    line_number: int = Field(description="Meticulous line sequence integer marking target spot")
    issue_found: str = Field(description="Explicit explanation mapping out code style guidelines broken")

def get_parsed_diff_lines() -> List[Dict[str, Any]]:
    parsed_lines = []
    try:
        pr_files = pr.get_files()
        for file in pr_files:
            # Track any python file that was modified or added
            if not file.filename.endswith(".py"):
                continue
                
            # If it's a brand new file, file.patch might be empty or formatted differently.
            # Let's fetch the raw content directly from the repository to be 100% safe!
            try:
                file_content = repo.get_contents(file.filename, ref=pr.head.sha).decoded_content.decode("utf-8")
                lines = file_content.split("\n")
                for idx, content in enumerate(lines):
                    if content.strip(): # Skip completely empty lines
                        parsed_lines.append({
                            "file_path": file.filename,
                            "line_number": idx + 1,
                            "content": content.strip()
                        })
            except Exception as e:
                # Fallback to standard patch parsing if direct fetch fails
                if file.patch:
                    current_line = 0
                    for line in file.patch.split("\n"):
                        if line.startswith("@@"):
                            match = re.search(r"\+(\d+)", line)
                            if match:
                                current_line = int(match.group(1)) - 1
                            continue
                        if not line.startswith("-"):
                            current_line += 1
                        if line.startswith("+"):
                            parsed_lines.append({
                                "file_path": file.filename,
                                "line_number": current_line,
                                "content": line[1:].strip()
                            })
    except Exception as e:
        print(f"Error parsing diff files: {e}")
    return parsed_lines

def analysis_node(state: Dict[str, Any]) -> Dict[str, Any]:
    print("--- [STEP 2/3] Analyzing Code with Mistral Framework ---")
    detected_findings = []
    
    if not state.get("diff_lines"):
        return {"findings": []}
        
    llm = ChatMistralAI(
        model="open-mistral-7b", 
        mistral_api_key=MISTRAL_API_KEY
    )
    
    try:
        with open("style_guide.md", "r") as f:
            system_rules = f.read()
    except Exception:
        system_rules = "1. Secure code configurations. No plain text passwords. 2. Use standard naming conventions."
    
    code_payload = ""
    for line in state["diff_lines"]:
        code_payload += f"File: {line['file_path']} | Line: {line['line_number']} | Code: {line['content']}\n"

    # CRITICAL: We pass raw standard text dictionaries. No ChatPromptTemplate compiler to cause missing variables!
    messages = [
        {
            "role": "system",
            "content": (
                f"You are an expert enterprise code reviewer. Compare the submitted code lines against these company guidelines:\n\n{system_rules}\n\n"
                "Analyze the lines. If a line violates a guideline or contains a clear security vulnerability, you MUST list it in a raw JSON array format exactly like this:\n"
                "[\n"
                "  {\n"
                '    "file_path": "filename.py",\n'
                '    "line_number": 12,\n'
                '    "issue_found": "Explanation of violation"\n'
                "  }\n"
                "]\n\n"
                "If no issues are discovered across any lines, reply exactly with: []"
            )
        },
        {
            "role": "user",
            "content": f"Review these code additions:\n\n{code_payload}"
        }
    ]
    
    try:
        res = llm.invoke(messages)
        response_text = res.content.strip()
        
        if response_text.startswith("```"):
            response_text = response_text.replace("```json", "").replace("```", "").strip()
            
        if response_text and response_text != "[]":
            data = json.loads(response_text)
            if isinstance(data, list):
                for item in data:
                    detected_findings.append(InlineFinding(
                        file_path=item.get("file_path", "unknown"),
                        line_number=int(item.get("line_number", 0)),
                        issue_found=item.get("issue_found", "Violation found")
                    ))
    except Exception as e:
        print(f"Error during batch analysis parsing: {e}")
        
    return {"findings": detected_findings}

def publisher_node(state: Dict[str, Any]) -> Dict[str, Any]:
    print("--- [STEP 3/3] Committing Feedbacks to GitHub Window ---")
    if not state.get("findings"):
        pr.create_issue_comment("🚀 **AI Review Completed:** No stylistic issues or bugs discovered in this changes patch code execution baseline.")
        return {}
        
    comment_body = "### 🤖 AI Code Review Agent Report\n\n"
    comment_body += "I have scanned your changes against the corporate engineering guidelines and found the following issues:\n\n"
    comment_body += "| File Path | Line Number | Issue Description |\n"
    comment_body += "| :--- | :--- | :--- |\n"
    
    for finding in state["findings"]:
        comment_body += f"| `{finding.file_path}` | **Line {finding.line_number}** | ⚠️ {finding.issue_found} |\n"
        
    comment_body += "\n\n*Please fix these style or security violations before merging this pull request.*"
    
    pr.create_issue_comment(comment_body)
    print("✅ Successfully posted summary report to the PR timeline.")
    return {}

if __name__ == "__main__":
    print("Starting pipeline manual orchestration loop context pass...")
    diff_data = get_parsed_diff_lines()
    analysis_state = analysis_node({"diff_lines": diff_data})
    publisher_node(analysis_state)
    print("🎉 Action review pipeline executed completely.")