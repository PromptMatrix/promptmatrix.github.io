#!/usr/bin/env python3
import argparse
import os
import sys
from typing import Optional

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"


class PromptMatrixCLI:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        # PM_TOKEN for authenticated remote governance
        self.token = os.environ.get("PM_TOKEN")
        
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            
        self.client = httpx.Client(
            base_url=self.base_url, 
            timeout=30.0,
            headers=headers
        )

    def _handle_error(self, response: httpx.Response):
        try:
            data = response.json()
            detail = data.get("detail", response.text)
        except:
            detail = response.text
        print(f"Error: {response.status_code} - {detail}")
        sys.exit(1)

    def status(self):
        try:
            resp = self.client.get("/")
            if resp.status_code == 200:
                print(f"[OK] PromptMatrix is alive at {self.base_url}")
                if self.token:
                    print("[AUTH] Using PM_TOKEN for authentication.")
            else:
                print(f"[WARN] PromptMatrix responded with {resp.status_code}")
        except Exception:
            print(f"[FAIL] Could not connect to PromptMatrix at {self.base_url}")
            print("Make sure the server is running (e.g., python main.py)")
            sys.exit(1)

    def list_prompts(self):
        # 1. Get projects to find the development environment
        resp = self.client.get("/api/v1/projects")
        if resp.status_code != 200:
            self._handle_error(resp)

        projects = resp.json().get("projects", [])
        if not projects:
            print("No projects found.")
            return

        for proj in projects:
            print(f"\nProject: {proj['name']} ({proj['id']})")
            for env in proj.get("environments", []):
                print(f"  Env: {env['name']} [{env['display_name']}] ({env['id']})")

                # Fetch prompts for this environment
                p_resp = self.client.get(f"/api/v1/prompts?environment_id={env['id']}")
                if p_resp.status_code != 200:
                    continue

                prompts = p_resp.json().get("prompts", [])
                if not prompts:
                    print("    (no prompts)")
                for p in prompts:
                    live_v = p.get("live_version")
                    v_str = f"v{live_v['version_num']}" if live_v else "none"
                    print(f"    - {p['key']} [{v_str}]")

    def push(self, key: str, file_path: str, description: Optional[str] = None):
        if not os.path.exists(file_path):
            print(f"Error: File not found: {file_path}")
            sys.exit(1)

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 1. Find development environment
        resp = self.client.get("/api/v1/projects")
        if resp.status_code != 200:
            self._handle_error(resp)

        projects = resp.json().get("projects", [])
        dev_env_id = None
        for proj in projects:
            for env in proj.get("environments", []):
                if env["name"] == "development":
                    dev_env_id = env["id"]
                    break
            if dev_env_id:
                break

        if not dev_env_id:
            print("Error: Could not find a 'development' environment.")
            sys.exit(1)

        # 2. Check if prompt exists
        p_resp = self.client.get(f"/api/v1/prompts?environment_id={dev_env_id}")
        if p_resp.status_code != 200:
            self._handle_error(p_resp)

        prompts = p_resp.json().get("prompts", [])
        existing_prompt = next((p for p in prompts if p["key"] == key), None)

        if not existing_prompt:
            # Create new prompt
            print(f"Creating new prompt: {key}...")
            payload = {
                "environment_id": dev_env_id,
                "key": key,
                "content": content,
                "description": description or f"CLI push of {key}",
                "commit_message": "Initial CLI push",
            }
            create_resp = self.client.post("/api/v1/prompts", json=payload)
            if create_resp.status_code != 200:
                self._handle_error(create_resp)

            prompt_id = create_resp.json()["prompt"]["id"]
            detail_resp = self.client.get(f"/api/v1/prompts/{prompt_id}")
            versions = detail_resp.json().get("versions", [])
            draft_v = next((v for v in versions if v["status"] == "draft"), None)
            if not draft_v:
                print("Warning: Prompt created but no draft version found to approve.")
                return
            version_id = draft_v["id"]
        else:
            # Create new version for existing prompt
            prompt_id = existing_prompt["id"]
            print(f"Updating prompt: {key} (ID: {prompt_id})...")
            v_payload = {"content": content, "commit_message": "CLI update"}
            v_resp = self.client.post(
                f"/api/v1/prompts/{prompt_id}/versions", json=v_payload
            )
            if v_resp.status_code != 200:
                self._handle_error(v_resp)
            version_id = v_resp.json()["version"]["id"]

        # 3. Quick Approve (Dev Mode Only)
        print(f"Approving version {version_id}...")
        app_resp = self.client.post(
            f"/api/v1/prompts/{prompt_id}/versions/{version_id}/quick-approve"
        )
        if app_resp.status_code == 200:
            print(
                f"[OK] Successfully pushed and approved '{key}' (v{app_resp.json()['version']['version_num']})"
            )
        else:
            print(f"[WARN] Push succeeded but quick-approve failed: {app_resp.text}")
            print("You may need to approve it manually in the dashboard.")

    def pull(self, key: str, file_path: str):
        print(f"Pulling live content for '{key}'...")
        resp = self.client.get(f"/pm/serve/{key}")
        if resp.status_code == 200:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(resp.text)
            print(f"[OK] Saved to {file_path}")
        elif resp.status_code == 404:
            print(f"Error: Prompt '{key}' not found or has no live version.")
        else:
            self._handle_error(resp)

    def diff(self, key: str, file_path: str):
        import difflib

        if not os.path.exists(file_path):
            print(f"Error: File not found: {file_path}")
            sys.exit(1)

        with open(file_path, "r", encoding="utf-8") as f:
            local_content = f.read()

        resp = self.client.get(f"/pm/serve/{key}")
        if resp.status_code == 200:
            remote_content = resp.text
        elif resp.status_code == 404:
            remote_content = ""
            print(f"[NOTE] Remote prompt '{key}' does not exist or has no live version. Diff will show as all additions.")
        else:
            self._handle_error(resp)

        diff = list(
            difflib.unified_diff(
                remote_content.splitlines(keepends=True),
                local_content.splitlines(keepends=True),
                fromfile=f"remote:{key}",
                tofile=f"local:{file_path}",
            )
        )
        if not diff:
            print("No differences found.")
        else:
            sys.stdout.writelines(diff)

    def eval_prompt(self, key: str, file_path: str, eval_type: str = "rule_based", provider: str = None, model: str = None, api_key: str = None):
        """Pushes a draft version and evaluates it."""
        if not os.path.exists(file_path):
            print(f"Error: File not found: {file_path}")
            sys.exit(1)

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Get dev env
        resp = self.client.get("/api/v1/projects")
        if resp.status_code != 200:
            self._handle_error(resp)

        projects = resp.json().get("projects", [])
        dev_env_id = None
        for proj in projects:
            for env in proj.get("environments", []):
                if env["name"] == "development":
                    dev_env_id = env["id"]
                    break
            if dev_env_id:
                break

        if not dev_env_id:
            print("Error: Could not find 'development' environment.")
            sys.exit(1)

        # Check prompt
        p_resp = self.client.get(f"/api/v1/prompts?environment_id={dev_env_id}")
        prompts = p_resp.json().get("prompts", [])
        existing = next((p for p in prompts if p["key"] == key), None)

        if not existing:
            print(f"Creating new prompt '{key}' for evaluation...")
            c_resp = self.client.post("/api/v1/prompts", json={"environment_id": dev_env_id, "key": key, "content": content, "commit_message": "CLI Eval Push"})
            if c_resp.status_code != 200:
                self._handle_error(c_resp)
            version_id = c_resp.json()["prompt"]["live_version_id"] # newly created
            if not version_id:
                # get detail
                detail = self.client.get(f"/api/v1/prompts/{c_resp.json()['prompt']['id']}").json()
                version_id = detail["versions"][0]["id"]
        else:
            print(f"Updating prompt '{key}' for evaluation...")
            v_resp = self.client.post(f"/api/v1/prompts/{existing['id']}/versions", json={"content": content, "commit_message": "CLI Eval Push"})
            if v_resp.status_code != 200:
                self._handle_error(v_resp)
            version_id = v_resp.json()["version"]["id"]

        print("Running evaluation...")
        payload = {"version_id": version_id, "eval_type": eval_type}
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model
        if api_key:
            payload["api_key"] = api_key

        eval_resp = self.client.post("/api/v1/evals/run", json=payload)
        if eval_resp.status_code != 200:
            self._handle_error(eval_resp)
            
        res = eval_resp.json()
        print(f"\n--- EVALUATION RESULT [{res.get('eval_type', 'unknown').upper()}] ---")
        print(f"Score: {res.get('overall_score')}/10.0 ({'PASSED' if res.get('passed') else 'FAILED'})")
        
        print("\nCriteria:")
        for k, v in res.get("criteria", {}).items():
            print(f"  - {k}: {v}/10.0")
            
        issues = res.get("issues", [])
        if issues:
            print("\nIssues:")
            for i in issues:
                print(f"  - {i}")
                
        suggestions = res.get("suggestions", [])
        if suggestions:
            print("\nSuggestions:")
            for s in suggestions:
                print(f"  - {s}")

    def promote(self, key: str, target_env: str):
        # Find the prompt ID and target env ID
        resp = self.client.get("/api/v1/projects")
        if resp.status_code != 200:
            self._handle_error(resp)

        dev_env_id = None
        target_env_id = None
        for proj in resp.json().get("projects", []):
            for env in proj.get("environments", []):
                if env["name"] == "development":
                    dev_env_id = env["id"]
                elif env["name"] == target_env:
                    target_env_id = env["id"]

        if not dev_env_id or not target_env_id:
            print(f"Error: Could not locate development env or target env '{target_env}'.")
            sys.exit(1)

        p_resp = self.client.get(f"/api/v1/prompts?environment_id={dev_env_id}")
        existing = next((p for p in p_resp.json().get("prompts", []) if p["key"] == key), None)
        if not existing:
            print(f"Error: Prompt '{key}' not found in development environment.")
            sys.exit(1)

        print(f"Promoting '{key}' to '{target_env}'...")
        promo_resp = self.client.post(
            f"/api/v1/prompts/{existing['id']}/promote",
            json={"target_environment_id": target_env_id, "auto_approve": False}
        )
        if promo_resp.status_code != 200:
            self._handle_error(promo_resp)
            
        print(f"[OK] Promotion requested. Status: {promo_resp.json().get('status')}")


def main():
    parser = argparse.ArgumentParser(description="PromptMatrix CLI - Local Edition")
    parser.add_argument(
        "--url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL (default: {DEFAULT_BASE_URL})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    subparsers.add_parser("status", help="Check connection to PromptMatrix")
    subparsers.add_parser("list", help="List all prompts and environments")

    push_parser = subparsers.add_parser(
        "push", help="Push a local file as a live prompt"
    )
    push_parser.add_argument("key", help="Prompt key (e.g. system.assistant)")
    push_parser.add_argument("file", help="Path to text file")
    push_parser.add_argument("--desc", help="Optional description")

    pull_parser = subparsers.add_parser(
        "pull", help="Pull live prompt content to a local file"
    )
    pull_parser.add_argument("key", help="Prompt key")
    pull_parser.add_argument("file", help="Path to save the file")
    diff_parser = subparsers.add_parser(
        "diff", help="Diff local file against live remote prompt"
    )
    diff_parser.add_argument("key", help="Prompt key")
    diff_parser.add_argument("file", help="Path to local file")

    eval_parser = subparsers.add_parser(
        "eval", help="Push and evaluate a prompt"
    )
    eval_parser.add_argument("key", help="Prompt key")
    eval_parser.add_argument("file", help="Path to local file")
    eval_parser.add_argument("--type", default="rule_based", help="Eval type: rule_based or llm_judge")
    eval_parser.add_argument("--provider", help="Provider (e.g., anthropic, openai)")
    eval_parser.add_argument("--model", help="Model name")
    eval_parser.add_argument("--api-key", help="Provider API key (bypasses saved DB key)")

    promo_parser = subparsers.add_parser(
        "promote", help="Promote a prompt to a target environment"
    )
    promo_parser.add_argument("key", help="Prompt key")
    promo_parser.add_argument("target", help="Environment name (e.g., production)")

    args = parser.parse_args()
    cli = PromptMatrixCLI(args.url)

    if args.command == "status":
        cli.status()
    elif args.command == "list":
        cli.list_prompts()
    elif args.command == "push":
        cli.push(args.key, args.file, args.desc)
    elif args.command == "pull":
        cli.pull(args.key, args.file)
    elif args.command == "diff":
        cli.diff(args.key, args.file)
    elif args.command == "eval":
        cli.eval_prompt(args.key, args.file, args.type, args.provider, args.model, getattr(args, "api_key", None))
    elif args.command == "promote":
        cli.promote(args.key, args.target)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
