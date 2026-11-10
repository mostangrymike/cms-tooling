"""Capability policy for the local z/VM CMS MCP server.

There is one declaration per capability, one frozen capability set per server
process, and one table saying which MCP tool requires which capability.  This
module performs no I/O; it is data plus the refusal payload a disabled tool
returns.

The historical `--allow-*` flags remain the operator-facing switch.  They are
mapped once here instead of being threaded through six modules as separate
booleans.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

#: capability name -> the server flag that enables it
CAPABILITY_FLAGS = {
    "input": "allow_input",
    "login": "allow_login",
    "startup": "allow_startup",
    "hx": "allow_hx",
    "commands": "allow_commands",
    "arbitrary_commands": "allow_arbitrary_commands",
    "downloads": "allow_downloads",
    "uploads": "allow_uploads",
    "local_edits": "allow_local_edits",
    "create_only_upload": "allow_create_only_upload",
    "query_links": "allow_query_links",
}

_FIELD_BY_FLAG = {flag: name for name, flag in CAPABILITY_FLAGS.items()}


@dataclass(frozen=True)
class Capabilities:
    """The capabilities a server process was started with.

    Frozen so that a tool cannot widen its own authority.  Tests and operator
    scripts that predate this module still assign `session.allow_<name>`; that
    shim rebuilds the set through `with_flag`.
    """

    input: bool = False
    login: bool = False
    startup: bool = False
    hx: bool = False
    commands: bool = False
    arbitrary_commands: bool = False
    downloads: bool = False
    uploads: bool = False
    local_edits: bool = False
    create_only_upload: bool = False
    query_links: bool = False

    @classmethod
    def from_flags(cls, flags: Mapping[str, object]) -> "Capabilities":
        """Build from `allow_*` keywords, rejecting anything unknown."""
        unknown = set(flags) - set(CAPABILITY_FLAGS.values())
        if unknown:
            raise TypeError("unknown capability flag(s): " + ", ".join(sorted(unknown)))
        return cls(**{name: bool(flags.get(flag, False)) for name, flag in CAPABILITY_FLAGS.items()})

    @classmethod
    def from_namespace(cls, namespace) -> "Capabilities":
        """Build from an argparse namespace produced by `main()`."""
        return cls(**{name: bool(getattr(namespace, flag, False))
                      for name, flag in CAPABILITY_FLAGS.items()})

    def enabled(self, name: str) -> bool:
        if name not in CAPABILITY_FLAGS:
            raise KeyError(f"unknown capability {name!r}")
        return bool(getattr(self, name))

    def with_flag(self, flag: str, value: object) -> "Capabilities":
        try:
            name = _FIELD_BY_FLAG[flag]
        except KeyError:
            raise TypeError(f"unknown capability flag {flag!r}") from None
        return replace(self, **{name: bool(value)})

    def flags(self) -> dict[str, bool]:
        return {flag: bool(getattr(self, name)) for name, flag in CAPABILITY_FLAGS.items()}


@dataclass(frozen=True)
class ToolDeclaration:
    """One MCP tool's capability contract.

    `refusal` carries the structured fields the tool promises to return when
    it is disabled, so a boundary refusal stays shaped like the tool's own
    refusal.  `cms_query_links`, for example, must still say
    `replacement_safe: False`.
    """

    name: str
    requires: tuple[str, ...] = ()
    refusal: Mapping[str, object] = field(default_factory=dict)


#: Reviewed tool inventory.  Order matches registration in `create_server`.
#: validate_cms_mcp.py cross-checks this against its independent EXPECTED set,
#: so adding or removing a tool fails the offline validation instead of
#: silently changing the server contract.
TOOL_DECLARATIONS = (
    ToolDeclaration("cms_connect"),
    ToolDeclaration("cms_screen"),
    ToolDeclaration("cms_status"),
    ToolDeclaration("cms_send", ("input",)),
    ToolDeclaration("cms_login", ("login",)),
    ToolDeclaration("cms_startup", ("startup",)),
    ToolDeclaration("cms_continue_more", ("startup",)),
    ToolDeclaration("cms_abort_read", ("hx",)),
    ToolDeclaration("cms_prepare_runner", ("commands",)),
    ToolDeclaration("cms_command", ("commands",)),
    ToolDeclaration("cms_resolve_failed_capture", ("commands",)),
    ToolDeclaration("cms_restart_runner", ("commands",)),
    ToolDeclaration("cms_query_links", ("query_links",), {"replacement_safe": False}),
    ToolDeclaration("cms_download", ("downloads", "commands")),
    ToolDeclaration("cms_edit_prepare", ("local_edits",)),
    ToolDeclaration("cms_edit_plan", ("local_edits",)),
    ToolDeclaration("cms_operation_plan", ("local_edits",), {
        "execution_authorized": False,
        "execution_implemented": False,
        "host_operations_performed": False,
        "replacement_safe": False,
    }),
    ToolDeclaration("cms_upload_create_only", ("commands", "create_only_upload")),
    ToolDeclaration("cms_upload_file", ("uploads", "commands")),
    ToolDeclaration("cms_disconnect"),
)

TOOL_CAPABILITIES = {declaration.name: declaration.requires
                     for declaration in TOOL_DECLARATIONS}

_DECLARATION_BY_NAME = {declaration.name: declaration for declaration in TOOL_DECLARATIONS}


def declaration(name: str) -> ToolDeclaration:
    """Return the reviewed declaration for one tool, or fail loudly."""
    try:
        return _DECLARATION_BY_NAME[name]
    except KeyError:
        raise RuntimeError(
            f"MCP tool {name!r} has no capability declaration in cms_policy.py") from None


def refusal(tool: ToolDeclaration, capabilities: Capabilities) -> dict | None:
    """Return the tool's documented refusal, or None when it may run."""
    missing = [name for name in tool.requires if not capabilities.enabled(name)]
    if not missing:
        return None
    flags = ", ".join("--" + CAPABILITY_FLAGS[name].replace("_", "-") for name in missing)
    return {"ok": False, "message": f"{tool.name} requires {flags}", **dict(tool.refusal)}
