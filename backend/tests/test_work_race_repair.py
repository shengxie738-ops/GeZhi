import asyncio,json
from unittest.mock import patch
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage
from app.core.database import Base,engine,SessionLocal
from app.models.chat_message import ChatMessage
from app.api.endpoints import chat
from app.schemas.chat import ChatRequest
from app.services.chat_history import clear_chat_history

@pytest.fixture(autouse=True)
def clean():
 Base.metadata.create_all(engine)
 with SessionLocal() as db: db.query(ChatMessage).delete();db.commit()

async def no_profile(*a,**k): pass

def test_partial_stream_failure_replaces_body_with_saved_canonical_answer():
 class Graph:
  async def astream_events(self,*a,**k):
   yield {'event':'on_chat_model_stream','data':{'chunk':AIMessage(content='MODEL_PARTIAL_ANSWER')}}
   raise RuntimeError('offline midstream failure')
 async def go():
  with SessionLocal() as db:
   return [json.loads(e[6:]) async for e in chat.stream_chat_events(ChatRequest(message='question',sessionId='alice',agent_mode='paper',conversation_id='task'),db)]
 with patch.object(chat,'agent_graph',Graph()),patch.object(chat,'query_data_structure_knowledge',SimpleNamespace(invoke=lambda *a,**k:'OFFLINE_FALLBACK')),patch('app.services.profile_extractor.extract_and_update_profile',no_profile): events=asyncio.run(go())
 shown=''.join(e['content'] for e in events if e['type']=='token')
 with SessionLocal() as db: stored=db.query(ChatMessage).filter_by(role='assistant').one().content
 assert events[-1]['content'] == stored
 assert any(e['type']=='reset' and e['content']==stored for e in events)
 assert events[-1]['history_saved'] is True
 print('PARTIAL_STREAM',json.dumps({'shown':shown,'stored':stored,'completion':events[-1]},ensure_ascii=False))

def test_queued_request_after_clear_cannot_resurrect_same_task():
 async def go():
  entered=asyncio.Event(); release=asyncio.Event(); calls=[]
  class Graph:
   async def ainvoke(self,state,**k):
    calls.append(state['messages'][-1].content)
    if len(calls)==1: entered.set();await release.wait()
    return {'messages':[AIMessage(content='OFFLINE_REPLY')]}
  with patch.object(chat,'agent_graph',Graph()),patch('app.services.profile_extractor.extract_and_update_profile',no_profile):
   db1=SessionLocal();db2=SessionLocal()
   try:
    a=asyncio.create_task(chat.chat(ChatRequest(message='first',agent_mode='paper',conversation_id='same'),{'sub':'alice'},db1))
    await entered.wait()
    b=asyncio.create_task(chat.chat(ChatRequest(message='already queued before clear',agent_mode='paper',conversation_id='same'),{'sub':'alice'},db2))
    await asyncio.sleep(.02)
    with SessionLocal() as clearer: count=clear_chat_history(clearer,user_id='alice',agent_mode='paper')
    release.set(); replies=await asyncio.gather(a,b)
    with SessionLocal() as db: rows=[(r.role,r.content) for r in db.query(ChatMessage).all()]
    return count,replies,rows
   finally:db1.close();db2.close()
 count,replies,rows=asyncio.run(go())
 assert replies[0]['history_invalidated'] and replies[1]['history_invalidated']
 assert rows==[]
 print('QUEUED_CLEAR',json.dumps({'deleted':count,'replies':replies,'remaining':rows},ensure_ascii=False))

def test_actual_graph_empty_model_reports_unsaved_empty_answer():
 from langchain_core.language_models.chat_models import BaseChatModel
 from langchain_core.outputs import ChatGenerationChunk,ChatResult,ChatGeneration
 from langchain_core.messages import AIMessageChunk
 from app.services import agent_workflow as workflow
 class EmptyModel(BaseChatModel):
  @property
  def _llm_type(self):return 'offline_empty_model'
  def bind_tools(self,tools,**kwargs):return self
  def _generate(self,messages,**kwargs):return ChatResult(generations=[ChatGeneration(message=AIMessage(content=''))])
  def _stream(self,messages,**kwargs):yield ChatGenerationChunk(message=AIMessageChunk(content=''))
 async def go():
  with SessionLocal() as db:
   return [json.loads(e[6:]) async for e in chat.stream_chat_events(ChatRequest(message='question',sessionId='alice',agent_mode='paper',conversation_id='empty'),db)]
 with patch.object(workflow,'build_chat_model',lambda *a,**k:EmptyModel()),patch('app.services.profile_extractor.extract_and_update_profile',no_profile):events=asyncio.run(go())
 with SessionLocal() as db:stored=db.query(ChatMessage).filter_by(role='assistant').all()
 assert stored==[] and events[-1]['history_saved'] is False
 assert events[-1]['delivery_status']=='empty'
 assert not any(e['type']=='token' for e in events)
 print('EMPTY_MODEL',json.dumps({'events':events,'stored':stored},ensure_ascii=False))

def test_disconnected_http_request_waiting_before_clear_cannot_save():
 from fastapi import FastAPI
 from app.api.deps import get_auth_payload
 async def go():
  entered=asyncio.Event();release=asyncio.Event();seen=[]
  class Graph:
   async def ainvoke(self,state,**kwargs):
    seen.append(state['messages'][-1].content)
    if len(seen)==1:entered.set();await release.wait()
    return {'messages':[AIMessage(content='OFFLINE_REPLY')]}
  app=FastAPI();app.include_router(chat.router)
  app.dependency_overrides[get_auth_payload]=lambda:{'sub':'alice','role':'student'}
  body=json.dumps({'message':'queued disconnected request','agent_mode':'paper','conversation_id':'same'}).encode()
  incoming=asyncio.Queue();await incoming.put({'type':'http.request','body':body,'more_body':False})
  outgoing=[]
  async def send(event):outgoing.append(event)
  scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.0'},'http_version':'1.1','method':'POST','scheme':'http','path':'/chat','raw_path':b'/chat','query_string':b'','root_path':'','headers':[(b'content-type',b'application/json')],'server':('test',80),'client':('test',1)}
  with patch.object(chat,'agent_graph',Graph()),patch('app.services.profile_extractor.extract_and_update_profile',no_profile):
   with SessionLocal() as firstdb:
    a=asyncio.create_task(chat.chat(ChatRequest(message='first',agent_mode='paper',conversation_id='same'),{'sub':'alice'},firstdb));await entered.wait()
    b=asyncio.create_task(app(scope,incoming.get,send));await asyncio.sleep(.05)
    assert not b.done()
    await incoming.put({'type':'http.disconnect'})
    with SessionLocal() as clearer:clear_chat_history(clearer,user_id='alice',agent_mode='paper')
    release.set();await asyncio.gather(a,b)
  with SessionLocal() as db:rows=[r.content for r in db.query(ChatMessage).all()]
  return rows,outgoing,incoming.qsize()
 rows,outgoing,pending=asyncio.run(go())
 assert rows==[]
 assert pending==0
 print('DISCONNECTED_QUEUED_CLEAR',json.dumps({'remaining':rows,'unconsumed_disconnect_events':pending,'response_status':outgoing[0]['status']},ensure_ascii=False))

def test_explicitly_cancelled_waiter_does_not_save():
 async def go():
  entered=asyncio.Event();release=asyncio.Event()
  class Graph:
   async def ainvoke(self,*a,**k):entered.set();await release.wait();return {'messages':[AIMessage(content='reply')]}
  with patch.object(chat,'agent_graph',Graph()),patch('app.services.profile_extractor.extract_and_update_profile',no_profile):
   with SessionLocal() as db1,SessionLocal() as db2:
    a=asyncio.create_task(chat.chat(ChatRequest(message='first',agent_mode='paper',conversation_id='same'),{'sub':'alice'},db1));await entered.wait()
    b=asyncio.create_task(chat.chat(ChatRequest(message='queued',agent_mode='paper',conversation_id='same'),{'sub':'alice'},db2));await asyncio.sleep(.02);b.cancel()
    with pytest.raises(asyncio.CancelledError):await b
    with SessionLocal() as clearer:clear_chat_history(clearer,user_id='alice',agent_mode='paper')
    release.set();await a
  with SessionLocal() as db:return db.query(ChatMessage).count()
 assert asyncio.run(go())==0

@pytest.mark.parametrize('stream', [False, True])
def test_whitespace_rejected_without_persistence(stream):
 from fastapi import HTTPException
 async def go():
  with SessionLocal() as db:
   req=ChatRequest(message=' \n\t ', sessionId='alice', agent_mode='paper')
   with pytest.raises(HTTPException) as exc:
    if stream: [e async for e in chat.stream_chat_events(req,db)]
    else: await chat.chat(req, {'sub':'alice'}, db)
   assert exc.value.status_code==422
   assert db.query(ChatMessage).count()==0
 asyncio.run(go())

@pytest.mark.parametrize('stream',[False,True])
def test_clear_during_origin_insert_wait_does_not_recreate(stream):
 original=chat.save_chat_message
 def racing_save(db,**kw):
  with SessionLocal() as clearer: clear_chat_history(clearer,user_id='alice',agent_mode='paper')
  return original(db,**kw)
 async def go():
  with SessionLocal() as db:
   req=ChatRequest(message='question',sessionId='alice',agent_mode='paper',conversation_id='blocked-origin')
   if stream:return [json.loads(e[6:]) async for e in chat.stream_chat_events(req,db)][-1]
   return await chat.chat(req,{'sub':'alice'},db)
 with patch.object(chat,'save_chat_message',racing_save):result=asyncio.run(go())
 assert result['history_invalidated']
 with SessionLocal() as db:assert db.query(ChatMessage).count()==0

@pytest.mark.parametrize('stream',[False,True])
@pytest.mark.parametrize('operation',['delete','failed_clear','other_task','other_mode','other_user'])
def test_admission_scope_commit_boundary_and_cleanup(stream,operation):
 from app.services import chat_history as history
 async def go():
  entered=asyncio.Event();release=asyncio.Event();calls=[]
  class Graph:
   async def ainvoke(self,state,**kwargs):
    calls.append(state['messages'][-1].content)
    if len(calls)==1:entered.set();await release.wait()
    return {'messages':[AIMessage(content='answer')]}
   async def astream_events(self,state,**kwargs):
    await self.ainvoke(state,**kwargs)
    yield {'event':'on_chat_model_stream','data':{'chunk':AIMessage(content='answer')}}
  async def run(db,msg):
   req=ChatRequest(message=msg,sessionId='alice',agent_mode='paper',conversation_id='task')
   if stream:return [json.loads(e[6:]) async for e in chat.stream_chat_events(req,db)][-1]
   return await chat.chat(req,{'sub':'alice'},db)
  with patch.object(chat,'agent_graph',Graph()),patch('app.services.profile_extractor.extract_and_update_profile',no_profile):
   with SessionLocal() as db1,SessionLocal() as db2:
    a=asyncio.create_task(run(db1,'first'));await entered.wait()
    b=asyncio.create_task(run(db2,'queued'));await asyncio.sleep(.02)
    with SessionLocal() as db:
     if operation=='delete':history.delete_chat_message(db,user_id='alice',message_id=db.query(ChatMessage).filter_by(role='user').one().id)
     elif operation=='failed_clear':
      with patch.object(db,'commit',side_effect=RuntimeError('synthetic commit failure')):
       with pytest.raises(RuntimeError):history.clear_chat_history(db,user_id='alice',agent_mode='paper')
     elif operation=='other_task':
      row=history.save_chat_message(db,user_id='alice',agent_mode='paper',role='user',content='other',conversation_id='other')
      history.delete_chat_message(db,user_id='alice',message_id=row.id)
     elif operation=='other_mode':history.clear_chat_history(db,user_id='alice',agent_mode='chat')
     else:history.clear_chat_history(db,user_id='bob',agent_mode='paper')
    release.set();result=await asyncio.gather(a,b)
    assert result[1]['history_invalidated'] is (operation=='delete')
    assert result[1]['history_saved'] is (operation!='delete')
    assert calls==(['first'] if operation=='delete' else ['first','queued'])
  assert len(history._admissions)==0
 asyncio.run(go())


def test_nonstream_empty_model_does_not_save_assistant_or_replay():
 class Graph:
  async def ainvoke(self,*a,**kw):return {'messages':[AIMessage(content='   ')]}
 async def go():
  with SessionLocal() as db:return await chat.chat(ChatRequest(message='question',agent_mode='paper'),{'sub':'alice'},db)
 with patch.object(chat,'agent_graph',Graph()),patch.object(chat,'query_data_structure_knowledge',SimpleNamespace(invoke=lambda *a,**k:pytest.fail('must not replay'))):result=asyncio.run(go())
 assert result['error']=='empty_response' and result['history_saved'] is False
 with SessionLocal() as db:assert db.query(ChatMessage).filter_by(role='assistant').count()==0


def test_delete_legacy_reply_invalidates_anchor_admission():
 from app.services import chat_history as history
 with SessionLocal() as db:
  anchor=history.save_chat_message(db,user_id='alice',agent_mode='paper',role='user',content='q')
  reply=history.save_chat_message(db,user_id='alice',agent_mode='paper',role='assistant',content='a')
  with history.admit_chat_request('alice','paper',f'legacy-paper-{anchor.id}') as admission:
   history.delete_chat_message(db,user_id='alice',message_id=reply.id)
   assert admission.reason=='context_deleted'


def test_disconnect_at_model_completion_prevents_reply_commit():
 class Connection:
  disconnected=False
  async def is_disconnected(self):return self.disconnected
 connection=Connection()
 class Graph:
  async def ainvoke(self,*a,**k):
   connection.disconnected=True
   return {'messages':[AIMessage(content='answer after disconnect')]}
 async def go():
  with SessionLocal() as db:return await chat.chat(ChatRequest(message='question',agent_mode='paper'),{'sub':'alice'},db,http_request=connection)
 with patch.object(chat,'agent_graph',Graph()),patch('app.services.profile_extractor.extract_and_update_profile',no_profile):asyncio.run(go())
 with SessionLocal() as db:assert db.query(ChatMessage).filter_by(role='assistant').count()==0

@pytest.mark.parametrize('stream',[False,True])
def test_empty_rag_model_returns_no_answer(stream):
 class Model:
  def invoke(self,*a,**k):return AIMessage(content='')
  async def astream(self,*a,**k):yield AIMessage(content='')
 async def go():
  with SessionLocal() as db:
   req=ChatRequest(message='question',sessionId='alice',agent_mode='rag')
   if stream:return [json.loads(e[6:]) async for e in chat.stream_chat_events(req,db)][-1]
   return await chat.chat(req,{'sub':'alice'},db)
 with patch.object(chat,'get_request_chat_model',lambda *a,**k:Model()),patch.object(chat,'retrieve_chunks_for_user',lambda *a,**k:[{'document_name':'test','content':'reference'}]),patch('app.services.profile_extractor.extract_and_update_profile',no_profile):result=asyncio.run(go())
 assert result['delivery_status']=='empty' and not result['history_saved']
 with SessionLocal() as db:assert db.query(ChatMessage).filter_by(role='assistant').count()==0
