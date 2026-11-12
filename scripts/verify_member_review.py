"""Verify the member copy against the unchanged canonical master and seal file hashes."""
import base64,copy,csv,hashlib,json
from collections import Counter
import rebuild_web_benchmark as r
from build_member_review import DEST,PAGE

def main():
    master=r.read(r.OUT/'questions.jsonl');by={q['id']:q for q in master};rows=r.read(DEST/'题目集合.jsonl')
    build=json.loads((DEST/'构建记录.json').read_text(encoding='utf-8'))
    assert r.sha(r.OUT/'questions.jsonl')==build['source_questions_sha256']
    assert len(rows)==len({q['id'] for q in rows})==1800 and set(by)=={q['id'] for q in rows}
    assert [q['review_number'] for q in rows]==list(range(1,1801))
    for index,grade in [(0,7),(600,8),(1200,9)]:assert {q['grade'] for q in rows[index:index+600]}=={grade}
    number={q['id']:q['review_number'] for q in rows};images=0;digests=set()
    for q in rows:
        before=by[q['id']];clone=copy.deepcopy(q);clone.pop('review_number');clone.pop('parent_review_number')
        for group in ['image_assets','answer_image_assets']:
            for a in clone.get(group,[]):
                url=a.pop('data_url');digest=hashlib.sha256(base64.b64decode(url.split(',',1)[1],validate=True)).hexdigest()
                assert digest==a['sha256'];images+=1;digests.add(digest)
        assert clone==before,('source record changed',q['id'])
        if q['source_type']=='variant':assert q['parent_review_number']==number[q['parent_id']]==q['review_number']-1
    tables={}
    for name in ['复核填写表.csv','答案与来源对照.csv','题号对应表.csv']:
        with (DEST/name).open(encoding='utf-8-sig',newline='') as f:table=list(csv.DictReader(f))
        assert len(table)==1800 and [int(q['复核编号']) for q in table]==list(range(1,1801))
        assert [q['原始题号'] for q in table]==[q['id'] for q in rows]
        tables[name]=table
    for q in tables['复核填写表.csv']:
        assert q['复核结论']=='待复核' and all(q[k]=='' for k in ['复核成员','复核日期','独立作答','建议答案','题干或选项问题','答案问题','年级模块难度问题','修改建议','备注'])
    for q,answer in zip(rows,tables['答案与来源对照.csv']):assert answer['候选答案']==q['answer'] and answer['来源链接']==q['source']['url']
    audit=json.loads((DEST/'页面检查报告.json').read_text(encoding='utf-8'))
    assert audit['passed'] and audit['html_sha256']==r.sha(DEST/PAGE) and audit['jsonl_sha256']==r.sha(DEST/'题目集合.jsonl')
    report={'records':1800,'sequential_numbers':True,'canonical_content_ids_answers_provenance_unchanged':True,'parent_variant_adjacency':True,'portable_image_occurrences_verified':images,'distinct_images_verified':len(digests),'all_csv_rows_aligned':True,'review_form_all_pending':True,'browser_3600_visits_passed':audit['render_visits']==3600,'master_sha256':r.sha(r.OUT/'questions.jsonl'),'human_review_completed':False,'passed':True}
    r.dump(DEST/'集合一致性检查.json',report)
    manifest={'files':[{'name':p.name,'bytes':p.stat().st_size,'sha256':r.sha(p)} for p in sorted(DEST.iterdir()) if p.is_file() and p.name!='交付文件摘要.json'],'zip_created':False}
    r.dump(DEST/'交付文件摘要.json',manifest)
    print(json.dumps({'passed':True,'records':1800,'files':len(manifest['files'])+1,'image_instances':images,'normal_folder':str(DEST)},ensure_ascii=False))

if __name__=='__main__':main()
