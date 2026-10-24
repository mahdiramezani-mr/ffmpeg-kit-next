import ctypes as ct
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time


def native_library(root, platform):
    if platform == "windows":
        ct.windll.kernel32.SetErrorMode(0x8003)
        handle = os.add_dll_directory(str(root / "bin"))
        return ct.CDLL(str(next((root / "bin").glob("*ffmpegkit-*.dll")))), handle
    frameworks = []
    binary = None
    for framework in root.glob("*.xcframework"):
        libraries = plistlib.loads((framework / "Info.plist").read_bytes())["AvailableLibraries"]
        item = next(item for item in libraries if item["SupportedPlatform"] == "macos")
        folder = framework / item["LibraryIdentifier"]
        frameworks.append(str(folder))
        if framework.name == "ffmpegkit.xcframework":
            binary = folder / item["LibraryPath"] / "ffmpegkit"
    if not os.environ.get("STUDIO_SMOKE_CHILD"):
        env = dict(os.environ, DYLD_FRAMEWORK_PATH=os.pathsep.join(frameworks), STUDIO_SMOKE_CHILD="1")
        subprocess.run([sys.executable, __file__, *sys.argv[1:]], env=env, check=True, timeout=180)
        sys.exit(0)
    return ct.CDLL(str(binary)), None


def check(root, platform, wrapper_version, ffmpeg_tag):
    library, directory_handle = native_library(root, platform)
    signatures = {
        "ffk_string_free": (None, [ct.c_void_p]),
        "ffk_config_get_ffmpeg_version": (ct.c_void_p, []),
        "ffk_config_get_version": (ct.c_void_p, []),
        "ffk_ffmpegkit_execute_with_arguments": (ct.c_void_p, [ct.POINTER(ct.c_char_p), ct.c_size_t]),
        "ffk_ffmpegkit_execute_with_arguments_async": (ct.c_void_p, [ct.POINTER(ct.c_char_p), ct.c_size_t, *([ct.c_void_p] * 9)]),
        "ffk_session_get_return_code": (ct.c_int, [ct.c_void_p, ct.POINTER(ct.c_int)]),
        "ffk_session_get_output": (ct.c_void_p, [ct.c_void_p]),
        "ffk_session_cancel": (None, [ct.c_void_p]),
        "ffk_session_free": (None, [ct.c_void_p]),
    }
    for name, (returns, arguments) in signatures.items():
        function = getattr(library, name)
        function.restype, function.argtypes = returns, arguments

    def string(pointer):
        try:
            return ct.string_at(pointer).decode("utf-8", errors="replace") if pointer else ""
        finally:
            library.ffk_string_free(pointer)

    actual = string(library.ffk_config_get_ffmpeg_version())
    if ffmpeg_tag.removeprefix("n") not in actual:
        raise ValueError(f"Unexpected FFmpeg version: {actual}")
    actual = string(library.ffk_config_get_version())
    if actual != wrapper_version:
        raise ValueError(f"Unexpected wrapper version: {actual}")

    def execute(arguments):
        values = [value.encode("utf-8") for value in arguments]
        vector = (ct.c_char_p * len(values))(*values)
        session = library.ffk_ffmpegkit_execute_with_arguments(vector, len(values))
        if not session:
            raise ValueError("Native session creation failed")
        try:
            code = ct.c_int()
            present = library.ffk_session_get_return_code(session, ct.byref(code))
            output = string(library.ffk_session_get_output(session))
            if not present or code.value != 0:
                raise ValueError(f"FFmpeg failed ({code.value}): {output}")
            return output
        finally:
            library.ffk_session_free(session)

    encoders = execute(["-encoders"])
    if not all(name in encoders for name in ("libx264", "libx265", "libmp3lame")):
        raise ValueError("Missing Studio encoders")
    if "libdav1d" not in execute(["-decoders"]) or "zscale" not in execute(["-filters"]):
        raise ValueError("Missing dav1d/zimg")
    if not all(name in execute(["-protocols"]) for name in ("ffkitmem", "ffkitstream")):
        raise ValueError("Missing memory protocols")
    for expression in ("gblur=sigma=10:steps=3", "dblur=angle=45:radius=5:planes=7", "bilateral=planes=7"):
        for width in (572, 574):
            for pixel_format in ("yuv420p", "yuv420p10le"):
                execute(["-hide_banner", "-nostats", "-loglevel", "error", "-f", "lavfi", "-i",
                         f"testsrc2=size={width}x140:rate=30", "-filter_threads", "2", "-vf",
                         f"format={pixel_format},{expression}", "-frames:v", "30", "-f", "null", "-"])
    with tempfile.TemporaryDirectory() as directory:
        execute(["-y", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=2", "-frames:v", "2",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", str(Path(directory) / "smoke.mp4")])
    arguments = ["-re", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30", "-t", "120", "-f", "null", "-"]
    encoded = [value.encode("utf-8") for value in arguments]
    vector = (ct.c_char_p * len(encoded))(*encoded)
    session = library.ffk_ffmpegkit_execute_with_arguments_async(vector, len(encoded), *([None] * 9))
    if not session:
        raise ValueError("Native asynchronous session creation failed")
    time.sleep(1)
    code = ct.c_int()
    if library.ffk_session_get_return_code(session, ct.byref(code)):
        raise ValueError("Cancellation test finished before the request")
    library.ffk_session_cancel(session)
    deadline = time.monotonic() + 30
    while not library.ffk_session_get_return_code(session, ct.byref(code)):
        if time.monotonic() >= deadline:
            raise ValueError("Cancellation exceeded 30 seconds")
        time.sleep(0.05)
    try:
        if code.value != 255:
            raise ValueError(f"Cancellation returned {code.value}, expected 255")
    finally:
        library.ffk_session_free(session)
    if directory_handle:
        directory_handle.close()
    print(f"Native smoke passed on {platform}: versions, encoders, blur and cancellation")


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve(), *sys.argv[2:])
