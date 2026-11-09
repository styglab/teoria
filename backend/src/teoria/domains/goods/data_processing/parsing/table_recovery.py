"""Bounded PDF table-region OCR; retain native text and diagnostic uncertainty."""
import asyncio
import json
from pathlib import Path

TABLE_FAILURE_CODES = frozenset({'INVALID_TABLE', 'TABLE_PARSE_FAILED'})
MAX_RECOVERY_REGIONS = 3

# Rendering/OCR stays in the isolated parser environment, outside the API/worker event loop.
RECOVERY_CODE = '''import json,sys
from pathlib import Path
import pymupdf
from kory_parser import parse,ParseOptions
regions=json.loads(sys.argv[3]);output=[]
with pymupdf.open(sys.argv[1]) as document:
 for region in regions:
  page=document[region['page']-1]
  clip=pymupdf.Rect(region['bbox']) & page.rect
  if clip.is_empty:continue
  scale=min(2.0,(16000000/max(clip.width*clip.height,1))**0.5)
  pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=clip,alpha=False,colorspace=pymupdf.csRGB)
  raster=pymupdf.open()
  raster_page=raster.new_page(width=clip.width,height=clip.height)
  raster_page.insert_image(raster_page.rect,stream=pix.tobytes('png'))
  parsed=parse(raster.tobytes(),ParseOptions(ocr=True,images=False))
  raster.close()
  blocks=[]
  for block in parsed.to_dict().get('blocks',[]):
   if not block.get('text','').strip():continue
   ref=block.get('source') or {};box=ref.get('bbox')
   if box and len(box)==4:
    ref['bbox']=[box[0]+clip.x0,box[1]+clip.y0,box[2]+clip.x0,box[3]+clip.y0]
   else:ref['bbox']=list(clip)
   ref.update(part='pdf',page=region['page'],unit='pt',coordinate_system='top_left',anchor='ocr:table_recovery')
   block['source']=ref;blocks.append(block)
  output.append({'region':region,'blocks':blocks})
Path(sys.argv[2]).write_text(json.dumps(output,ensure_ascii=False))
'''


def table_failure_regions(native):
    regions = []
    for warning in native.get('warnings', []):
        if not isinstance(warning, dict) or warning.get('code') not in TABLE_FAILURE_CODES:
            continue
        source = warning.get('source') or {}
        page, bbox = source.get('page'), source.get('bbox')
        if isinstance(page, int) and page > 0 and isinstance(bbox, (tuple, list)) and len(bbox) == 4:
            region = {'page': page, 'bbox': list(bbox)}
            if region not in regions:
                regions.append(region)
    return regions


async def recover_table_regions(source, native, native_path, executable):
    """Try only diagnosed PDF table regions once; missing inventories do not trigger OCR."""
    failures = [w for w in native.get('warnings', [])
                if isinstance(w, dict) and w.get('code') in TABLE_FAILURE_CODES]
    report = {'status': 'not_needed', 'attempted_regions': [], 'recovered_regions': []}
    if not failures:
        return report
    regions = table_failure_regions(native)
    if Path(source).suffix.lower() != '.pdf' or not regions:
        return {**report, 'status': 'unsupported', 'reason': 'no_renderable_table_region'}
    selected = regions[:MAX_RECOVERY_REGIONS]
    report.update(status='failed', attempted_regions=selected)
    output = Path(native_path).with_name('table_ocr_recovery.json')
    try:
        process = await asyncio.create_subprocess_exec(
            executable, '-c', RECOVERY_CODE, str(source), str(output), json.dumps(selected),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    except OSError:
        return {**report, 'reason': 'ocr_process_unavailable'}
    try:
        await asyncio.wait_for(process.communicate(), 90)
        if process.returncode:
            return {**report, 'reason': 'ocr_process_failed'}
        observations = json.loads(await asyncio.to_thread(output.read_text))
        # Recovered text is supplementary evidence, not a claim of reconstructed table layout.
        accepted=[]
        for observation in observations:
            if observation.get('region') not in selected:
                raise ValueError('unexpected recovery region')
            blocks = observation.get('blocks', [])
            if not blocks:
                continue
            for block in blocks:
                if not block.get('text', '').strip() or block.get('type') != 'paragraph':
                    raise ValueError('invalid recovered block')
                accepted.append(block)
            report['recovered_regions'].append(observation['region'])
        native['blocks'].extend(accepted)
        report['status'] = 'text_recovered' if len(report['recovered_regions']) == len(regions) else 'partial'
        return report
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill(); await process.communicate()
        raise
    except TimeoutError:
        if process.returncode is None:
            process.kill(); await process.communicate()
        return {**report, 'reason': 'ocr_timeout'}
    except (ValueError, OSError, KeyError):
        return {**report, 'reason': 'invalid_recovery_output'}
    finally:
        await asyncio.to_thread(output.unlink,missing_ok=True)
