from datetime import datetime,timezone
from pathlib import Path
import httpx
import pytest
from teoria.domains.goods.data_processing.storage.artifact_store import FileArtifactStore,S3ArtifactStore,signed_headers

async def test_file_objects_are_immutable_and_replayable(tmp_path):
    store=FileArtifactStore(tmp_path)
    ref=await store.put('specification_processing/run_1/extracted.json',b'{"ok":true}')
    assert await store.get(ref.key)==b'{"ok":true}'
    assert await store.put(ref.key,b'{"ok":true}')==ref
    with pytest.raises(ValueError,match='conflict'):await store.put(ref.key,b'changed')
    assert not any(p.name.startswith('tmp') for p in tmp_path.rglob('*'))

async def test_artifact_paths_cannot_escape_storage(tmp_path):
    store=FileArtifactStore(tmp_path)
    for key in ['../secret','a/../secret','/absolute','a//b','a\\b']:
        with pytest.raises(ValueError):await store.put(key,b'x')
    (tmp_path/'external').symlink_to(tmp_path.parent,target_is_directory=True)
    with pytest.raises(ValueError):await store.put('external/secret',b'x')

def test_signature_matches_official_aws_s3_example():
    # AWS S3 single-chunk SigV4 GET /test.txt example; these are public example credentials.
    headers=signed_headers('GET','https://examplebucket.s3.amazonaws.com/test.txt',b'',
        access_key='AKIAIOSFODNN7EXAMPLE',secret_key='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY',region='us-east-1',
        now=datetime(2013,5,24,tzinfo=timezone.utc),headers={'range':'bytes=0-9'})
    assert headers['authorization'].endswith('Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41')

async def test_s3_uses_signed_native_http_and_conditional_put():
    objects={};calls=[]
    async def handle(request):
        calls.append(request)
        assert request.headers['authorization'].startswith('AWS4-HMAC-SHA256')
        if request.method=='GET':
            return httpx.Response(200,content=objects[request.url.path]) if request.url.path in objects else httpx.Response(404)
        assert request.headers['if-none-match']=='*'
        if request.url.path in objects:return httpx.Response(412)
        objects[request.url.path]=request.content;return httpx.Response(200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        store=S3ArtifactStore('s3://specifications/tests',client,endpoint='http://localhost:9000',access_key='example',secret_key='example')
        first=await store.put('run_1/extracted.json',b'canonical')
        assert first.uri=='s3://specifications/tests/run_1/extracted.json'
        assert await store.get(first.key)==b'canonical'
        assert await store.put(first.key,b'canonical')==first
        with pytest.raises(ValueError,match='conflict'):await store.put(first.key,b'other')
    assert {r.method for r in calls}=={'PUT','GET'}
    assert sum(r.method=='PUT' for r in calls)==1


async def test_s3_does_not_confirm_an_upload_with_wrong_persisted_bytes():
    uploaded=False
    async def handle(request):
        nonlocal uploaded
        if request.method=='GET':return httpx.Response(200,content=b'corrupted') if uploaded else httpx.Response(404)
        uploaded=True
        return httpx.Response(200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        store=S3ArtifactStore('s3://specifications',client,endpoint='http://localhost:9000',access_key='example',secret_key='example')
        with pytest.raises(ValueError,match='checksum verification'):
            await store.put('file.json',b'correct')


async def test_s3_reuses_large_existing_original_without_sending_its_body_again():
    original=b'x'*(5*1024*1024)
    async def handle(request):
        if request.method=='PUT':raise httpx.ReadError('endpoint closed a rejected upload',request=request)
        return httpx.Response(200,content=original)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        store=S3ArtifactStore('s3://specifications',client,access_key='example',secret_key='example')
        ref=await store.put('source.hwp',original,'application/octet-stream')
        assert ref.size_bytes==len(original)


@pytest.mark.parametrize('concurrent_content',[b'canonical',b'conflicting'])
async def test_s3_conditional_put_still_guards_concurrent_creation(concurrent_content):
    reads=0
    async def handle(request):
        nonlocal reads
        if request.method=='GET':
            reads+=1
            return httpx.Response(404) if reads==1 else httpx.Response(200,content=concurrent_content)
        assert request.headers['if-none-match']=='*'
        return httpx.Response(412)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        store=S3ArtifactStore('s3://specifications',client,access_key='example',secret_key='example')
        if concurrent_content==b'canonical':assert (await store.put('file.json',b'canonical')).size_bytes==9
        else:
            with pytest.raises(ValueError,match='immutable S3 artifact conflict'):await store.put('file.json',b'canonical')


async def test_production_storage_never_falls_back_to_local_files(tmp_path,monkeypatch):
    from teoria.domains.goods.data_processing.storage.artifact_store import artifact_store
    monkeypatch.setenv('TEORIA_SPECIFICATION_REQUIRE_OBJECT_STORAGE','true')
    with pytest.raises(ValueError,match='require S3'):
        async with artifact_store(tmp_path.as_uri()):
            pytest.fail('local artifact store must not open')
    assert not list(tmp_path.iterdir())
