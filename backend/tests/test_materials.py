import base64
from unittest.mock import Mock

import httpx
import pytest

from backend.materials import MaterialSession, parse_attachment


def encoded(text):
    return base64.b64encode(text.encode()).decode()


def test_text_snapshot_preserves_all_content_and_locations():
    text = '第一行\n' + 'x' * 2300 + '\n结束'
    parsed = parse_attachment('example.md', encoded(text))
    assert ''.join(s['text'] for s in parsed['segments']) == text
    assert parsed['segments'][0]['line'] == 1
    assert parsed['segments'][1]['line'] == 2


@pytest.mark.parametrize('name,value', [('x.docx', 'text'), ('x.txt', '\x00binary'), ('x.md', '   '), ('x.txt', 'a' * 150001)])
def test_invalid_uploads_fail_without_silent_truncation(name, value):
    with pytest.raises(ValueError):
        parse_attachment(name, encoded(value))


def test_attachment_scope_and_real_citation_ids():
    event = Mock()
    session = MaterialSession({'attachments': [{'id': 'owned', 'name': 'facts.txt', 'source_kind': 'upload',
        'segments': [{'id': 's1', 'text': '保留期限为17天。', 'location': '第1行'}]}]}, 'run', 'user', event, lambda: False)
    assert not session.read_attachment({'attachment_id': 'other', 'segment': 1})['success']
    found = session.read_attachment({'attachment_id': 'owned', 'segment': 1})
    assert found['sources'][0]['evidence_id'] == 'E1'
    session.search_attachments({'query': '期限'})
    assert len(session.sources) == 1
    result = session.finish({'final_answer': '17天[E1]，其他[E9]'})
    assert result['final_answer'] == '17天[E1]，其他[来源未验证]'
    assert result['sources'][0]['cited']


def test_unselected_knowledge_never_calls_embedding(monkeypatch):
    client = Mock()
    monkeypatch.setattr(httpx, 'Client', client)
    session = MaterialSession({}, 'run', 'user', Mock(), lambda: False)
    assert not session.search_knowledge({'query': '问题'})['success']
    client.assert_not_called()


def test_knowledge_remote_embedding_and_authorized_search(tmp_path, monkeypatch):
    secret = tmp_path / 'embedding.env'
    secret.write_text('SILICONFLOW_API_KEY=test-only-key', encoding='utf-8')
    monkeypatch.setenv('RAG_EMBEDDING_ENV_FILE', str(secret))
    monkeypatch.setenv('INTERNAL_SERVICE_TOKEN', 'test-token')
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.host == 'api.siliconflow.cn':
            return httpx.Response(200, json={'data': [{'embedding': [0.1] * 1024}]})
        return httpx.Response(200, json={'results': [{'document_id': 'doc', 'chunk_id': 'chunk', 'text': '证据', 'location': '字符0–2'}]})
    original_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    event = Mock()
    session = MaterialSession({'knowledge_ids': ['duretrieval']}, 'run', 'user', event, lambda: False)
    result = session.search_knowledge({'query': '测试问题'})
    assert result['success'] and result['sources'][0]['evidence_id'] == 'E1'
    assert len(calls) == 2
    assert calls[1].headers['X-Internal-Token'] == 'test-token'
    assert b'"run_id":"run"' in calls[1].content
    assert event.call_args_list[-1].args[0] == 'agent.knowledge.search.completed'
