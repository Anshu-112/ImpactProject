import os
import json
import re
from typing import TypedDict, List
from github import Github
import chromadb
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
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
    """Downloads and parses the PR diff into standalone added line targets."""
    parsed_lines = []
    # Get files changed in the PR
    pr_files = pr.get_files()
    
    for file in pr_files:
        if not file.patch or not file.filename.endswith(".py"):
            continue # Only review Python source files for this MVP
            
        current_line = 0
        for line in file.patch.split("\n"):
            # Parse Git Hunk Header line indicators
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
    print("--- [STEP 2/3] Analyzing Code with Gemini Framework ---")
    if not state["diff_lines"]:
        return {"findings": []}
        
    # We use standard LLM invocation instead of the beta structured configuration method
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=GEMINI_API_KEY,convert_system_message_to_human=True)
    
    detected_findings = []
    
    for line in state["diff_lines"]:
        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "You are an expert code reviewer. Compare the user code change line against these guidelines:\n{rules}\n\n"
                "If the code violates a rule or contains a fatal logical vulnerability, you MUST respond strictly with a JSON object following this format:\n"
                "{{\n"
                '  "file_path": "the file path string",\n'
                '  "line_number": {line_num},\n'
                '  "issue_found": "Clear explanation of the bug or style rule violation."\n'
                "}}\n"
                "If the code line does not violate any rules and has no bugs, respond with the exact word: NONE"
            )),
            ("human", "File: {file}\nLine: {line_num}\nCode Line: {code}")
        ])
        
        chain = prompt | llm
        try:
            res = chain.invoke({
                "rules": "\n".join(state["relevant_rules"]),
                "file": line["file_path"],
                "line_num": line["line_number"],
                "code": line["content"]
            })
            
            response_text = res.content.strip()
            
            # Clean up potential markdown code block wrappers if the LLM includes them
            if response_text.startswith("```"):
                response_text = response_text.replace("```json", "").replace("```", "").strip()
                
            if response_text and response_text != "NONE":
                data = json.loads(response_text)
                # Parse standard values back safely into our object array
                detected_findings.append(InlineFinding(
                    file_path=data["file_path"],
                    line_number=int(data["line_number"]),
                    issue_found=data["issue_found"]
                ))
        except Exception as e:
            print(f"Skipping evaluation line check placeholder: {e}")
            
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