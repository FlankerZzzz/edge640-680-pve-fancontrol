'use strict';
const $ = id => document.getElementById(id);
let token = '', state = null, formRevision = null, dirty = false, busy = false, refreshing = false;
let lastSample = null;
const samples = [];
const reasons = {auto:'自动温控', manual:'手动 PWM', cooldown:'降速等待', high_temperature:'高温全速保护', protection_cooldown:'全速保护恢复等待', failsafe:'故障全速保护'};

async function api(path, data) {
  const headers = {Authorization:'Bearer ' + token};
  const options = {headers, cache:'no-store', signal:AbortSignal.timeout(15000)};
  if (data) {options.method='POST'; headers['Content-Type']='application/json'; options.body=JSON.stringify(data);}
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) {
    if (response.status===401) {$('login').hidden=false; token='';}
    throw new Error(body.error || body.state?.error || '请求失败，请刷新核对主机状态');
  }
  return body;
}
function formValue(){return {mode:$('manual').checked?'manual':'auto', pwm:Number($('pwm-input').value), revision:formRevision};}
function controls(){
  $('manual-controls').hidden=!$('manual').checked;
  const form=formValue(), config=state?.config;
  const changed=!!config && (form.mode!==config.mode || form.pwm!==config.manual_pwm);
  $('apply').disabled=busy || !state?.control_available || !changed || formRevision!==config?.revision;
  $('reset').disabled=busy || !config;
  ['auto','manual','slider','pwm-input'].forEach(id=>$(id).disabled=busy || !state?.control_available);
  $('apply').textContent=busy?'正在执行…':'保存并执行';
  $('logs-refresh').disabled=!token;
}
function sync(){
  if(!state?.config)return;
  const config=state.config;
  $('auto').checked=config.mode==='auto'; $('manual').checked=config.mode==='manual';
  $('slider').value=$('pwm-input').value=config.manual_pwm;
  formRevision=config.revision;dirty=false;controls();
}
function metric(id,value,unit){$(id).replaceChildren(document.createTextNode(value==null?'—':String(value)));const small=document.createElement('small');small.textContent=unit;$(id).append(small);}
function unavailable(message){
  if(state)state.control_available=false;
  metric('temp',null,'°C');metric('lm75',null,'°C');metric('rpm1',null,'RPM');metric('rpm2',null,'RPM');
  ['pwm','requested','wait','sample-time','actual','service','i2c','watchdog','pwm-mode'].forEach(id=>$(id).textContent='—');
  $('meter-fill').style.width='0%';$('badge').textContent='状态不可用';$('badge').className='badge bad';
  $('notice').hidden=false;$('notice').textContent=message;controls();
}
async function refresh(){
  if(!token||refreshing)return;
  refreshing=true;
  try{
    state=await api('/api/status');
    const live=state.live||{}, current=state.state||{}, config=state.config;
    $('login').hidden=true; $('version').textContent=state.version;
    $('host').textContent=state.host+' · '+(state.demo?'模拟设备预览 · 不连接真实硬件':'PVE 本机控制服务');
    if(state.stale){unavailable('控制采样超过 35 秒未更新。请检查温控 timer 和 watchdog；当前数值不作为有效控制结果。');return;}
    metric('temp',live.temp,'°C');metric('lm75',live.lm75,'°C');
    metric('rpm1',live.rpm?.[0],'RPM');metric('rpm2',live.rpm?.[1],'RPM');
    $('pwm').textContent=live.pwm??'—';$('requested').textContent=current.last_pwm??'—';
    $('meter-fill').style.width=Math.min(100,Math.max(0,(live.pwm||0)/255*100))+'%';
    $('wait').textContent=state.cooldown_remaining>0?state.cooldown_remaining+' 秒':'无';
    $('pwm-mode').textContent=live.pwm_mode===1?'SMBus / PWM':live.pwm_mode===0?'Vin 模拟输入':'未知';
    $('sample-time').textContent=current.updated_at?new Date(current.updated_at*1000).toLocaleTimeString():'—';
    $('service').textContent=state.services?.timer==='active'?'定时器运行中':state.demo?'模拟控制':'定时器未运行';
    $('i2c').textContent=state.services?.i2c==='active'?'已就绪':state.demo?'模拟设备':'未就绪';
    $('watchdog').textContent=state.services?.watchdog==='active'?'已启用':state.demo?'模拟保护':'未运行';
    $('actual').textContent=reasons[current.reason]||'等待采样';
    $('saved').textContent=config?(config.mode==='auto'?'自动温控':'手动 PWM '+config.manual_pwm):'配置不可用';
    $('revision').textContent='配置版本 '+(config?.revision??'—');
    if(config)$('curve').textContent=config.stop_temp+'°C 起调节 · '+config.full_temp+'°C 全速';
    $('badge').textContent=state.error?'全速保护':state.demo?'模拟运行':'已连接';
    $('badge').className='badge '+(state.error?'bad':'good');
    const warning=state.error||state.warning||(formRevision!==null&&dirty&&formRevision!==config?.revision?'配置已被其他页面修改，请点“恢复当前设置”后重试。':'');
    $('notice').hidden=!warning;$('notice').textContent=warning;
    $('updated').textContent='最近读取 '+new Date(state.collected_at*1000).toLocaleTimeString();
    if(current.sample!==lastSample&&live.temp!=null){
      lastSample=current.sample;samples.push(live.temp);if(samples.length>120)samples.shift();
      $('chart-line').setAttribute('points',samples.map((v,i)=>`${i*1000/119},${140-Math.max(0,Math.min(100,v))*1.4}`).join(' '));
      $('chart-empty').textContent='显示当前页面最多 120 次控制采样，纵轴 0–100°C。';
    }
    if(formRevision===null||(!dirty&&!busy))sync();
    controls();
  }catch(error){unavailable(error.message);}finally{refreshing=false;}
}
$('login-form').onsubmit=async event=>{event.preventDefault();token=$('token').value.trim();$('token').value='';formRevision=null;await refresh();if(token)await logs();};
['auto','manual','slider','pwm-input'].forEach(id=>$(id).addEventListener('input',()=>{
  if(id==='slider')$('pwm-input').value=$('slider').value;
  if(id==='pwm-input')$('slider').value=$('pwm-input').value;
  dirty=true;controls();
}));
$('reset').onclick=sync;
$('theme').onclick=()=>document.body.classList.toggle('dark');
if(window.matchMedia('(prefers-color-scheme: dark)').matches)document.body.classList.add('dark');
$('apply').onclick=async()=>{
  if(busy)return;
  const value=formValue();
  if(!Number.isInteger(value.pwm)||value.pwm<0||value.pwm>255){$('result').textContent='PWM 必须为 0–255 的整数';$('result').className='error';return;}
  if(value.mode==='manual'&&value.pwm===0&&!window.confirm('PWM 0 会停转风扇。确认保存？'))return;
  busy=true;controls();$('result').textContent='正在保存并执行…';$('result').className='';
  try{const result=await api('/api/control',value);dirty=false;formRevision=null;$('result').textContent=result.message;$('result').className='success';}
  catch(error){$('result').textContent=error.message+'；请核对已保存设置和实际状态。';$('result').className='error';}
  finally{busy=false;await refresh();await logs();controls();}
};
async function logs(){if(!token)return;try{const result=await api('/api/logs');$('logs').textContent=result.lines.map(line=>{try{const e=JSON.parse(line);return new Date(e.updated_at*1000).toLocaleTimeString()+'  CPU '+(e.temp??'—')+'°C  请求 '+e.last_pwm+' / 读回 '+(e.readback_pwm??'—')+'  '+(reasons[e.reason]||e.reason)+(e.error?' · '+e.error:'');}catch{return line;}}).join('\n')||'暂无日志';}catch(error){$('logs').textContent=error.message;}}
$('logs-refresh').onclick=logs;
controls();setInterval(refresh,3000);
if(document.body.dataset.demo==='true'){token='demo-only';refresh().then(logs);}
