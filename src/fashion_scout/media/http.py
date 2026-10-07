"""Bounded HTTPX requests with per-connection DNS pinning, no proxy or implicit redirects."""
import ipaddress
import json
import math
import queue
import random
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urljoin, urlencode

import certifi
import httpcore
import httpx
from httpcore._backends.sync import SyncStream  # Exact httpcore version locked and tested.

from fashion_scout.domain import ScoutError


def public_address(value):
    ip = ipaddress.ip_address(value)
    return ip.is_global and not (ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local)


def validate_url(url, hosts):
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as exc:
        raise ScoutError("UNSAFE_URL", "Invalid port") from exc
    if (parts.scheme not in ("http", "https") or parts.hostname not in hosts
            or parts.username or parts.password or parts.fragment
            or port not in (None, 80 if parts.scheme == "http" else 443)):
        raise ScoutError("UNSAFE_URL", "Source URL is outside verified origins")
    return parts


def remaining(deadline, timeout=None):
    left = deadline - time.monotonic()
    if left <= 0:
        raise httpcore.ReadTimeout("Request total deadline")
    return min(left, timeout) if timeout is not None else left


def retry_seconds(value):
    try:
        delay = float(value)
    except ValueError:
        try:
            delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError) as exc:
            raise ScoutError("RETRY_DEFERRED", "Unparseable Retry-After") from exc
    if not math.isfinite(delay):
        raise ScoutError("RETRY_DEFERRED", "Invalid Retry-After")
    return max(0, delay)


class DeadlineStream:
    def __init__(self, stream, deadline):
        self.stream, self.deadline = stream, deadline

    def read(self, max_bytes, timeout=None):
        return self.stream.read(max_bytes, remaining(self.deadline, timeout))

    def write(self, buffer, timeout=None):
        return self.stream.write(buffer, remaining(self.deadline, timeout))

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return DeadlineStream(self.stream.start_tls(ssl_context, server_hostname,
                              remaining(self.deadline, timeout)), self.deadline)

    def get_extra_info(self, name):
        return self.stream.get_extra_info(name)

    def close(self):
        self.stream.close()


class PinnedBackend:
    def __init__(self, deadline, resolver=socket.getaddrinfo, socket_factory=socket.socket):
        self.deadline, self.resolver, self.socket_factory = deadline, resolver, socket_factory

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        # DNS can block in the OS; daemon resolution has an explicit caller deadline.
        answers = queue.Queue(maxsize=1)
        def resolve():
            try:
                answers.put(self.resolver(host, port, type=socket.SOCK_STREAM))
            except Exception as exc:
                answers.put(exc)
        threading.Thread(target=resolve, daemon=True).start()
        try:
            records = answers.get(timeout=remaining(self.deadline, timeout))
        except queue.Empty as exc:
            raise httpcore.ConnectTimeout("DNS deadline") from exc
        if isinstance(records, Exception):
            raise httpcore.ConnectError("DNS failed") from records
        if not records or any(not public_address(record[4][0]) for record in records):
            raise ScoutError("UNSAFE_ADDRESS", "DNS includes a non-public address")
        family, socktype, proto, _, target = records[0]
        sock = None
        try:
            sock = self.socket_factory(family, socktype, proto)
            sock.settimeout(remaining(self.deadline, timeout))
            # Exact resolved numeric sockaddr: no second DNS lookup or proxy resolution.
            sock.connect(target)
            if ipaddress.ip_address(sock.getpeername()[0]) != ipaddress.ip_address(target[0]):
                raise ScoutError("PEER_MISMATCH", "Connected peer differs from verified address")
            return DeadlineStream(SyncStream(sock), self.deadline)
        except OSError as exc:
            if sock is not None:
                sock.close()
            raise httpcore.ConnectError("Pinned TCP connection failed") from exc
        except BaseException:
            if sock is not None:
                sock.close()
            raise

    def connect_unix_socket(self, *args, **kwargs):
        raise ScoutError("UNSAFE_URL", "Unix sockets are not supported")

    def sleep(self, seconds):
        time.sleep(min(seconds, remaining(self.deadline)))


class CoreStream(httpx.SyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    def __iter__(self):
        yield from self.stream

    def close(self):
        self.stream.close()


class PinnedTransport(httpx.BaseTransport):
    def __init__(self, deadline, resolver=socket.getaddrinfo):
        self.pool = httpcore.ConnectionPool(ssl_context=ssl.create_default_context(cafile=certifi.where()),
            network_backend=PinnedBackend(deadline, resolver=resolver), max_connections=1, max_keepalive_connections=0,
            retries=0, http2=False)

    def handle_request(self, request):
        response = self.pool.handle_request(httpcore.Request(method=request.method,
            url=httpcore.URL(scheme=request.url.raw_scheme, host=request.url.raw_host,
                             port=request.url.port, target=request.url.raw_path),
            headers=request.headers.raw, content=request.stream, extensions=request.extensions))
        return httpx.Response(response.status, headers=response.headers,
                              stream=CoreStream(response.stream), extensions=response.extensions)

    def close(self):
        self.pool.close()


def google_doh(host, port, type=socket.SOCK_STREAM):
    """Fixed authenticated provider. No source-supplied resolver, cache, or private fallback."""
    deadline = time.monotonic() + 8
    def bootstrap(name, service, **kwargs):
        if name != "dns.google" or service != 443:
            raise ScoutError("DNS_PROVIDER_MISMATCH", "Unexpected DNS infrastructure")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))]
    url = "https://dns.google/resolve?" + urlencode({"name": host, "type": "A"})
    with httpx.Client(transport=PinnedTransport(deadline, bootstrap), trust_env=False,
                      follow_redirects=False, timeout=8, headers={"Accept-Encoding": "identity"}) as client:
        with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise ScoutError("DNS_PROVIDER_FAILED", "DNS provider did not return success")
            body = bytearray()
            for chunk in response.iter_raw():
                remaining(deadline)
                body.extend(chunk)
                if len(body) > 65536:
                    raise ScoutError("DNS_PROVIDER_FAILED", "DNS response exceeded limit")
    try:
        data = json.loads(body)
        question = data["Question"]
        if data["Status"] != 0 or data.get("TC", False) or len(question) != 1 or question[0]["name"].rstrip(".").lower() != host.lower() or question[0]["type"] != 1:
            raise ValueError("question/status")
        allowed_names = {host.lower().rstrip(".")}
        records = data.get("Answer", [])
        # Follow a bounded CNAME chain within this authenticated response only.
        for _ in range(8):
            for answer in records:
                if answer["type"] == 5 and answer["name"].lower().rstrip(".") in allowed_names:
                    allowed_names.add(answer["data"].lower().rstrip("."))
        addresses = []
        for answer in records:
            if answer["type"] not in (1, 5) or not 0 <= answer["TTL"] <= 86400:
                raise ValueError("record type/TTL")
            if answer["name"].lower().rstrip(".") not in allowed_names:
                raise ValueError("answer name")
            if answer["type"] == 1:
                ip = ipaddress.ip_address(answer["data"])
                if ip.version != 4 or not public_address(str(ip)):
                    raise ValueError("non-public A")
                addresses.append(str(ip))
        if not addresses:
            raise ValueError("no A records")
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port)) for ip in addresses]
    except (KeyError, TypeError, ValueError) as exc:
        raise ScoutError("DNS_PROVIDER_FAILED", "DNS response failed validation") from exc


class SafeHTTP:
    def __init__(self, network, hosts, checkpoint=lambda: None, request_charge=lambda u, k: None,
                 byte_charge=lambda n: None, response_record=lambda i,s,r,p: None, transport_factory=None, sleep=time.sleep, source_hosts=None):
        self.network, self.hosts, self.checkpoint = network, frozenset(hosts), checkpoint
        self.source_hosts = frozenset(source_hosts) if source_hosts is not None else self.hosts
        self.request_charge, self.byte_charge = request_charge, byte_charge
        self.response_record = response_record
        self.transport_factory = transport_factory or (lambda deadline: PinnedTransport(deadline,
            google_doh if network.resolver_mode == "google_doh" else socket.getaddrinfo))
        self.sleep, self.last_request = sleep, 0.0
        self.not_before = 0.0

    def wait(self, seconds, deadline):
        left_budget = deadline - time.monotonic()
        if left_budget <= 0:
            raise ScoutError("HTTP_TOTAL_TIMEOUT", "Request total deadline reached")
        if seconds > left_budget:
            raise ScoutError("RETRY_DEFERRED", "Retry delay exceeds request time budget")
        # Cooperative safe-stop checkpoints during rate limiting and backoff.
        left = seconds
        while left > 0:
            self.checkpoint()
            step = min(left, 0.2)
            self.sleep(step)
            left -= step

    def fetch(self, url, kind, limit, destination=None):
        deadline = time.monotonic() + self.network.timeouts.total
        for attempt in range(self.network.max_attempts):
            current = url
            try:
                for hop in range(4):
                    hosts = self.hosts if kind == "image" else self.source_hosts
                    validate_url(current, hosts)
                    self.checkpoint()
                    self.wait(max(0, self.not_before-time.monotonic(), self.network.min_interval_ms / 1000 - (time.monotonic() - self.last_request)), deadline)
                    request_id = self.request_charge(current, kind)
                    self.last_request = time.monotonic()
                    left = remaining(deadline)
                    timeouts = self.network.timeouts
                    timeout = httpx.Timeout(connect=min(timeouts.connect, left), read=min(timeouts.read, left),
                                            write=min(timeouts.write, left), pool=min(timeouts.pool, left))
                    with httpx.Client(transport=self.transport_factory(deadline), trust_env=False,
                                      follow_redirects=False, timeout=timeout,
                                      headers={"User-Agent": "FashionScout/0.2 (bounded local research)",
                                               "Accept-Encoding": "identity"}) as client:
                        with client.stream("GET", current) as response:
                            network_stream = response.extensions.get("network_stream")
                            peer = network_stream.get_extra_info("server_addr") if network_stream else None
                            retry_after = response.headers.get("retry-after", "")[:128] or None
                            self.response_record(request_id, response.status_code, retry_after, peer[0] if peer else None)
                            if response.status_code in (301, 302, 303, 307, 308):
                                if "location" not in response.headers:
                                    raise ScoutError("BAD_REDIRECT", "Redirect has no location")
                                target = urljoin(current, response.headers["location"])
                                if current.startswith("https:") and not target.startswith("https:"):
                                    raise ScoutError("UNSAFE_URL", "HTTPS downgrade is not supported")
                                current = target
                                validate_url(current, hosts)
                                continue
                            if response.status_code == 429 or 500 <= response.status_code <= 599:
                                delay = (2, 8, 8)[attempt] + random.uniform(0, 0.1)
                                if value := response.headers.get("retry-after"):
                                    delay = retry_seconds(value)
                                self.not_before = time.monotonic() + delay
                                if attempt + 1 == self.network.max_attempts:
                                    raise ScoutError("HTTP_RETRIES_EXHAUSTED", "HTTP retries exhausted")
                                self.wait(delay, deadline)
                                break
                            if response.status_code != 200:
                                raise ScoutError("HTTP_" + str(response.status_code), "Source returned unsuccessful status")
                            if response.headers.get("content-encoding", "identity").lower() != "identity":
                                raise ScoutError("UNSUPPORTED_ENCODING", "Compressed response not requested")
                            if response.headers.get("content-length", "").isdigit() and int(response.headers["content-length"]) > limit:
                                raise ScoutError("RESPONSE_TOO_LARGE", "Declared response exceeds byte limit")
                            total, chunks = 0, []
                            stream = destination.open("wb") if destination else None
                            try:
                                for chunk in response.iter_raw():
                                    self.checkpoint()
                                    remaining(deadline)
                                    self.byte_charge(len(chunk))
                                    total += len(chunk)
                                    if total > limit:
                                        raise ScoutError("RESPONSE_TOO_LARGE", "Response exceeded byte limit")
                                    if stream:
                                        stream.write(chunk)
                                    else:
                                        chunks.append(chunk)
                            finally:
                                if stream:
                                    stream.close()
                            return {"url": current, "bytes": total, "headers": dict(response.headers),
                                    "body": b"".join(chunks) if destination is None else None}
                else:
                    raise ScoutError("REDIRECT_LIMIT", "Too many redirects")
            except (httpcore.NetworkError, httpcore.TimeoutException, httpx.TransportError) as exc:
                if attempt + 1 == self.network.max_attempts:
                    raise ScoutError("HTTP_RETRIES_EXHAUSTED", "Bounded network request failed") from exc
                self.wait((2, 8, 8)[attempt], deadline)
        raise ScoutError("HTTP_RETRIES_EXHAUSTED", "Bounded request failed")

    def json(self, url, kind="discovery"):
        result = self.fetch(url, kind, 8 * 1024**2)
        try:
            value = json.loads(result["body"])
        except (ValueError, UnicodeDecodeError) as exc:
            raise ScoutError("SOURCE_STRUCTURE_CHANGED", "Expected source JSON") from exc
        return value
