/* EDGE_FANCONTROL_NATIVE: PVE node panel. Uses PVE session/CSRF/ACL only. */
(function () {
    // ExtJS 7 callParent inspects Function.caller. These class methods must
    // remain non-strict; strict mode prevents the parent initializer running.
    if (window.__edgeFanNative || !window.Ext || !window.PVE) { return; }
    window.__edgeFanNative = true;
    const esc = value => Ext.String.htmlEncode(String(value == null ? '—' : value));
    const reasons = {auto:'自动温控', manual:'手动 PWM', cooldown:'降速等待',
        high_temperature:'高温全速保护', protection_cooldown:'全速保护恢复等待', failsafe:'故障全速保护'};

    Ext.define('PVE.node.EdgeFanControl', {
        extend: 'Ext.panel.Panel',
        alias: 'widget.pveEdgeFanControl',
        scrollable: true,
        bodyPadding: 15,
        layout: {type:'vbox', align:'stretch'},
        dirty: false,
        busy: false,
        snapshot: null,

        api: function (method, suffix, params, success, failure) {
            const me = this;
            Proxmox.Utils.API2Request({
                url: '/nodes/' + encodeURIComponent(me.nodename) + '/edge-fancontrol' + (suffix || ''),
                method: method, params: params, timeout: 15000,
                success: function (response) {
                    if (!me.destroyed && !me.destroying) { success(response.result.data); }
                },
                failure: function (response) {
                    if (!me.destroyed && !me.destroying) {
                        failure(response.result && response.result.message || response.statusText || 'PVE API 请求失败');
                    }
                }
            });
        },

        message: function (text) { this.down('#edge-result').setHtml(esc(text)); },

        syncForm: function () {
            const me = this, config = me.snapshot && me.snapshot.config;
            if (!config) { return; }
            me.suppress = true;
            me.down('#edge-mode').setValue({edgeMode:config.mode});
            me.down('#edge-pwm').setValue(config.manual_pwm);
            me.formRevision = config.revision;
            me.suppress = false;
            me.dirty = false;
            me.updateButtons();
        },

        updateButtons: function () {
            const me = this, status = me.snapshot;
            const config = status && status.config;
            const mode = me.down('#edge-mode').getValue().edgeMode;
            const pwm = me.down('#edge-pwm').getValue();
            const allowed = !!(status && status.control_available && status.native_access && status.native_access.can_modify);
            const conflict = !!config && me.formRevision !== config.revision;
            const changed = !!config && (mode !== config.mode || pwm !== config.manual_pwm);
            me.down('#edge-apply').setDisabled(me.busy || !allowed || !changed || conflict || !me.down('#edge-pwm').isValid());
            me.down('#edge-reset').setDisabled(me.busy || !config);
            me.down('#edge-mode').setDisabled(me.busy || !allowed);
            me.down('#edge-pwm').setDisabled(me.busy || !allowed || mode !== 'manual');
        },

        displayStatus: function (status) {
            const me = this, live = status.live || {}, state = status.state || {}, config = status.config;
            me.snapshot = status;
            const stale = status.stale || status.error;
            const value = (v, unit) => '<div style="font-size:25px;padding:10px 0">' + esc(v) + ' <small style="font-size:12px">' + esc(unit) + '</small></div>';
            me.down('#edge-cpu').setHtml(value(status.stale ? null : live.temp, '°C'));
            me.down('#edge-board').setHtml(value(status.stale ? null : live.lm75, '°C'));
            me.down('#edge-rpm1').setHtml(value(status.stale ? null : (live.rpm || [])[0], 'RPM'));
            me.down('#edge-rpm2').setHtml(value(status.stale ? null : (live.rpm || [])[1], 'RPM'));
            me.down('#edge-actual').setValue(status.stale ? '采样过期，状态未知' : (reasons[state.reason] || '等待采样'));
            me.down('#edge-readback').setValue(status.stale ? '—' : String(live.pwm == null ? '—' : live.pwm) + ' / 255');
            me.down('#edge-requested').setValue(status.stale ? '—' : state.last_pwm);
            me.down('#edge-wait').setValue(status.cooldown_remaining > 0 ? status.cooldown_remaining + ' 秒' : '无');
            me.down('#edge-saved').setValue(config ? (config.mode === 'auto' ? '自动温控' : '手动 PWM ' + config.manual_pwm) + ' · 版本 ' + config.revision : '配置不可用');
            me.down('#edge-services').setValue('温控 ' + ((status.services || {}).timer || 'unknown') + ' / watchdog ' + ((status.services || {}).watchdog || 'unknown'));
            me.down('#edge-updated').setValue(state.updated_at ? new Date(state.updated_at * 1000).toLocaleTimeString() : '—');
            const warning = status.error || status.warning || (status.stale ? '采样已过期；请检查温控服务和独立 watchdog。' : '');
            me.down('#edge-warning').setHtml(esc(warning));
            if (me.formRevision == null || (!me.dirty && !me.busy)) { me.syncForm(); }
            if (me.dirty && config && me.formRevision !== config.revision) {
                me.message('配置已被其他页面修改，请恢复当前设置后再试。');
            }
            if (!status.native_access || !status.native_access.can_modify) {
                me.message('当前 PVE 用户为只读；调速需要此节点上的 Sys.Modify 权限。');
            }
            me.updateButtons();
        },

        refreshStatus: function () {
            const me = this;
            if (!me.rendered || me.destroyed || me.loading) { return; }
            me.loading = true;
            me.api('GET', '', undefined, function (status) {
                me.loading = false;
                me.displayStatus(status);
            }, function (error) {
                me.loading = false;
                me.displayStatus({stale:true, control_available:false, error:error});
                me.message(error);
            });
        },

        refreshLogs: function () {
            const me = this;
            me.api('GET', '/logs', undefined, function (result) {
                const lines = (result.lines || []).map(function (line) {
                    try {
                        const event = JSON.parse(line);
                        return new Date(event.updated_at * 1000).toLocaleTimeString() + ' CPU=' + event.temp + '°C 请求=' + event.last_pwm + ' 读回=' + event.readback_pwm + ' ' + (reasons[event.reason] || event.reason) + (event.error ? ' ' + event.error : '');
                    } catch (_) { return line; }
                });
                me.down('#edge-logs').setHtml('<pre style="font:12px/1.7 monospace;white-space:pre-wrap;margin:0">' + esc(lines.join('\n') || '暂无日志') + '</pre>');
            }, function (error) { me.down('#edge-logs').setHtml(esc(error)); });
        },

        applySelection: function () {
            const me = this;
            if (me.busy || !me.snapshot || !me.snapshot.native_access || !me.snapshot.native_access.can_modify) { return; }
            const mode = me.down('#edge-mode').getValue().edgeMode;
            const pwm = me.down('#edge-pwm').getValue();
            if (!Number.isInteger(pwm) || pwm < 0 || pwm > 255 || !['auto','manual'].includes(mode)) {
                me.message('PWM 必须为 0–255 的整数。'); return;
            }
            const apply = function () {
                if (me.destroyed || me.busy) { return; }
                me.busy = true; me.updateButtons(); me.message('正在保存并执行…');
                me.api('POST', '', {mode:mode, pwm:pwm, revision:me.formRevision}, function (result) {
                    me.busy = false;
                    if (result.success) { me.dirty = false; me.formRevision = null; }
                    me.message(result.success ? result.message : (result.error || (result.state || {}).error || '操作未确认，请核对已保存和实际状态'));
                    me.refreshStatus(); me.refreshLogs();
                }, function (error) {
                    me.busy = false; me.message(error + '；请核对已保存与实际状态。'); me.refreshStatus();
                });
            };
            if (mode === 'manual' && pwm === 0) {
                Ext.Msg.confirm('停止风扇', 'PWM 0 会停止风扇，确认保存？', answer => { if (answer === 'yes') { apply(); } });
            } else { apply(); }
        },

        initComponent: function () {
            const me = this;
            me.nodename = me.nodename || me.pveSelNode.data.node;
            me.suppress = true;
            const edited = function () { if (!me.suppress) { me.dirty = true; me.updateButtons(); } };
            const display = (id, label) => ({xtype:'displayfield', itemId:id, fieldLabel:label, labelWidth:125, value:'—'});
            me.items = [{
                xtype:'container', layout:{type:'hbox', align:'stretch'}, margin:'0 0 15 0',
                items:[['edge-cpu','CPU Package'],['edge-board','LM75 主板温度'],['edge-rpm1','风扇 1'],['edge-rpm2','风扇 2']].map(function (item) {
                    return {xtype:'panel', title:item[1], flex:1, margin:'0 8 0 0', bodyPadding:10,
                        items:[{xtype:'component', itemId:item[0], html:'—'}]};
                })
            }, {
                xtype:'form', title:'风扇设置', bodyPadding:15, margin:'0 0 15 0',
                defaults:{anchor:'100%'}, items:[
                    {xtype:'radiogroup', itemId:'edge-mode', fieldLabel:'控制模式', labelWidth:125, columns:2,
                        items:[{boxLabel:'自动温控', name:'edgeMode', inputValue:'auto', checked:true},
                               {boxLabel:'手动 PWM', name:'edgeMode', inputValue:'manual'}], listeners:{change:edited}},
                    {xtype:'numberfield', itemId:'edge-pwm', fieldLabel:'请求 PWM (0–255)', labelWidth:125,
                        minValue:0, maxValue:255, allowDecimals:false, allowExponential:false, value:160,
                        disabled:true, listeners:{change:edited}},
                    display('edge-saved','已保存设置'), display('edge-actual','实际控制状态'),
                    display('edge-readback','读回 PWM'), display('edge-requested','当前控制请求'),
                    display('edge-wait','降速／保护等待'), display('edge-services','温控／保护服务'),
                    display('edge-updated','最后控制采样'),
                    {xtype:'component', itemId:'edge-warning', style:'font-weight:600', margin:'8 0', html:''},
                    {xtype:'component', html:'高温、传感器或控制故障时请求全速 PWM 255。保护优先于手动设置；关闭此页不影响后台温控。', margin:'10 0'},
                    {xtype:'container', layout:'hbox', margin:'10 0', items:[
                        {xtype:'button', itemId:'edge-apply', text:'保存并执行', disabled:true, handler:()=>me.applySelection()},
                        {xtype:'button', itemId:'edge-reset', text:'恢复当前设置', margin:'0 0 0 10', handler:()=>me.syncForm()}
                    ]},
                    {xtype:'component', itemId:'edge-result', html:'通过当前 PVE 登录身份读取主机状态。'}
                ]
            }, {
                xtype:'panel', title:'最近 30 行日志 · 每日轮转，保留 30 天', bodyPadding:12,
                tbar:[{text:'刷新日志', handler:()=>me.refreshLogs()}],
                items:[{xtype:'component', itemId:'edge-logs', html:'等待采样…'}]
            }];
            me.callParent();
            me.suppress = false;
            me.on('afterrender', function () {
                me.refreshStatus(); me.refreshLogs();
                me.pollTask = Ext.TaskManager.start({interval:3000, run:function () {
                    if (!me.destroyed && me.isVisible(true)) { me.refreshStatus(); }
                }});
            });
            me.on('destroy', function () { if (me.pollTask) { Ext.TaskManager.stop(me.pollTask); } });
        }
    });

    // Node.Config prepares its items before calling PVE.panel.Config.initComponent.
    // Insert the declarative card at that point so PVE builds its own menu/history.
    Ext.define('PVE.edge.FanControlNavigation', {
        override:'PVE.panel.Config',
        initComponent:function () {
            if (this instanceof PVE.node.Config && Ext.isArray(this.items) &&
                !this.items.some(item => item.itemId === 'edge-fancontrol')) {
                this.items.push({xtype:'pveEdgeFanControl', itemId:'edge-fancontrol',
                    title:'风扇控制', iconCls:'fa fa-thermometer-half'});
            }
            this.callParent(arguments);
        }
    });
}());
