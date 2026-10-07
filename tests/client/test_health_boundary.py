import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from unittest.mock import patch
import uuid
import pytest
from fashion_scout import client as c, launcher
from fashion_scout.config import Paths
from fashion_scout.domain import ScoutError


@pytest.mark.parametrize('mode',['valid','redirect','wrong-instance','wrong-pid','wrong-born','wrong-proof'])
def test_real_health_transport_no_proxy_redirect_or_false_identity(tmp_path,monkeypatch,mode):
    paths=Paths.at(tmp_path);paths.prepare()
    instance=str(uuid.uuid4());token='a'*64
    (tmp_path/'control'/(instance+'.key')).write_text(token)
    hits=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            hits.append((self.path,self.headers.get('Authorization')))
            if mode=='redirect':
                self.send_response(302);self.send_header('Location','http://127.0.0.1:9/stolen');self.end_headers();return
            challenge=self.headers['X-Scout-Challenge']
            value={'app_instance_id':instance,'pid':123,'born':1.0,'worker_state':'offline',
                   'proof':hmac.new(token.encode(),(challenge+instance).encode(),hashlib.sha256).hexdigest()}
            if mode=='wrong-instance':value['app_instance_id']='wrong'
            if mode=='wrong-pid':value['pid']=456
            if mode=='wrong-born':value['born']=2
            if mode=='wrong-proof':value['proof']='wrong'
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(value).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    descriptor={'instance':instance,'port':server.server_port,'processes':{'web':{'pid':123,'born':1.0}}}
    monkeypatch.setenv('HTTP_PROXY','http://127.0.0.1:9')
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:9')
    monkeypatch.setenv('NO_PROXY','')
    try:
        fn=c.guarded_launcher()['verify_health']
        if mode=='valid':assert fn(paths,descriptor)['pid']==123
        elif mode=='redirect':
            with pytest.raises(c.ClientError) as e:fn(paths,descriptor)
            assert e.value.code=='REDIRECT_REJECTED'
        else:
            with pytest.raises(ScoutError) as e:fn(paths,descriptor)
            assert e.value.code=='PORT_IDENTITY_CONFLICT'
        assert hits==[('/v1/health',None)]
        assert launcher.verify_health.__globals__['build_opener'] is not fn.__globals__['build_opener']
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)


def test_api_boundary_real_redirect_sends_no_second_request(tmp_path,monkeypatch):
    hits=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            hits.append(self.path)
            self.send_response(302);self.send_header('Location','/stolen');self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    conn=c.Connection(Paths.at(tmp_path),server.server_port);conn.token='a'*64
    monkeypatch.setenv('HTTP_PROXY','http://127.0.0.1:9');monkeypatch.setenv('NO_PROXY','')
    try:
        with patch.object(conn,'verify'):
            with pytest.raises(c.ClientError) as e:conn.request('GET','/v1/sites')
        assert e.value.code=='REDIRECT_REJECTED' and hits==['/v1/sites']
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
