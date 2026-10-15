"""Build a source-and-evidence ZIP, excluding local tooling and bytecode."""

from pathlib import Path
import hashlib
import json
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]


def main():
    archive=ROOT.parent/'vector-can-door-alert_2026-10-15.zip'
    excluded={'.git','.verification-venv','.verification-deps','.venv','__pycache__'}
    files=[]
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT)
        if any(p in excluded for p in rel.parts):continue
        if path.is_file() and path.suffix not in {'.pyc','.pyo','.log'}:
            files.append(path)
    manifest={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    with ZipFile(archive,'w',ZIP_DEFLATED) as z:
        for path in files:
            z.write(path,'vector-can-door-alert/'+path.relative_to(ROOT).as_posix())
        z.writestr('vector-can-door-alert/SHA256SUMS.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    with ZipFile(archive) as z:
        assert z.testzip() is None
        for name,digest in manifest.items():
            assert hashlib.sha256(z.read('vector-can-door-alert/'+name)).hexdigest()==digest,name
        assert len(z.namelist())==len(files)+1
    print(json.dumps({'archive':str(archive),'source_and_evidence_files':len(files),
                      'bytes':archive.stat().st_size,'crc_and_sha256':'passed'},ensure_ascii=False))


if __name__=='__main__':main()
