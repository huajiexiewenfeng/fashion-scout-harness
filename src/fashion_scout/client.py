"""Local fixed-command client with durable, non-secret intent recovery."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from types import FunctionType
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
import uuid

import httpx
from pydantic import ValidationError
from . import launcher
from .config import Paths
from .domain import ScoutError
from .client_models import MODELS, Configure

WRITES = {'start', 'retry', 'cancel', 'user-state', 'set-default-plan', 'export', 'export-retry','verify','backup','set-storage'}
WRITES |= {'browser-attach', 'browser-observe', 'browser-upload', 'browser-continue', 'browser-asset-failure'}
CAS = {'user-state', 'set-default-plan','set-storage'}
MAX_JSON = 1_048_576


class ClientError(Exception):
    def __init__(self, code, message, exit_code=2, details=None):
        self.code, self.message, self.exit_code, self.details = code, message, exit_code, details


def fail(code, message, exit_code=2, details=None):
    raise ClientError(code, message, exit_code, details)


def load_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            raise ValueError('too large')
        result = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(result, dict):
            raise ValueError('object required')
        return result
    except (OSError, ValueError, UnicodeError):
        fail('INVALID_JSON_FILE', '需要可读、有限大小且无重复键的 JSON 对象文件')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fail('REDIRECT_REJECTED', '本机服务不允许重定向', 3)


def guarded_launcher():
    """Reuse the exact T1 functions with a local opener dependency, no global patch.

    T1 has no opener injection parameter. Bind its existing function code into a
    private namespace so verify_health, ensure and open share redirect rejection.
    """
    namespace = dict(vars(launcher))
    namespace['build_opener'] = lambda *args: build_opener(ProxyHandler({}), NoRedirect())
    for name in ('verify_health', 'ensure', 'open_browser', 'status'):
        fn = getattr(launcher, name)
        namespace[name] = FunctionType(fn.__code__, namespace, fn.__name__, fn.__defaults__, fn.__closure__)
    return namespace


class Connection:
    def __init__(self, paths, port):
        self.paths, self.port = paths, port
        self.token = None
        self.service = {'checked': False, 'web_ready': None, 'worker_state': 'unknown'}

    def verify(self):
        descriptor = launcher.read_descriptor(self.paths)
        if descriptor is None or descriptor.get('stopped'):
            fail('SERVICE_OFFLINE', '服务未启动；可使用固定 ensure 命令', 3)
        if type(descriptor['port']) is not int or descriptor['port'] != self.port:
            fail('PORT_CONFIG_CONFLICT', '描述符端口与已保存配置不一致', 3)
        # Canonical UUID prevents descriptor text from becoming a credential path.
        if str(uuid.UUID(descriptor['instance'])) != descriptor['instance']:
            fail('DESCRIPTOR_INVALID', '实例标识不合法', 3)
        if not launcher.verified_process(self.paths, descriptor, 'web'):
            fail('SERVICE_OFFLINE', '已记录的 Web 进程不在线', 3)
        health = guarded_launcher()['verify_health'](self.paths, descriptor)
        worker = launcher.verified_process(self.paths, descriptor, 'worker')
        self.service = {**health, 'checked': True, 'worker_state': health['worker_state'] if worker else 'offline'}
        self.token = (self.paths.root / 'control' / (descriptor['instance'] + '.key')).read_text('ascii')
        if not re.fullmatch(r'[0-9a-f]{64}', self.token):
            fail('CREDENTIAL_INVALID', '实例凭据格式无效', 3)

    def upload(self, path, payload, key):
        from .media.browser_intake import selected_export
        # Validate the local native manifest before any credential-bearing write.
        with selected_export(payload) as stream:
            self.verify()
            headers = {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/octet-stream',
                       'X-Source-Session': payload['session_id'], 'X-Request-Key': key,
                       'X-Source-Sha256': payload['sha256'], 'X-Source-Bytes': str(payload['bytes']),
                       'X-Source-Url': payload['source_url']}
            def chunks():
                while chunk := stream.read(65536):
                    yield chunk
            try:
                with httpx.Client(trust_env=False, follow_redirects=False, timeout=30) as client:
                    with client.stream('POST', f'http://127.0.0.1:{self.port}' + path, content=chunks(), headers=headers) as response:
                        if 300 <= response.status_code < 400:
                            fail('REDIRECT_REJECTED', '本机服务不允许重定向', 3)
                        raw=bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw)>8*MAX_JSON:fail('INVALID_RESPONSE','本机响应超过限制',3)
                        try:
                            value=json.loads(raw)
                            if not isinstance(value,dict):raise ValueError()
                        except ValueError:fail('INVALID_RESPONSE','本机服务未返回 JSON 对象',3)
                        return response.status_code,sanitize(value,self.token)
            except httpx.HTTPError:
                fail('TRANSPORT_UNCERTAIN','图片传输中断；保留原意图并使用 resume 核对',3)

    def request(self, method, path, payload=None, query=None):
        self.verify()  # Check identity before every credential-bearing request.
        url = f'http://127.0.0.1:{self.port}' + path
        try:
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
                with client.stream(method, url, params=query, json=payload,
                                   headers={'Authorization': 'Bearer ' + self.token}) as response:
                    if 300 <= response.status_code < 400:
                        fail('REDIRECT_REJECTED', '本机服务不允许重定向', 3)
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 8 * MAX_JSON:
                            fail('INVALID_RESPONSE', '本机响应超过限制，保留原意图以便核对', 3)
                    try:
                        value = json.loads(data)
                        if not isinstance(value, dict):
                            raise ValueError()
                    except ValueError:
                        fail('INVALID_RESPONSE', '本机服务未返回 JSON 对象', 3)
                    return response.status_code, sanitize(value, self.token)
        except httpx.HTTPError:
            fail('TRANSPORT_UNCERTAIN', '通信中断；写意图已保留，请使用 resume 核对', 3)


def sanitize(value, secret=None):
    if isinstance(value, dict):
        return {sanitize(k, secret): sanitize(v, secret) for k, v in value.items()
                if k.lower() not in {'authorization', 'cookie', 'set-cookie', 'token', 'csrf_token', 'bootstrap_url', 'proof'}}
    if isinstance(value, list):
        return [sanitize(v, secret) for v in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, '[redacted]')
        return re.sub(r'http://127\.0\.0\.1:\d+/bootstrap#[^\s"<>]+', '[redacted-entry]', value)
    return value


class Journal:
    def __init__(self, paths):
        self.root = paths.root / 'control' / 'client-intents'

    @contextmanager
    def lock(self):
        import msvcrt
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / 'journal.lock').open('a+b') as stream:
            if stream.seek(0, 2) == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                fail('CLIENT_BUSY', '另一个客户端正在处理意图', 3)
            try:
                yield
            finally:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def save(self, record):
        try:
            launcher.atomic_json(self.root / (record['intent_id'] + '.json'), record)
        except OSError:
            fail('INTENT_STORAGE_ERROR', '意图记录无法持久化；不要创建替代意图，请先核对', 3,
                 {'intent_id': record['intent_id']})

    def read(self, intent_id):
        record = load_json(self.root / (intent_id + '.json'))
        try:
            spec = record['spec']
            if (record['intent_id'] != intent_id or record['sha256'] != fingerprint(spec)
                    or spec['command'] not in WRITES):
                raise ValueError()
            # Rebuild the fixed route from saved validated inputs, never trust a URL in a journal.
            validated = validate(spec['command'], spec['input'])
            expected = write_spec(spec['command'], validated, spec.get('request_key'))
            if expected != spec or record['state'] not in {'prepared', 'sending', 'accepted', 'rejected', 'review_required'}:
                raise ValueError()
        except (KeyError, ValueError, ClientError):
            fail('INTENT_INTEGRITY_ERROR', '意图参数发生变化；禁止换键或发送', 4)
        return record

    def records(self):
        return sorted([self.read(p.stem) for p in self.root.glob('*.json')],
                      key=lambda r: r['created_at'], reverse=True)


def validate(command, payload):
    if command not in MODELS:
        fail('COMMAND_NOT_ALLOWED', '命令不在固定白名单内')
    try:
        return MODELS[command].model_validate(payload).model_dump(mode='json', exclude_unset=True)
    except (ValidationError, ValueError):
        fail('INVALID_PAYLOAD', '输入字段、类型或值不符合固定命令要求')


def write_spec(command, payload, key):
    if command not in CAS and (not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{32}', key)):
        fail('INTENT_INTEGRITY_ERROR', '意图键无效', 4)
    body = {k: v for k, v in payload.items() if k not in {'new_intent', 'run_id', 'product_id'}}
    method = 'PATCH' if command in CAS else 'POST'
    if command.startswith('browser-'):
        prefix='/v1/runs/'+quote(payload['run_id'],safe='')+'/browser-source'
        if command=='browser-upload':
            path=prefix+'/assets/'+quote(payload['ticket_id'],safe='')+'/body'
            body={'session_id':payload['session_id'],'sha256':payload['sha256'],'bytes':payload['bytes'],'source_url':payload['source_url']}
        elif command=='browser-asset-failure':
            path=prefix+'/assets/'+quote(payload['ticket_id'],safe='')+'/failure'
            body={'request_key':key,'session_id':payload['session_id'],'code':payload['code']}
        else:
            path=prefix+{'browser-attach':'/attach','browser-observe':'/observations','browser-continue':'/continue'}[command]
            body={'request_key':key,**{k:v for k,v in body.items() if k!='ticket_id'}}
        return {'spec_schema':2,'command':command,'input':payload,'request_key':key,'method':method,'path':path,'body':body}
    if command in {'verify','backup'}:
        path='/v1/maintenance/'+command;body={k:v for k,v in body.items() if v is not None};body['request_key']=key
    elif command=='set-storage':
        path='/v1/settings/storage'
    elif command == 'export':
        path='/v1/exports';body={'request_key':key,'selection':'favorites'}
    elif command == 'export-retry':
        path='/v1/exports/'+quote(payload['export_id'],safe='')+'/retry';body={'request_key':key}
    elif command == 'start':
        path = '/v1/runs'
        body = {'request_key': key, 'trigger': 'skill', 'overrides': payload.get('overrides', {})}
    elif command in {'retry', 'cancel'}:
        path = '/v1/runs/' + quote(payload['run_id'], safe='') + '/' + command
        body = {'request_key': key, **({'scope': 'failed'} if command == 'retry' else {})}
    elif command == 'user-state':
        path = '/v1/products/' + quote(payload['product_id'], safe='') + '/user-state'
    else:
        path = '/v1/settings/default-plan'
    return {'command': command, 'input': payload, 'request_key': key,
            'method': method, 'path': path, 'body': body}


def require_success(status, data):
    if status >= 400:
        code = data.get('error', {}).get('code', 'API_ERROR')
        if not isinstance(code, str) or not re.fullmatch(r'[A-Z0-9_]{1,80}', code):
            code = 'API_ERROR'
        fail(code, '本机 API 拒绝请求；请核对当前状态，勿盲目覆盖或换键',
             5 if status == 501 else 4, {'http_status': status, 'response': data})
    return data


class Client:
    def __init__(self, paths, connection_factory=Connection):
        self.paths, self.connection_factory = paths, connection_factory
        self.service = {'checked': False, 'web_ready': None, 'worker_state': 'unknown'}
        self.intent_id = None

    def configured(self):
        path = self.paths.root / 'control' / 'client.json'
        if not path.exists():
            fail('CLIENT_NOT_CONFIGURED', '请先完成一次性 configure；日常操作不安装或重新配置', 3)
        data = load_json(path)
        if set(data) != {'schema', 'data_root', 'port'} or data['schema'] != 1 or data['data_root'] != str(self.paths.root):
            fail('CLIENT_CONFIG_INVALID', '客户端配置与数据根不匹配', 3)
        try:
            return Configure.model_validate({'port': data['port']}).port
        except ValidationError:
            fail('CLIENT_CONFIG_INVALID', '保存的端口不合法', 3)

    def configure(self, payload):
        try:
            config = Configure.model_validate(payload)
        except ValidationError:
            fail('INVALID_PAYLOAD', '配置仅接受整数 port')
        path = self.paths.root / 'control' / 'client.json'
        value = {'schema': 1, 'data_root': str(self.paths.root), 'port': config.port}
        if path.exists() and load_json(path) != value:
            fail('CLIENT_CONFIG_CONFLICT', '已有配置不可静默重绑定；保留原数据根与端口', 4)
        (self.paths.root / 'control').mkdir(parents=True, exist_ok=True)
        launcher.atomic_json(path, value)
        return {'configured': True, 'data_root': str(self.paths.root), 'port': config.port,
                'service_started': False}

    def execute(self, command, payload):
        payload = validate(command, payload)
        port = self.configured()
        if command in {'ensure', 'open', 'status'}:
            name = {'open': 'open_browser'}.get(command, command)
            # Validate recorded identity before launcher can reuse it.
            descriptor = launcher.read_descriptor(self.paths)
            if descriptor and descriptor['port'] != port and not descriptor.get('stopped'):
                fail('PORT_CONFIG_CONFLICT', '实例端口与配置不同', 3)
            result = guarded_launcher()[name](self.paths, port) if command != 'status' else guarded_launcher()[name](self.paths)
            self.service = {**result, 'checked': True}
            return {**result, 'may_resume_accepted_runs': command != 'status',
                    'notice': '服务启动或打开页面可恢复此前已接受任务；不会创建新巡检。'}
        journal = Journal(self.paths)
        if command == 'intents':
            return {'items': [{'intent_id': r['intent_id'], 'command': r['spec']['command'],
                               'state': r['state'], 'created_at': r['created_at'],
                               'payload': r['spec']['body']} for r in journal.records()],
                    'intent_directory': str(journal.root)}
        conn = self.connection_factory(self.paths, port)
        try:
            if command in WRITES or command == 'resume':
                with journal.lock():
                    if command == 'resume':
                        record = journal.read(payload['intent_id'])
                    else:
                        unresolved = [r for r in journal.records() if r['state'] in {'prepared', 'sending'}]
                        if unresolved:
                            fail('INTENT_PENDING', '先核对尚未确定结果的写意图；不会生成替代键', 4,
                                 {'intent_id': unresolved[0]['intent_id']})
                        iid = uuid.uuid4().hex
                        spec = write_spec(command, payload, None if command in CAS else uuid.uuid4().hex)
                        record = {'intent_id': iid, 'created_at': time.time(), 'state': 'prepared',
                                  'spec': spec, 'sha256': fingerprint(spec)}
                        journal.save(record)
                    self.intent_id = record['intent_id']
                    return self.deliver(conn, journal, record)
            path, query = self.read_route(command, payload)
            status, data = conn.request('GET', path, query=query)
            return require_success(status, data)
        finally:
            self.service = conn.service

    @staticmethod
    def read_route(command, payload):
        if command=='browser-status':
            return '/v1/runs/'+quote(payload['run_id'],safe='')+'/browser-source',None
        if command=='maintenance-status':return '/v1/maintenance/'+quote(payload['maintenance_id'],safe=''),None
        if command == 'export-status':
            return '/v1/exports/'+quote(payload['export_id'],safe=''),None
        if command in {'new', 'favorites'}:
            return '/v1/products', {'view': 'new' if command == 'new' else 'favorites',
                                    **{k: v for k, v in payload.items() if v is not None}}
        if command == 'product':
            return '/v1/products/' + quote(payload['product_id'], safe=''), {
                k: v for k, v in payload.items() if k != 'product_id' and v is not None}
        if command == 'progress':
            return '/v1/runs/' + quote(payload['run_id'], safe=''), None
        return {'latest': '/v1/runs/latest', 'sites': '/v1/sites','maintenance':'/v1/maintenance','storage':'/v1/settings/storage',
                'default-plan': '/v1/settings/default-plan'}[command], None

    def deliver(self, conn, journal, record):
        spec, state = record['spec'], record['state']
        if state in {'rejected', 'review_required'}:
            fail('INTENT_REVIEW_REQUIRED', '此意图需要核对；新意图必须依据当前 revision 单独确认', 4,
                 {'intent_id': record['intent_id'], 'saved_result': record.get('result')})
        if state == 'accepted':
            return {'intent_id': record['intent_id'], 'intent_state': state,
                    'cached_receipt': True, 'result': record['result'],
                    'notice': '原意图回执；使用 progress 或详情读取当前业务状态。'}
        if state == 'sending' and spec['command'] in CAS:
            path = '/v1/settings/storage' if spec['command']=='set-storage' else '/v1/settings/default-plan' if spec['command'] == 'set-default-plan' else '/v1/products/' + quote(spec['input']['product_id'], safe='')
            status, observed = conn.request('GET', path)
            require_success(status, observed)
            record.update(state='review_required', result={'current': observed, 'attribution': 'unknown'})
            journal.save(record)
            fail('CAS_REVIEW_REQUIRED', '上次写入结果不确定；已读取当前状态，须核对意图后再决定，不自动重放', 4,
                 {'intent_id': record['intent_id'], 'current': observed})
        if state == 'sending' and spec['command'] == 'start':
            status, observed = conn.request('GET', '/v1/runs/by-request/' + quote(spec['request_key'], safe=''))
            if status != 404:
                require_success(status, observed)
                # Query confirms association, but only same-payload replay returns the original
                # reused/ignored_overrides receipt. Do not infer these from the Run snapshot.
                record.update(state='accepted', result={**observed, 'reconciled_by_request': True,
                    'reused': None, 'reuse_reason': None, 'ignored_overrides': None,
                    'notice': '已核对原键对应任务；首次复用/忽略参数回执未取得，不推测。'})
                journal.save(record)
                return {'intent_id': record['intent_id'], 'intent_state': 'accepted', 'result': record['result']}
        if state=='sending' and spec['command']=='browser-upload':
            prefix='/v1/runs/'+quote(spec['input']['run_id'],safe='')+'/browser-source/receipts/'
            status,observed=conn.request('GET',prefix+quote(spec['request_key'],safe=''))
            if status!=404:
                require_success(status,observed)
                record.update(state='accepted',result=observed)
                journal.save(record)
                return {'intent_id':record['intent_id'],'intent_state':'accepted','result':observed}
        record['state'] = 'sending'
        journal.save(record)  # fsync + replace before the first network mutation.
        if spec['command']=='browser-upload':
            status,data=conn.upload(spec['path'],spec['input'],spec['request_key'])
            if status==409 and data.get('error',{}).get('code')=='SOURCE_UPLOAD_IN_PROGRESS':
                require_success(status,data)  # Preserve sending; the original receiver still owns it.
        else:
            status, data = conn.request(spec['method'], spec['path'], spec['body'])
        if status >= 500 and status != 501:
            require_success(status, data)  # Remain uncertain; preserve key/payload.
        record.update(state='accepted' if status < 400 else 'rejected', result=data)
        journal.save(record)
        require_success(status, data)
        return {'intent_id': record['intent_id'], 'intent_state': record['state'], 'result': data}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        fail('INVALID_ARGUMENTS', '使用 configure 或 request <固定命令> --json-input <JSON文件>')


def main(argv=None):
    client = None
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('action', choices=['configure', 'request'])
        parser.add_argument('command', nargs='?')
        parser.add_argument('--json-input', required=True)
        parser.add_argument('--data-root')
        args = parser.parse_args(argv)
        if (args.action == 'configure' and args.command is not None) or (args.action == 'request' and args.command not in MODELS):
            fail('COMMAND_NOT_ALLOWED', '命令不在固定白名单内')
        payload = load_json(args.json_input)
        client = Client(Paths.at(args.data_root))
        result = client.configure(payload) if args.action == 'configure' else client.execute(args.command, payload)
        output, code = {'ok': True, 'data': result}, 0
    except ClientError as exc:
        output, code = {'ok': False, 'error': {'code': exc.code, 'message': exc.message, 'details': exc.details}}, exc.exit_code
    except ScoutError as exc:
        output, code = {'ok': False, 'error': {'code': exc.code, 'message': '本机环境或实例校验未通过'}}, 3
    except (URLError, HTTPError, TimeoutError, ConnectionError):
        output, code = {'ok': False, 'error': {'code': 'SERVICE_OFFLINE', 'message': '健康核验未通过；保留原意图'}}, 3
    except Exception:
        output, code = {'ok': False, 'error': {'code': 'CLIENT_ERROR', 'message': '客户端未能完成操作；无凭据或原始异常输出'}}, 3
    output['service'] = client.service if client else {'checked': False, 'web_ready': None, 'worker_state': 'unknown'}
    output['intent_id'] = client.intent_id if client else None
    output['exit_code'] = code
    # ASCII JSON is valid UTF-8 even under a Windows legacy console code page.
    print(json.dumps(sanitize(output), ensure_ascii=True))
    return code


if __name__ == '__main__':
    sys.exit(main())
