"""Unified, non-LLM collection/processing command line; variants are imported drafts."""
import argparse,subprocess,sys,json
from pathlib import Path
import rebuild_web_benchmark as r

def node():
    import shutil
    candidate=shutil.which('node')
    if candidate:return candidate
    candidate=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    if candidate.is_file():return str(candidate)
    raise RuntimeError('需要安装Node.js与scripts/site_crawler/package.json所列依赖')

def run_node(file,*args):
    subprocess.run([node(),str(r.ROOT/'scripts/site_crawler'/file),*args],cwd=r.ROOT,check=True)

def main():
    p=argparse.ArgumentParser(description='EduMathBench 网页采集与重建统一入口')
    p.add_argument('command',choices=['trial','login-capture','collect','reparse','select','assets','variants','replay','verify','build','review','status','reviewed-build','reviewed-verify','reviewed-viewer','eval-self-test','eval-run','eval-score','eval-batch-check','eval-batch-run','eval-pilot-report','eval-image-check','eval-prepare-followup'])
    p.add_argument('--budget',type=int,default=500);p.add_argument('--config');p.add_argument('--no-prompt',action='store_true')
    p.add_argument('--split',choices=['debug','dev','test','all']);p.add_argument('--output');p.add_argument('--run');p.add_argument('--manifest');p.add_argument('--resume',action='store_true');p.add_argument('--allow-test',action='store_true');a=p.parse_args()
    if a.command=='trial':r.initialize();r.probe();r.discover();r.qualify()
    elif a.command=='login-capture':
        args=[]
        if a.config:args+=['--config',str(Path(a.config).resolve())]
        if a.no_prompt:args+=['--no-prompt']
        run_node('capture_logged_in.mjs',*args);r.import_browser()
    elif a.command=='collect':
        selected=r.OUT/'selected/new_questions.jsonl'
        if selected.exists() and len(r.read(selected))==1137 and not any(r.rejection_reasons(q) for q in r.read(selected)):
            print('现有1137道新爬题已满足配额，停止扩量。');return
        assert 1<=a.budget<=500,'追加一轮候选最多500道'
        r.crawl(a.budget);r.qualify();r.select(False);r.materialize();r.status();r.select(True)
    elif a.command=='reparse':r.reparse()
    elif a.command=='select':r.qualify();r.select(True)
    elif a.command=='assets':r.materialize();r.status()
    elif a.command=='variants':
        import web_benchmark_delivery as d;d.variants()
    elif a.command in ('verify','replay'):
        import verify_web_delivery as v
        report=v.verify() if a.command=='verify' else v.replay();print(json.dumps({'passed':report['passed']},ensure_ascii=False))
    elif a.command=='build':
        import web_benchmark_delivery as d,web_review_materials as review,verify_web_delivery as v
        previous={q['id']:q for q in r.read(r.OUT/'variants/parents.jsonl')};rows=d.public();d.families(rows)
        assert all(q['family_id']==previous[q['id']]['family_id'] for q in rows if q['id'] in previous),'题族发生变化，需重核母题绑定'
        r.jsonl(r.OUT/'public/questions.jsonl',rows);d.build();review.build()
        run_node('audit_rebuild_formulas.mjs',str(r.OUT/'questions.jsonl'));run_node('audit_web_render.mjs');run_node('audit_web_review.mjs');v.replay();v.verify()
    elif a.command=='review':
        import web_review_materials as review;review.build()
    elif a.command=='reviewed-build':
        import build_reviewed_release as reviewed;reviewed.build()
    elif a.command=='reviewed-verify':
        import verify_reviewed_release as reviewed
        report=reviewed.verify();print(json.dumps({'passed':report['passed'],'issues':report['issues']},ensure_ascii=False))
        if not report['passed']:raise SystemExit(1)
    elif a.command=='reviewed-viewer':
        import render_reviewed_viewer as reviewed;reviewed.render()
    elif a.command=='eval-self-test':
        import eval_engine;print(json.dumps(eval_engine.self_test(),ensure_ascii=False))
    elif a.command=='eval-run':
        import eval_engine
        from eval_credentials import load_project_env
        load_project_env()
        if not a.config or not a.output:p.error('eval-run requires --config and --output')
        cfg=json.loads(Path(a.config).read_text(encoding='utf-8-sig'))
        if a.split:cfg['split']=a.split
        if not Path(cfg['data_root']).is_absolute():cfg['data_root']=str(r.ROOT/cfg['data_root'])
        print(json.dumps(eval_engine.execute_run(cfg,Path(a.output),resume=a.resume,allow_test=a.allow_test),ensure_ascii=False))
    elif a.command=='eval-score':
        import eval_engine
        if not a.run:p.error('eval-score requires --run')
        print(json.dumps(eval_engine.score_run(Path(a.run)),ensure_ascii=False))
    elif a.command in ('eval-batch-check','eval-batch-run'):
        import eval_batch
        from eval_credentials import load_project_env
        load_project_env()
        manifest=Path(a.manifest) if a.manifest else r.ROOT/'config/evaluation_domestic_six.json'
        output=Path(a.output) if a.output else r.ROOT/'runs/domestic_six_debug'
        if a.command=='eval-batch-check':report=eval_batch.check(manifest,output,allow_test=a.allow_test)
        else:report=eval_batch.run_batch(manifest,output,resume=a.resume,allow_test=a.allow_test)
        print(json.dumps(report,ensure_ascii=False))
    elif a.command=='eval-pilot-report':
        run=a.run if a.run else str(r.ROOT/'runs/domestic_six_debug')
        subprocess.run([sys.executable,str(r.ROOT/'scripts/summarize_api_pilot.py'),'--run',run],cwd=r.ROOT,check=True)
    elif a.command=='eval-image-check':
        import check_api_image_preparation as image_check
        output=Path(a.output) if a.output else r.ROOT/'runs/domestic_six_followup_offline_images.json'
        report=image_check.check(r.ROOT/'data/benchmark_web_v0.3',32,output)
        print(json.dumps({k:v for k,v in report.items() if k!='padding_evidence'},ensure_ascii=False))
        if not report['passed']:raise SystemExit(1)
    elif a.command=='eval-prepare-followup':
        import prepare_api_followup
        print(json.dumps(prepare_api_followup.prepare(),ensure_ascii=False))
    else:print(json.dumps(r.status(),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
