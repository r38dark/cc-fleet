"""Компоновка «Обзор»: существующие узлы и обработчики остаются на месте в DOM."""

CSS = r'''
/* Оформление первоначального «Обзора». Действующие контролы сохраняют свои ID. */
:root{--fleet-line:#25303f;--fleet-muted:#8c9bad;--fleet-faint:#647388;--fleet-accent:#45d6ab;--fleet-accent-soft:#16352e;--fleet-claude:#e7af85;--fleet-claude-soft:#372b25;--fleet-terminal:#0a0e14;--fleet-toolbar:#111722}
html:not([data-skin]){--bg:#0c1017;--card:#131923;--txt:#e8edf4;--mut:#8c9bad;--ok:#45d6ab;--warn:#ecc277;--bad:#ef969e;--acc:#45d6ab}
html[data-skin="phosphor"]{--fleet-line:var(--phl);--fleet-muted:var(--mut);--fleet-faint:#4f9f6b;--fleet-accent:var(--ok);--fleet-claude:#c2da9a}
html[data-skin="aurora"]{--fleet-line:#343650;--fleet-accent:#59ddbe;--fleet-claude:#d6b4f0}
html[data-skin="slate"]{--fleet-line:#2d333b;--fleet-muted:var(--mut);--fleet-faint:#6c7887}
html[data-skin="blocks"]{--fleet-line:#c5c9ce;--fleet-muted:#5d6f80;--fleet-faint:#687b8d;--fleet-accent:#087b5c;--fleet-accent-soft:#e0f2eb;--fleet-claude:#9c5931;--fleet-claude-soft:#f6e9e0}
html:root:root:not(.conly) body{height:auto!important;min-height:100dvh;overflow:auto!important;display:block!important;max-width:1680px;margin:0 auto;padding:23px 40px 28px;background:var(--bg);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--txt)}
#cxp .cxprof[hidden]{display:none!important}
html:root:root:not(.conly) .hdr{display:flex;align-items:center;gap:24px;padding:0;margin:0 0 22px;min-height:40px}
html:not(.conly) .hdrl{flex:1;min-width:180px;display:flex;gap:13px;align-items:center}
html:not(.conly) #h1{display:flex;align-items:center;gap:11px;font-size:24px;font-weight:750;letter-spacing:-1px;line-height:1.12;margin:0;color:var(--txt);white-space:nowrap}
.fleet-brand{display:grid;place-items:center;width:40px;height:40px;border-radius:11px;background:var(--fleet-accent);color:#0c1017;font:600 22px/1 ui-monospace,Consolas,monospace;letter-spacing:-3px;padding-right:3px;flex:none}
.fleet-brand-word{font-weight:400;color:var(--fleet-muted)}.fleet-brand-sub{display:block;font-size:8px;font-weight:650;letter-spacing:.17em;margin-top:5px;color:var(--fleet-faint)}
html:not(.conly) .hdrctl{display:flex;align-items:center;flex-wrap:wrap;justify-content:flex-end;gap:12px!important}
.fleet-profilebar{display:contents}.fleet-profilelabel{display:none}.fleet-profilebar .cxgrp{margin:0}.hdr .cxgrp{border:0;background:transparent;box-shadow:none}.hdr .cxbtn{border:0;background:transparent;box-shadow:none;max-width:390px}.hdr .cxmodbtn{border:1px solid var(--fleet-line);border-radius:7px}.hdr .cxlim{opacity:.75}.hdr .hdrgear{color:var(--fleet-muted);border-color:var(--fleet-line);background:transparent;border-radius:8px}
.hdr #gear{width:auto!important;display:flex;align-items:center;gap:7px;padding:8px 11px;height:36px}.hdr #gear::after{content:"Настройки";font-size:12px;font-weight:550}.hdr #rfBtn{border:0;width:32px;height:32px}.hdr .hdrbtns{gap:8px!important}.hdr #termDot{width:6px;height:6px;margin:0;flex:none}
html:not(.conly) .termwrap{height:auto!important;min-height:0;margin:0;border:1px solid #303a48;border-radius:16px;background:var(--fleet-terminal);overflow:hidden;display:flex;flex-direction:column;box-shadow:0 8px 30px #0001}
.fleet-console-toolbar{display:flex;align-items:center;gap:16px;min-height:50px;padding:0 16px;border-bottom:1px solid #242d39;background:var(--fleet-toolbar);color:#dbe3ed;flex:none}
html:root:root .fleet-console-toolbar #cTabs{position:static;display:flex;align-self:stretch;align-items:center;gap:18px;padding:0;border-radius:0;background:none;min-width:0;flex-wrap:nowrap}
html:root:root .fleet-console-toolbar .ctab{position:relative;display:flex;align-self:stretch;align-items:center;gap:7px;width:auto;height:auto;padding:0 4px;border:0!important;border-radius:0;background:none!important;box-shadow:none;color:#7d8da2;font-size:12px;font-weight:450}
.fleet-console-toolbar .ctab::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--fleet-claude)}.fleet-console-toolbar #ctCodex::before{background:var(--fleet-accent)}
html:root:root .fleet-console-toolbar .ctab.on{color:#ecf1f6}.fleet-console-toolbar .ctab.on::after{content:"";height:2px;position:absolute;bottom:-1px;left:0;right:0;background:#4cdbb0}
html:root:root .fleet-console-toolbar .ctacts{margin:0 0 0 4px;display:flex;gap:5px}.fleet-console-toolbar .iconbtn{background:transparent!important;color:#8799ae;border-color:#2a3542;border-radius:6px;width:26px;height:26px}.fleet-console-toolbar .iconbtn svg{width:14px;height:14px}
html:root:root .fleet-console-toolbar .tzoom{position:static;margin-left:auto;display:flex;gap:4px;padding:0;background:transparent}.fleet-console-toolbar .tzval{color:#8da0b7;font-size:11px;font-weight:450}
html:not(.conly) #termBox{height:clamp(360px,41dvh,510px)!important;min-height:360px!important;max-height:none!important;flex:none!important;margin:0;border:0;border-radius:0;padding:28px 30px 16px;background:var(--fleet-terminal);color:#d2dce9;font:calc(12px * var(--tz,1))/1.65 ui-monospace,"SFMono-Regular",Consolas,monospace;white-space:pre;overflow:auto}
.fleet-composer{display:flex;align-items:center;gap:11px;margin:0;padding:11px 20px;border-top:1px solid #263140;background:#101620;color:#dbe3ed;flex:none}
.fleet-composer::before{content:"›";color:#73dbb7;font:22px ui-monospace,monospace}
.fleet-composer textarea{flex:1;min-width:0;resize:vertical;min-height:28px;max-height:180px;margin:0;padding:5px 0;background:none;color:#dbe3ed;border:0;outline:0;border-radius:0;font:12px/1.5 ui-monospace,Consolas,monospace}.fleet-composer textarea::placeholder{color:#65768c}.fleet-composer textarea:focus-visible{box-shadow:0 1px #45d6ab}
.fleet-composer button{margin:0;min-height:0;padding:0;flex:none}.fleet-composer #fleetSend{display:grid;place-items:center;width:29px;height:29px;background:#1a342d;color:#a5c6bb;border:0;border-radius:6px;font-size:19px;box-shadow:none}.fleet-key{background:transparent!important;color:#73869d!important;border:1px solid #2a3644!important;padding:2px 5px!important;border-radius:4px!important;font:10px ui-monospace,monospace!important}
.fleet-input-status{display:flex;align-items:center;gap:8px;padding:0 18px;min-height:32px;background:#101620;border-top:1px solid #1d2733;font-size:10px;line-height:1.5;color:#8b9bb0;flex:none}.fleet-input-status::before{content:"";width:5px;height:5px;border-radius:50%;background:#4cdbb0;flex:none}.fleet-input-status span:last-child{margin-left:auto;color:#6d839a}
html:not(.conly) .toolrow{margin:10px 0 0;padding:0 4px;border:0;background:transparent;border-radius:0;gap:8px;min-height:28px}.fleet-model-label{font-size:10px;color:var(--fleet-faint);margin:0 9px 0 0}.toolrow .mbtn,.toolrow .modelbtn,.toolrow #mrow button{font-size:10px;padding:4px 10px;background:transparent;border:1px solid var(--fleet-line);color:var(--mut);box-shadow:none}.toolrow #mrow button.on{background:var(--card);color:var(--txt);border-color:var(--fleet-muted)}.toolrow .efB{font-size:11px}
#fleetAccounts{margin-top:28px}.fleet-accounts-intro{margin:0 0 20px}.fleet-eyebrow{display:block;font-size:9px;letter-spacing:.16em;font-weight:700;color:var(--fleet-faint)}.fleet-accounts-intro h2{font-size:20px;font-weight:550;letter-spacing:-.35px;margin:4px 0 0}
.fleet-section{margin:0;min-width:0}.fleet-section+.fleet-section{margin-top:24px}.fleet-section-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 11px;min-height:28px}.fleet-section-head h2{display:flex;align-items:center;font-size:14px;font-weight:600;margin:0;gap:10px}.fleet-provider{display:grid;place-items:center;width:25px;height:25px;border-radius:7px;background:var(--fleet-claude-soft);color:var(--fleet-claude);font-size:18px;line-height:1}.fleet-provider.codex{background:var(--fleet-accent-soft);color:var(--fleet-accent);font:550 15px/1 ui-monospace,monospace}.fleet-count{font-size:10px;color:var(--fleet-faint)}
.fleet-section-head #addAcct,.fleet-section-head .fleet-add-codex{margin:0 0 0 auto!important;width:auto!important;min-width:28px;display:flex;align-items:center;gap:5px;padding:5px 8px;height:28px;font-size:11px;font-weight:450;color:var(--txt);border:1px solid var(--fleet-line);border-radius:7px;background:transparent;box-shadow:none}.fleet-section-head #addAcct::after,.fleet-section-head .fleet-add-codex::after{content:"Добавить"}.fleet-section-head #addAcct svg,.fleet-section-head .fleet-add-codex svg{width:13px;height:13px}
html:not(.conly) #cards,html:not(.conly) #cxcards{height:auto!important;max-height:none!important;min-height:0!important;overflow:visible!important;display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px!important;margin:0!important;align-items:stretch}
html:root:root .fleet-section .card{position:relative;height:auto;min-width:0;min-height:200px;margin:0!important;border:1px solid var(--fleet-line);border-radius:12px;padding:15px 17px!important;background:var(--card);box-shadow:none;display:flex;flex-direction:column;container-type:normal}
html:root:root #fleetClaude .card.active{border-color:color-mix(in srgb,var(--fleet-claude) 50%,var(--fleet-line));background:linear-gradient(120deg,var(--fleet-claude-soft),var(--card) 70%)}
html:root:root #fleetCodex .card.fleet-active{border-color:color-mix(in srgb,var(--fleet-accent) 64%,var(--fleet-line));background:linear-gradient(120deg,var(--fleet-accent-soft),var(--card) 65%);box-shadow:none}
html:root:root .fleet-section .card:has(.fleet-card-details[open]){z-index:35}
.fleet-section .card .top{display:flex;align-items:flex-start;gap:8px;flex-wrap:nowrap;padding-right:22px;min-height:38px;margin:0 0 6px}.fleet-identity{min-width:0;flex:1}.fleet-titleline{display:flex;align-items:center;gap:6px;min-width:0}.fleet-account-name{font-size:13px;font-weight:620;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;letter-spacing:0}.fleet-section .card .email{display:block;font-size:10px;font-weight:400;color:var(--fleet-faint);line-height:1.5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:3px;max-width:100%}
html:root:root .fleet-section .tag.plan,html:root:root .fleet-section .tag.free{font-size:9px;font-weight:450;border:1px solid var(--fleet-line);border-radius:4px;padding:1px 5px;color:var(--fleet-muted);background:transparent;text-transform:capitalize;line-height:1.2;letter-spacing:0}.fleet-section .fleet-active-label{display:none}.fleet-section .tag.pin{position:static;transform:none;display:none;box-shadow:none}
.fleet-card-state{align-self:flex-start;display:inline-flex;gap:5px;align-items:center;font-size:9px;line-height:1.35;font-weight:550;border-radius:4px;color:var(--fleet-muted);background:color-mix(in srgb,var(--card),var(--fleet-line) 50%);padding:2px 5px;margin:5px 0 12px}.fleet-card-state.active{color:var(--fleet-accent);background:var(--fleet-accent-soft)}.fleet-card-state.next{color:var(--fleet-claude);background:var(--fleet-claude-soft)}.fleet-card-state.limited{color:var(--warn);background:color-mix(in srgb,var(--warn) 13%,var(--card))}.fleet-card-state.problem{color:var(--bad);background:color-mix(in srgb,var(--bad) 12%,var(--card))}
.fleet-section .card>.row{margin:0 0 11px!important;padding:0}.fleet-section .card>.row .lbl{display:grid;grid-template-columns:minmax(0,1fr) auto 112px;align-items:center;gap:7px;margin-bottom:4px;line-height:1.3;font-size:10px;font-weight:400;color:var(--fleet-muted);letter-spacing:0;text-transform:none}
.fleet-section .card>.row .lbl b{font-size:11px;font-weight:550;color:var(--txt)!important;font-variant-numeric:tabular-nums}.fleet-section .card>.row .lbl>span:last-child{font-size:9px;color:var(--fleet-faint);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fleet-section .card>.row .bar{height:4px!important;border-radius:5px;background:var(--fleet-line);box-shadow:none;margin:0;overflow:hidden}.fleet-section .card>.row .fill{height:100%;border-radius:5px;background:var(--fleet-accent)!important;box-shadow:none}.fleet-section#fleetClaude .card>.row .fill{background:var(--fleet-claude)!important}.fleet-section .card>.row[data-fleet-tone="warn"] .fill{background:var(--warn)!important}.fleet-section .card>.row[data-fleet-tone="bad"] .fill{background:var(--bad)!important}
.fleet-card-footer{display:flex;align-items:center;gap:6px;border-top:1px solid var(--fleet-line);padding-top:9px;margin-top:auto;min-height:26px}.fleet-card-caption{font-size:9px;color:var(--fleet-faint);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fleet-card-footer .btn-sw{font-size:10px!important;font-weight:400;color:var(--fleet-muted)!important;background:transparent!important;border:0!important;box-shadow:none!important;border-radius:0!important;margin:0 0 0 auto!important;padding:0!important;white-space:nowrap;opacity:1}.fleet-card-footer .btn-sw:not(:disabled)::after{content:" →"}.fleet-card-footer .btn-sw:disabled{color:var(--fleet-faint)!important}
.fleet-card-details{position:absolute;top:13px;right:13px;z-index:1}.fleet-card-details summary{display:flex;align-items:center;justify-content:center;list-style:none;cursor:pointer;width:25px;height:24px;color:var(--fleet-faint);font-size:19px;line-height:1;font-weight:650;border-radius:5px}.fleet-card-details summary::-webkit-details-marker{display:none}.fleet-card-details summary:hover,.fleet-card-details[open] summary{background:var(--fleet-line);color:var(--txt)}
.fleet-card-panel{position:absolute;top:30px;right:0;min-width:270px;width:310px;max-width:calc(100vw - 50px);padding:14px;background:var(--card);color:var(--txt);border:1px solid var(--fleet-line);border-radius:10px;box-shadow:0 18px 45px #0007;z-index:36}.fleet-card-panel-title{font-size:11px;font-weight:600;margin:0 0 12px}.fleet-card-panel .hdrright{display:flex;gap:10px;align-items:center;justify-content:flex-start;margin:0 0 12px}.fleet-card-panel .ring{display:block}.fleet-card-panel .iconrow{display:flex;gap:7px}.fleet-card-panel .iconbtn{color:var(--fleet-muted);border-color:var(--fleet-line);background:transparent}.fleet-card-panel .cxsel{display:flex;flex-wrap:wrap;margin:0 0 12px;gap:8px}.fleet-card-panel .cxsel select{width:100%;flex-basis:100%;min-width:0;max-width:100%;height:35px;background:var(--bg);color:var(--txt);border:1px solid var(--fleet-line);border-radius:6px;font-size:11px;padding:6px 8px}.fleet-card-panel .acts{display:flex;flex-wrap:wrap;gap:8px;margin:0!important;align-items:center}.fleet-card-panel .acts button{font-size:11px;color:var(--mut);border:1px solid var(--fleet-line);border-radius:6px;padding:6px 8px;line-height:1.4;background:transparent;flex:none;max-width:100%;white-space:normal}.fleet-card-panel .acts .btn-del{margin-left:0}.fleet-card-panel .acts .btn-del .dl{display:inline}.fleet-card-panel .cxfast{font-size:11px}.fleet-card-panel .btn-del svg{width:13px;height:13px}
.fleet-group-footer{display:flex;align-items:center;justify-content:space-between;gap:14px;min-height:30px;margin-top:5px;font-size:10px;color:var(--fleet-muted)}.fleet-group-footer #optWrap,.fleet-group-footer .switchrow{display:inline-flex;align-items:center;gap:7px;margin:0 0 0 auto;font-size:10px;color:var(--fleet-muted);white-space:nowrap}.fleet-group-footer input[type="checkbox"]{appearance:none;-webkit-appearance:none;position:relative;flex:none;width:25px;height:14px;min-height:0;border:0;border-radius:8px;background:var(--fleet-faint);margin:0;cursor:pointer;vertical-align:middle}.fleet-group-footer input[type="checkbox"]::after{content:"";position:absolute;width:10px;height:10px;left:2px;top:2px;border-radius:50%;background:#fff;transition:transform .15s}.fleet-group-footer input[type="checkbox"]:checked{background:var(--fleet-accent)}.fleet-group-footer input[type="checkbox"]:checked::after{transform:translateX(11px)}.fleet-group-footer input[type="checkbox"]:focus-visible{outline:2px solid var(--fleet-accent);outline-offset:3px}
.fleet-rotation-state{font-size:10px;color:var(--fleet-muted);padding:0;display:flex;gap:8px;align-items:center;flex-wrap:wrap;line-height:1.55;min-width:0}.fleet-rotation-state .err{font-size:10px;margin:0}.fleet-group-note{font-size:10px;color:var(--fleet-muted);line-height:1.5}.fleet-codex #cxAccW{border:0;margin:0}.fleet-codex #cxAccW>.cxacch,.fleet-codex .cxhead{display:none!important}.fleet-codex #cxAccW>#cx{display:block!important}.fleet-codex #cx{margin:0}
.fleet-design-note{display:flex;align-items:center;gap:10px;margin-top:22px;padding-top:14px;border-top:1px solid var(--fleet-line);color:var(--fleet-faint);font-size:10px;line-height:1.6}.fleet-design-note p{margin:0}.fleet-design-note>span{font-size:14px}
.fleet-profile-search{display:block;width:calc(100% - 32px);margin:16px 16px 2px;padding:10px 12px;border:1px solid var(--fleet-line);border-radius:8px;color:var(--txt);background:var(--bg);font-size:13px}.fleet-profile-note{font-size:11px;line-height:1.5;color:var(--mut);padding:0 16px;margin:10px 0 4px}html:root:root .cxpop.cxmenu{width:min(480px,calc(100vw - 20px))}.cxmenu .cxpbody{padding:10px 16px 18px}.cxmenu .cxprof{padding:13px 10px 13px 15px}.cxmenu .cxpnm{font-size:14px}.cxmenu .cxprof .cxps{font-size:12px;line-height:1.5;-webkit-line-clamp:3}.cxmenu .cxprof .cxpf{display:flex;margin-top:7px}.cxmenu .cxpinfo{font-size:12px;line-height:1.6}.cxmenu .cxw{font-size:10px}
.fleet-cx-options label{font-size:12px;margin-right:12px;display:inline-flex;gap:6px;align-items:center}.fleet-cx-options input{width:60px;padding:5px;color:var(--txt);background:var(--card);border:1px solid var(--fleet-line);border-radius:6px}.fleet-cx-options button{font-size:11px;padding:7px 10px}
html:not(.conly) #verTag{position:static;margin:25px 0 0;text-align:right;font-size:10px;color:var(--fleet-faint)}html.conly #fleetAccounts,html.conly .fleet-profilebar,html.conly .toolrow{display:none!important}html.conly .fleet-composer,html.conly .fleet-input-status,html.conly .fleet-console-toolbar{flex:none}html.conly #termBox{min-height:0!important;flex:1!important;padding-top:16px!important}html.conly .termwrap{display:flex;flex-direction:column}
.fleet-preview{display:flex;align-items:center;gap:8px;background:var(--card);color:var(--fleet-muted);font-size:10px;padding:9px 12px;border:1px solid var(--fleet-line);border-radius:7px;margin-bottom:20px;line-height:1.5}.fleet-preview::before{content:"";width:6px;height:6px;border-radius:50%;background:#ecc277;flex:none}
@media(max-width:1150px){html:root:root:not(.conly) body{padding:20px 25px}.hdr{gap:14px!important}.hdr .cxlim{display:none}.hdr #gear::after{display:none}.hdr #gear{padding:7px!important}.fleet-section .card>.row .lbl{grid-template-columns:minmax(0,1fr) auto 96px}.fleet-model-label{font-size:9px}.fleet-group-footer{align-items:flex-start}.fleet-rotation-state{max-width:65%}}
@media(max-width:900px){html:not(.conly) #cards,html:not(.conly) #cxcards{grid-template-columns:repeat(2,minmax(0,1fr))}.hdr .cxmodbtn{max-width:165px}.hdr .hdrl{min-width:145px!important}html:not(.conly) .hdrctl{gap:7px!important}.fleet-profilebar .cxgrp{max-width:100%}.fleet-section .card>.row .lbl{grid-template-columns:minmax(0,1fr) auto 102px}}
@media(max-width:640px){html:root:root:not(.conly) body{padding:17px 12px 24px}html:root:root:not(.conly) .hdr{flex-wrap:wrap;gap:12px;margin-bottom:16px}html:not(.conly) #h1{font-size:20px;gap:8px}.fleet-brand{width:33px;height:33px;font-size:19px;border-radius:9px}.fleet-brand-sub{font-size:7px;letter-spacing:.08em}.hdr .hdrl{flex:1;min-width:0!important}.hdr .hdrctl{flex-basis:100%!important;justify-content:flex-start!important;max-width:100%;gap:6px!important}.hdr .hdrbtns{margin-left:auto}.hdr .cxgrp{flex:1 1 auto!important;min-width:0!important;max-width:100%}.hdr .cxbtnname{max-width:160px!important}.hdr .cxmodbtn{max-width:150px}.hdr #termDot{margin-left:auto}.fleet-profilebar .cxbtn{max-width:100%}.fleet-console-toolbar{padding:0 12px;min-height:45px;gap:8px;flex-wrap:wrap}html:root:root .fleet-console-toolbar #cTabs{gap:11px;min-height:45px}.fleet-console-toolbar .ctab{font-size:11px!important}.fleet-console-toolbar .iconbtn{width:24px;height:24px}.fleet-console-toolbar .ctacts{gap:3px!important;margin-left:0!important}.fleet-console-toolbar .tzoom{gap:2px!important}.fleet-console-toolbar .tzval{font-size:10px}
html:not(.conly) #termBox{height:390px!important;min-height:300px!important;padding:20px 15px 12px;font-size:calc(11px * var(--tz,1))}.fleet-composer{padding:10px 12px;gap:9px}.fleet-composer textarea{font-size:11px}.fleet-composer .fleet-key{font-size:9px!important}.fleet-input-status{font-size:9px;padding:5px 12px;min-height:30px}.fleet-input-status span:last-child{display:none}.fleet-model-label{font-size:9px;flex-basis:100%;margin:0 0 5px}.toolrow{flex-wrap:wrap}.toolrow #mrow button{font-size:10px}.fleet-accounts-intro{margin:0 3px 16px}.fleet-accounts-intro h2{font-size:19px}.fleet-eyebrow{font-size:8px}#fleetAccounts{margin-top:23px}.fleet-section+.fleet-section{margin-top:23px}.fleet-section-head{gap:7px;margin:0 3px 11px}.fleet-section-head h2{font-size:13px;gap:7px}.fleet-count{font-size:9px}.fleet-section-head #addAcct,.fleet-section-head .fleet-add-codex{font-size:10px;padding:5px 7px}html:not(.conly) #cards,html:not(.conly) #cxcards{grid-template-columns:1fr}.fleet-section .card>.row .lbl{grid-template-columns:minmax(0,1fr) auto 112px}.fleet-section .card{padding:14px 15px!important;min-height:198px!important}.fleet-group-footer{flex-wrap:wrap;gap:4px;margin:6px 3px 0}.fleet-group-footer #optWrap,.fleet-group-footer .switchrow{font-size:10px;min-height:26px}.fleet-group-note{max-width:65%;font-size:9px}.fleet-rotation-state{font-size:9px;max-width:100%;flex-basis:100%}.fleet-design-note{margin:19px 3px 0;align-items:flex-start;font-size:10px}.fleet-card-panel{width:285px}.fleet-card-panel .acts button{font-size:11px;min-height:34px}.fleet-preview{font-size:9px;margin-bottom:16px}.cxmenu .cxprof .cxpf{display:flex}}
@media(prefers-reduced-motion:reduce){.fleet-group-footer input[type="checkbox"]::after{transition:none}}

html:root:root .fleet-console-toolbar #cTabs .ctab.on{color:#ecf1f6!important}
#fleetClaude .card>.row[data-fleet-tone="warn"] .fill,#fleetCodex .card>.row[data-fleet-tone="warn"] .fill{background:var(--warn)!important}
#fleetClaude .card>.row[data-fleet-tone="bad"] .fill,#fleetCodex .card>.row[data-fleet-tone="bad"] .fill{background:var(--bad)!important}
.fleet-group-footer #optLbl,.fleet-group-footer .switchrow{font-size:0!important}
.fleet-group-footer .switchrow::after{content:"Автовыбор";font-size:10px}

.fleet-console-toolbar .iconbtn{color:#8799ae!important;border-color:#2a3542!important;box-shadow:none!important}
.fleet-card-panel.fleet-menu-above{top:auto;bottom:30px}

/* Мобильный обзор: аккаунты всегда остаются в обычной прокрутке страницы. */
.fleet-current-accounts,.fleet-account-jump{display:none}
html:root:root.fleet-mobile{height:auto!important;min-height:100%;overflow-x:hidden;overflow-y:auto}
html:root:root.fleet-mobile body{height:auto!important;min-height:100svh;max-width:none;display:block!important;overflow:visible!important;padding:max(12px,env(safe-area-inset-top)) max(12px,env(safe-area-inset-right)) max(24px,env(safe-area-inset-bottom)) max(12px,env(safe-area-inset-left))}
html:root:root.fleet-mobile .hdr{display:flex!important;flex-wrap:wrap;gap:10px!important;margin:0 0 14px;align-items:center}
html:root:root.fleet-mobile .hdrl{display:flex;flex:1;gap:12px;min-width:0!important}
html:root:root.fleet-mobile #h1{display:flex;font-size:21px;order:0;white-space:normal}
html:root:root.fleet-mobile #termDot{order:0;margin:0 0 0 auto}
html:root:root.fleet-mobile .hdrctl{display:flex;flex:1 0 100%;width:100%;max-width:100%;margin:0;gap:8px!important;justify-content:stretch!important}
html:root:root.fleet-mobile #cxGrp:not([hidden]){display:grid!important;grid-template-columns:minmax(0,1fr) 44px;gap:6px;flex:1 0 100%;width:100%;min-width:0!important;max-width:100%;border:1px solid var(--fleet-line);border-radius:10px;padding:7px;background:var(--card)}
html:root:root.fleet-mobile #cxBtn:not([hidden]){grid-column:1;grid-row:1;display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:flex-start;width:100%;max-width:none;height:auto;min-height:44px;margin:0;padding:7px 6px;border:0;box-shadow:none;border-radius:7px;font-size:13px}
html:root:root.fleet-mobile .cxbtnname,html:root:root.fleet-mobile .cxmodn{max-width:none!important;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere;font-size:13px}
html:root:root.fleet-mobile .cxbtnname{flex:1;min-width:0}
html:root:root.fleet-mobile #cxLim:not([hidden]){display:flex!important;flex:1 0 100%;gap:9px;justify-content:flex-start;margin:1px 0 0 22px;opacity:1;white-space:normal;font-size:11px}
html:root:root.fleet-mobile #cxGear{grid-column:2;grid-row:1;align-self:start;width:44px;height:44px;margin:0;border:1px solid var(--fleet-line);border-radius:8px}
html:root:root.fleet-mobile #cxMod:not([hidden]){display:flex;grid-column:1/-1;grid-row:2;gap:8px;justify-content:flex-start;flex:none;min-height:44px;height:auto;width:100%;max-width:none;margin:0;padding:8px 10px;border:1px solid var(--fleet-line);border-radius:7px;box-shadow:none}
html:root:root.fleet-mobile #cxModE{font-size:12px;margin-left:auto}
html:root:root.fleet-mobile .hdrbtns{display:flex;gap:8px!important;justify-content:flex-end;width:100%;margin:0}
html:root:root.fleet-mobile #rfBtn{width:44px;height:44px;border:1px solid var(--fleet-line)}
html:root:root.fleet-mobile #gear{min-height:44px;height:auto;padding:9px 12px!important}
html:root:root.fleet-mobile #gear::after{display:inline;content:"Настройки";font-size:13px}
html:root:root.fleet-mobile .termwrap{display:flex!important;flex-direction:column;flex:none!important;height:auto!important;min-height:0!important;overflow:hidden;margin:0;border-radius:12px}
html:root:root.fleet-mobile .fleet-console-toolbar{display:flex;flex-wrap:wrap;justify-content:space-between;gap:0 10px;padding:0 10px;min-height:48px}
html:root:root.fleet-mobile #cTabs:not([hidden]){display:flex!important;position:static;flex:1 1 auto;gap:12px;min-height:48px;flex-wrap:wrap;align-items:center}
html:root:root.fleet-mobile .fleet-console-toolbar .ctab{font-size:13px!important;min-height:48px;padding:0 3px}
html:root:root.fleet-mobile .fleet-console-toolbar .ctacts{display:flex;gap:5px!important;flex-wrap:nowrap;margin:0!important}
html:root:root.fleet-mobile .fleet-console-toolbar .iconbtn{width:36px;height:40px;flex:none}
html:root:root.fleet-mobile .fleet-console-toolbar .tzoom{position:static;display:flex;flex:1 0 100%;justify-content:flex-end;gap:7px!important;margin:0;padding:0 0 5px;background:transparent;border-top:1px solid #242d39;border-radius:0}
html:root:root.fleet-mobile .fleet-console-toolbar .tzval{font-size:12px;min-width:44px}
html:root:root.fleet-mobile #termBox{height:clamp(220px,40svh,340px)!important;min-height:220px!important;max-height:none;flex:none!important;padding:14px 12px!important;white-space:pre-wrap!important;word-break:break-word;overflow-wrap:anywhere;overflow-x:hidden;overflow-y:auto;overscroll-behavior-y:auto;font-size:calc(12px * var(--tz,1));line-height:1.5}
html:root:root.fleet-mobile.conly #termBox{height:clamp(280px,65svh,560px)!important;min-height:280px!important;flex:none!important}
html:root:root.fleet-mobile .fleet-composer{display:flex;gap:8px;padding:10px 12px;align-items:center}
html:root:root.fleet-mobile #fleetInput{font-size:16px;line-height:1.45;min-height:44px;padding:9px 0}
html:root:root.fleet-mobile #fleetSend{width:40px;height:44px;font-size:22px}
html:root:root.fleet-mobile .fleet-key{min-height:36px;padding:7px 5px!important;font-size:11px!important}
html:root:root.fleet-mobile .fleet-input-status{display:flex;flex-wrap:wrap;gap:5px 8px;padding:0 12px;min-height:44px;font-size:11px}
html:root:root.fleet-mobile .fleet-input-status>span:last-of-type{display:none}
html:root:root.fleet-mobile .fleet-account-jump{display:inline-flex;align-items:center;justify-content:center;min-height:44px;margin-left:auto;padding:3px 0 3px 6px;color:#72dec0;background:none;border:0;font-size:12px;white-space:normal;text-align:right}
html:root:root.fleet-mobile #fleetAccounts{display:block!important;margin-top:20px;min-width:0}
html:root:root.fleet-mobile .fleet-accounts-intro{margin:0 0 14px}
html:root:root.fleet-mobile .fleet-accounts-intro h2{font-size:21px;line-height:1.3}
html:root:root.fleet-mobile .fleet-eyebrow{font-size:10px}
html:root:root.fleet-mobile .fleet-current-accounts{display:grid;grid-template-columns:1fr;gap:10px;margin:0 0 20px;scroll-margin-top:12px}
.fleet-current-heading{font-size:16px;font-weight:600;margin:0 0 1px}
.fleet-current-tile{padding:13px 14px;border:1px solid var(--fleet-line);border-radius:10px;background:var(--card);min-width:0}
.fleet-current-tile[data-provider="claude"]{border-left:3px solid var(--fleet-claude)}.fleet-current-tile[data-provider="codex"]{border-left:3px solid var(--fleet-accent)}
.fleet-current-title{display:flex;flex-wrap:wrap;gap:7px;align-items:center;line-height:1.4;font-size:14px}.fleet-current-provider{font-size:12px;color:var(--fleet-muted)}.fleet-current-name{font-weight:650;overflow-wrap:anywhere}
.fleet-current-email{font-size:13px;line-height:1.45;color:var(--fleet-muted);margin-top:3px;overflow-wrap:anywhere}.fleet-current-model{font-size:13px;line-height:1.5;color:var(--txt);margin-top:7px;overflow-wrap:anywhere}.fleet-current-quota{font-size:13px;line-height:1.5;color:var(--fleet-muted);margin-top:5px;white-space:normal}.fleet-current-warning{font-size:12px;color:var(--warn);line-height:1.5;margin-top:6px}
.fleet-current-link{display:flex;align-items:center;min-height:40px;padding:5px 0 0;font-size:12px;color:var(--fleet-accent);background:none;border:0;text-align:left}
html:root:root.fleet-mobile .toolrow{display:flex!important;flex-wrap:wrap;margin:0 0 20px;padding:12px;background:var(--card);border:1px solid var(--fleet-line);border-radius:9px;gap:9px}
html:root:root.fleet-mobile .fleet-model-label{font-size:12px;flex-basis:100%;margin:0;line-height:1.4}
html:root:root.fleet-mobile #mrow{display:flex;flex-wrap:wrap;gap:7px}
html:root:root.fleet-mobile #mrow button{font-size:13px;min-height:40px;padding:7px 12px}
html:root:root.fleet-mobile #efrow{width:100%;flex-basis:100%;font-size:13px}
html:root:root.fleet-mobile .fleet-section-head{gap:9px;margin:0 0 12px;align-items:center}
html:root:root.fleet-mobile .fleet-section-head h2{font-size:16px;gap:9px;line-height:1.4}
html:root:root.fleet-mobile .fleet-count{font-size:12px}
html:root:root.fleet-mobile .fleet-section-head #addAcct,html:root:root.fleet-mobile .fleet-add-codex{font-size:12px;height:auto;min-height:40px;padding:8px 9px}
html:root:root.fleet-mobile #cards,html:root:root.fleet-mobile #cxcards{display:grid!important;grid-template-columns:minmax(0,1fr)!important;gap:14px!important;margin:0!important;max-height:none!important;overflow:visible!important}
html:root:root.fleet-mobile .fleet-section .card{height:auto!important;min-height:0!important;padding:16px!important;min-width:0;scroll-margin-top:12px}
html:root:root.fleet-mobile .card.active,html:root:root.fleet-mobile .card.fleet-active{order:-1}
html:root:root.fleet-mobile .fleet-section .card .top{min-height:0;margin:0 0 10px;padding-right:0}
html:root:root.fleet-mobile .fleet-titleline{flex-wrap:wrap;gap:7px;row-gap:5px}
html:root:root.fleet-mobile .fleet-account-name{font-size:16px;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere}
html:root:root.fleet-mobile .fleet-section .card .email{font-size:14px;line-height:1.5;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere;margin-top:4px}
html:root:root.fleet-mobile .fleet-section .tag.plan,html:root:root.fleet-mobile .fleet-section .tag.free{font-size:11px;padding:2px 6px}
html:root:root.fleet-mobile .fleet-card-state{font-size:12px;line-height:1.5;padding:3px 7px;margin:0 0 14px}
html:root:root.fleet-mobile .fleet-section .card>.row{margin:0 0 15px!important}
html:root:root.fleet-mobile .fleet-section .card>.row .lbl{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 10px;font-size:13px;line-height:1.45;margin:0 0 6px}
html:root:root.fleet-mobile .fleet-section .card>.row .lbl b{font-size:14px}
html:root:root.fleet-mobile .fleet-section .card>.row .lbl>span:last-child{grid-column:1/-1;font-size:12px;white-space:normal;overflow:visible;text-overflow:clip;text-align:left;line-height:1.45;overflow-wrap:anywhere}
html:root:root.fleet-mobile .fleet-section .card>.row .bar{height:5px!important}
html:root:root.fleet-mobile .fleet-card-footer{flex-wrap:wrap;gap:7px;min-height:44px;margin:0;padding-top:9px}
html:root:root.fleet-mobile .fleet-card-caption{font-size:12px;white-space:normal;overflow:visible;line-height:1.45}
html:root:root.fleet-mobile .fleet-card-footer .btn-sw{font-size:13px!important;min-height:44px;white-space:normal;text-align:right;padding:6px 0 6px 8px!important}
html:root:root.fleet-mobile .fleet-card-details{position:static;display:block;top:auto;right:auto;margin-top:10px;border-top:1px solid var(--fleet-line)}
html:root:root.fleet-mobile .fleet-card-details>summary{display:none}
html:root:root.fleet-mobile .fleet-card-panel,html:root:root.fleet-mobile .fleet-card-panel.fleet-menu-above{position:static;top:auto;bottom:auto;right:auto;width:100%;max-width:none;min-width:0;margin:0;padding:14px 0 0;border:0;border-radius:0;background:transparent;box-shadow:none}
html:root:root.fleet-mobile .fleet-card-panel-title{font-size:13px;line-height:1.5;margin-bottom:10px;font-weight:550;color:var(--fleet-muted)}
html:root:root.fleet-mobile .fleet-card-panel .hdrright{gap:12px;margin-bottom:12px;flex-wrap:wrap}
html:root:root.fleet-mobile .fleet-card-panel .iconbtn{height:44px;width:44px}
html:root:root.fleet-mobile .fleet-card-panel .cxsel{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px}
html:root:root.fleet-mobile .fleet-card-panel .cxsel select{font-size:16px;height:auto;min-height:44px;padding:10px 9px;white-space:normal;width:100%;max-width:100%;box-sizing:border-box}
html:root:root.fleet-mobile .fleet-card-panel .cxfast{font-size:14px;min-height:40px;gap:8px}
html:root:root.fleet-mobile .fleet-card-panel .cxfast input{width:20px;height:20px}
html:root:root.fleet-mobile .fleet-card-panel .acts{display:flex;gap:8px;flex-wrap:wrap}
html:root:root.fleet-mobile .fleet-card-panel .acts button{font-size:13px;line-height:1.5;min-height:44px;padding:9px 10px;max-width:100%;white-space:normal;overflow-wrap:anywhere}
html:root:root.fleet-mobile .fleet-card-panel .acts .btn-del .dl{display:inline!important}
html:root:root.fleet-mobile .fleet-group-footer{font-size:12px;line-height:1.5;gap:8px;margin:8px 0 0;align-items:center;flex-wrap:wrap}
html:root:root.fleet-mobile .fleet-group-note,html:root:root.fleet-mobile .fleet-rotation-state{font-size:12px;line-height:1.5;max-width:100%;flex-basis:100%;white-space:normal;overflow-wrap:anywhere}
html:root:root.fleet-mobile .fleet-group-footer #optWrap,html:root:root.fleet-mobile .fleet-group-footer .switchrow{min-height:44px;font-size:0!important;gap:9px}
html:root:root.fleet-mobile .fleet-group-footer .switchrow::after{font-size:13px}
html:root:root.fleet-mobile .fleet-group-footer input[type="checkbox"]{width:36px;height:22px;border-radius:12px}
html:root:root.fleet-mobile .fleet-group-footer input[type="checkbox"]::after{width:16px;height:16px;left:3px;top:3px}
html:root:root.fleet-mobile .fleet-group-footer input[type="checkbox"]:checked::after{transform:translateX(14px)}
html:root:root.fleet-mobile .fleet-section+.fleet-section{margin-top:26px}
html:root:root.fleet-mobile .fleet-design-note{font-size:12px;line-height:1.6;margin-top:22px}
html:root:root.fleet-mobile .dock{display:none!important}
html:root:root.fleet-mobile #verTag{display:block!important;position:static;height:auto;margin-top:20px;font-size:11px}
html:root:root.fleet-mobile #cxMenu:not([hidden]){top:max(8px,env(safe-area-inset-top))!important;bottom:max(8px,env(safe-area-inset-bottom))!important;left:8px!important;right:8px!important;width:auto!important;height:auto!important;max-height:calc(100dvh - 16px)!important;z-index:90;border-radius:12px;overflow:hidden}
html:root:root.fleet-mobile #cxMenu .cxpbody{min-height:0;flex:1;overflow-y:auto;overscroll-behavior:contain}
html:root:root.fleet-mobile #cxMenuScrim:not([hidden]){display:block!important;z-index:89}
html:root:root.fleet-mobile .cxmenu .cxprof{min-height:44px}
html:root:root.fleet-mobile #cxQ .cxqm,html:root:root.fleet-mobile #cxQ .cxqe{min-height:44px;font-size:13px}
html:root:root.fleet-mobile #cTabs .ctab{width:auto!important;min-width:66px;flex:0 0 auto;gap:7px;padding:0 4px;white-space:nowrap}
html:root:root.fleet-mobile #cTabs .ctab::before{flex:none}
html:root:root.fleet-mobile #cxBtn .cxbtnname{order:1;text-align:left}
html:root:root.fleet-mobile #cxBtn .cxcar{order:2;flex:none}
html:root:root.fleet-mobile #cxBtn #cxLim{order:3}
html:root:root.fleet-mobile #fleetInput{min-height:72px}
html:root:root.fleet-mobile .fleet-key{min-height:44px}
html:root:root.fleet-mobile .fleet-card-panel .ring{display:none}
html:root:root.fleet-mobile .fleet-card-panel .hdrright:not(:has(.iconrow)){display:none}
html:root:root.fleet-mobile .fleet-card-panel .iconrow{display:flex;flex-wrap:wrap;gap:8px}
html:root:root.fleet-mobile .fleet-card-panel .iconrow .iconbtn{display:inline-flex;align-items:center;gap:7px;width:auto;padding:8px 10px;min-height:44px}
html:root:root.fleet-mobile .fleet-card-panel .iconrow .iconbtn::after{content:attr(title);font-size:12px;line-height:1.4;white-space:normal}

'''

JS = r'''
(()=>{
 const el=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls||'';if(text)n.textContent=text;return n};
 document.body.classList.add('fleet-overview');
 const hdr=document.querySelector('.hdr'),term=document.querySelector('.termwrap');
 document.getElementById('h1').innerHTML='<span class="fleet-brand">›_</span>ccfleet';
 const accountArea=el('main','');accountArea.id='fleetAccounts';term.after(accountArea);
 const claude=el('section','fleet-section');claude.id='fleetClaude';
 const ch=el('div','fleet-section-head');ch.innerHTML='<h2><span class="fleet-provider">✳</span>Claude</h2>';
 ch.append(document.getElementById('optWrap'),document.getElementById('addAcct'));
 claude.append(ch,document.getElementById('cards'));accountArea.append(claude);
 const codex=el('section','fleet-section fleet-codex');codex.id='fleetCodex';
 const xh=el('div','fleet-section-head');xh.innerHTML='<h2><span class="fleet-provider codex">›_</span>Codex / ChatGPT</h2><label class="switchrow"><input type="checkbox" id="fleetCxOpt"> Оптимизация переключений лимитов</label>';
 const rotation=el('div','fleet-rotation-state');rotation.id='fleetRotation';
 codex.append(xh,document.getElementById('cxAccW'),rotation);accountArea.append(codex);
 const models=document.querySelector('.toolrow');models.prepend(el('span','fleet-model-label','Claude: модель и уровень рассуждений'));term.after(models);
 const profilebar=el('div','fleet-profilebar');profilebar.innerHTML='<span class="fleet-profilelabel">Профиль, модель и настройки Codex</span>';
 profilebar.append(document.getElementById('cxGrp'));term.before(profilebar);
 const form=el('form','fleet-composer');form.id='fleetConsoleForm';
 form.innerHTML='<textarea id="fleetInput" rows="1" aria-label="Сообщение или команда в выбранную консоль" placeholder="Сообщение или команда… Enter — отправить, Shift+Enter — новая строка"></textarea><button type="button" class="fleet-key" data-console-key="escape" title="Esc в консоль">Esc</button><button type="submit" id="fleetSend">Отправить ↑</button>';
 const inputStatus=el('div','fleet-input-status');inputStatus.innerHTML='<span id="fleetInputState">Ввод в выбранную консоль</span><span>Claude / Codex · действующая сессия</span>';term.append(form,inputStatus);
 const menu=document.getElementById('cxMenu');const search=el('input','fleet-profile-search');search.placeholder='Найти профиль…';search.setAttribute('aria-label','Поиск профилей');
 const note=el('p','fleet-profile-note','Профиль определяет права и способ работы. Аккаунт определяет подписку и лимиты. Активный профиль отмечен галочкой.');menu.prepend(search,note);
 function filterProfiles(){const q=search.value.trim().toLocaleLowerCase('ru');menu.querySelectorAll('.cxprof').forEach(n=>n.hidden=!!q&&!n.textContent.toLocaleLowerCase('ru').includes(q))}
 search.addEventListener('input',filterProfiles);new MutationObserver(filterProfiles).observe(document.getElementById('cxp'),{childList:true});
 const cxOptions=el('div','fleet-cx-options');cxOptions.innerHTML='<div class="modalh">Codex · пороги оптимизации</div><label>Сессия, % <input id="fleetCxThreshold" type="number" min="50" max="100" value="90"></label><label>Неделя, % <input id="fleetCxCap" type="number" min="50" max="100" value="99"></label><button type="button" id="fleetCxSave">Сохранить пороги Codex</button>';
 document.getElementById('autoNote').after(cxOptions);
 document.getElementById('fleetCxSave').addEventListener('click',async e=>{e.target.disabled=true;try{const d=await post('chatgpt/rotation/config',{threshold:Number(document.getElementById('fleetCxThreshold').value),weekly_cap:Number(document.getElementById('fleetCxCap').value)});toast(d.message);await loadRotation()}catch(err){toast('⚠ '+err.message)}finally{e.target.disabled=false}});
 const stateNode=document.getElementById('fleetInputState'),input=document.getElementById('fleetInput'),send=document.getElementById('fleetSend');
 let sending=false,rotationData=null,lastRequest=null;
 async function post(path,body){const r=await fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':TOKEN},body:JSON.stringify(body)});const d=await r.json();if(!r.ok||!d.ok)throw Error(d.message||'Не удалось выполнить действие');return d}
 form.addEventListener('submit',async e=>{e.preventDefault();if(sending||!input.value.trim())return;const text=input.value;const session=typeof consCur==='function'?consCur():'claude';sending=true;send.disabled=true;stateNode.textContent='Отправляю в '+(session==='codex'?'Codex':'Claude')+'…';try{const d=await post('console/input',{session,text,request_id:(lastRequest&&lastRequest.text===text&&lastRequest.session===session?lastRequest.id:(lastRequest={text,session,id:crypto.randomUUID()}).id)});if(input.value===text)input.value='';lastRequest=null;stateNode.textContent=d.message||'Ввод передан в консоль';ccConsole()}catch(err){stateNode.textContent=err.message;toast('⚠ '+err.message)}finally{sending=false;send.disabled=false}});
 input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();form.requestSubmit()}});
 form.querySelector('[data-console-key]').addEventListener('click',async()=>{try{const d=await post('console/key',{session:typeof consCur==='function'?consCur():'claude',key:'escape'});stateNode.textContent=d.message;ccConsole()}catch(e){toast('⚠ '+e.message)}});
 function renderRotation(d){rotationData=d;if(!document.querySelector('.fleet-cx-options:focus-within')){document.getElementById('fleetCxThreshold').value=d.threshold||90;document.getElementById('fleetCxCap').value=d.weekly_cap||99;}document.getElementById('fleetCxOpt').checked=!!d.optimize;rotation.replaceChildren();const text=el('span','',d.message||'Проверка лимитов');rotation.append(text);if(d.next_label)rotation.append(el('span','','Следующий: '+d.next_label));if(d.last_error)rotation.append(el('span','err',d.last_error));
  document.querySelectorAll('#cxcards .card').forEach((c,i)=>{const a=typeof cxData!=='undefined'&&cxData.accounts&&cxData.accounts[i];c.classList.toggle('fleet-active',!!a&&a.slot===d.active);if(!a)return;const top=c.querySelector('.top .email');if(top&&a.slot!==d.active)top.querySelector('.fleet-active-label')?.remove();if(top&&a.slot===d.active&&!top.querySelector('.fleet-active-label'))top.append(el('span','fleet-active-label','Выбран'));const existing=c.querySelector('.fleet-pick');if(existing){existing.textContent=a.slot===d.active?'Выбран':'Выбрать';existing.disabled=a.slot===d.active||!!d.optimize;existing.title=d.optimize?'Ручной выбор доступен при выключенной оптимизации':'';}if(!existing){const b=el('button','btn-sw fleet-pick',a.slot===d.active?'Выбран':'Выбрать');b.disabled=a.slot===d.active||!!d.optimize;b.title=d.optimize?'Ручной выбор доступен при выключенной оптимизации':'';b.onclick=async()=>{b.disabled=true;try{const r=await post('chatgpt/rotation/switch',{slot:a.slot});toast(r.message);loadRotation()}catch(e){toast('⚠ '+e.message);loadRotation()}};const acts=c.querySelector('.acts');if(acts)acts.prepend(b)}});
  refreshVisuals();
 }
 let refreshing=false;async function loadRotation(){if(refreshing)return;refreshing=true;try{const r=await fetch(API+'chatgpt/rotation',{headers:{'X-CC-Token':TOKEN}});if(r.ok)renderRotation(await r.json())}catch(e){}finally{refreshing=false}}
 document.getElementById('fleetCxOpt').addEventListener('change',async e=>{const on=e.target.checked;e.target.disabled=true;try{await post('chatgpt/rotation/config',{optimize:on});await loadRotation()}catch(err){e.target.checked=!on;toast('⚠ '+err.message)}finally{e.target.disabled=false}});
 const oldCxRender=cxRender;cxRender=function(){oldCxRender();if(rotationData)renderRotation(rotationData);if(typeof cxData!=='undefined'&&cxData&&cxData.loading&&!cxData.accounts.length)document.getElementById('cx').textContent='Загружаем сохранённые аккаунты…'};
 const accLink=document.querySelector('#cxAccW>.cxacch');if(accLink)accLink.title='Аккаунты показаны на главной странице';
 document.getElementById('cxAccW').classList.add('open');
  // Только оформление: переносим существующие узлы, не заменяя обработчики действий.
 document.body.classList.add('fleet-reference');
 const openAccountMenus=new Map();
 const brand=document.getElementById('h1');
 brand.innerHTML='<span class="fleet-brand" aria-hidden="true">›_</span><span>cc<span class="fleet-brand-word">fleet</span><small class="fleet-brand-sub">БАЛАНСЕР АККАУНТОВ</small></span>';
 hdr.querySelector('.hdrctl').prepend(profilebar);
 const headerButtons=hdr.querySelector('.hdrbtns');if(headerButtons)hdr.querySelector('.hdrctl').append(headerButtons);
 const toolbar=el('div','fleet-console-toolbar');toolbar.append(document.getElementById('cTabs'),term.querySelector('.tzoom'));term.prepend(toolbar);
 send.textContent='↑';send.title='Отправить в выбранную консоль · Enter';send.setAttribute('aria-label','Отправить в выбранную консоль');
 input.placeholder='Сообщение или команда в выбранную консоль…';input.title='Enter — отправить · Shift+Enter — новая строка';
 const intro=el('div','fleet-accounts-intro');intro.innerHTML='<span class="fleet-eyebrow">УПРАВЛЕНИЕ АККАУНТАМИ</span><h2>Лимиты и переключения</h2>';accountArea.prepend(intro);
 const claudeFoot=el('div','fleet-group-footer'),claudeNote=el('span','fleet-group-note');claudeFoot.append(claudeNote,document.getElementById('optWrap'));claude.append(claudeFoot);
 const codexFoot=el('div','fleet-group-footer');codexFoot.append(rotation,xh.querySelector('.switchrow'));codex.append(codexFoot);
 const noteFooter=el('div','fleet-design-note');noteFooter.innerHTML='<span aria-hidden="true">ⓘ</span><p>Проценты показывают использованный лимит. Плановая смена аккаунта — между ответами.</p>';accountArea.append(noteFooter);
 for(const head of [ch,xh]){const count=el('span','fleet-count');head.querySelector('h2').after(count)}
 // На телефоне обзор и карточки доступны в обычной прокрутке, включая сохранённый conly.
 const mobileLayout=matchMedia('(max-width:700px), (pointer:coarse) and (max-width:1000px)');
 const currentAccounts=el('section','fleet-current-accounts');currentAccounts.id='fleetCurrentAccounts';currentAccounts.setAttribute('aria-label','Активные аккаунты');intro.after(currentAccounts);
 const accountJump=el('button','fleet-account-jump','Активные аккаунты ↓');accountJump.type='button';accountJump.addEventListener('click',()=>currentAccounts.scrollIntoView({behavior:'smooth',block:'start'}));inputStatus.append(accountJump);
 let currentSignature='';
 function modelSummary(account,engine,snapshot){
  if(engine==='codex')return (rotationData?.model||account.model||'По умолчанию')+((rotationData?.effort||account.effort)?' · '+(rotationData?.effort||account.effort):'');
  const model=snapshot?.model;return model?.session_name||model?.session||model?.default_name||model?.default||'По умолчанию';
 }
 function refreshCurrentAccounts(snapshot){
  const rows=Object.entries(snapshot?.accounts||{}),chosen=[];
  const cl=rows.find(([,a])=>a.active);if(cl)chosen.push({engine:'claude',slot:cl[0],account:cl[1]});
  const cx=((typeof cxData!=='undefined'&&cxData?.accounts)||[]).find(a=>a.slot===rotationData?.active);if(cx)chosen.push({engine:'codex',slot:cx.slot,account:cx});
  const values=chosen.map(({engine,slot,account:a})=>{
   const windows=engine==='codex'?a.windows||[]:[{mins:300,...a.five_hour},{mins:10080,...a.seven_day}];
   const ses=windows.find(w=>w.mins===300)?.pct,week=windows.find(w=>w.mins===10080)?.pct;
   return {engine,slot,name:a.label||a.name||slot,email:a.email||'',model:modelSummary(a,engine,snapshot),quota:'Использовано: 5 ч — '+(ses==null?'нет данных':ses+'%')+' · неделя — '+(week==null?'нет данных':week+'%'),warning:a.stale||a.error||a.login_required?'Проверь данные аккаунта в карточке ниже.':engine==='codex'&&rotationData?.pending_model?'Смена модели ожидает завершения ответа.':''};
  });
  const signature=JSON.stringify(values);if(signature===currentSignature)return;currentSignature=signature;
  currentAccounts.replaceChildren(el('h3','fleet-current-heading','Активные аккаунты'));
  if(!values.length){currentAccounts.append(el('p','fleet-current-email','Получаем данные выбранных аккаунтов…'));return;}
  for(const a of values){
   const tile=el('article','fleet-current-tile');tile.dataset.provider=a.engine;
   const title=el('div','fleet-current-title');title.append(el('span','fleet-current-provider',a.engine==='codex'?'Codex / ChatGPT':'Claude'),el('strong','fleet-current-name',a.name));
   tile.append(title,el('div','fleet-current-email',a.email),el('div','fleet-current-model','Модель: '+a.model),el('div','fleet-current-quota',a.quota));if(a.warning)tile.append(el('div','fleet-current-warning',a.warning));
   const link=el('button','fleet-current-link','Открыть карточку ниже ↓');link.type='button';link.addEventListener('click',()=>{const card=[...document.querySelectorAll('.fleet-section .card')].find(n=>n.dataset.fleetReference===a.engine+':'+a.slot);if(card){card.scrollIntoView({behavior:'smooth',block:'start'});card.tabIndex=-1;card.focus({preventScroll:true})}});tile.append(link);currentAccounts.append(tile);
  }
 }
 function updateMobileConsoleTitle(){if(!mobileLayout.matches)return;const button=document.getElementById('fsBtn'),text=document.documentElement.classList.contains('conly')?'Уменьшить консоль':'Увеличить консоль';button.title=text;button.setAttribute('aria-label',text)}
 function syncMobileLayout(){
  const mobile=mobileLayout.matches;document.documentElement.classList.toggle('fleet-mobile',mobile);input.rows=mobile?2:1;
  if(mobile){if(models.parentElement!==accountArea)currentAccounts.after(models)}else if(models.parentElement!==term.parentElement)term.after(models);
  document.querySelectorAll('.fleet-card-details').forEach(menu=>{
   if(mobile){if(!menu.dataset.mobileExpanded)menu.dataset.desktopOpen=menu.open?'1':'0';menu.dataset.mobileExpanded='1';menu.open=true;menu.querySelector('summary').tabIndex=-1;menu.querySelector('.fleet-card-panel').classList.remove('fleet-menu-above')}
   else if(menu.dataset.mobileExpanded){menu.open=menu.dataset.desktopOpen==='1';delete menu.dataset.mobileExpanded;delete menu.dataset.desktopOpen;menu.querySelector('summary').removeAttribute('tabindex')}
  });updateMobileConsoleTitle();
 }
 mobileLayout.addEventListener('change',syncMobileLayout);
 document.getElementById('fsBtn').addEventListener('click',()=>requestAnimationFrame(updateMobileConsoleTitle));document.addEventListener('fullscreenchange',updateMobileConsoleTitle);
 if(mobileLayout.matches&&document.documentElement.classList.contains('conly'))setConly(false,false);
 syncMobileLayout();

 function countText(n){const k=n%100,m=n%10;return n+' '+(k>=11&&k<=14?'аккаунтов':m===1?'аккаунт':m>=2&&m<=4?'аккаунта':'аккаунтов')}
 function putText(node,value){if(node.textContent!==value)node.textContent=value}
 function decorateCard(card,a,slot,engine){
  const key=engine+':'+slot;const isActive=card.classList.contains(engine==='codex'?'fleet-active':'active');
  if(!card.dataset.fleetReference){
   card.dataset.fleetReference=key;
   const top=card.querySelector(':scope > .top'),email=top?.querySelector('.email');if(!top||!email)return;
   const identity=el('div','fleet-identity'),title=el('div','fleet-titleline'),name=el('strong','fleet-account-name',a.label||a.name||slot);
   name.title=a.label||a.name||slot;title.append(name);
   for(const tag of email.querySelectorAll('.tag,.chip'))title.append(tag);
   email.replaceChildren(document.createTextNode(a.email||slot));email.title=a.email||slot;
   identity.append(title,email);top.prepend(identity);
   const badge=el('span','fleet-card-state');top.after(badge);
   const details=el('details','fleet-card-details'),summary=el('summary','','⋯');summary.title='Все действия и настройки аккаунта';summary.setAttribute('aria-label','Все действия и настройки аккаунта '+(a.label||slot));
   const panel=el('div','fleet-card-panel');panel.append(el('div','fleet-card-panel-title','Действия и настройки аккаунта'));
   const right=top.querySelector('.hdrright');if(right)panel.append(right);
   const selection=card.querySelector(':scope > .cxsel');if(selection)panel.append(selection);
   const acts=card.querySelector(':scope > .acts'),primary=acts?.querySelector('.btn-sw');
   const bottom=el('div','fleet-card-footer');bottom.append(el('span','fleet-card-caption'));if(primary)bottom.append(primary);if(acts)panel.append(acts);
   details.append(summary,panel);details.open=!!openAccountMenus.get(key);details.addEventListener('toggle',()=>{if(!mobileLayout.matches)openAccountMenus.set(key,details.open);if(details.open&&!mobileLayout.matches){panel.classList.remove('fleet-menu-above');const r=summary.getBoundingClientRect(),h=panel.getBoundingClientRect().height;panel.classList.toggle('fleet-menu-above',r.bottom+h>innerHeight-12&&r.top>h+12)}});card.append(bottom,details);
   card.querySelectorAll(':scope > .row').forEach(row=>{
    const label=row.querySelector('.lbl'),percent=label?.querySelector('b');if(!label||!percent)return;
    label.insertBefore(percent,label.lastElementChild);
    for(const node of label.firstElementChild.childNodes)if(node.nodeType===Node.TEXT_NODE)node.textContent=node.textContent.replace(/:\s*$/,'');
    const reset=label.lastElementChild;reset.title=reset.textContent;reset.textContent=reset.textContent.replace(/^сброс\s+/,'').replace(/\s*\([^)]*\)\s*$/,'');
    const n=Number.parseFloat(percent.textContent);row.dataset.fleetTone=n>=100?'bad':n>=85?'warn':'normal';
   });
  }
  const footer=card.querySelector('.fleet-card-footer');
  const pick=card.querySelector('.fleet-pick')||card.querySelector('.acts .btn-sw');if(pick&&pick.parentElement!==footer)footer.append(pick);
  const windows=engine==='codex'?a.windows||[]:[{mins:300,...a.five_hour},{mins:10080,...a.seven_day}];
  const session=windows.find(w=>w.mins===300),week=windows.find(w=>w.mins===10080);
  let text='В ожидании',tone='',caption='Запас лимита';
  if(a.loading){text='Проверка данных';caption='Обновляем лимиты'}
  else if(a.error||a.login_required||a.stale||a.lapsed){text='Нужна проверка';tone='problem';caption='Подробности в меню ⋯'}
  else if(isActive){text='Выбран';tone='active';caption='Сейчас в работе'}
  else if(a.reached||session?.pct>=100||week?.pct>=100){text='Лимит '+(week?.pct>=100?'недели':'сессии');tone='limited';caption='Время сброса указано выше'}
  else if(engine==='codex'&&rotationData?.next===slot){text='Следующий';tone='next';caption='Кандидат для переключения'}
  else if(session?.pct==null&&week?.pct==null){text='Нет данных';caption='Ожидаем данные лимитов'}
  const state=card.querySelector('.fleet-card-state');state.className='fleet-card-state'+(tone?' '+tone:'');putText(state,text);putText(card.querySelector('.fleet-card-caption'),caption);
 }
 function refreshVisuals(snapshot){
  const d=snapshot||((typeof lastSnap!=='undefined'&&lastSnap)||{}),rows=Object.entries(d.accounts||{});
  document.querySelectorAll('#cards > .card').forEach((card,i)=>{if(rows[i])decorateCard(card,rows[i][1],rows[i][0],'claude')});
  putText(ch.querySelector('.fleet-count'),countText(rows.length));
  const current=rows.find(([,a])=>a.active);putText(claudeNote,current?'Сейчас: '+(current[1].label||current[1].name||current[0]):'Активный аккаунт не выбран');
  const accounts=(typeof cxData!=='undefined'&&cxData?.accounts)||[];
  document.querySelectorAll('#cxcards > .card').forEach((card,i)=>{if(accounts[i])decorateCard(card,accounts[i],accounts[i].slot,'codex')});
  putText(xh.querySelector('.fleet-count'),countText(accounts.length));
  const add=document.querySelector('#cx .cxhead .hdrgear');if(add){xh.querySelector('.fleet-add-codex')?.remove();add.classList.add('fleet-add-codex');xh.append(add)}
  refreshCurrentAccounts(d);syncMobileLayout();
 }
 const originalCards=renderCards;renderCards=function(d){originalCards(d);refreshVisuals(d)};
 const previousCodexRender=cxRender;cxRender=function(){previousCodexRender();refreshVisuals()};
 document.addEventListener('click',event=>{if(mobileLayout.matches)return;document.querySelectorAll('.fleet-card-details[open]').forEach(menu=>{if(!menu.contains(event.target))menu.open=false})});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!mobileLayout.matches)document.querySelectorAll('.fleet-card-details[open]').forEach(menu=>menu.open=false)});
 refreshVisuals();

 loadRotation();setInterval(()=>{if(!document.hidden)loadRotation()},5000);
})();
'''


def render(page):
    return page.replace('</head>', '<style id="fleetOverviewStyle">'+CSS+'</style></head>', 1).replace(
        '</body>', '<script id="fleetOverviewScript">'+JS+'</script></body>', 1)
