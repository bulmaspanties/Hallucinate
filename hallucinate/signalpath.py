"""What happens to the sound between the file and the speakers, for the signal path readout.

`describe` is pure so it can be tested without audio hardware; the Player feeds it its current state."""
import math

from .core.insights import LOSSLESS


def _rate(hz):
    return f"{hz / 1000:.1f}".rstrip("0").rstrip(".") + " kHz" if hz else ""


def describe(track, *, rg_factor=1.0, rg_mode="off", volume=1.0, speed=1.0, eq_enabled=False, eq_preset="",
             crossfade=0, device_name="", device_rate=0):
    """Stages from the file to the output, each {"name", "detail", "active"} where active means it changes the
    sound, and whether the path is untouched: nothing between file and device alters the samples (the system
    mixer may still resample when the device runs at another rate, which is reported too)."""
    if not track:
        return {"stages": [], "untouched": False, "summary": ""}
    codec = (track.get("codec") or track.get("fmt") or "").upper()
    rate = int(track.get("sample_rate") or 0)
    lossless = codec in LOSSLESS
    source = [codec] if codec else []
    if rate:
        source.append(_rate(rate))
    if not lossless and track.get("bitrate"):
        source.append(f"{round(track['bitrate'] / 1000)} kbps")
    stages = [{"name": "Source", "detail": "  ·  ".join(source) + ("  ·  lossless" if lossless else ""),
               "active": False}]

    rg_db = 20 * math.log10(rg_factor) if rg_factor > 0 else 0.0
    rg_on = rg_mode in ("track", "album") and abs(rg_db) >= 0.05
    if rg_mode in ("track", "album"):
        detail = f"{rg_mode.capitalize()} gain {rg_db:+.1f} dB" if rg_on else f"{rg_mode.capitalize()} gain: none tagged"
    else:
        detail = "Off"
    stages.append({"name": "ReplayGain", "detail": detail, "active": rg_on})

    eq_on = bool(eq_enabled)
    stages.append({"name": "Equalizer", "detail": (eq_preset or "Custom") if eq_on else "Off", "active": eq_on})

    speed_on = abs(speed - 1.0) > 1e-3
    stages.append({"name": "Speed", "detail": f"{speed:g}×" if speed_on else "Normal", "active": speed_on})

    vol_on = volume < 0.999
    stages.append({"name": "Volume", "detail": f"{round(volume * 100)}%", "active": vol_on})

    if crossfade:
        stages.append({"name": "Crossfade", "detail": f"{crossfade} s between tracks", "active": False})

    resampled = bool(rate and device_rate and rate != device_rate)
    out = [device_name or "System default"]
    if device_rate:
        out.append(_rate(device_rate) + (f" (resampled from {_rate(rate)})" if resampled else ""))
    stages.append({"name": "Output", "detail": "  ·  ".join(out), "active": resampled})

    changed = [s["name"] for s in stages if s["active"]]
    untouched = not changed
    summary = "Untouched" if untouched else "Changed by " + ", ".join(n.lower() for n in changed).replace(
        "output", "resampling")
    return {"stages": stages, "untouched": untouched, "summary": summary}
