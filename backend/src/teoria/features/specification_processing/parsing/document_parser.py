"""01 Original files → isolated parser evidence. Parser executable is deployment configuration."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from teoria.features.specification_processing.parsing.document_evidence import build_document_evidence

PARSER_CODE='''import json,sys
from pathlib import Path
from kory_parser import parse,ParseOptions
result=parse(Path(sys.argv[1]),ParseOptions(ocr=False,images=False,extract_contents=True))
Path(sys.argv[2]).write_text(json.dumps(result.to_dict(),ensure_ascii=False))
'''

async def parse_document(source:Path,native_path:Path,document_id:str,parser_python=None):
    executable=parser_python or os.getenv('TEORIA_SPECIFICATION_PARSER_PYTHON') or sys.executable
    process=await asyncio.create_subprocess_exec(executable,'-c',PARSER_CODE,str(source),str(native_path),
        stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
    try:await asyncio.wait_for(process.wait(),90)
    except (TimeoutError,asyncio.CancelledError):
        process.kill();await process.wait();raise
    if process.returncode:raise ValueError('parser_process_failed')
    native=json.loads(await asyncio.to_thread(native_path.read_text))
    if not native['success']:raise ValueError('parser_unsuccessful')
    raw=await asyncio.to_thread(native_path.read_bytes)
    source_bytes=await asyncio.to_thread(source.read_bytes)
    digest=hashlib.sha256(source_bytes).hexdigest()
    if native['sha256']!=digest:raise ValueError('parser_source_checksum_mismatch')
    context=build_document_evidence(native,document_id=document_id,parse_run_id='specification_pipeline',native_sha256=hashlib.sha256(raw).hexdigest()).context()
    context.update({'source_path':str(source),'source_sha256':digest,'parse_path':str(native_path),
        'parser_version':native['parser_version'],'source_file_reverified':True})
    return context
