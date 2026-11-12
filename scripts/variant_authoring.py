"""Record explicitly assistant-authored variants; this is not a question generator."""
import hashlib,json
from pathlib import Path
from rebuild_web_benchmark import ROOT,OUT,read,jsonl,site

PARENT_SHA='9455e30e88f3e52fb3061211f7e152af8b5773f91d09963a5d7df6384bad7435'
class Session:
    def __init__(self,batch,revision=None):
        self.batch=batch;self.rows=[];self.revision=revision
        self.directory=OUT/'variants/regeneration_v2' if revision=='v2' else OUT/'variants'
        file=self.directory/'parents.jsonl'
        self.parent_sha='c324cf22c31b3d2e4a258e0404132391f63a32b2fb28cade28ca46caed266495' if revision=='v2' else PARENT_SHA
        assert hashlib.sha256(file.read_bytes()).hexdigest()==self.parent_sha,'母题版本变化，需要重新核对逐题改编内容'
        self.parents=read(file)
    def add(self,index,question,options,answer,change,note,difficulty,expr=None,values=None,spec=None):
        p=self.parents[index-1]
        if spec is None:
            spec={'kind':'derived_value','derived_expr':expr,'option_exprs':dict(zip('ABCD',values))} if expr is not None else {'kind':'manual_review_required','reason':'概念或几何语义需后续阅读题面复核；不以结构检查替代数学证明。'}
        prefix='EMB-V-WEB2R2' if self.revision=='v2' else 'EMB-V-WEB2'
        self.rows.append({'id':f'{prefix}-G{p["grade"]}-{index:03d}','parent_id':p['id'],'source_type':'variant',
          'question':question,'options':dict(zip('ABCD',options)),'answer':answer,'difficulty':difficulty,
          'change_description':change,'verification_note':note,'verification_spec':spec,
          'authored_at':site.stamp(),'authoring_batch':self.batch,'parent_snapshot_sha256':self.parent_sha,
          **({'generation_revision':'v2_regeneration','parent_difficulty':p['difficulty']} if self.revision=='v2' else {})})
    def save(self):
        from verify_web_variant_math import check_spec
        for q in self.rows:
            if q['verification_spec']['kind']!='manual_review_required':
                try:
                    matches,_=check_spec(q['verification_spec']);assert matches==[q['answer']],(matches,q['answer'])
                except Exception as error:
                    raise ValueError(q['id']+': '+str(error)) from error
        file=self.directory/'authored'/(self.batch+'.jsonl');jsonl(file,self.rows)
        print(json.dumps({'batch':self.batch,'explicitly_assistant_authored':len(self.rows),'program_checks_passed':True},ensure_ascii=False))
