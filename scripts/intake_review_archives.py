"""Preserve and safely unpack the six user-submitted review archives. No bundled code runs."""
import hashlib,json,stat,subprocess,zipfile
from pathlib import Path,PurePosixPath

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'AI复核/反馈汇总_20261107'
ARCHIVES={'P01':'第1份_P01_已修改.zip','P02':'P02.zip','P03':'3(1).rar','P04':'第4份_P04_已修改.zip','P05':'P05_已修改版.zip','P06':'第6份_P06-修改后.zip'}
SEVEN=Path('C:/Program Files/7-Zip/7z.exe')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def safe_path(base,name):
    p=PurePosixPath(name.replace('\\','/'))
    if p.is_absolute() or any(x in {'..',''} or ':' in x for x in p.parts):raise ValueError('Unsafe archive path: '+name)
    dest=base.joinpath(*p.parts).resolve()
    if not dest.is_relative_to(base.resolve()):raise ValueError('Archive path escapes output')
    return dest
def run7(args):
    p=subprocess.run([str(SEVEN),*args],capture_output=True,encoding='utf-8',errors='strict')
    if p.returncode:raise RuntimeError(p.stdout+'\n'+p.stderr)
    return p.stdout
def unpack():
    OUT.mkdir(parents=True,exist_ok=True);report=[]
    for batch,name in ARCHIVES.items():
        src=ROOT/name;dest=OUT/'原始反馈'/batch;dest.mkdir(parents=True,exist_ok=True);entries=[]
        if src.suffix=='.zip':
            with zipfile.ZipFile(src) as z:
                for item in z.infolist():
                    target=safe_path(dest,item.filename)
                    if stat.S_ISLNK(item.external_attr>>16):raise ValueError('Symlink in archive')
                    if item.is_dir():continue
                    entries.append({'path':item.filename.replace('\\','/'),'size':item.file_size})
                if sum(x['size'] for x in entries)>500_000_000:raise ValueError('Unexpected archive size')
                for item in z.infolist():
                    if item.is_dir():continue
                    target=safe_path(dest,item.filename);target.parent.mkdir(parents=True,exist_ok=True)
                    content=z.read(item)
                    if target.exists() and target.read_bytes()!=content:raise ValueError('Existing extraction differs: '+str(target))
                    target.write_bytes(content)
        else:
            listing=run7(['l','-slt','-sccUTF-8','--',str(src)])
            detail=listing.split('----------',1)[1]
            for block in detail.strip().split('\n\n'):
                values=dict(line.split(' = ',1) for line in block.splitlines() if ' = ' in line)
                if 'Path' not in values:continue
                safe_path(dest,values['Path'])
                if any(values.get(k) for k in ['Symbolic Link','Hard Link','Copy Link']) or values.get('Alternate Stream')=='+':raise ValueError('Links/streams in RAR')
                if values.get('Folder')=='-':entries.append({'path':values['Path'].replace('\\','/'),'size':int(values['Size'])})
            if sum(x['size'] for x in entries)>500_000_000:raise ValueError('Unexpected RAR size')
            if any(dest.iterdir()):
                if not (OUT/'intake_manifest.json').exists():raise ValueError('RAR output already populated without receipt')
            else:run7(['x','-y','-sccUTF-8','-o'+str(dest),'--',str(src)])
        files=[]
        for entry in entries:
            p=safe_path(dest,entry['path']);assert p.is_file() and p.stat().st_size==entry['size']
            files.append(entry|{'sha256':sha(p)})
        report.append({'batch_id':batch,'archive':str(src),'archive_sha256':sha(src),'extracted_directory':str(dest),'files':files})
    (OUT/'intake_manifest.json').write_text(json.dumps({'archives':report,'untrusted_archive_content_executed':False},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'archives':len(report),'files':sum(len(x['files']) for x in report),'out':str(OUT)},ensure_ascii=False))
if __name__=='__main__':unpack()
