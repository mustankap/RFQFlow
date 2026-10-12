import json

import httpx

from backend.app.retrieval.observability import RetrievalRun, embedding_event


def test_prism_real_api_contract_with_mocked_transport(monkeypatch, tmp_path):
    monkeypatch.setenv('PRISMTRACE_API_KEY','test-prism-not-real')
    monkeypatch.setenv('PRISMTRACE_PROJECT_ID','test-project')
    monkeypatch.setenv('PRISMTRACE_HOST','https://prism.blockconvey.com')
    calls=[]

    def post(url, **kwargs):
        calls.append(kwargs['json'])
        assert url=='https://prism.blockconvey.com/api/traces'
        assert kwargs['headers']['X-PRISMtrace-Key']=='test-prism-not-real'
        return httpx.Response(200, json={'id':'receipt-id'},request=httpx.Request('POST',url))

    monkeypatch.setattr(httpx,'post',post)
    import prismtrace
    trajectories=[]
    monkeypatch.setattr(prismtrace.PRISMtrace,'submit_trajectory',lambda self,*args,**kwargs: trajectories.append(kwargs) or {'id':'trajectory-id'})
    with RetrievalRun(tmp_path) as run:
        embedding_event(model='test-model',texts=['synthetic input'],latency_ms=12,dimensions=3,tokens=2)
        assert run.finish({'result':'evidence'},'test-model')==[]
    assert calls[0]['session_id']==trajectories[0]['conversation_id']==run.session_id
    saved=json.loads((tmp_path/f'{run.session_id}.json').read_text())
    assert saved['prism_status']=='delivered'
    assert saved['prism_trace_ids']==['receipt-id']
    assert 'test-prism-not-real' not in json.dumps(saved)


def test_prism_failure_preserves_local_result(monkeypatch,tmp_path):
    monkeypatch.setenv('PRISMTRACE_API_KEY','test-key')
    monkeypatch.setenv('PRISMTRACE_PROJECT_ID','test-project')
    monkeypatch.setattr(httpx,'post',lambda *a,**k: (_ for _ in ()).throw(httpx.ConnectError('unavailable')))
    with RetrievalRun(tmp_path) as run:
        embedding_event(model='test-model',texts=['x'],latency_ms=1)
        warnings=run.finish({'items':[]},'test-model')
    assert any('PRISM delivery failed' in w for w in warnings)
    saved=json.loads((tmp_path/f'{run.session_id}.json').read_text())
    assert saved['prism_status']=='delivery_failed'
    assert saved['result']=={'items':[]}


def test_failed_operation_is_recorded(monkeypatch,tmp_path):
    monkeypatch.delenv('PRISMTRACE_API_KEY',raising=False)
    monkeypatch.delenv('PRISMTRACE_PROJECT_ID',raising=False)
    try:
        with RetrievalRun(tmp_path) as run:
            raise ValueError('example')
    except ValueError:
        pass
    saved=json.loads((tmp_path/f'{run.session_id}.json').read_text())
    assert saved['result']['status']=='error'
