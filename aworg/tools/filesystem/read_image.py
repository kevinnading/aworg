"""Look at a picture the owner left in the workspace.

The Resident could see a page it opened in a browser and not a PNG sitting in
its own workspace, which is the wrong way round: a mockup to match, a design
exported from somewhere, a chart in an email, a photograph of an error on a
phone screen. Those are how people hand over what they mean, and `read_file`
answered every one of them with "that is not UTF-8 text".

Nothing was hard about reading the bytes. What has limits is *sending* them,
and the limits belong to the model provider rather than to AWORG: Anthropic
refuses an image over about five megabytes, OpenAI takes considerably more,
and both scale the picture down themselves before charging for it. That last
part is the one worth knowing -- a ten-megabyte screenshot costs the same
tokens as a one-megabyte one, because the provider resizes it either way. So
the ceiling here is generous and exists only to stop something absurd being
turned into base64 and posted.

Dimensions are read out of the file's own header rather than decoded, which
takes thirty lines and no library, and means a refusal can say *why*: "8000
by 6000" is a fact the Resident can act on by asking for a smaller export.
"""

from __future__ import annotations

import base64
import struct
from pathlib import Path

from ..base import ToolContext, ToolError, ToolResult, resolve_path


NAME = "read_image"

DESCRIPTION = (
    "Look at an image file: PNG, JPEG, GIF or WebP. You see the image itself."
)

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "The image to look at. A relative path is inside the Living "
                "Workspace."
            ),
        },
    },
    "required": ["path"],
}

#: What may be sent. Not a token budget -- providers resize before charging,
#: so a large file costs no more than a small one -- but an upload this size
#: is already past what any of them accept, and posting it would waste a
#: minute to be refused.
MAX_BYTES = 10 * 1024 * 1024

#: What each format's first bytes look like, and what to call it afterwards.
KINDS = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


async def run(context: ToolContext, path: str) -> ToolResult:
    target = resolve_path(context, path)
    if not target.exists():
        raise ToolError(f"There is nothing at {target}.")
    if not target.is_file():
        raise ToolError(f"{target} is a directory, not an image.")

    size = target.stat().st_size
    if size > MAX_BYTES:
        raise ToolError(
            f"{target.name} is {size / 1024 / 1024:.1f} MB, past the "
            f"{MAX_BYTES // 1024 // 1024} MB a model will accept. Ask for a "
            "smaller export, or open it in a browser and screenshot it."
        )
    if size == 0:
        raise ToolError(f"{target.name} is empty.")

    try:
        data = target.read_bytes()
    except OSError as exc:
        raise ToolError(f"Could not read {target}: {exc}") from exc

    media_type = _kind(data)
    if media_type is None:
        raise ToolError(
            f"{target.name} is not an image this can read -- its contents are "
            "not PNG, JPEG, GIF or WebP, whatever it is called. For text, "
            "use read_file."
        )

    shape = _dimensions(data, media_type)
    said = f"{target} -- {media_type.split('/')[1].upper()}"
    if shape:
        said += f", {shape[0]} by {shape[1]}"
    said += f", {size / 1024:.0f} KB. Here it is:"

    return ToolResult(
        text=said,
        payload={"path": str(target), "bytes": size,
                 "media_type": media_type,
                 "width": shape[0] if shape else None,
                 "height": shape[1] if shape else None},
        summary=(f"{shape[0]}x{shape[1]}" if shape else media_type)
        + f", {size // 1024} KB",
        images=[{"media_type": media_type,
                 "data": base64.b64encode(data).decode("ascii")}],
    )


def _kind(data: bytes) -> str | None:
    """What this actually is, from its first bytes rather than its name.

    A file called .png that is really a JPEG is common enough -- anything
    that has been through a screenshot tool and a rename -- and a media type
    taken from the extension would be a lie told to the model provider,
    which then refuses the whole request.
    """
    for magic, media_type in KINDS:
        if data.startswith(magic):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _dimensions(data: bytes, media_type: str) -> tuple[int, int] | None:
    """Width and height, read from the header. None if it cannot be found.

    Best-effort by design: the size of the picture is useful context and
    never the point, so a header this does not understand costs a line of
    output rather than the image.
    """
    try:
        if media_type == "image/png":
            # IHDR is always the first chunk, at a fixed offset.
            return struct.unpack(">II", data[16:24])
        if media_type == "image/gif":
            return struct.unpack("<HH", data[6:10])
        if media_type == "image/webp":
            if data[12:16] == b"VP8X":
                return (
                    int.from_bytes(data[24:27], "little") + 1,
                    int.from_bytes(data[27:30], "little") + 1,
                )
            if data[12:16] == b"VP8 ":
                return struct.unpack("<HH", data[26:30])
            if data[12:16] == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            return None
        if media_type == "image/jpeg":
            return _jpeg_size(data)
    except (struct.error, IndexError, ValueError):
        return None
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """Walk the segments to the frame header, which carries the size.

    JPEG has no fixed place for it: the file is a chain of segments and the
    dimensions live in whichever start-of-frame marker turns up, which
    depends on how it was encoded.
    """
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        # The start-of-frame markers, minus the four that are not frames.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[index + 5:index + 9])
            return width, height
        length = struct.unpack(">H", data[index + 2:index + 4])[0]
        index += 2 + length
    return None
