"""CLI commands for specification processing."""
import asyncio
import json
from .models import SpecificationRun

def run_command(args):
    if args.specification_command=='evaluate':
        from .evaluation import prepare_cycle,run_variant,finish_cycle,abort_cycle
        step=args.evaluation_step
        if step=='schema':
            from .evaluation_cases import EvaluationManifest
            print(json.dumps(EvaluationManifest.model_json_schema(),ensure_ascii=False,indent=2))
            return 0
        if step=='prepare':result=prepare_cycle(args.manifest,args.state_dir)
        elif step=='abort':result=abort_cycle(args.cycle_id,args.state_dir)
        elif step=='finish':result=asyncio.run(finish_cycle(args.cycle_id,args.state_dir))
        else:result=asyncio.run(run_variant(args.cycle_id,step,args.state_dir))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if result.get('decision')=='rejected' else 0
    from .flows import standard_management_flow,document_processing_flow
    manifest=json.loads(args.manifest.read_text())
    request=SpecificationRun.model_validate(manifest)
    entry=standard_management_flow if request.mode=='standard_management' else document_processing_flow
    result=asyncio.run(entry(request.model_dump(mode='json')))
    print(result.model_dump_json(indent=2));return 1 if result.status=='failed' else 0
