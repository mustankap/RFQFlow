"""Run-scoped local evidence and optional real PRISM delivery."""
import json
import os
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

ACTIVE_RUN = ContextVar('retrieval_run', default=None)
AGENT = 'rudco-rfq-phase1'


def embedding_event(**event):
    run = ACTIVE_RUN.get()
    if run is not None:
        run.events.append(event)


class RetrievalRun:
    def __init__(self, directory: Path | None = None):
        self.session_id = str(uuid4())
        self.directory = directory
        self.events = []
        self.finished = False

    def __enter__(self):
        self.token = ACTIVE_RUN.set(self)
        return self

    def __exit__(self, exc_type, exc, traceback):
        ACTIVE_RUN.reset(self.token)
        if exc_type and not self.finished:
            self.finish({'status': 'error', 'error_type': exc_type.__name__},
                        self.events[-1]['model'] if self.events else 'not-called')

    def finish(self, result: dict, model: str) -> list[str]:
        self.finished = True
        warnings = []
        key = os.getenv('PRISMTRACE_API_KEY')
        project = os.getenv('PRISMTRACE_PROJECT_ID')
        host = os.getenv('PRISMTRACE_HOST', 'https://prism.blockconvey.com').rstrip('/')
        status = 'not_configured'
        trace_ids = []
        if key and project:
            try:
                for event in self.events:
                    payload = {'project_id': project, 'model': event['model'],
                        'input_messages': [{'role': 'user', 'content': json.dumps(event['texts'])}],
                        'output_message': json.dumps({k: v for k, v in event.items() if k != 'texts'}),
                        'latency_ms': event['latency_ms'], 'token_count_input': event.get('tokens', 0),
                        'session_id': self.session_id, 'trace_id': str(uuid4()),
                        'agent_id': AGENT, 'agent_name': AGENT,
                        'metadata': {'operation': 'embedding', 'request_id': event.get('request_id')}}
                    response = httpx.post(host+'/api/traces', headers={'X-PRISMtrace-Key': key}, json=payload, timeout=10)
                    response.raise_for_status()
                    trace_ids.append(response.json().get('id'))
                from prismtrace import PRISMtrace
                with PRISMtrace(api_key=key, host=host, project_id=project, timeout=10) as client:
                    receipt = client.submit_trajectory(
                        [{'step_type': 'tool_call', 'tool_name': 'hybrid_retrieval', 'label': 'SQLite + Chroma evidence retrieval',
                          'output_summary': json.dumps(result), 'status': 'error' if result.get('status') == 'error' else 'success'}],
                        agent_name=AGENT, agent_id=AGENT, conversation_id=self.session_id, model=model,
                        final_status='error' if result.get('status') == 'error' else 'success')
                status = 'delivered' if receipt else 'trajectory_delivery_failed'
                if not receipt:
                    warnings.append('PRISM trajectory delivery failed; local evidence retained')
            except (httpx.HTTPError, ValueError, KeyError):
                status = 'delivery_failed'
                warnings.append('PRISM delivery failed; inspect project credentials and connectivity')
        else:
            warnings.append('PRISM is not configured; live tracing/grounding not verified')
        if self.directory:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                (self.directory/f'{self.session_id}.json').write_text(json.dumps({
                    'session_id': self.session_id, 'agent_name': AGENT,
                    'recorded_at': datetime.now(timezone.utc).isoformat(), 'embedding_events': self.events,
                    'result': result, 'prism_status': status, 'prism_trace_ids': trace_ids}, indent=2))
            except OSError:
                warnings.append('Local trace write failed')
        return warnings
