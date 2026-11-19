"""Assemble official GStreamer wheels for a Python-free native application.

GNU import libraries are generated from the DLL's public PE export table. This
uses system-deps' documented manual-link configuration; no C headers or Python
bindings are needed by the pre-generated Rust FFI bindings.
"""
import argparse
from pathlib import Path
import os
import shutil
import struct
import subprocess
import zipfile

LIBRARIES = {
    "GLIB_2_0": "glib-2.0", "GOBJECT_2_0": "gobject-2.0", "GIO_2_0": "gio-2.0",
    "GSTREAMER_1_0": "gstreamer-1.0", "GSTREAMER_BASE_1_0": "gstbase-1.0",
    "GSTREAMER_APP_1_0": "gstapp-1.0", "GSTREAMER_VIDEO_1_0": "gstvideo-1.0",
}
PREVIEW_PLUGINS = (
    'coreelements','app','playback','typefindfunctions','videoconvertscale',
    'videorate','videocrop','isomp4','matroska','avi','videoparsersbad',
    'libav','jpeg','png','rawparse','audioparsers','audioconvert',
    'audioresample','ogg','opus','vorbis','d3d11',
)

def exports(path):
    data = path.read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    count = struct.unpack_from('<H', data, pe + 6)[0]
    opt_size = struct.unpack_from('<H', data, pe + 20)[0]
    opt = pe + 24
    directory = opt + (112 if struct.unpack_from('<H', data, opt)[0] == 0x20b else 96)
    export_rva, export_size = struct.unpack_from('<II', data, directory)
    sections = []
    for n in range(count):
        offset = opt + opt_size + n * 40
        size, address, raw_size, raw = struct.unpack_from('<IIII', data, offset + 8)
        flags = struct.unpack_from('<I', data, offset + 36)[0]
        sections.append((address, max(size, raw_size), raw, flags))
    def offset(rva):
        for address, size, raw, _ in sections:
            if address <= rva < address + size:
                return raw + rva - address
        raise ValueError(f'Unmapped PE address {rva:x} in {path}')
    table = struct.unpack_from('<IIHHIIIIIII', data, offset(export_rva))
    functions, names, ordinals = table[8:11]
    for n in range(table[7]):
        name = struct.unpack_from('<I', data, offset(names) + n * 4)[0]
        start = offset(name)
        symbol = data[start:data.index(b'\0', start)].decode('ascii')
        ordinal = struct.unpack_from('<H', data, offset(ordinals) + n * 2)[0]
        address = struct.unpack_from('<I', data, offset(functions) + ordinal * 4)[0]
        forwarded = export_rva <= address < export_rva + export_size
        executable = any(a <= address < a + size and flags & 0x20000000 for a, size, _, flags in sections)
        yield symbol, not executable and not forwarded

def prepare(wheels, output, dlltool):
    output.mkdir(parents=True, exist_ok=True)
    for wheel in sorted(wheels.glob('gstreamer_*.whl')):
        # GPL DVD/audio plugins are unused by the video preview.
        if wheel.name.startswith('gstreamer_plugins_gpl-'):
            continue
        with zipfile.ZipFile(wheel) as archive:
            for item in archive.infolist():
                parts = Path(item.filename).parts
                if '.data/purelib/' in item.filename:
                    position = next((i for i, value in enumerate(parts) if value in ('bin','lib','libexec','share')), None)
                    if position is None or item.is_dir():
                        continue
                    target = output.joinpath(*parts[position:])
                elif '.dist-info/' in item.filename and not item.is_dir():
                    target = output / 'share' / 'wheel-notices' / wheel.stem / item.filename
                else:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open('wb') as destination:
                    shutil.copyfileobj(source, destination)
    lib = output / 'lib'
    lib.mkdir(exist_ok=True)
    preview_plugins = lib / 'gstreamer-1.0-preview'
    preview_plugins.mkdir(exist_ok=True)
    for plugin in PREVIEW_PLUGINS:
        source = lib / 'gstreamer-1.0' / f'gst{plugin}.dll'
        if source.is_file():
            shutil.copy2(source, preview_plugins / source.name)
    for library in LIBRARIES.values():
        dll = output / 'bin' / f'{library}-0.dll'
        definition = lib / f'{library}.def'
        definition.write_text('LIBRARY "' + dll.name + '"\nEXPORTS\n' + '\n'.join(name + (' DATA' if data else '') for name, data in exports(dll)) + '\n')
        result = subprocess.run([str(dlltool), '-d', str(definition), '-D', dll.name, '-l', str(lib / f'lib{library}.dll.a'), '-m', 'i386:x86-64'], check=True, capture_output=True, text=True)
        if result.stderr.strip():
            raise RuntimeError(result.stderr)
    lines = [f"$env:PAL_VHS_GSTREAMER_ROOT = '{str(output.resolve()).replace(chr(39), chr(39)*2)}'",
             "$env:PATH = (Join-Path $env:PAL_VHS_GSTREAMER_ROOT 'bin') + ';' + $env:PATH"]
    for name, library in LIBRARIES.items():
        lines.extend([f"$env:SYSTEM_DEPS_{name}_NO_PKG_CONFIG = '1'",
                      f"$env:SYSTEM_DEPS_{name}_LIB = '{library}'",
                      f"$env:SYSTEM_DEPS_{name}_SEARCH_NATIVE = Join-Path $env:PAL_VHS_GSTREAMER_ROOT 'lib'"])
    (output / 'build-env.ps1').write_text('\n'.join(lines) + '\n')
    print(f'Prepared native GStreamer runtime and 7 GNU import libraries in {output}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheels', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dlltool', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.wheels, args.output, args.dlltool.resolve())
