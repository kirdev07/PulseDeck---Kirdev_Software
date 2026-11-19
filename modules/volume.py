"""Exact Windows master volume (optional dependency: pycaw). Without it the phone uses volume keys.

IMPORTANT: comtypes/pycaw must be imported only inside the dedicated thread below. Importing comtypes
initializes COM as a single-threaded apartment for the importing thread, and in the API (asyncio) thread
that would freeze the WinRT "now playing" calls. All volume COM work therefore lives in one thread of its own.
"""
import importlib.util
from concurrent.futures import ThreadPoolExecutor

AVAILABLE = importlib.util.find_spec("pycaw") is not None and importlib.util.find_spec("comtypes") is not None

_executor = None
_audio = {}


def _init_thread():
    from pycaw.pycaw import AudioUtilities      # imports comtypes -> COM initialized for THIS thread only
    _audio["utilities"] = AudioUtilities


def _run(function, *args):
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pulse-volume", initializer=_init_thread)
    return _executor.submit(function, *args).result(timeout=5)


def _endpoint():
    return _audio["utilities"].GetSpeakers().EndpointVolume


def _get():
    endpoint = _endpoint()
    return {"level": round(endpoint.GetMasterVolumeLevelScalar() * 100), "muted": bool(endpoint.GetMute())}


def _set_level(level):
    _endpoint().SetMasterVolumeLevelScalar(level / 100.0, None)
    return level


def _adjust(delta):
    endpoint = _endpoint()
    level = max(0, min(100, round(endpoint.GetMasterVolumeLevelScalar() * 100) + delta))
    endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)
    return level


def _set_muted(muted):
    _endpoint().SetMute(1 if muted else 0, None)


def _meter_interface():
    """IAudioMeterInformation with every method (pycaw declares only GetPeakValue)."""
    if "meter_type" not in _audio:
        from ctypes import POINTER, c_float, c_uint
        from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

        class IAudioMeterInformationFull(IUnknown):
            _iid_ = GUID("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")
            _methods_ = (
                COMMETHOD([], HRESULT, "GetPeakValue", (["out"], POINTER(c_float), "pfPeak")),
                COMMETHOD([], HRESULT, "GetMeteringChannelCount", (["out"], POINTER(c_uint), "pnChannelCount")),
                COMMETHOD([], HRESULT, "GetChannelsPeakValues", (["in"], c_uint, "u32ChannelCount"),
                          (["in"], POINTER(c_float), "afPeakValues")),
                COMMETHOD([], HRESULT, "QueryHardwareSupport", (["out"], POINTER(c_uint), "pdwHardwareSupportMask")),
            )
        _audio["meter_type"] = IAudioMeterInformationFull
    return _audio["meter_type"]


def _levels():
    """What the speakers play right now: peak 0..1 overall, left and right (the first two channels)."""
    from ctypes import c_float
    meter = _audio.get("meter")
    if meter is None:
        from comtypes import CLSCTX_ALL
        speakers = _audio["utilities"].GetSpeakers()
        device = getattr(speakers, "_dev", speakers)
        kind = _meter_interface()
        meter = device.Activate(kind._iid_, CLSCTX_ALL, None).QueryInterface(kind)
        _audio["meter"] = meter
        _audio["channels"] = max(1, int(meter.GetMeteringChannelCount()))
    count = _audio["channels"]
    values = (c_float * count)()
    try:
        meter.GetChannelsPeakValues(count, values)
    except Exception:  # noqa: BLE001 - the output device changed: open the new one next time
        _audio.pop("meter", None)
        raise
    left = float(values[0])
    right = float(values[1]) if count > 1 else left
    return {"peak": max(left, right), "left": left, "right": right}


def levels():
    """{'peak', 'left', 'right'} 0..1 of the sound being played, or None without pycaw."""
    if not AVAILABLE:
        return None
    try:
        return _run(_levels)
    except Exception:
        return None


def get():
    """{'level': 0..100, 'muted': bool}, or None when exact volume is not available."""
    if not AVAILABLE:
        return None
    try:
        return _run(_get)
    except Exception:
        return None


def set_level(level):
    return _run(_set_level, max(0, min(100, int(level))))


def adjust(delta):
    return _run(_adjust, int(delta))


def set_muted(muted):
    _run(_set_muted, bool(muted))
