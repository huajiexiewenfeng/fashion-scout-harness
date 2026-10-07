"""T6a test-only provenance and loopback guard; copied into the isolated environment."""
import atexit
import ipaddress
import json
import os
from pathlib import Path
import socket
import sys
import webbrowser

sys.dont_write_bytecode=True
blocked=[]
def permitted(host):
    try:return ipaddress.ip_address(host).is_loopback
    except ValueError:return host=='localhost'

real_connect=socket.socket.connect
real_connect_ex=socket.socket.connect_ex
real_resolve=socket.getaddrinfo
def guard(address):
    if isinstance(address,tuple) and not permitted(address[0]):
        blocked.append(str(address[0]));raise OSError('T6a allows loopback only')
def connect(self,address):guard(address);return real_connect(self,address)
def connect_ex(self,address):guard(address);return real_connect_ex(self,address)
def resolve(host,*args,**kwargs):
    if host is not None and not permitted(host):
        blocked.append(str(host));raise OSError('T6a denies source DNS')
    return real_resolve(host,*args,**kwargs)
socket.socket.connect=connect;socket.socket.connect_ex=connect_ex;socket.getaddrinfo=resolve
opened=[]
def open_browser(url,**kwargs):
    from urllib.parse import urlsplit
    value=urlsplit(url);assert value.scheme=='http' and value.hostname=='127.0.0.1'
    opened.append({'origin':value.scheme+'://'+value.netloc,'bootstrap':value.path=='/bootstrap','one_time_code_present':bool(value.fragment)})
    return True
webbrowser.open=open_browser

def save():
    out=Path(os.environ['T6A_AUDIT_DIR']);out.mkdir(exist_ok=True)
    modules={name:str(Path(m.__file__).resolve()) for name,m in list(sys.modules.items())
             if (name=='__main__' or name=='fashion_scout' or name.startswith('fashion_scout.')) and getattr(m,'__file__',None)}
    value={'pid':os.getpid(),'executable':sys.executable,'argv':sys.argv,'modules':modules,'sys_path':sys.path,
           'editable_finders':[str(m) for m in sys.meta_path if '__editable__' in str(m)],'blocked_network':blocked,'browser_open_intercepted':opened}
    (out/(str(os.getpid())+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
atexit.register(save)
