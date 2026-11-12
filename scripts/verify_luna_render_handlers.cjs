// Unit-test checker callbacks with synthetic controls; this is not a browser render.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const base=path.resolve(__dirname,'..');
const source=JSON.parse(fs.readFileSync(path.join(base,'data/reports/luna_render_audit/handler_sources.json'),'utf8'));
const scope={window:{}};
vm.createContext(scope);
vm.runInContext('let state={};let observedState;const list={querySelector(){return {dataset:{questionId:"synthetic-"+state.page}};}};function draw(){observedState={...state};}\n'+source.gateway,scope);
scope.window.__embAuditDraw(0);
assert.strictEqual(vm.runInContext('observedState.page',scope),0);
scope.window.__embAuditDraw(1499);
assert.strictEqual(vm.runInContext('observedState.page',scope),1499);

async function controlsTest(fail) {
  const elements={};
  for(const id of ['start-audit','stop-audit','download-audit','audit-status','audit-progress','audit-count','audit-details']) {
    elements[id]={disabled:false,textContent:'',listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}};
  }
  const items=[{id:'synthetic-item',status:'checked',issues:[]}];
  const report={status:'completed',items,questionsExpected:1,questionsChecked:1,renderedQuestionStates:1,uniqueQuestionIds:1,issueQuestionCount:0,pagesChecked:1,katexNodeCount:2,imageElementsObserved:0,tablesObserved:0,tableCellsObserved:0,viewportWidth:736,browserUserAgent:'synthetic-unit-test'};
  let stopCalled=false;
  const env={window:{__lunaRenderAudit:{stop(){stopCalled=true;},snapshot(){return {...report,status:'incomplete'};},async run(fn){fn({completed:1,total:1,issueCount:0});if(fail)throw Error('synthetic runtime failure');return report;}}},
    document:{getElementById(id){return elements[id];},createElement(){return {click(){},href:'',download:''};}},
    navigator:{userAgent:'synthetic-unit-test'},innerWidth:736,Blob:class {},URL:{createObjectURL(){return 'blob:synthetic';},revokeObjectURL(){}},setTimeout(){},console};
  vm.createContext(env);vm.runInContext(source.controls,env);
  assert.strictEqual(typeof elements['start-audit'].listeners.click,'function');
  assert.strictEqual(typeof elements['stop-audit'].listeners.click,'function');
  elements['stop-audit'].listeners.click();assert(stopCalled);
  await elements['start-audit'].listeners.click();
  assert.strictEqual(elements['download-audit'].disabled,false);
  assert.strictEqual(elements['start-audit'].disabled,false);
  assert.strictEqual(elements['stop-audit'].disabled,true);
  if(fail) assert(elements['audit-status'].textContent.includes('中断'));
  else assert.strictEqual(elements['audit-status'].textContent,'检查完成');
  elements['download-audit'].listeners.click();
}
(async()=>{await controlsTest(false);await controlsTest(true);console.log(JSON.stringify({gateway_scope_and_page_state:true,control_initialization:true,completed_and_partial_report_controls:true,actual_browser_execution:false}));})().catch(e=>{console.error(e);process.exitCode=1;});
