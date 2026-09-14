"""Compressing an already-compressed PNG must be a no-op.

pngquant is lossy and, for a .png input, writes back over the same path with
--force. The publish pipeline makes repeat passes easy to hit: .last_build only
moves forward after a successful push, so an abort at preflight or a failed
hugo build leaves every image still "modified", and the next run quantizes them
all again — a little more quality gone per aborted run.

The guard reads the PNG IHDR colour type directly, so these tests need neither
Pillow nor pngquant installed.
"""

from unittest.mock import patch

import compress_image

PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_header(colour_type: int) -> bytes:
    """A PNG prefix long enough for the guard: signature + IHDR through colour type."""
    return (
        PNG_SIG
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + (8).to_bytes(4, "big")      # width
        + (8).to_bytes(4, "big")      # height
        + bytes([8])                  # bit depth
        + bytes([colour_type])
    )


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_palette_png_is_recognised(tmp_path):
    assert compress_image._is_palette_png(_write(tmp_path, "p.png", _png_header(3)))


def test_truecolour_pngs_are_not_palette(tmp_path):
    for colour_type in (0, 2, 4, 6):  # grey, RGB, grey+alpha, RGBA
        path = _write(tmp_path, f"c{colour_type}.png", _png_header(colour_type))
        assert not compress_image._is_palette_png(path)


def test_non_png_and_damaged_inputs_are_not_palette(tmp_path):
    assert not compress_image._is_palette_png(_write(tmp_path, "a.png", b"not a png at all"))
    assert not compress_image._is_palette_png(_write(tmp_path, "b.png", PNG_SIG))  # truncated
    assert not compress_image._is_palette_png(str(tmp_path / "missing.png"))


def test_already_palettised_png_is_not_reencoded(tmp_path):
    """The whole point: no pngquant subprocess for an already-quantized file."""
    path = _write(tmp_path, "done.png", _png_header(3))
    with patch.object(compress_image.subprocess, "run",
                      side_effect=AssertionError("must not re-quantize")):
        compress_image.compress_with_pngquant(path)


def test_truecolour_png_still_gets_compressed(tmp_path):
    """The guard must not turn compression off for images that need it."""
    path = _write(tmp_path, "fresh.png", _png_header(6))
    with patch.object(compress_image.subprocess, "run") as run:
        compress_image.compress_with_pngquant(path)
    assert run.call_count == 1
    assert run.call_args[0][0][0] == "pngquant"
