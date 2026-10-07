import json
import socket
import time
import httpcore
import httpx
import pytest
from fashion_scout.domain import ScoutError
from fashion_scout.domain.models import Network, Timeouts
from fashion_scout.media.http import SafeHTTP, PinnedBackend, validate_url, google_doh


def client(handler, **kwargs):
    return SafeHTTP(Network(min_interval_ms=1, **kwargs), {"futario.com"},
        transport_factory=lambda deadline: httpx.MockTransport(handler), sleep=lambda n: None)


@pytest.mark.parametrize("url", ["file:///tmp/a", "https://127.0.0.1/x", "https://futario.com@evil.test/x",
    "https://futario.com:444/x", "https://evil.test/x", "https://futario.com/x#fragment"])
def test_disallowed_url(url):
    with pytest.raises(ScoutError):
        validate_url(url, {"futario.com"})


def test_redirect_validated_before_followup():
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location":"http://127.0.0.1/private"})
    with pytest.raises(ScoutError) as error:
        client(handler).fetch("https://futario.com/a", "detail", 100)
    assert error.value.code=="UNSAFE_URL" and len(calls)==1


@pytest.mark.parametrize("status", [429, 503])
def test_finite_retries(status):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status)
    with pytest.raises(ScoutError) as error:
        client(handler).fetch("https://futario.com/a", "detail", 100)
    assert error.value.code=="HTTP_RETRIES_EXHAUSTED" and len(calls)==3


def test_retry_after_longer_than_budget_is_not_ignored():
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After":"600"})
    with pytest.raises(ScoutError) as error:
        client(handler, timeouts=Timeouts(total=1)).fetch("https://futario.com/a","detail",100)
    assert error.value.code=="RETRY_DEFERRED" and len(calls)==1


def test_timeout_retries_are_finite():
    calls=[]
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("injected")
    with pytest.raises(ScoutError):
        client(handler).fetch("https://futario.com/a","detail",100)
    assert len(calls)==3


def test_dns_rebinding_not_re_resolved_for_connect():
    lookups, connects=[],[]
    class Socket:
        def settimeout(self,value): pass
        def connect(self,target): connects.append(target)
        def getpeername(self): return ("93.184.216.34",443)
        def close(self): pass
    def resolver(host,port,**kwargs):
        lookups.append(host)
        return [(socket.AF_INET,socket.SOCK_STREAM,6,"",("93.184.216.34",port))]
    stream=PinnedBackend(time.monotonic()+2,resolver,lambda *a:Socket()).connect_tcp("futario.com",443)
    stream.close()
    assert lookups==["futario.com"] and connects==[("93.184.216.34",443)]


@pytest.mark.parametrize("address", ["127.0.0.1","10.0.0.1","198.18.0.210","169.254.169.254","::1","224.0.0.1"])
def test_dns_nonpublic_never_creates_socket(address):
    def resolver(*args,**kwargs):
        return [(socket.AF_INET,socket.SOCK_STREAM,6,"",("93.184.216.34",443)),
                (socket.AF_INET,socket.SOCK_STREAM,6,"",(address,443))]
    calls=[]
    with pytest.raises(ScoutError) as error:
        PinnedBackend(time.monotonic()+1,resolver,lambda *a:calls.append(a)).connect_tcp("futario.com",443)
    assert error.value.code=="UNSAFE_ADDRESS" and calls==[]


@pytest.mark.parametrize("change", ["private","name","type","status","ttl"])
def test_doh_rejects_untrusted_answer(monkeypatch,change):
    data={"Status":0,"Question":[{"name":"futario.com.","type":1}],
          "Answer":[{"name":"futario.com.","type":1,"TTL":300,"data":"93.184.216.34"}]}
    if change=="private": data["Answer"][0]["data"]="10.0.0.1"
    if change=="name": data["Answer"][0]["name"]="unrelated.test"
    if change=="type": data["Answer"][0]["type"]=16
    if change=="status": data["Status"]=2
    if change=="ttl": data["Answer"][0]["TTL"]=9999999
    real_client=httpx.Client
    def factory(**kwargs):
        kwargs["transport"].close()
        kwargs["transport"]=httpx.MockTransport(lambda r:httpx.Response(200,stream=httpx.ByteStream(json.dumps(data).encode())))
        return real_client(**kwargs)
    monkeypatch.setattr(httpx,"Client",factory)
    with pytest.raises(ScoutError) as error:
        google_doh("futario.com",443)
    assert error.value.code=="DNS_PROVIDER_FAILED"


def test_response_size_bounded(tmp_path):
    c=client(lambda r:httpx.Response(200,stream=httpx.ByteStream(b"x"*101)))
    with pytest.raises(ScoutError) as error:
        c.fetch("https://futario.com/x","image",100,tmp_path/"image")
    assert error.value.code=="RESPONSE_TOO_LARGE"
    assert (tmp_path/"image").stat().st_size==0


def test_storage_permission_is_not_network_retry(tmp_path,monkeypatch):
    from pathlib import Path
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,stream=httpx.ByteStream(b"image"))
    def denied(*args,**kwargs): raise PermissionError("injected storage access")
    monkeypatch.setattr(Path,"open",denied)
    with pytest.raises(PermissionError):
        client(handler).fetch("https://futario.com/x","image",100,tmp_path/"image")
    assert len(calls)==1
