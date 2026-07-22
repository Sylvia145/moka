"""Pico 运行时实现模块。"""

from .workspace import WorkspaceContext


def build_child_runtime(parent, subagent_type, write_scope, workspace_root=None):
    """执行 `build_child_runtime` 的内部逻辑。"""
    from .runtime import Pico

    child = Pico(
        model_client=new_model_client(parent),
        workspace=WorkspaceContext.build(workspace_root or parent.root, repo_root_override=workspace_root or parent.root),
        session_store=parent.session_store,
        run_store=parent.run_store,
        approval_policy="never" if subagent_type == "Explore" else "auto",
        max_steps=parent.max_steps,
        max_new_tokens=parent.max_new_tokens,
        depth=parent.depth + 1,
        max_depth=parent.max_depth,
        read_only=subagent_type == "Explore"
        or (subagent_type == "worker" and not write_scope),
        secret_env_names=parent.secret_env_names,
        shell_env_allowlist=parent.shell_env_allowlist,
        feature_flags=parent.feature_flags,
        write_scope=write_scope,
        model_client_factory=getattr(parent, "model_client_factory", None),
        sandbox_config=getattr(parent, "sandbox_config", None),
        ask_user_callback=getattr(parent, "ask_user_callback", None),
        max_concurrent_workers=getattr(parent, "max_concurrent_workers", 2),
        max_pending_tasks=getattr(parent, "max_pending_tasks", 16),
        worker_timeout_seconds=getattr(parent, "worker_timeout_seconds", 60),
    )
    child.set_tool_profile("readonly" if subagent_type == "Explore" else "worker")
    child.refresh_prefix(force=True)
    return child


def new_model_client(parent):
    """执行 `new_model_client` 的内部逻辑。"""
    factory = getattr(parent, "model_client_factory", None)
    if factory is not None:
        return factory()
    return parent.model_client
