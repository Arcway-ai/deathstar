from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
import time
import uuid

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_server.providers.registry import ProviderRegistry
from deathstar_server.services.github import GitHubService
from deathstar_server.services.gitops import GitService
from deathstar_shared.models import ErrorCode, WorkflowKind, WorkflowRequest, WorkflowResponse

logger = logging.getLogger(__name__)


class WorkflowService:
    def __init__(
        self,
        settings: Settings,
        providers: ProviderRegistry,
        git: GitService,
        github: GitHubService,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.git = git
        self.github = github

    async def execute(self, request: WorkflowRequest) -> WorkflowResponse:
        request_id = str(uuid.uuid4())
        started = time.perf_counter()
        model_name = request.model or self.providers.providers[request.provider].default_model

        try:
            logger.info(
                "workflow.start request_id=%s workflow=%s provider=%s workspace_subpath=%s",
                request_id,
                request.workflow,
                request.provider,
                request.workspace_subpath,
            )

            if request.workflow == WorkflowKind.PROMPT:
                content, model_name, usage, artifacts = await self._prompt(request)
            elif request.workflow == WorkflowKind.PATCH:
                content, model_name, usage, artifacts = await self._patch(request)
            elif request.workflow == WorkflowKind.PR:
                content, model_name, usage, artifacts = await self._pr(request)
            elif request.workflow == WorkflowKind.REVIEW:
                content, model_name, usage, artifacts = await self._review(request)
            else:
                raise AppError(
                    ErrorCode.INVALID_REQUEST,
                    f"unsupported workflow: {request.workflow}",
                    status_code=400,
                )

            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "workflow.done request_id=%s workflow=%s duration_ms=%s",
                request_id,
                request.workflow,
                duration_ms,
            )
            return WorkflowResponse(
                request_id=request_id,
                workflow=request.workflow,
                status="succeeded",
                provider=request.provider,
                model=model_name,
                content=content,
                workspace_subpath=request.workspace_subpath,
                duration_ms=duration_ms,
                usage=usage,
                artifacts=artifacts,
            )
        except AppError as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "workflow.failed request_id=%s workflow=%s code=%s message=%s",
                request_id,
                request.workflow,
                exc.code.value,
                exc.message,
            )
            return WorkflowResponse(
                request_id=request_id,
                workflow=request.workflow,
                status="failed",
                provider=request.provider,
                model=model_name,
                workspace_subpath=request.workspace_subpath,
                duration_ms=duration_ms,
                error=exc.to_envelope(),
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "workflow.unexpected request_id=%s workflow=%s error=%s",
                request_id,
                request.workflow,
                exc,
            )
            envelope = AppError(
                ErrorCode.INTERNAL_ERROR,
                "an unexpected error occurred during workflow execution",
                status_code=500,
            ).to_envelope()
            return WorkflowResponse(
                request_id=request_id,
                workflow=request.workflow,
                status="failed",
                provider=request.provider,
                model=model_name,
                workspace_subpath=request.workspace_subpath,
                duration_ms=duration_ms,
                error=envelope,
            )

    async def _prompt(self, request: WorkflowRequest) -> tuple[str, str, object, dict[str, object]]:
        prompt = request.prompt
        if request.workspace_subpath != ".":
            context = self.git.build_workspace_context(request.workspace_subpath)
            prompt = f"{request.prompt}\n\nRemote workspace context:\n{context}"

        result = await self.providers.generate_text(
            provider=request.provider,
            prompt=prompt,
            model=request.model,
            system=request.system,
            timeout_seconds=request.timeout_seconds,
        )

        return (
            result.text,
            result.model,
            result.usage,
            {"remote_response_id": result.remote_response_id},
        )

    async def _patch(self, request: WorkflowRequest) -> tuple[str, str, object, dict[str, object]]:
        if request.workspace_subpath == ".":
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "patch workflows require --workspace-subpath to point at a repo or subdirectory",
                status_code=400,
            )

        target = self.git.resolve_target(request.workspace_subpath)
        full_tree = self.git.full_file_tree(target)
        tree_text = "\n".join(full_tree) if full_tree else "<empty>"

        # ── Pass 1: Ask the LLM which files it needs to edit ──────────
        plan_system = (
            "You are a code editing assistant. Given a task and a file tree, "
            "identify which existing files need to be modified and any new files "
            "that need to be created.\n\n"
            "Return ONLY a JSON object with two keys:\n"
            '- "files_to_modify": array of repo-relative paths from the tree below\n'
            '- "files_to_create": array of repo-relative paths for new files\n\n'
            "RULES:\n"
            "- files_to_modify MUST only contain paths from the file tree\n"
            "- Keep the list minimal — only files that actually need changes\n"
            "- Do NOT wrap in markdown fences"
        )
        plan_prompt = (
            f"Task:\n{request.prompt}\n\n"
            f"Complete file tree:\n{tree_text}\n\n"
            "Return the JSON file list only."
        )

        plan_result = await self.providers.generate_text(
            provider=request.provider,
            prompt=plan_prompt,
            model=request.model,
            system=plan_system,
            timeout_seconds=min(request.timeout_seconds, 60),
        )

        # Parse file list from plan
        try:
            plan = _extract_json_object(plan_result.text)
            files_to_modify = [str(f) for f in (plan.get("files_to_modify") or []) if isinstance(f, str)]
            files_to_create = [str(f) for f in (plan.get("files_to_create") or []) if isinstance(f, str)]
        except AppError:
            logger.warning("patch plan response was not valid JSON, falling back to workspace context")
            files_to_modify = []
            files_to_create = []

        # ── Pass 2: Fetch file contents and generate the diff ─────────
        if files_to_modify:
            file_contents = self.git.read_files_by_paths(request.workspace_subpath, files_to_modify)
            numbered_files: list[str] = []
            for path, content in file_contents.items():
                lines = content.split("\n")
                numbered = "\n".join(f"{i + 1:4d} | {line}" for i, line in enumerate(lines))
                numbered_files.append(f"File: {path}\n{numbered}")
            files_context = "\n\n".join(numbered_files)
        else:
            files_context = self.git.build_workspace_context(request.workspace_subpath)

        diff_system = _join_system_prompts(
            request.system,
            "You are editing code on a remote git workspace. Return ONLY a valid unified diff.\n\n"
            "CRITICAL RULES:\n"
            "- You may ONLY modify files whose full contents are provided below.\n"
            "- Context lines MUST be copied EXACTLY from the numbered file contents provided.\n"
            "- Do NOT invent or guess file contents — use what is given.\n"
            "- For new files, use --- /dev/null as the old-file path.\n\n"
            "Diff format requirements:\n"
            "- Start each file with: diff --git a/path b/path\n"
            "- Then: --- a/path\n"
            "- Then: +++ b/path\n"
            "- Then hunk headers: @@ -start,count +start,count @@\n"
            "- Context lines (unchanged) must start with a SPACE character\n"
            "- Added lines start with +\n"
            "- Removed lines start with -\n"
            "- Use repo-relative paths (not absolute paths)\n"
            "- Do NOT wrap in markdown fences or backticks\n"
            "- Do NOT include any prose, explanation, or commentary\n"
            "- Include 3 lines of context around each change\n"
            "- Line numbers in @@ headers must match the source file line numbers",
        )

        new_files_note = ""
        if files_to_create:
            new_files_note = "\n\nNew files to create:\n" + "\n".join(files_to_create)

        diff_prompt = (
            f"Task:\n{request.prompt}\n\n"
            f"Complete file tree:\n{tree_text}\n\n"
            f"File contents (with line numbers):\n{files_context}"
            f"{new_files_note}\n\n"
            "Return a unified diff only — no other text."
        )

        result = await self.providers.generate_text(
            provider=request.provider,
            prompt=diff_prompt,
            model=request.model,
            system=diff_system,
            timeout_seconds=request.timeout_seconds,
        )

        patch_text = _extract_unified_diff(result.text)
        artifacts: dict[str, object] = {
            "patch": patch_text,
            "files_planned": files_to_modify + files_to_create,
            "remote_response_id": result.remote_response_id,
        }

        if request.write_changes:
            repo_root = self.git.apply_patch(request.workspace_subpath, patch_text)
            artifacts["changed_files"] = self.git.changed_files(repo_root)
            artifacts["git_status"] = self.git.status_short(repo_root)
            content = "Patch applied to the remote workspace."
        else:
            content = patch_text

        return content, result.model, result.usage, artifacts

    async def _pr(self, request: WorkflowRequest) -> tuple[str, str, object, dict[str, object]]:
        if request.workspace_subpath == ".":
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "PR workflows require --workspace-subpath to point at a git repo or subdirectory",
                status_code=400,
            )

        snapshot = self.git.collect_diff_snapshot(request.workspace_subpath, request.base_branch)
        prompt = (
            "You are preparing a pull request summary.\n\n"
            f"User intent:\n{request.prompt}\n\n"
            f"Base branch: {request.base_branch}\n"
            f"Current branch: {snapshot.branch}\n\n"
            f"Diff:\n{snapshot.diff_text}\n\n"
            'Return strict JSON with keys "title", "body", and "summary".'
        )
        system = _join_system_prompts(
            request.system,
            "Write a concise, technically accurate pull request title and body. "
            "Do not invent changes. The title should be under 72 characters.",
        )

        result = await self.providers.generate_text(
            provider=request.provider,
            prompt=prompt,
            model=request.model,
            system=system,
            timeout_seconds=request.timeout_seconds,
        )

        pr_payload = _extract_json_object(result.text)
        title = str(pr_payload.get("title") or "").strip()
        body = str(pr_payload.get("body") or "").strip()
        summary = str(pr_payload.get("summary") or body).strip()
        if not title or not body:
            raise AppError(
                ErrorCode.INVALID_PROVIDER_OUTPUT,
                "provider did not return a valid PR title and body",
                status_code=502,
            )

        branch = snapshot.branch
        commit_sha = None
        if snapshot.dirty:
            branch = request.head_branch or _generate_branch_name(title)
            self.git.ensure_branch(snapshot.repo_root, branch)
            commit_sha = self.git.commit_all(snapshot.repo_root, title)

        pull_request_url = None
        if request.open_pr:
            self.github.push_branch(snapshot.repo_root, branch)
            pull_request_url = await self.github.create_pull_request(
                repo_root=snapshot.repo_root,
                title=title,
                body=body,
                head_branch=branch,
                base_branch=request.base_branch,
                draft=request.draft_pr,
            )

        artifacts = {
            "title": title,
            "body": body,
            "branch": branch,
            "commit_sha": commit_sha,
            "pull_request_url": pull_request_url,
            "changed_files": snapshot.changed_files,
            "remote_response_id": result.remote_response_id,
        }

        return summary, result.model, result.usage, artifacts

    async def _review(self, request: WorkflowRequest) -> tuple[str, str, object, dict[str, object]]:
        if request.workspace_subpath == ".":
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "review workflows require --workspace-subpath to point at a git repo or subdirectory",
                status_code=400,
            )

        snapshot = self.git.collect_diff_snapshot(request.workspace_subpath, request.base_branch)
        system = _join_system_prompts(
            request.system,
            "You are a separate code reviewer with no access to the implementation chat history. "
            "Review the diff for correctness, regressions, security issues, and missing tests. "
            "Return concise markdown with sections Findings, Risks, and Recommended follow-ups.",
        )
        prompt = (
            f"Review request:\n{request.prompt}\n\n"
            f"Base branch: {request.base_branch}\n"
            f"Current branch: {snapshot.branch}\n\n"
            f"Diff:\n{snapshot.diff_text}"
        )

        result = await self.providers.generate_text(
            provider=request.provider,
            prompt=prompt,
            model=request.model,
            system=system,
            timeout_seconds=request.timeout_seconds,
        )

        artifacts = {
            "branch": snapshot.branch,
            "changed_files": snapshot.changed_files,
            "remote_response_id": result.remote_response_id,
        }
        return result.text, result.model, result.usage, artifacts


def _extract_unified_diff(text: str) -> str:
    stripped = text.strip()
    fenced = re.search(r"```(?:diff)?\s*(.*?)```", stripped, re.DOTALL)
    candidate = fenced.group(1).strip() if fenced else stripped

    diff_index = candidate.find("diff --git ")
    if diff_index >= 0:
        candidate = candidate[diff_index:]

    if candidate.startswith("--- ") and "\n+++ " in candidate:
        return candidate.strip()
    if "diff --git " in candidate:
        return candidate.strip()

    raise AppError(
        ErrorCode.INVALID_PROVIDER_OUTPUT,
        "provider did not return a valid unified diff",
        status_code=502,
    )


def _extract_json_object(text: str) -> dict[str, object]:
    stripped = text.strip()

    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = _find_first_json_object(stripped)

    if not isinstance(payload, dict):
        raise AppError(
            ErrorCode.INVALID_PROVIDER_OUTPUT,
            "provider returned JSON, but not an object",
            status_code=502,
        )
    return payload


def _find_first_json_object(text: str) -> object:
    start = text.find("{")
    if start == -1:
        raise AppError(
            ErrorCode.INVALID_PROVIDER_OUTPUT,
            "provider did not return a valid JSON object",
            status_code=502,
        )

    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(text)):
        char = text[i]
        if escape_next:
            escape_next = False
            continue
        if in_string:
            if char == "\\":
                escape_next = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    break

    raise AppError(
        ErrorCode.INVALID_PROVIDER_OUTPUT,
        "provider did not return a valid JSON object",
        status_code=502,
    )


def _join_system_prompts(user_system: str | None, required_system: str) -> str:
    return required_system if not user_system else f"{required_system}\n\n{user_system}"


def _generate_branch_name(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:40] or "change"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"deathstar/{timestamp}-{slug}"
