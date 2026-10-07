import json
import uuid
from unittest.mock import patch
import pytest
from fashion_scout import client as c
from fashion_scout.config import Paths
from fashion_scout.client_models import MODELS


@pytest.mark.parametrize('command,payload', [
    ('GET', {}), ('https://evil.invalid', {}), ('start', {'new_intent': 1}),
    ('start', {'new_intent': True, 'url': 'https://evil.invalid'}),
    ('start', {'new_intent': True, 'overrides': {'window_days': 7.0}}),
    ('start', {'new_intent': True, 'request_key': 'caller'}),
    ('product', {'product_id': '../sites'}), ('progress', {'run_id': 'a?x=1'}),
    ('retry', {'new_intent': True, 'run_id': 'r', 'overrides': {}}),
    ('new', {'limit': True}), ('user-state', {'product_id': 'p', 'expected_revision': 1}),
    ('user-state', {'product_id': 'p', 'expected_revision': 1, 'favorite': 'yes'}),
    ('set-default-plan', {'expected_revision': 1, 'window_days': None}),
    ('resume', {'intent_id': 'a'*32, 'payload': {}}),
])
def test_strict(command, payload):
    with pytest.raises(c.ClientError): c.validate(command, payload)


@pytest.mark.parametrize('raw', ['{"x":1,"x":2}', '[]', '{"x":NaN}', '{', '"oops"'])
def test_json(tmp_path, raw):
    p=tmp_path/'input.json';p.write_text(raw)
    with pytest.raises(c.ClientError):c.load_json(p)


class Fake:
    calls=[]
    answers=[]
    service={'web_ready': True, 'worker_state': 'offline'}
    def __init__(self,*args):pass
    def request(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        answer=self.answers.pop(0)
        if isinstance(answer,Exception):raise answer
        return answer


@pytest.fixture
def setup(tmp_path):
    Fake.calls=[];Fake.answers=[]
    app=c.Client(Paths.at(tmp_path),Fake);app.configure({'port':18765})
    return app


def test_start_lost_response_query_404_replay_and_active_receipt(setup):
    Fake.answers=[c.ClientError('TRANSPORT_UNCERTAIN','lost',3)]
    with pytest.raises(c.ClientError):setup.execute('start',{'new_intent':True,'overrides':{'window_days':7}})
    iid=setup.intent_id;original=Fake.calls[0]
    restored=c.Client(setup.paths,Fake)
    Fake.answers=[(404,{'error':{'code':'RUN_NOT_FOUND'}}),(200,{'run':{'id':'r','state':'queued'},'reused':True,'reuse_reason':'active_run','ignored_overrides':['window_days']})]
    result=restored.execute('resume',{'intent_id':iid})
    assert Fake.calls[1][0][0]=='GET'
    assert Fake.calls[2]==original
    assert result['result']['ignored_overrides']==['window_days']
    assert original[0][2]['trigger']=='skill'
    assert restored.execute('resume',{'intent_id':iid})['cached_receipt']
    assert len(Fake.calls)==3


def test_lost_start_query_found_and_no_post(setup):
    Fake.answers=[c.ClientError('TRANSPORT_UNCERTAIN','lost',3)]
    with pytest.raises(c.ClientError):setup.execute('start',{'new_intent':True})
    Fake.answers=[(200,{'run':{'id':'r','state':'partial','coverage':[{'complete':False}]}})]
    result=setup.execute('resume',{'intent_id':setup.intent_id})
    assert len(Fake.calls)==2 and result['result']['ignored_overrides'] is None
    assert result['result']['run']['state']=='partial'


@pytest.mark.parametrize('command', ['retry','cancel'])
def test_operation_replays_same_key_after_restart(setup,command):
    Fake.answers=[c.ClientError('TRANSPORT_UNCERTAIN','lost',3)]
    with pytest.raises(c.ClientError):setup.execute(command,{'new_intent':True,'run_id':'original'})
    Fake.answers=[(200,{'run':{'id':'original'}})]
    c.Client(setup.paths,Fake).execute('resume',{'intent_id':setup.intent_id})
    assert Fake.calls[0]==Fake.calls[1]


@pytest.mark.parametrize('command,payload', [
    ('set-default-plan',{'expected_revision':1,'window_days':7}),
    ('user-state',{'product_id':'p','expected_revision':1,'favorite':True}),
])
def test_cas_uncertain_only_reads_then_requires_review(setup,command,payload):
    Fake.answers=[c.ClientError('TRANSPORT_UNCERTAIN','lost',3)]
    with pytest.raises(c.ClientError):setup.execute(command,payload)
    Fake.answers=[(200,{'revision':2})]
    with pytest.raises(c.ClientError) as e:setup.execute('resume',{'intent_id':setup.intent_id})
    assert e.value.code=='CAS_REVIEW_REQUIRED'
    assert Fake.calls[-1][0][0]=='GET'
    assert 'request_key' not in Fake.calls[0][0][2]


def test_storage_failure_zero_send_and_payload_tamper(setup):
    with patch.object(c.Journal,'save',side_effect=c.ClientError('INTENT_STORAGE_ERROR','no',3)):
        with pytest.raises(c.ClientError):setup.execute('start',{'new_intent':True})
    assert not Fake.calls
    Fake.answers=[c.ClientError('TRANSPORT_UNCERTAIN','lost',3)]
    with pytest.raises(c.ClientError):setup.execute('start',{'new_intent':True})
    iid=setup.intent_id
    with pytest.raises(c.ClientError) as e:setup.execute('start',{'new_intent':True})
    assert e.value.code=='INTENT_PENDING'
    p=c.Journal(setup.paths).root/(iid+'.json');data=json.loads(p.read_text('utf-8'))
    data['spec']['body']['overrides']={'window_days':7};p.write_text(json.dumps(data))
    with pytest.raises(c.ClientError) as e:setup.execute('resume',{'intent_id':iid})
    assert e.value.code=='INTENT_INTEGRITY_ERROR' and len(Fake.calls)==1


def test_conflict_does_not_replace_key(setup):
    Fake.answers=[(409,{'error':{'code':'REQUEST_KEY_CONFLICT'}})]
    with pytest.raises(c.ClientError):setup.execute('start',{'new_intent':True})
    iid=setup.intent_id
    with pytest.raises(c.ClientError):setup.execute('resume',{'intent_id':iid})
    assert len(Fake.calls)==1


def test_readonly_maintenance_storage_and_latest_empty(setup):
    for command in ('maintenance','storage'):
        Fake.answers=[(200,{'read_only':True})]
        assert setup.execute(command,{})['read_only']
        assert Fake.calls[-1][0][0]=='GET'
    Fake.answers=[(200,{'latest_run':None})]
    assert setup.execute('latest',{})['latest_run'] is None


def test_secret_and_exception_redaction(tmp_path,capsys):
    p=tmp_path/'i.json';p.write_text('{}')
    secret='b'*64
    with patch.object(c.Client,'execute',side_effect=RuntimeError('Bearer '+secret)):
        assert c.main(['request','latest','--data-root',str(tmp_path),'--json-input',str(p)])==3
    assert secret not in capsys.readouterr().out
    assert secret not in json.dumps(c.sanitize({'Authorization':secret,'title':secret,'bootstrap_url':'secret'},secret))


def test_connection_checks_identity_before_credentials(setup):
    conn=c.Connection(setup.paths,18765)
    with patch.object(c.launcher,'read_descriptor',return_value={'port':1,'stopped':False}):
        with pytest.raises(c.ClientError) as e:conn.verify()
        assert e.value.code=='PORT_CONFIG_CONFLICT' and conn.token is None
    with patch.object(c.launcher,'read_descriptor',return_value={'port':18765,'instance':str(uuid.uuid4())}),patch.object(c.launcher,'verified_process',return_value=None):
        with pytest.raises(c.ClientError) as e:conn.verify()
        assert e.value.code=='SERVICE_OFFLINE' and conn.token is None


def test_proxy_and_redirect_are_disabled(monkeypatch,setup):
    seen={}
    class HTTP:
        def __init__(self,**kwargs):seen.update(kwargs)
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def stream(self,*args,**kwargs):
            from contextlib import contextmanager
            @contextmanager
            def response():yield type('Response',(),{'status_code':302})()
            return response()
    conn=c.Connection(setup.paths,18765);conn.token='b'*64
    with patch.object(conn,'verify'),patch.object(c.httpx,'Client',HTTP):
        with pytest.raises(c.ClientError) as e:conn.request('GET','/v1/sites')
    assert e.value.code=='REDIRECT_REJECTED'
    assert seen['trust_env'] is False and seen['follow_redirects'] is False
    with pytest.raises(c.ClientError):c.NoRedirect().redirect_request(None,None,302,None,None,'http://evil.invalid')


def test_result_disk_failure_keeps_recoverable_original_intent(setup):
    real_save=c.Journal.save
    saves=[]
    def save(journal,record):
        saves.append(record['state'])
        if record['state']=='accepted':raise c.ClientError('INTENT_STORAGE_ERROR','disk',3)
        return real_save(journal,record)
    Fake.answers=[(202,{'run':{'id':'accepted'}})]
    with patch.object(c.Journal,'save',save):
        with pytest.raises(c.ClientError):setup.execute('start',{'new_intent':True})
    iid=setup.intent_id
    assert saves==['prepared','sending','accepted']
    assert c.Journal(setup.paths).read(iid)['state']=='sending'
    Fake.answers=[(200,{'run':{'id':'accepted'}})]
    assert setup.execute('resume',{'intent_id':iid})['result']['run']['id']=='accepted'
    assert Fake.calls[-1][0][0]=='GET'
