#!/usr/bin/env python3
"""Build-host inventory of bundled ELF libraries and unmodified license notices.

This records evidence, not a legal clearance or a corresponding-source offer.
Run after bundle_colmap.py, before the internal research package is built.
"""
import hashlib, json, shutil, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def main():
    runtime = ROOT / 'runtime/colmap'
    info = json.loads((runtime / 'BUILD_INFO.json').read_text())
    out = ROOT / 'licenses/colmap-runtime'
    out.mkdir(parents=True, exist_ok=True)
    owners = {}
    names = set(info['bundled_libraries'])
    for listing in Path('/var/lib/dpkg/info').glob('*.list'):
        if ':i386.' in listing.name:
            continue  # this runtime is ELF64 x86-64, not the host's optional 32-bit ABI
        for name in names.intersection(Path(line).name for line in listing.read_text(errors='replace').splitlines()):
            owners.setdefault(name, []).append(listing.name[:-5])
    records = []
    for name in sorted(names):
        packages = []
        notices = []
        for owner in owners.get(name, []):
            copyright = Path('/usr/share/doc') / owner.split(':')[0] / 'copyright'
            if copyright.is_file():
                target = out / (owner.replace(':','_') + '-copyright')
                shutil.copyfile(copyright, target)
                notices.append(target.name)
                packages.append(subprocess.check_output(['dpkg-query','-W','-f=${binary:Package} ${Version} source=${source:Package} ${source:Version}',owner],text=True))
        if name == 'libOpenImageIO.so.2.5' or name == 'libOpenImageIO_Util.so.2.5':
            notices, packages = ['OpenImageIO-LICENSE.md'], ['OpenImageIO 2.5.19.1 f32bf6e6f8de38ab6d197a72fd72366b66fd30a3 (custom minimal build)']
        if name == 'libcudart.so.12':
            notices, packages = ['CUDA-12.6-EULA'], ['conda-forge cuda-cudart 12.6.77 h5888daf_0']
        records.append(dict(library=name, sha256=hashlib.sha256((runtime/'lib'/name).read_bytes()).hexdigest(), build_packages=packages, notices=notices))
    for source, target in [
        (ROOT/'.build/oiio-src/LICENSE.md', 'OpenImageIO-LICENSE.md'),
        (ROOT/'.build/oiio-src/THIRD-PARTY.md', 'OpenImageIO-THIRD-PARTY.md'),
        (ROOT/'.build/oiio-src/CREDITS.md', 'OpenImageIO-CREDITS.md'),
        (ROOT/'.build/colmap-src/COPYING.txt', 'COLMAP-COPYING.txt'),
        (ROOT/'.build/colmap-build-dist/_deps/poselib-src/LICENSE', 'PoseLib-LICENSE'),
        (ROOT/'.build/colmap-build-dist/_deps/faiss-src/LICENSE', 'faiss-LICENSE'),
        (Path.home()/'anaconda3/pkgs/cuda-cudart-12.6.77-h5888daf_0/info/licenses/LICENSE', 'CUDA-12.6-EULA'),
    ]:
        shutil.copyfile(source, out/target)
    for name in ('GPL-2','GPL-3','LGPL-2.1','LGPL-3','Apache-2.0','GFDL-1.3'):
        shutil.copyfile(Path('/usr/share/common-licenses')/name, out/name)
    missing = [r['library'] for r in records if not r['notices']]
    used = {n for r in records for n in r['notices']}
    # Remove only this generator's obsolete package-notice copies (e.g. an i386
    # owner or a distro OIIO notice superseded by the actual custom-build text).
    for obsolete in out.glob('*-copyright'):
        if obsolete.name not in used:
            obsolete.unlink()
    (out/'inventory.json').write_text(json.dumps(dict(schema=1, colmap_commit=info['commit'], libraries=records, unresolved_notices=missing, public_redistribution='BLOCKED: corresponding-source/relinking and legal compatibility review pending'),indent=2)+'\n')
    if missing: raise SystemExit(f'Unresolved license notices: {missing}')
    print(f'{len(records)} bundled libraries inventoried; public redistribution remains BLOCKED')

if __name__ == '__main__': main()
