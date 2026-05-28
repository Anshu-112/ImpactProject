import os
import json
import re
from typing import TypedDict, List
from github import Github
import chromadb
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_mistralai import ChatMistralAI
from langgraph.graph import StateGraph, END

# =====================================================================
# 1. ENVIRONMENT CONFIGURATION & SETUP
# =====================================================================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Read the GitHub environment event payload
with open(os.getenv("GITHUB_EVENT_PATH"), "r") as f:
    event_data = json.load(f)

repo_name = event_data["repository"]["full_name"]
pr_number = event_data["pull_request"]["number"]

gh = Github(GITHUB_TOKEN)
repo = gh.get_repo(repo_name)
pr = repo.get_pull(pr_number)

# =====================================================================
# 2. DEFINE THE DATA LAYOUT (STATE & INLINE MODELS)
# =====================================================================
class CodeDiffLine(TypedDict):
    file_path: str
    line_number: int
    content: str

class InlineFinding(BaseModel):
    file_path: str = Field(description="The path to the file containing a flaw.")
    line_number: int = Field(description="The exact integer line number destination.")
    issue_found: str = Field(description="Clear explanation of the bug or style rule violation.")

class AgentState(TypedDict):
    diff_lines: List[CodeDiffLine]
    relevant_rules: List[str]
    findings: List[InlineFinding]

# =====================================================================
# 3. CORE PROCESSING HELPER FUNCTIONS
# =====================================================================
def get_parsed_diff_lines() -> List[CodeDiffLine]:
    """Downloads and parses the PR diff cleanly without risk of infinite loops."""
    parsed_lines = []
    
    try:
        pr_files = pr.get_files()
        for file in pr_files:
            # Only analyze Python files, skip deleted or empty files
            if not file.filename.endswith(".py") or not file.patch:
                continue
                
            current_line = 0
            # Read the patch changes sequentially, line by line
            for line in file.patch.split("\n"):
                if line.startswith("@@"):
                    # Extract the starting destination line number from hunk header
                    match = re.search(r"\+(\d+)", line)
                    if match:
                        current_line = int(match.group(1)) - 1
                    continue
                
                # If it's a normal or added line, increment the tracker
                if not line.startswith("-"):
                    current_line += 1
                    
                # Store the change if it's an explicit addition (+)
                if line.startswith("+"):
                    parsed_lines.append({
                        "file_path": file.filename,
                        "line_number": current_line,
                        "content": line[1:].strip()
                    })
    except Exception as e:
        print(f"Error parsing diff files: {e}")
        
    return parsed_lines

def setup_ephemeral_rag(diff_content: str) -> List[str]:
    """Loads guidelines dynamically into ChromaDB and returns matching entries."""
    chroma_client = chromadb.EphemeralClient()
    collection = chroma_client.create_collection(name="style_rules")
    
    with open("style_guide.md", "r") as f:
        guide_text = f.read()
        
    # Chunking by sections
    rules = [r.strip() for r in guide_text.split("##") if r.strip()]
    for i, rule in enumerate(rules):
        collection.add(
            documents=[rule],
            ids=[f"rule_{i}"]
        )
        
    results = collection.query(query_texts=[diff_content], n_results=1)
    return results["documents"][0] if results["documents"] else []

# =====================================================================
# 4. LANGGRAPH NODE WORKFLOW OPERATIONS
# =====================================================================
def ingestion_node(state: AgentState) -> dict:
    print("--- [STEP 1/3] Fetching and Parsing PR Diffs ---")
    lines = get_parsed_diff_lines()
    all_code_snippet = "\n".join([l["content"] for l in lines])
    rules = setup_ephemeral_rag(all_code_snippet)
    return {"diff_lines": lines, "relevant_rules": rules}

def analysis_node(state: AgentState) -> dict:
    print("--- [STEP 2/3] Analyzing Code with Mistral Framework ---")
    
    # 1. ALWAYS define your return variable at the absolute top of the function scope
    detected_findings = []
    
    if not state.get("diff_lines"):
        return {"findings": []}
        
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
    if not MISTRAL_API_KEY:
        print("❌ Error: MISTRAL_API_KEY environment variable is missing!")
        return {"findings": []}
        
    # Using 'open-mistral-7b' or 'codestral-latest' depending on your free tier tier allocations
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

    prompt = ChatPromptTemplate.from_messages([
        ("system", (
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
        )),
        ("human", f"Review these code additions:\n\n{code_payload}")
    ])
    
    chain = prompt | llm
    try:
        res = chain.invoke({})
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

def publisher_node(state: AgentState) -> dict:
    print("--- [STEP 3/3] Committing Feedbacks to GitHub Window ---")
    if not state["findings"]:
        pr.create_issue_comment("🚀 **AI Review Completed:** No stylistic issues or bugs discovered in this changes patch code execution baseline.")
        return {}

    # Build a beautiful, structured Markdown report for the main PR conversation timeline
    comment_body = "### 🤖 AI Code Review Agent Report\n\n"
    comment_body += "I have scanned your changes against the corporate engineering guidelines and found the following issues:\n\n"
    comment_body += "| File Path | Line Number | Issue Description |\n"
    comment_body += "| :--- | :--- | :--- |\n"

    for finding in state["findings"]:
        comment_body += f"| `{finding.file_path}` | **Line {finding.line_number}** | ⚠️ {finding.issue_found} |\n"

    comment_body += "\n\n*Please fix these style or security violations before merging this pull request.*"

    # Post it as a single master comment on the main timeline
    pr.create_issue_comment(comment_body)
    print("✅ Successfully posted summary report to the PR timeline.")
    return {}

# =====================================================================
# 5. ASSEMBLE AND RUN THE COMPUTATION GRAPH
# =====================================================================
workflow = StateGraph(AgentState)

workflow.add_node("IngestDiffAndRAG", ingestion_node)
workflow.add_node("AnalyzeCode", analysis_node)
workflow.add_node("PostToGitHub", publisher_node)

workflow.set_entry_point("IngestDiffAndRAG")
workflow.add_edge("IngestDiffAndRAG", "AnalyzeCode")
workflow.add_edge("AnalyzeCode", "PostToGitHub")
workflow.add_edge("PostToGitHub", END)

app = workflow.compile()

if __name__ == "__main__":
    app.invoke({"diff_lines": [], "relevant_rules": [], "findings": []})
    print("🎉 Action review pipeline executed completely.")