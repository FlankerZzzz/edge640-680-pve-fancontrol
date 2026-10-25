const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');
const definitions = {};
const calls = [];
const PVE = {node:{Config:function NodeConfig(){}}};
const Ext = {define:(name, spec)=>{definitions[name]=spec;}, isArray:Array.isArray,
    String:{htmlEncode:String}};
const Proxmox = {Utils:{API2Request:request=>calls.push(request)}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../native/edge-fancontrol.js'),'utf8'),
    {window:{Ext,PVE},Ext,PVE,Proxmox,console,Date,Number});
const navigation = definitions['PVE.edge.FanControlNavigation'];
const node = new PVE.node.Config();
node.items=[{itemId:'summary'}];
// Match the real ExtJS 7 callParent mechanism; a strict caller is invisible.
node.callParent=function () {
    assert(this.callParent.caller, 'Strict-mode method broke ExtJS callParent caller inspection');
    node.parentCalled=true;
};
navigation.initComponent.call(node);
assert(node.parentCalled);
assert.equal(node.items.length,2);
assert.equal(node.items[1].itemId,'edge-fancontrol');
navigation.initComponent.call(node);
assert.equal(node.items.length,2);
const vmPanel={items:[{itemId:'summary'}],callParent:()=>{}};
navigation.initComponent.call(vmPanel);
assert.equal(vmPanel.items.length,1);
const panel = definitions['PVE.node.EdgeFanControl'];
const built = {nodename:'node A',callParent:function () {
    assert(this.callParent.caller, 'Panel initializer must also remain non-strict');
},on:()=>{}};
panel.initComponent.call(built);
assert.equal(built.items[0].items.length,5);
assert.equal(built.items[0].items[3].items[0].itemId,'edge-rpm2');
assert.equal(built.items[0].items[4].title,'当前 PWM');
assert.equal(built.items[0].items[4].items[0].itemId,'edge-pwm-card');
assert(panel.pwmCardHtml(88).includes('2 / 16'));
assert(panel.pwmCardHtml(88).includes('PWM 1/15'));
assert(panel.pwmCardHtml(88).includes('34.5%'));
assert(panel.pwmCardHtml(255).includes('16 / 16'));
assert(panel.pwmCardHtml(255).includes('100.0%'));
assert(panel.pwmCardHtml(0).includes('已停转'));
assert(panel.pwmCardHtml(null).includes('等待有效读回'));
assert(panel.pwmCardHtml(119).includes('非标准档位'));
const combo=built.items[1].items.find(item=>item.itemId==='edge-pwm');
assert.equal(combo.xtype,'combobox');
assert.equal(combo.editable,false);
assert.equal(combo.store.data.length,16);
assert.deepEqual(Array.from(combo.store.data,item=>item.pwm),[77,88,102,112,124,136,148,160,172,184,196,207,219,231,243,255]);
assert.equal(combo.store.data[0].label,'档位 1 · 约 1,800 RPM');
assert.equal(combo.store.data[15].label,'档位 16 · 约 8,800 RPM');
assert(!combo.store.data.some(item=>item.pwm===0));
assert.equal(panel.describePwm(77),'档位 1 / 16 · PWM 77');
assert.equal(panel.describePwm(255),'档位 16 / 16 · PWM 255');
assert.equal(panel.describePwm(0),'已停转 · PWM 0');
assert.equal(panel.describePwm(119),'PWM 119 / 255');
panel.api.call({nodename:'node A'},'POST','',{mode:'manual',pwm:160,revision:0},()=>{},()=>{});
assert.equal(calls[0].url,'/nodes/node%20A/edge-fancontrol');
assert.equal(calls[0].method,'POST');
assert.equal(calls[0].params.pwm,160);
assert(!JSON.stringify(calls[0]).includes('19090'));
const fields = {};
for(const id of ['edge-mode','edge-pwm','edge-apply','edge-reset']) {
    fields['#'+id]={setDisabled(v){this.disabled=v;}, isValid(){return true;}, getValue(){return id==='edge-mode'?{edgeMode:'manual'}:160;}};
}
const view = {snapshot:{config:{mode:'auto',manual_pwm:160,revision:0}, control_available:true,
    native_access:{can_modify:false}}, formRevision:0, down:id=>fields[id], busy:false};
panel.updateButtons.call(view);
assert.equal(fields['#edge-apply'].disabled,true);
view.snapshot.native_access.can_modify=true;
panel.updateButtons.call(view);
assert.equal(fields['#edge-apply'].disabled,false);
view.formRevision=1;
panel.updateButtons.call(view);
assert.equal(fields['#edge-apply'].disabled,true);
console.log('PASS: native node-menu hook, duplicate avoidance, PVE API transport, read-only ACL and revision conflict');
