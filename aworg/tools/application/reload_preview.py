"""Put the owner's preview back in step with the application.

The preview is an iframe of a server the Resident started, and its address
does not change when the files behind it do. So a Resident that edits
index.html leaves the owner looking at the page from before the edit, on the
same URL, with nothing to indicate it is stale. The spec asks the preview to
reflect the application's current state; without this it reflects its state
at the moment it was first served.

AWORG reloads on its own when the Living Workspace changes, which covers the
ordinary case. This is for the two it does not: a change whose effect the
model knows about and the filesystem does not -- a restarted server, a
regenerated database, a template rendered from something outside the
workspace -- and simply wanting the owner to look again now rather than on
the next poll.

Nothing about the application changes here. It asks a browser to fetch a page
again, which is why it is cheap enough to call whenever a change is worth
seeing.
"""

from __future__ import annotations

from ..base import ToolContext, ToolError, ToolResult


NAME = "reload_preview"

DESCRIPTION = (
    "Reload the live preview the owner is watching, so it shows the "
    "application as it is now. Call it after changing something the owner "
    "should see. It does not restart or alter the application -- it only "
    "asks the owner's view to refresh."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {
            "type": "string",
            "description": (
                "Optionally, what changed. Shown to nobody yet; useful to "
                "say so that the call reads clearly in the Activities pane."
            ),
        },
    },
}


async def run(context: ToolContext, reason: str = "") -> ToolResult:
    resident = getattr(context, "preview", None)
    if resident is None:
        raise ToolError(
            "The preview is not wired up in this Aworg, so there is nothing "
            "to reload."
        )

    revision = resident()
    return ToolResult(
        text=(
            "The owner's preview will reload within a couple of seconds."
            + (f" ({reason.strip()})" if reason.strip() else "")
            + "\n\nThis asked a browser to fetch the page again. It is not "
            "evidence that the page is correct -- fetch it yourself if you "
            "need to know what it now says."
        ),
        summary=reason.strip()[:40] or f"revision {revision}",
    )
