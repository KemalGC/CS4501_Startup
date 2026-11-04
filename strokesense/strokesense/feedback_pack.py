"""Initial private study provisioning only. Never replace an existing study."""
from __future__ import annotations
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile
from .feedback import load_catalog, _path

MAX_UPLOAD = 750 * 1024**2
MAX_EXPANDED = 900 * 1024**2


def install_pack(archive: Path, data_dir: Path):
    target = data_dir / 'study'
    if target.exists():
        raise FileExistsError('study_already_initialized')
    with tempfile.TemporaryDirectory(prefix='.install-', dir=data_dir) as tmp:
        stage = Path(tmp) / 'study'
        stage.mkdir(mode=0o700)
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            if len(members) > 2000 or sum(i.file_size for i in members) > MAX_EXPANDED:
                raise ValueError('package_limits_exceeded')
            names = set()
            for info in members:
                p = PurePosixPath(info.filename)
                if (p.is_absolute() or '..' in p.parts or '\\' in info.filename
                        or ':' in info.filename or info.filename in names
                        or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                    raise ValueError('unsafe_package_path')
                names.add(info.filename)
            catalogs = [i for i in members if i.filename == 'catalog.json'
                        or i.filename.endswith('/study/catalog.json') or i.filename == 'study/catalog.json']
            if len(catalogs) != 1 or catalogs[0].file_size > 4 * 1024**2:
                raise ValueError('one_study_catalog_required')
            catalog = catalogs[0]
            prefix = catalog.filename[:-len('catalog.json')]
            raw = z.read(catalog)
            (stage / 'catalog.json').write_bytes(raw)
            parsed = load_catalog(stage / 'catalog.json')
            if not parsed['clips']:
                raise ValueError('empty_study')
            wanted = set()
            for clip in parsed['clips']:
                for kind in ('video', 'poster', 'report', 'annotated'):
                    name = clip.get(kind)
                    if not name:
                        continue
                    p = PurePosixPath(name)
                    allowed = {'video': {'.mp4', '.webm', '.mov'}, 'annotated': {'.mp4', '.webm'},
                               'poster': {'.jpg', '.jpeg', '.png'}, 'report': {'.html'}}[kind]
                    if any(x.startswith('.') for x in p.parts) or p.suffix.lower() not in allowed:
                        raise ValueError('unexpected_asset_type')
                    wanted.add(name)
            for name in sorted(wanted):
                dest = _path(stage, name)
                member = z.getinfo(prefix + name)
                if member.is_dir() or not 0 < member.file_size <= MAX_EXPANDED:
                    raise ValueError('missing_or_invalid_asset')
                dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                copied = 0
                with z.open(member) as source, dest.open('xb') as output:
                    while block := source.read(1024**2):
                        copied += len(block)
                        if copied > member.file_size:
                            raise ValueError('incorrect_asset_size')
                        output.write(block)
                dest.chmod(0o600)
                if copied != member.file_size:
                    raise ValueError('incomplete_asset')
            # Caller holds the single-process setup lock. Nothing from app/ or
            # .feedback/ is imported; the hosted app creates its own credentials.
            if target.exists():
                raise FileExistsError('study_already_initialized')
            os.rename(stage, target)
    return len(parsed['clips'])


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description='Initialize a private hosted study from a transferred ZIP; refuses replacement.')
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--data-dir', type=Path, default=Path('/var/data'))
    p.add_argument('--permission-confirmed', action='store_true', required=True)
    a = p.parse_args(argv)
    a.data_dir.mkdir(parents=True, exist_ok=True)
    count = install_pack(a.archive, a.data_dir)
    print(f'Installed {count} clips. Restart the service before inviting participants.')


if __name__ == '__main__':
    main()
