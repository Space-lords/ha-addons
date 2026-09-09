#!/usr/bin/env python3
"""Build-time patches to the installed `ledfx` Python package.

Patches:
1. Audio delay / Sendspin-reset fix.
2. De-Blade effect display names.
3. Temporary Sendspin/FLAC data-flow diagnostics.
"""

from __future__ import annotations

import glob
import os

import ledfx

ROOT = os.path.dirname(ledfx.__file__)

# ---------------------------------------------------------------------------
# 1. Audio delay / Sendspin-reset fix
# ---------------------------------------------------------------------------

AUDIO_ANCHOR = "new_config = self.AUDIO_CONFIG_SCHEMA.fget()(config)"

AUDIO_MERGE = (
    'if hasattr(self, "_config") and isinstance(self._config, dict):\n'
    "            config = {**self._config, **config}\n"
    "        " + AUDIO_ANCHOR
)

AUDIO_DONE_MARK = "{**self._config, **config}"

# ---------------------------------------------------------------------------
# 2. De-Blade effect display names
# ---------------------------------------------------------------------------

BLADE_NAME_PREFIX = 'NAME = "Blade '

# ---------------------------------------------------------------------------
# 3. Temporary Sendspin/FLAC diagnostics
# ---------------------------------------------------------------------------

SENDSPIN_DEBUG_MARK = "SPACELORDS_SENDSPIN_DEBUG_V1"


def patch_audio_delay() -> None:
    path = os.path.join(ROOT, "effects", "audio.py")

    with open(path, encoding="utf-8") as handle:
        src = handle.read()

    if AUDIO_DONE_MARK in src:
        print("[patch-backend] audio delay fix: already applied")
        return

    hits = src.count(AUDIO_ANCHOR)

    if hits != 1:
        print(
            f"[patch-backend] WARNING: audio delay anchor found "
            f"{hits}x (expected 1) - NOT patching"
        )
        return

    src = src.replace(AUDIO_ANCHOR, AUDIO_MERGE, 1)

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(src)

    print(
        "[patch-backend] audio delay fix: "
        "merged delta over existing config before validation"
    )


def patch_effect_names() -> None:
    total = 0

    for path in glob.glob(os.path.join(ROOT, "effects", "*.py")):
        with open(path, encoding="utf-8") as handle:
            src = handle.read()

        n = src.count(BLADE_NAME_PREFIX)

        if not n:
            continue

        src = src.replace(BLADE_NAME_PREFIX, 'NAME = "')

        with open(path, "w", encoding="utf-8") as handle:
            handle.write(src)

        total += n

        print(
            f"[patch-backend] de-Blade effect name in "
            f"{os.path.basename(path)}: {n}"
        )

    if not total:
        print(
            "[patch-backend] note: no 'NAME = \"Blade ' "
            "effect names found (may already be patched)"
        )


def patch_sendspin_debug() -> None:
    """Add temporary diagnostics to ledfx/sendspin/stream.py.

    This patch deliberately does not change Sendspin/FLAC behaviour.
    It only records:
      - incoming Sendspin chunks
      - entry/exit of FLAC decoder.process()
      - pyFLAC callbacks
      - scheduling buffer state
      - LedFx audio callback delivery
    """

    path = os.path.join(ROOT, "sendspin", "stream.py")

    with open(path, encoding="utf-8") as handle:
        src = handle.read()

    if SENDSPIN_DEBUG_MARK in src:
        print(
            "[patch-backend] Sendspin debug: already applied"
        )
        return

    # ---------------------------------------------------------------
    # A. Add debug counters to __init__
    # ---------------------------------------------------------------

    anchor = (
        '        self._heartbeat_task = None  # type: Optional[asyncio.Task]\n'
    )

    replacement = (
        anchor
        + "\n"
        + "        # SPACELORDS_SENDSPIN_DEBUG_V1\n"
        + "        self._debug_chunk_count = 0\n"
        + "        self._debug_flac_block_count = 0\n"
        + "        self._debug_callback_count = 0\n"
        + "        self._debug_last_chunk_mono = None\n"
    )

    hits = src.count(anchor)

    if hits != 1:
        print(
            f"[patch-backend] WARNING: Sendspin __init__ anchor "
            f"found {hits}x (expected 1) - NOT patching"
        )
        return

    src = src.replace(anchor, replacement, 1)

    # ---------------------------------------------------------------
    # B. Log every incoming audio chunk
    # ---------------------------------------------------------------

    anchor = (
        "        now_mono = time.monotonic()\n"
        "        self._last_audio_chunk_time = now_mono\n"
        "        self._expecting_audio = True\n"
    )

    replacement = (
        "        now_mono = time.monotonic()\n"
        "        self._last_audio_chunk_time = now_mono\n"
        "        self._expecting_audio = True\n"
        "\n"
        "        # SPACELORDS_SENDSPIN_DEBUG_V1\n"
        "        self._debug_chunk_count += 1\n"
        "        chunk_no = self._debug_chunk_count\n"
        "        if self._debug_last_chunk_mono is None:\n"
        "            delta_ms = 0.0\n"
        "        else:\n"
        "            delta_ms = (\n"
        "                now_mono - self._debug_last_chunk_mono\n"
        "            ) * 1000.0\n"
        "        self._debug_last_chunk_mono = now_mono\n"
        "\n"
        "        _LOGGER.warning(\n"
        "            \"SENDSPIN DEBUG chunk #%d received: bytes=%d \"\n"
        "            \"codec=%s delta_ms=%.1f\",\n"
        "            chunk_no,\n"
        "            len(chunk_data),\n"
        "            getattr(audio_format, \"codec\", \"unknown\"),\n"
        "            delta_ms,\n"
        "        )\n"
    )

    hits = src.count(anchor)

    if hits != 1:
        print(
            f"[patch-backend] WARNING: Sendspin chunk anchor "
            f"found {hits}x (expected 1) - NOT patching"
        )
        return

    src = src.replace(anchor, replacement, 1)

    # ---------------------------------------------------------------
    # C. Log FLAC process START / END
    # ---------------------------------------------------------------

    anchor = (
        "                try:\n"
        "                    self._flac_decoder.process(chunk_data)\n"
        "                except Exception as e:\n"
    )

    replacement = (
        "                try:\n"
        "                    # SPACELORDS_SENDSPIN_DEBUG_V1\n"
        "                    _LOGGER.warning(\n"
        "                        \"SENDSPIN DEBUG chunk #%d -> \"\n"
        "                        \"FLAC process START bytes=%d\",\n"
        "                        chunk_no,\n"
        "                        len(chunk_data),\n"
        "                    )\n"
        "                    _flac_process_start = time.monotonic()\n"
        "\n"
        "                    self._flac_decoder.process(chunk_data)\n"
        "\n"
        "                    _LOGGER.warning(\n"
        "                        \"SENDSPIN DEBUG chunk #%d -> \"\n"
        "                        \"FLAC process END duration_ms=%.2f\",\n"
        "                        chunk_no,\n"
        "                        (time.monotonic() - _flac_process_start) * 1000.0,\n"
        "                    )\n"
        "                except Exception as e:\n"
    )

    hits = src.count(anchor)

    if hits != 1:
        print(
            f"[patch-backend] WARNING: FLAC process anchor "
            f"found {hits}x (expected 1) - NOT patching"
        )
        return

    src = src.replace(anchor, replacement, 1)

    # ---------------------------------------------------------------
    # D. Log every pyFLAC callback
    # ---------------------------------------------------------------

    anchor = (
        "        try:\n"
        "            if not self._flac_fmt_logged:\n"
    )

    replacement = (
        "        try:\n"
        "            # SPACELORDS_SENDSPIN_DEBUG_V1\n"
        "            self._debug_flac_block_count += 1\n"
        "            _flac_block_no = self._debug_flac_block_count\n"
        "            _LOGGER.warning(\n"
        "                \"SENDSPIN DEBUG pyFLAC block #%d: \"\n"
        "                \"shape=%s dtype=%s rate=%d channels=%d samples=%d\",\n"
        "                _flac_block_no,\n"
        "                audio.shape,\n"
        "                audio.dtype,\n"
        "                sample_rate,\n"
        "                num_channels,\n"
        "                num_samples,\n"
        "            )\n"
        "\n"
        "            if not self._flac_fmt_logged:\n"
    )

    hits = src.count(anchor)

    if hits != 1:
        print(
            f"[patch-backend] WARNING: pyFLAC callback anchor "
            f"found {hits}x (expected 1) - NOT patching"
        )
        return

    src = src.replace(anchor, replacement, 1)

    # ---------------------------------------------------------------
    # E. Log scheduling result
    # ---------------------------------------------------------------

    anchor = (
        "            self._schedule_mono_samples(\n"
        "                mono, current_play_time_us, sample_rate\n"
        "            )\n"
    )

    replacement = (
        "            self._schedule_mono_samples(\n"
        "                mono, current_play_time_us, sample_rate\n"
        "            )\n"
        "\n"
        "            # SPACELORDS_SENDSPIN_DEBUG_V1\n"
        "            with self._buffer_lock:\n"
        "                _buffer_len = len(self._chunk_buffer)\n"
        "            _LOGGER.warning(\n"
        "                \"SENDSPIN DEBUG pyFLAC block #%d scheduled: \"\n"
        "                \"buffer_chunks=%d\",\n"
        "                _flac_block_no,\n"
        "                _buffer_len,\n"
        "            )\n"
    )

    hits = src.count(anchor)

    if hits != 1:
        print(
            f"[patch-backend] WARNING: scheduling anchor "
            f"found {hits}x (expected 1) - NOT patching"
        )
        return

    src = src.replace(anchor, replacement, 1)

    # ---------------------------------------------------------------
    # F. Log delivery to LedFx audio callback
    # ---------------------------------------------------------------

    anchor = (
        "                try:\n"
        "                    self.callback(chunk, len(chunk), None, None)\n"
        "                except Exception as e:\n"
    )

    replacement = (
        "                try:\n"
        "                    # SPACELORDS_SENDSPIN_DEBUG_V1\n"
        "                    self._debug_callback_count += 1\n"
        "                    _LOGGER.warning(\n"
        "                        \"SENDSPIN DEBUG LedFx callback #%d: \"\n"
        "                        \"samples=%d remaining_buffer=%d\",\n"
        "                        self._debug_callback_count,\n"
        "                        len(chunk),\n"
        "                        len(self._chunk_buffer),\n"
        "                    )\n"
        "                    self.callback(chunk, len(chunk), None, None)\n"
        "                except Exception as e:\n"
    )

    hits = src.count(anchor)

    if hits != 1:
        print(
            f"[patch-backend] WARNING: LedFx callback anchor "
            f"found {hits}x (expected 1) - NOT patching"
        )
        return

    src = src.replace(anchor, replacement, 1)

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(src)

    print(
        "[patch-backend] Sendspin debug diagnostics installed"
    )


if __name__ == "__main__":
    patch_audio_delay()
    patch_effect_names()
    patch_sendspin_debug()
