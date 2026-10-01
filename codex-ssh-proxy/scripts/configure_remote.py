"""Remote helper: the local runner sends this source to python3 over SSH."""
import datetime,json,os,re,shutil,socket,subprocess,sys,tempfile
from pathlib import Path
h=Path.home(); host=socket.gethostname(); port=int(sys.argv[1]); check=sys.argv[2]=='check'
proxy='http://127.0.0.1:'+str(port)
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
os.umask(0o077)
def run(a): return subprocess.run(a,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=30)
def save(p,text,mode=0o600):
    data=text.encode();p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists() and p.read_bytes()==data:return
    if p.exists():
        backup=p.with_name(p.name+'.bak.ssh-proxy-'+stamp);shutil.copy2(p,backup);backup.chmod(0o600)
        print('REMOTE_BACKUP',backup,flush=True)
    fd,name=tempfile.mkstemp(prefix='.'+p.name,dir=str(p.parent))
    with os.fdopen(fd,'wb') as f:f.write(data)
    os.chmod(name,mode);os.replace(name,p)
probe=run(['curl','--proxy',proxy,'--noproxy','','--connect-timeout','10','--max-time','20','-sS','-o','/dev/null','-w','%{http_code}','https://auth.openai.com/.well-known/openid-configuration'])
if probe.returncode or probe.stdout.strip()!='200':
    sys.exit('SSH proxy check failed; HTTP='+probe.stdout.strip()+'. Remote configuration was not changed.')
mapping=h/'.config/codex-proxy-hosts'/(host+'.json')
c=json.loads(mapping.read_text()) if mapping.exists() else {'vscode_dir':str(h/'.vscode-server')}
settings=Path(c['vscode_dir'])/'data/Machine/settings.json'
s=json.loads(settings.read_text()) if settings.exists() else {}
old_service=c.get('service')
wrapper=h/'.local/bin/codex-proxy'
if not check:
    c.update(mode='ssh',proxy=proxy)
    s['http.proxy']=proxy
    launcher='''#!/usr/bin/env python3
# Managed by codex-ssh-proxy skill. Supports SSH and standalone proxy modes.
import json,os,pathlib,shutil,socket,subprocess,sys,urllib.parse
p=pathlib.Path.home()/'.config/codex-proxy-hosts'/(socket.gethostname()+'.json')
if not p.exists():sys.exit('Configure the Codex proxy on this host first.')
c=json.loads(p.read_text())
if c.get('mode')=='ssh':
    u=urllib.parse.urlsplit(c['proxy'])
    try:
        with socket.create_connection((u.hostname,u.port),timeout=3):pass
    except OSError:
        sys.exit('SSH proxy is unavailable. Start local v2rayN and reconnect SSH/VS Code from that computer.')
elif c.get('service'):
    if subprocess.run(['systemctl','--user','is-active','--quiet',c['service']]).returncode:
        sys.exit('Start the proxy: systemctl --user start '+c['service'])
binary=shutil.which('codex');standalone=pathlib.Path.home()/'.local/bin/codex'
if not binary and standalone.is_file() and os.access(standalone,os.X_OK):binary=str(standalone)
if not binary:
    paths=[x for x in (pathlib.Path(c['vscode_dir'])/'extensions').glob('openai.chatgpt-*/bin/linux-x86_64/codex') if os.access(x,os.X_OK)]
    if not paths:sys.exit('Install the Codex CLI or remote Codex extension first.')
    binary=str(max(paths,key=lambda x:x.stat().st_mtime))
for k in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy']:os.environ[k]=c['proxy']
for k in ['ALL_PROXY','all_proxy','NO_PROXY','no_proxy']:os.environ.pop(k,None)
os.execv(binary,[binary]+sys.argv[1:])
'''
    compile(launcher,str(wrapper),'exec')
    bashrc=h/'.bashrc';original=bashrc.read_text() if bashrc.exists() else ''
    begin='# >>> Codex proxy launcher >>>';end='# <<< Codex proxy launcher <<<'
    block='''# >>> Codex proxy launcher >>>
codex() {
    if [ -f "$HOME/.config/codex-proxy-hosts/$(hostname).json" ]; then
        "$HOME/.local/bin/codex-proxy" "$@"
    else
        "$HOME/.local/bin/codex" "$@"
    fi
}
# <<< Codex proxy launcher <<<'''
    if begin in original or end in original:
        if original.count(begin)!=1 or original.count(end)!=1:sys.exit('Ambiguous launcher markers in .bashrc')
        first,last=original.index(begin),original.index(end)+len(end)
        if first>=last:sys.exit('Invalid launcher markers in .bashrc')
        new_bashrc=original[:first]+block+original[last:]
    else:new_bashrc=original.rstrip('\n')+'\n\n'+block+'\n'
    files=[mapping,settings,wrapper,bashrc]
    previous={p:(p.read_bytes(),p.stat().st_mode & 0o777) if p.exists() else None for p in files}
    try:
        save(mapping,json.dumps(c,indent=2)+'\n')
        save(wrapper,launcher,0o755)
        save(settings,json.dumps(s,ensure_ascii=False,indent=2)+'\n')
        save(bashrc,new_bashrc)
        version=run([str(wrapper),'--version'])
        if version.returncode:raise RuntimeError('Codex launcher validation failed')
        # Stop only the specific user service previously recorded for this host.
        if old_service and re.fullmatch(r'xray-codex-[A-Za-z0-9_.-]+\.service',old_service):
            unit=h/'.config/systemd/user'/old_service
            if unit.exists() and ('ConditionHost='+host) in unit.read_text():
                result=run(['systemctl','--user','disable','--now',old_service])
                if result.returncode:raise RuntimeError('Could not disable old Xray service')
    except Exception:
        for p,value in previous.items():
            if value is None:p.unlink(missing_ok=True)
            else:save(p,value[0].decode(),value[1])
        raise
else:
    if c.get('mode')!='ssh' or c.get('proxy')!=proxy or s.get('http.proxy')!=proxy:
        sys.exit('Remote proxy settings do not match SSH mode')
    version=run([str(wrapper),'--version'])
    if version.returncode:sys.exit('Codex launcher check failed')
print('NODE',host,'HTTP',probe.stdout.strip(),'PROXY',proxy,'CLI',version.stdout.strip(),flush=True)
if old_service:
    active=run(['systemctl','--user','is-active',old_service]).stdout.strip()
    enabled=run(['systemctl','--user','is-enabled',old_service]).stdout.strip()
    print('OLD_XRAY',active,enabled,flush=True)
print('CHECK_OK' if check else 'SSH_PROXY_CONFIGURED',flush=True)
