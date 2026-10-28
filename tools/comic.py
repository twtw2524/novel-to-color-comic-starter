"""Portable, bounded comic workspace. No model/API calls, no global config writes."""
from __future__ import annotations
import argparse, base64, contextlib, hashlib, html, json, os, re, shutil, struct, sys, time, zipfile
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET
from compile_comic_prompt import compile_prompt

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,v):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.tmp-'+str(os.getpid())); t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); t.replace(p)
def inside(root,value):
    p=(root/value).resolve(); p.relative_to(root.resolve()); return p
def ident(s):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,60}',s): raise ValueError('ID needs lowercase letters, digits or hyphens')
    return s
class Text(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self,t,a):
        if t in ('script','style'): self.skip+=1
        if t in ('p','br','div','h1','h2','h3','li'): self.parts.append('\n')
    def handle_endtag(self,t):
        if t in ('script','style'): self.skip=max(0,self.skip-1)
        if t in ('p','div','h1','h2','h3','li'): self.parts.append('\n')
    def handle_data(self,d):
        if not self.skip: self.parts.append(d)
def plain(s):
    p=Text(); p.feed(s); return ''.join(p.parts)
def ingest(root,path):
    src=Path(path).resolve(); digest=sha(src); dst=root/'sources'/digest[:12]
    if dst.exists(): return read(dst/'inventory.json')
    units=[]; ext=src.suffix.lower()
    if ext=='.txt': units=[(src.name,src.read_text(encoding='utf-8-sig'))]
    elif ext in ('.html','.htm'): units=[(src.name,plain(src.read_text(encoding='utf-8-sig')))]
    elif ext=='.epub':
        import posixpath
        with zipfile.ZipFile(src) as z:
            if z.testzip(): raise ValueError('EPUB CRC failed')
            c=ET.fromstring(z.read('META-INF/container.xml'))
            opf=next(x.attrib['full-path'] for x in c.iter() if x.tag.endswith('rootfile'))
            package=ET.fromstring(z.read(opf)); manifest={x.attrib['id']:x.attrib for x in package.iter() if x.tag.endswith('}item')}
            for x in package.iter():
                if x.tag.endswith('}itemref'):
                    a=manifest[x.attrib['idref']]; name=posixpath.normpath(posixpath.join(posixpath.dirname(opf),a['href'].split('#')[0]))
                    units.append((name,plain(z.read(name).decode('utf-8-sig'))))
    elif ext=='.pdf':
        try: from pypdf import PdfReader
        except ImportError: raise ValueError('PDF requires pypdf in this interpreter; ask AI to install into project .venv')
        pdf=PdfReader(src)
        if pdf.is_encrypted: raise ValueError('Encrypted PDF: provide an accessible file you may use')
        units=[('PDF page '+str(i+1),p.extract_text() or '') for i,p in enumerate(pdf.pages)]
    else: raise ValueError('Supported: UTF-8 TXT/HTML, unencrypted EPUB, text PDF. Scans require separate GPU OCR.')
    records=[]
    for i,(locator,text) in enumerate(units,1):
        paragraphs=[{'id':f'p{j:04d}','text':line.strip()} for j,line in enumerate([x for x in text.splitlines() if x.strip()],1)]
        if not paragraphs: continue
        records.append({'unit_id':f'u{i:04d}','locator':locator,'paragraphs':len(paragraphs),'preview':paragraphs[0]['text'][:80]})
    if not records: raise ValueError('NO_READABLE_TEXT: use a UTF-8 TXT or selectable-text file; no automatic OCR')
    dst.mkdir(parents=True); shutil.copyfile(src,dst/('original'+ext))
    for row in records:
        i=int(row['unit_id'][1:])-1; text=units[i][1]
        write(dst/(row['unit_id']+'.json'),{'paragraphs':[{'id':f'p{j:04d}','text':line.strip()} for j,line in enumerate([x for x in text.splitlines() if x.strip()],1)]})
    result={'source_sha256':digest,'original_name':src.name,'units':records,'images':'EPUB illustrations remain in original archive. AI must inspect/copy selected images and record their rights, identity and SHA.'}
    write(dst/'inventory.json',result); return result
def init(root,sample):
    root.mkdir(parents=True,exist_ok=True)
    if (root/'control.json').exists(): raise ValueError('WORKSPACE_EXISTS: resume; initialization does not overwrite')
    for d in ('sources','episodes','exports'): (root/d).mkdir(exist_ok=True)
    write(root/'control.json',{'hold':True,'generation_authorized':False,'episode':None,'max_attempts':2})
    if sample:
        bundle=Path(__file__).resolve().parents[1]/'samples'
        shutil.copytree(bundle,root/'sample',dirs_exist_ok=False)
    return {'workspace':str(root),'hold':True,'next':'Inspect sample/episode.json, then plan --episode sample/episode.json'}
def plan(root,episode):
    data=read(inside(root,episode)); eid=ident(data['episode']); pages=data['pages']; ids=[ident(x['id']) for x in pages]
    if len(ids)!=len(set(ids)): raise ValueError('DUPLICATE_PAGE')
    target=root/'episodes'/eid
    if target.exists(): raise ValueError('EPISODE_EXISTS: preserve it; use a new explicit episode ID for new scope')
    prompts=[]
    for page in pages:
        spec=read(inside(root,page['spec'])); refs=read(inside(root,page['references'])); source=read(inside(root,page['source_map']))
        prompts.append((page,compile_prompt(spec,refs,source,root)))
    target.mkdir(parents=True)
    for page,prompt in prompts:
        p=target/page['id'];p.mkdir(); (p/'prompt.txt').write_text(prompt,encoding='utf-8')
        refs=read(inside(root,page['references']))
        write(p/'input.json',{'page':page,'prompt_sha256':sha(p/'prompt.txt'),'bindings':{k:sha(inside(root,page[k])) for k in ('spec','references','source_map')},'reference_images':{r['path']:sha(inside(root,r['path'])) for r in refs['references']}})
    write(target/'episode.json',data)
    return {'episode':eid,'pages':ids,'next':'authorize --episode '+eid+' only after confirming this exact finite scope'}
def bind(root,p):
    b=read(p/'input.json')
    if sha(p/'prompt.txt')!=b['prompt_sha256']: raise ValueError('PROMPT_CHANGED')
    for k,d in b['bindings'].items():
        if sha(inside(root,b['page'][k]))!=d: raise ValueError('INPUT_CHANGED: '+k)
    for k,d in b['reference_images'].items():
        if sha(inside(root,k))!=d: raise ValueError('REFERENCE_CHANGED: '+k)
    # Re-run source and semantic bindings, not just JSON file hashes.
    pg=b['page']; compile_prompt(read(inside(root,pg['spec'])),read(inside(root,pg['references'])),read(inside(root,pg['source_map'])),root)
    return b
def locate(root,eid,pid): return root/'episodes'/ident(eid)/ident(pid)
@contextlib.contextmanager
def lock(p):
    file=p/'.lock'
    fd=os.open(file,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    try: os.write(fd,str(os.getpid()).encode()); os.close(fd); yield
    finally: file.unlink(missing_ok=True)
def attempts(p): return sorted(p.glob('attempt-*'))
def prepare(root,eid,pid):
    p=locate(root,eid,pid)
    with lock(p):
        c=read(root/'control.json')
        if c['hold'] or not c['generation_authorized'] or c['episode']!=eid: raise ValueError('HOLD_OR_SCOPE_NOT_AUTHORIZED')
        b=bind(root,p); previous=attempts(p)
        if previous:
            last=previous[-1]
            if not (last/'result.json').exists(): raise ValueError('UNKNOWN_RESULT: recover original call; do not retry')
            review=read(last/'review.json') if (last/'review.json').exists() else None
            if not review or review['status']!='FAIL': raise ValueError('ALREADY_SAVED_OR_PASS: inspect saved result; no new call')
            if sha(last/'native.png')!=review['image_sha256']: raise ValueError('STALE_REVIEW')
        if len(previous)>=c['max_attempts']: raise ValueError('ATTEMPT_LIMIT')
        n=len(previous)+1; a=p/f'attempt-{n:02d}'; a.mkdir()
        shutil.copyfile(p/'prompt.txt',a/'prompt.txt')
        request={'episode':eid,'page':pid,'attempt':n,'prompt':(a/'prompt.txt').read_text(encoding='utf-8'),'referenced_image_paths':[str(inside(root,x)) for x in b['reference_images']],'transparent_background':False}
        write(a/'pending.json',{'request':request,'prompt_sha256':sha(a/'prompt.txt'),'created_at':time.time(),'status':'prepared-outcome-unknown-until-recovered'})
        return {'attempt_dir':str(a),'tool_arguments':{k:request[k] for k in ('prompt','referenced_image_paths','transparent_background')},'next':'Make one built-in image_gen call and save complete result JSON immediately. Never retry an unknown call.'}
def save(root,eid,pid,image,result):
    p=locate(root,eid,pid)
    with lock(p):
        a=attempts(p)[-1]; pending=read(a/'pending.json')
        if (a/'result.json').exists(): raise ValueError('RESULT_EXISTS')
        src=Path(image); raw=src.read_bytes()
        if raw[:8]!=b'\x89PNG\r\n\x1a\n': raise ValueError('NATIVE_PNG_REQUIRED')
        result_data=read(result)
        url=result_data.get('image_url','')
        if not url.startswith('data:image/png;base64,') or base64.b64decode(url.split(',',1)[1],validate=True)!=raw: raise ValueError('RESULT_PNG_MISMATCH: use full actual built-in result and its exact native PNG')
        shutil.copyfile(src,a/'native.png'); shutil.copyfile(result,a/'result.json')
        write(a/'receipt.json',{'episode':eid,'page':pid,'attempt':pending['request']['attempt'],'png_sha256':sha(a/'native.png'),'result_sha256':sha(a/'result.json'),'prompt_sha256':sha(a/'prompt.txt'),'size':struct.unpack('>II',raw[16:24]),'provider_result_recorded':True})
        return {'saved':str(a),'requires_visual_review':True}
def revise(root,eid,pid,spec_path):
    p=locate(root,eid,pid)
    with lock(p):
        a=attempts(p)[-1];r=read(a/'review.json');c=read(root/'control.json')
        if r['status']!='FAIL' or sha(a/'native.png')!=r['image_sha256']: raise ValueError('REPAIR_REQUIRES_CURRENT_FAIL')
        if len(attempts(p))>=c['max_attempts']: raise ValueError('ATTEMPT_LIMIT')
        b=read(p/'input.json'); pg=b['page'];new=read(inside(root,spec_path))
        prompt=compile_prompt(new,read(inside(root,pg['references'])),read(inside(root,pg['source_map'])),root)
        history=p/('input-before-repair-'+str(len(attempts(p)))+'.json')
        if history.exists():raise ValueError('REPAIR_ALREADY_PREPARED')
        shutil.copyfile(p/'input.json',history);pg['spec']=spec_path
        (p/'prompt.txt').write_text(prompt,encoding='utf-8')
        b['prompt_sha256']=sha(p/'prompt.txt');b['bindings']['spec']=sha(inside(root,spec_path));write(p/'input.json',b)
        return {'revised_page':pid,'attempt_count_preserved':len(attempts(p))}
CRITERIA=('source_story','speaker_and_text','character_identity','page_order','visible_artifact')
def review(root,eid,pid,file):
    p=locate(root,eid,pid);a=attempts(p)[-1];r=read(file)
    if r.get('image_sha256')!=sha(a/'native.png'): raise ValueError('REVIEW_WRONG_IMAGE')
    if not r.get('observer') or not all(isinstance(r.get(k),dict) and r[k].get('status') in ('PASS','FAIL') and r[k].get('observation') for k in CRITERIA): raise ValueError('REVIEW_NEEDS_ACTUAL_OBSERVATIONS: '+', '.join(CRITERIA))
    r['status']='PASS' if all(r[k]['status']=='PASS' for k in CRITERIA) else 'FAIL'
    if (a/'review.json').exists(): raise ValueError('REVIEW_EXISTS: retain original evidence')
    write(a/'review.json',r); return r
def status(root):
    rows=[]
    for p in sorted((root/'episodes').glob('*/*')):
        if not p.is_dir(): continue
        aa=attempts(p); state='READY'
        if aa:
            a=aa[-1];state='UNKNOWN_RESULT'
            if (a/'result.json').exists(): state='SAVED_NEEDS_REVIEW'
            if (a/'review.json').exists():
                r=read(a/'review.json'); state=r['status'] if sha(a/'native.png')==r['image_sha256'] else 'STALE_REVIEW'
        rows.append({'episode':p.parent.name,'page':p.name,'attempts':len(aa),'status':state})
    return {'control':read(root/'control.json'),'pages':rows,'new_calls':'Only READY pages or explicit FAIL below the call limit; UNKNOWN_RESULT is never a retry.'}
def export(root,eid):
    e=root/'episodes'/ident(eid); data=read(e/'episode.json'); destination=root/'exports'/(eid+'.cbz')
    selected=[]
    for page in data['pages']:
        p=e/page['id'];bind(root,p);a=attempts(p)[-1];r=read(a/'review.json')
        if r['status']!='PASS' or sha(a/'native.png')!=r['image_sha256']: raise ValueError('EXPORT_REQUIRES_CURRENT_VISUAL_PASS')
        selected.append((a/'native.png',page['id']+'.png'))
    if destination.exists(): raise ValueError('EXPORT_EXISTS: preserve version')
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as z:
        for p,name in selected:z.write(p,name)
    write(destination.with_suffix('.manifest.json'),{'episode':eid,'pages':[{'name':n,'sha256':sha(p)} for p,n in selected],'cbz_sha256':sha(destination),'publication':'local-only'})
    return {'file':str(destination),'sha256':sha(destination),'pages':len(selected)}
def doctor():
    import platform, importlib.util
    return {'python':sys.executable,'version':platform.python_version(),'pypdf':bool(importlib.util.find_spec('pypdf')),'core':'standard-library deterministic parsing/hash/ZIP; CPU-only','imagegen':'Provided by the current Codex app/account, not by this script. AI must verify built-in image_gen availability; no API key or paid fallback is configured.','global_config_written':False}
def main():
    a=argparse.ArgumentParser();a.add_argument('--root',type=Path,default=Path('work'));s=a.add_subparsers(dest='cmd',required=True)
    p=s.add_parser('init');p.add_argument('--sample',action='store_true')
    p=s.add_parser('import');p.add_argument('file')
    for cmd in ('plan','authorize','export'):
        p=s.add_parser(cmd);p.add_argument('--episode',required=True)
    for cmd in ('prepare','save','review','revise'):
        p=s.add_parser(cmd);p.add_argument('--episode',required=True);p.add_argument('--page',required=True)
        if cmd=='save':p.add_argument('--image',required=True);p.add_argument('--result',required=True)
        if cmd=='review':p.add_argument('--observations',required=True)
        if cmd=='revise':p.add_argument('--spec',required=True)
    for cmd in ('pause','resume','status','doctor'):s.add_parser(cmd)
    args=a.parse_args();root=args.root.resolve();cmd=args.cmd
    if cmd=='doctor':out=doctor()
    elif cmd=='init':out=init(root,args.sample)
    elif cmd=='import':out=ingest(root,args.file)
    elif cmd=='plan':out=plan(root,args.episode)
    elif cmd=='prepare':out=prepare(root,args.episode,args.page)
    elif cmd=='save':out=save(root,args.episode,args.page,args.image,args.result)
    elif cmd=='review':out=review(root,args.episode,args.page,args.observations)
    elif cmd=='revise':out=revise(root,args.episode,args.page,args.spec)
    elif cmd=='export':out=export(root,args.episode)
    elif cmd=='status':out=status(root)
    else:
        c=read(root/'control.json')
        if cmd=='authorize':
            e=root/'episodes'/ident(args.episode)/'episode.json';read(e);c.update(episode=args.episode,generation_authorized=True,hold=False)
        elif cmd=='pause':c['hold']=True
        elif cmd=='resume':c['hold']=False
        write(root/'control.json',c);out=c
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    try:main()
    except (ValueError,KeyError,IndexError,OSError) as exc:print('GATE: '+str(exc),file=sys.stderr);sys.exit(2)
