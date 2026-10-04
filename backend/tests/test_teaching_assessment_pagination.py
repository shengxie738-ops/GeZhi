"""Pure three-kind bounded untrusted positions, without grant or issuer."""
import base64
import importlib
import json

import pytest

from tests.test_teaching_assessment_authorization import denied


def codec():
    try:
        return importlib.import_module('app.services.teaching.assessment_pagination')
    except ModuleNotFoundError as exc:
        pytest.fail(f'B2 Task3 pure cursor codec absent: {exc}')


def token(value):
    raw = value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


@pytest.mark.parametrize('kind,position',[('assignment_catalog_author',{'after_id':'a'}),('assignment_catalog_release',{'after_id':'a'}),('assignment_versions',{'after_version_number':9223372036854775807})])
def test_three_kind_cursor_round_trip_is_exact_and_unpadded(kind,position):
    c = codec()
    encoded = c.encode_cursor(kind,'object','老师🙂',**position)
    assert '=' not in encoded
    payload = json.loads(base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4)))
    assert payload == {'v':1,'kind':kind,'object_id':'object','actor_id':'老师🙂',**position}
    assert c.decode_cursor(encoded,kind,'object','老师🙂') == position
    assert c.decode_cursor(None,kind,'object','老师🙂') is None


@pytest.mark.parametrize('mutation',[{'actor_id':'other'},{'object_id':'other'},{'kind':'assignment_catalog_release'},{'v':2},{'extra':'unused'},{'after_version_number':1},{'after_id':' a '},{'after_id':True}])
def test_cursor_rejects_wrong_binding_schema_and_position(mutation):
    c = codec()
    payload = {'v':1,'kind':'assignment_catalog_author','object_id':'o','actor_id':'owner','after_id':'a'}
    denied(lambda:c.decode_cursor(token({**payload,**mutation}),'assignment_catalog_author','o','owner'),422,'invalid_cursor')


@pytest.mark.parametrize('bad',['=', '***','e30=', 'e30\n', 'e30+', 'e30/', 'e31', '', token(b'\xff'), token(b'{"v":1,"v":1}'), token(b'NaN'), token(b'[]')])
def test_cursor_rejects_alphabet_padding_noncanonical_utf8_and_json(bad):
    c = codec()
    denied(lambda:c.decode_cursor(bad,'assignment_catalog_author','o','owner'),422,'invalid_cursor')


@pytest.mark.parametrize('number',[0,-1,9223372036854775808,True,1.0,'1'])
def test_version_cursor_position_requires_positive_int64(number):
    c = codec()
    payload = {'v':1,'kind':'assignment_versions','object_id':'a','actor_id':'owner','after_version_number':number}
    denied(lambda:c.decode_cursor(token(payload),'assignment_versions','a','owner'),422,'invalid_cursor')


def test_codec_admits_only_current_finite_kinds():
    c = codec()
    for kind in ('own_history','teacher_heads','teacher_history','unknown'):
        denied(lambda:c.encode_cursor(kind,'o','owner',after_id='a'),422,'invalid_cursor')


def test_actual_maximum_three_kind_unicode_cursor_sizes_are_pinned():
    c = codec()
    actor = '\U00020000'*255
    identifier = '\U00020000'*36
    encoded = c.encode_cursor('assignment_catalog_release',identifier,actor,after_id=identifier)
    raw = base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4))
    assert len(raw) == 1394
    assert len(encoded) == 1859
    assert len(raw) <= 6144 and len(encoded) <= 8192
    assert c.decode_cursor(encoded,'assignment_catalog_release',identifier,actor) == {'after_id':identifier}


def test_cursor_caps_decoded_and_encoded_bytes_before_parsing():
    c = codec()
    denied(lambda:c.decode_cursor('a'*8193,'assignment_catalog_author','o','owner'),422,'invalid_cursor')
    denied(lambda:c.decode_cursor(token(b' '*6145),'assignment_catalog_author','o','owner'),422,'invalid_cursor')


@pytest.mark.parametrize('kind,position',[
    ('releases',{'after_id':'release'}),
    ('preview_recipients',{'after_student_id':'学生🙂'}),
    ('historical_recipients',{'after_student_id':'学生🙂'}),
])
def test_task4_finite_cursor_round_trip_and_bindings(kind,position):
    c = codec()
    encoded = c.encode_cursor(kind,'object','teacher',**position)
    assert '=' not in encoded and c.decode_cursor(encoded,kind,'object','teacher') == position
    payload = json.loads(base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4)))
    assert payload == {'v':1,'kind':kind,'object_id':'object','actor_id':'teacher',**position}
    for changes in ({'actor_id':'other'},{'object_id':'other'},{'kind':'assignment_catalog_author'},
                    {'student_id':'unused'},{'v':True}):
        denied(lambda:c.decode_cursor(token({**payload,**changes}),kind,'object','teacher'),422,'invalid_cursor')


@pytest.mark.parametrize('kind',['preview_recipients','historical_recipients'])
@pytest.mark.parametrize('student',[' x','x ','x\n','',True,'x'*256])
def test_task4_recipient_cursor_positions_are_exact_subjects(kind,student):
    c = codec()
    denied(lambda:c.encode_cursor(kind,'o','owner',after_student_id=student),422,'invalid_cursor')


@pytest.mark.parametrize('kind',['releases','preview_recipients','historical_recipients'])
def test_task4_cursor_rejects_wrong_position_field(kind):
    c = codec()
    position = {'after_student_id':'student'} if kind=='releases' else {'after_id':'id'}
    denied(lambda:c.encode_cursor(kind,'o','owner',**position),422,'invalid_cursor')


def test_actual_maximum_task4_unicode_cursor_sizes_are_pinned():
    c = codec()
    actor = '\U00020000'*255
    identifier = '\U00020000'*36
    student = '\U00020000'*255
    encoded = c.encode_cursor('historical_recipients',identifier,actor,after_student_id=student)
    raw = base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4))
    assert len(raw) == 2273 and len(encoded) == 3031
    assert len(raw) <= 6144 and len(encoded) <= 8192
    assert c.decode_cursor(encoded,'historical_recipients',identifier,actor) == {'after_student_id':student}


@pytest.mark.parametrize('kind,student,position',[
    ('own_history','teacher',{'after_sequence':1}),
    ('teacher_heads',None,{'after_student_id':'学生🙂'}),
    ('teacher_heads','学生🙂',{'after_student_id':'学生🙂'}),
    ('teacher_history','学生🙂',{'after_sequence':9223372036854775807}),
])
def test_task5_cursor_round_trip_binds_exact_student_filter(kind,student,position):
    c = codec()
    encoded = c.encode_cursor(kind,'release','teacher',student_id=student,**position)
    assert c.decode_cursor(encoded,kind,'release','teacher',student_id=student) == position
    assert c.decode_cursor(None,kind,'release','teacher',student_id=student) is None
    payload = json.loads(base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4)))
    assert payload == {'v':1,'kind':kind,'object_id':'release','actor_id':'teacher','student_id':student,**position}
    for changes in ({'actor_id':'other'},{'object_id':'other'},{'student_id':'other'},
                    {'kind':'releases'},{'v':True},{'unused':None}):
        denied(lambda:c.decode_cursor(token({**payload,**changes}),kind,'release','teacher',student_id=student),422,'invalid_cursor')


@pytest.mark.parametrize('kind',['own_history','teacher_heads','teacher_history'])
def test_task5_cursor_filter_field_is_required_even_when_null(kind):
    c = codec()
    position = {'after_student_id':'student'} if kind=='teacher_heads' else {'after_sequence':1}
    denied(lambda:c.encode_cursor(kind,'r','actor',**position),422,'invalid_cursor')
    denied(lambda:c.decode_cursor(None,kind,'r','actor'),422,'invalid_cursor')
    payload = {'v':1,'kind':kind,'object_id':'r','actor_id':'actor',**position}
    denied(lambda:c.decode_cursor(token(payload),kind,'r','actor',student_id='actor'),422,'invalid_cursor')


@pytest.mark.parametrize('kind,student',[
    ('own_history',None),('own_history','other'),('teacher_history',None),
    ('teacher_heads',' x'),('teacher_heads','x '),('teacher_history','x\n'),
    ('teacher_history',''),('teacher_history',True),('teacher_heads','x'*256),
])
def test_task5_cursor_filter_and_own_identity_are_exact(kind,student):
    c = codec()
    position = {'after_student_id':'student'} if kind=='teacher_heads' else {'after_sequence':1}
    denied(lambda:c.encode_cursor(kind,'r','actor',student_id=student,**position),422,'invalid_cursor')
    denied(lambda:c.decode_cursor(None,kind,'r','actor',student_id=student),422,'invalid_cursor')


@pytest.mark.parametrize('kind',['own_history','teacher_history'])
@pytest.mark.parametrize('number',[0,-1,9223372036854775808,True,1.0,'1'])
def test_task5_history_sequence_requires_positive_int64(kind,number):
    c = codec()
    payload = {'v':1,'kind':kind,'object_id':'r','actor_id':'actor','student_id':'actor','after_sequence':number}
    denied(lambda:c.decode_cursor(token(payload),kind,'r','actor',student_id='actor'),422,'invalid_cursor')


@pytest.mark.parametrize('bad',[' x','x ','x\n','',True,'x'*256])
def test_task5_teacher_head_position_is_exact_subject(bad):
    c = codec()
    denied(lambda:c.encode_cursor('teacher_heads','r','actor',student_id=None,after_student_id=bad),422,'invalid_cursor')


def test_task5_cursor_rejects_null_to_nonnull_filter_rebinding():
    c = codec()
    encoded = c.encode_cursor('teacher_heads','r','actor',student_id=None,after_student_id='student')
    denied(lambda:c.decode_cursor(encoded,'teacher_heads','r','actor',student_id='student'),422,'invalid_cursor')
    encoded = c.encode_cursor('teacher_heads','r','actor',student_id='student',after_student_id='student')
    denied(lambda:c.decode_cursor(encoded,'teacher_heads','r','actor',student_id=None),422,'invalid_cursor')


def test_task5_cursor_keeps_duplicate_unknown_and_cap_rejections():
    c = codec()
    raw = b'{"v":1,"kind":"teacher_heads","object_id":"r","actor_id":"actor","student_id":null,"student_id":null,"after_student_id":"student"}'
    denied(lambda:c.decode_cursor(token(raw),'teacher_heads','r','actor',student_id=None),422,'invalid_cursor')
    denied(lambda:c.decode_cursor('a'*8193,'teacher_heads','r','actor',student_id=None),422,'invalid_cursor')
    denied(lambda:c.decode_cursor(token(b' '*6145),'teacher_heads','r','actor',student_id=None),422,'invalid_cursor')
    denied(lambda:c.decode_cursor(token(b'\xff'),'teacher_heads','r','actor',student_id=None),422,'invalid_cursor')


@pytest.mark.parametrize('kind,raw_size,encoded_size',[
    ('assignment_catalog_author',1393,1858),('assignment_catalog_release',1394,1859),
    ('assignment_versions',1272,1696),('releases',1376,1835),
    ('preview_recipients',2270,3027),('historical_recipients',2273,3031),
    ('own_history',2294,3059),('teacher_heads',3301,4402),('teacher_history',2298,3064),
])
def test_all_nine_kind_actual_maximum_unicode_sizes_are_pinned(kind,raw_size,encoded_size):
    c = codec()
    subject = '\U00020000'*255
    identifier = '\U00020000'*36
    bindings = {}
    if kind in {'own_history','teacher_heads','teacher_history'}:
        bindings['student_id'] = subject
    if kind in {'own_history','teacher_history'}:
        position = {'after_sequence':9223372036854775807}
    elif kind == 'assignment_versions':
        position = {'after_version_number':9223372036854775807}
    elif kind in {'preview_recipients','historical_recipients','teacher_heads'}:
        position = {'after_student_id':subject}
    else:
        position = {'after_id':identifier}
    encoded = c.encode_cursor(kind,identifier,subject,**bindings,**position)
    raw = base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4))
    assert (len(raw),len(encoded)) == (raw_size,encoded_size)
    assert len(raw) <= 6144 and len(encoded) <= 8192
    assert c.decode_cursor(encoded,kind,identifier,subject,**bindings) == position
