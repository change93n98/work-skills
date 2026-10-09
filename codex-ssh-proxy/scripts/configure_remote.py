"""Remote helper: the local runner sends this source to python3 over SSH."""
import base64,datetime,json,os,re,shutil,socket,ssl,subprocess,sys,tempfile
from pathlib import Path


def read_headers(stream):
    data = b''
    while b'\r\n\r\n' not in data:
        chunk = stream.recv(4096)
        if not chunk:
            raise OSError('connection closed before response headers')
        data += chunk
        if len(data) > 16384:
            raise OSError('response headers exceed diagnostic limit')
    first = data.split(b'\r\n', 1)[0].split()
    if len(first) < 2 or not first[0].startswith(b'HTTP/'):
        raise OSError('invalid HTTP status line')
    return int(first[1])


def websocket_probe(proxy_port=None, timeout=8):
    """Check the TLS/Upgrade route without credentials or a model request.

    An HTTP 401 proves that the route reaches the authentication gate. It
    does not prove an authenticated WebSocket session or model inference.
    """
    stream = None
    stage = 'tcp'
    try:
        address = ('127.0.0.1', proxy_port) if proxy_port else ('chatgpt.com', 443)
        stream = socket.create_connection(address, timeout=timeout)
        stream.settimeout(timeout)
        if proxy_port:
            stage = 'proxy_connect'
            stream.sendall(b'CONNECT chatgpt.com:443 HTTP/1.1\r\n'
                           b'Host: chatgpt.com:443\r\n\r\n')
            status = read_headers(stream)
            if status != 200:
                return {'stage': stage, 'http': status, 'reachable': False}
        stage = 'tls'
        stream = ssl.create_default_context().wrap_socket(stream, server_hostname='chatgpt.com')
        stage = 'websocket_upgrade'
        key = base64.b64encode(os.urandom(16)).decode('ascii')
        request = ('GET /backend-api/codex/responses HTTP/1.1\r\n'
                   'Host: chatgpt.com\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                   'Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ' + key + '\r\n'
                   'User-Agent: codex-ssh-proxy-diagnostic\r\n\r\n')
        stream.sendall(request.encode('ascii'))
        status = read_headers(stream)
        return {'stage': stage, 'http': status, 'reachable': status in (101, 401)}
    except (OSError, ValueError) as error:
        # Never emit response bodies, cookies, Authorization, or process secrets.
        return {'stage': stage, 'reachable': False, 'error': type(error).__name__,
                'errno': getattr(error, 'errno', None)}
    finally:
        if stream is not None:
            stream.close()


def running_codex_proxy(proxy, proc_root=Path('/proc')):
    """Report same-user Codex proxy presence without exposing environment values."""
    result = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid() or (entry / 'comm').read_text().strip() != 'codex':
                continue
            env = {}
            for item in (entry / 'environ').read_bytes().split(b'\0'):
                key, _, value = item.partition(b'=')
                if key.lower() in (b'http_proxy', b'https_proxy', b'all_proxy'):
                    env[key.lower()] = value.decode(errors='replace')
            command = (entry / 'cmdline').read_bytes().split(b'\0')
            kind = 'app-server' if b'app-server' in command else 'cli'
            state = 'missing' if not env else ('matches' if all(value == proxy for value in env.values()) else 'different')
            result.append({'pid': int(entry.name), 'entry': kind, 'proxy_env': state})
        except OSError:
            continue
    return sorted(result, key=lambda item: item['pid'])


def report_diagnostics(proxy, port, wrapper, runner):
    print('WS_PROXY_ROUTE', json.dumps(websocket_probe(port), sort_keys=True), flush=True)
    print('WS_DIRECT_ROUTE', json.dumps(websocket_probe(), sort_keys=True), flush=True)
    try:
        login = runner([str(wrapper), 'login', 'status'])
        state = 'logged_in' if login.returncode == 0 else (
            'not_logged_in' if 'Not logged in' in login.stderr else 'unknown')
    except subprocess.TimeoutExpired:
        state = 'unknown'
    print('CLI_LOGIN', state, flush=True)
    print('RUNNING_CODEX', json.dumps(running_codex_proxy(proxy), sort_keys=True), flush=True)
    print('MODEL_NOT_TESTED: route checks do not prove inference; '
          'CLI login status does not describe credentials injected by a desktop client.', flush=True)


def main():
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
    if check:
        report_diagnostics(proxy, port, wrapper, run)
    if old_service:
        active=run(['systemctl','--user','is-active',old_service]).stdout.strip()
        enabled=run(['systemctl','--user','is-enabled',old_service]).stdout.strip()
        print('OLD_XRAY',active,enabled,flush=True)
    print('CHECK_OK: proxy configuration only; MODEL_NOT_TESTED' if check else 'SSH_PROXY_CONFIGURED',flush=True)


if __name__ == "__main__":
    main()
