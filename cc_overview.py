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

/* Выбранный Обзор: полная ширина и более крупные элементы выбора аккаунтов. */
html:root:root:not(.conly) body{width:100%;max-width:none;box-sizing:border-box;margin:0;padding-left:clamp(18px,1.5vw,32px);padding-right:clamp(18px,1.5vw,32px)}
html:root:root .fleet-section .card{min-height:232px;padding:18px!important}
.fleet-section .card .top{min-height:46px;margin-bottom:8px}
.fleet-titleline{flex-wrap:wrap;gap:7px;row-gap:5px}
.fleet-account-name{font-size:16px;font-weight:620}
.fleet-section .card .email{font-size:14px;line-height:1.45;margin-top:4px}
html:root:root .fleet-section .tag.plan,html:root:root .fleet-section .tag.free{font-size:11px;padding:2px 6px}
.fleet-card-state{font-size:12px;line-height:1.4;padding:3px 6px;margin:5px 0 14px}
.fleet-section .card>.row{margin-bottom:13px!important}
.fleet-section .card>.row .lbl{font-size:13px;line-height:1.4;grid-template-columns:minmax(0,1fr) auto 138px;gap:9px;margin-bottom:5px}
.fleet-section .card>.row .lbl b{font-size:14px}
.fleet-section .card>.row .lbl>span:last-child{font-size:12px}
.fleet-card-footer{gap:9px;min-height:34px;padding-top:10px;flex-wrap:wrap}
.fleet-card-caption{font-size:12px;line-height:1.4;flex:1;min-width:0}
.fleet-card-footer .btn-sw{font-size:13px!important;line-height:1.4;min-height:30px;padding:3px 0!important}
.fleet-section-head{gap:12px;margin-bottom:13px}
.fleet-section-head h2{font-size:17px}.fleet-count{font-size:12px}
.fleet-section-head #addAcct,.fleet-section-head .fleet-add-codex{font-size:13px;min-height:34px;height:auto;padding:7px 10px}
.fleet-group-footer,.fleet-group-note,.fleet-rotation-state{font-size:12px;line-height:1.5}
.fleet-group-footer .switchrow::after{font-size:12px}
.fleet-card-details{top:15px;right:15px}
.fleet-card-details summary{width:30px;height:30px;font-size:23px}
.fleet-card-panel{width:360px;min-width:270px;max-width:calc(100vw - 42px);padding:16px}
.fleet-card-panel-title{font-size:14px;line-height:1.45;margin-bottom:12px}
.fleet-card-panel .cxsel select{font-size:14px;min-height:40px;height:auto;padding:8px 10px}
.fleet-card-panel .cxfast{font-size:14px;min-height:32px;gap:7px}
.fleet-card-panel .acts button{font-size:13px;min-height:36px;padding:7px 9px;line-height:1.45}
.fleet-card-panel .iconbtn{width:34px;height:34px}
.fleet-card-panel.fleet-menu-above{bottom:36px}
html:root:root .hdr .cxbtnname{font-size:14px;max-width:190px}
html:root:root .hdr .cxmodn{font-size:14px;max-width:180px}
html:root:root .hdr .cxmode{font-size:12px}
.cxmenu .cxpnm{font-size:17px}.cxmenu .cxprof .cxps{font-size:14px;line-height:1.5;-webkit-line-clamp:4}
.cxmenu .cxprof .cxpf{gap:5px}.cxmenu .cxpf>span{font-size:12px;line-height:1.45}
.cxmenu .cxpinfo{font-size:14px;line-height:1.55}.cxmenu .cxw{font-size:12px}
.fleet-profile-search{font-size:16px;min-height:42px}
#cxbSlot{font-size:16px;min-height:42px}
.fleet-demo-note{font-size:12px;line-height:1.55;background:var(--fleet-accent-soft);color:var(--txt);border:1px solid var(--fleet-line);border-radius:8px;padding:10px 12px;margin-bottom:16px}
@media(max-width:1150px){.fleet-section .card>.row .lbl{grid-template-columns:minmax(0,1fr) auto 120px}.hdr .cxbtnname{max-width:155px!important}}
@media(max-width:700px){
 html:root:root:not(.conly) body{padding-left:12px;padding-right:12px}
 .fleet-section-head{gap:8px}.fleet-section-head h2{font-size:16px}.fleet-count{font-size:11px}
 html:root:root .fleet-section .card{padding:16px!important;min-height:250px}
 .fleet-section .card .top{padding-right:25px}.fleet-section .card .email{font-size:14px}
 .fleet-section .card>.row .lbl{grid-template-columns:minmax(0,1fr) auto;gap:3px 9px;font-size:13px}
 .fleet-section .card>.row .lbl>span:last-child{grid-column:1/-1;white-space:normal;text-align:left;overflow:visible;text-overflow:clip;font-size:12px}
 .fleet-card-panel{width:330px;max-width:calc(100vw - 48px);min-width:250px;padding:14px}
 .fleet-card-panel .cxsel select{font-size:16px;min-height:44px}
 .fleet-card-panel .acts button{font-size:13px;min-height:42px}
 .fleet-card-footer .btn-sw{font-size:13px!important;min-height:36px;max-width:100%;white-space:normal;text-align:right}
 .fleet-group-footer{gap:7px}.fleet-group-note{font-size:12px;max-width:100%}.fleet-rotation-state{font-size:12px;max-width:100%}
 .fleet-card-details summary{width:34px;height:34px}.hdr .cxbtnname{font-size:13px!important;max-width:160px!important}.hdr .cxmodn{font-size:13px!important}
}

/* Состояние паузы: короткая строка с таймером, подробности — по раскрытию. */
#ccPause:not([hidden]):has(>.fleet-pause-fold){display:block;padding:0;overflow:visible}
.fleet-pause-fold{width:100%;min-width:0}
.fleet-pause-summary{display:grid;grid-template-columns:8px minmax(0,1fr) auto 16px;column-gap:11px;align-items:center;min-height:48px;padding:10px 14px;list-style:none;cursor:pointer;border-radius:10px;color:var(--txt);user-select:none;-webkit-tap-highlight-color:transparent}
.fleet-pause-summary::-webkit-details-marker{display:none}
.fleet-pause-summary::marker{content:""}
.fleet-pause-summary:focus-visible{outline:2px solid var(--ccp-accent);outline-offset:3px}
.fleet-pause-summary .ccp-dot{width:8px;height:8px;margin:0}
.fleet-pause-summary .ccp-title{font-size:14px;font-weight:600;line-height:1.45;letter-spacing:0;min-width:0}
.fleet-pause-summary .ccp-timer{display:flex;align-items:baseline;gap:7px;text-align:right;margin:0;white-space:nowrap}
.fleet-pause-summary .ccp-timer .t{font-size:14px;line-height:1.45;font-weight:650}
.fleet-pause-summary .ccp-timer .l{font-size:11px;line-height:1.45;margin:0;color:var(--mut)}
.fleet-pause-chevron{grid-column:4;display:block;width:16px;height:16px;color:var(--mut);transition:transform .15s}
.fleet-pause-fold[open] .fleet-pause-chevron{transform:rotate(180deg)}
.fleet-pause-content{padding:0 14px 14px 33px}
.fleet-pause-content .ccp-body{min-width:0}
.fleet-pause-content .ccp-sub{margin-top:0;font-size:13px;line-height:1.5}
.fleet-pause-content .ccp-actions{margin-top:12px}
.fleet-pause-content .ccp-btn{min-height:34px}
@media(max-width:640px){
 .fleet-pause-summary{grid-template-columns:8px minmax(0,1fr) 16px;gap:3px 10px;padding:10px 12px;min-height:48px}
 .fleet-pause-summary .ccp-dot{grid-column:1;grid-row:1;align-self:start;margin-top:6px}
 .fleet-pause-summary .ccp-title{grid-column:2;grid-row:1;font-size:13px;white-space:normal;overflow-wrap:anywhere}
 .fleet-pause-summary .ccp-timer{grid-column:2;grid-row:2;justify-content:flex-start;flex-wrap:wrap;white-space:normal;text-align:left;gap:5px}
 .fleet-pause-summary .ccp-timer .t{font-size:13px}
 .fleet-pause-summary .ccp-timer .l{font-size:11px}
 .fleet-pause-chevron{grid-column:3;grid-row:1/span 2;align-self:center}
 .fleet-pause-content{padding:4px 12px 14px 30px}
 .fleet-pause-content .ccp-sub{font-size:13px;overflow-wrap:anywhere}
 .fleet-pause-content .ccp-chip{white-space:normal;font-size:12px}
 .fleet-pause-content .ccp-btn{min-height:40px;font-size:13px}
 .fleet-pause-content .ccp-hint{font-size:12px;line-height:1.5}
}
@media(prefers-reduced-motion:reduce){.fleet-pause-chevron{transition:none}}

/* Главное на первом экране; исходные настройки доступны в меню управления. */
html:not(.conly) .hdr{margin-bottom:14px!important}
.hdr #cxLim{display:none!important}
.hdr .hdrbtns:empty{display:none!important}
.fleet-preview{margin-bottom:12px}
.fleet-active-strip{position:relative;margin:0 0 12px;min-width:0}
.fleet-live-head{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:26px;margin-bottom:6px}
.fleet-live-label{font-size:10px;font-weight:500;letter-spacing:.025em;color:var(--fleet-muted)}
.fleet-live-rows{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.fleet-live-account{display:grid;grid-template-columns:minmax(0,1fr) 104px 104px;gap:18px;align-items:center;min-width:0;min-height:60px;padding:10px 14px;border:1px solid var(--fleet-line);border-radius:9px;color:var(--txt);text-decoration:none;background:var(--card);--live-accent:var(--fleet-claude);-webkit-tap-highlight-color:transparent}
.fleet-live-account.codex{--live-accent:var(--fleet-accent)}
.fleet-live-account:hover{border-color:var(--live-accent)}
.fleet-live-account:focus-visible{outline:2px solid var(--live-accent);outline-offset:2px}
.fleet-live-identity{min-width:0}
.fleet-live-name{display:block;font-size:14px;font-weight:600;line-height:1.45;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fleet-live-name::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--live-accent);margin-right:7px;vertical-align:2px}
.fleet-live-email{display:block;font-size:11px;color:var(--fleet-muted);line-height:1.6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fleet-live-account[data-state="warning"] .fleet-live-email{color:var(--warn)}
.fleet-live-meter{min-width:0}
.fleet-live-meter-label{display:flex;align-items:baseline;justify-content:space-between;gap:6px;font-size:11px;color:var(--fleet-muted);white-space:nowrap}
.fleet-live-meter-label b{font-size:14px;font-weight:600;color:var(--txt);font-variant-numeric:tabular-nums}
.fleet-live-track{display:block;height:3px;border-radius:3px;background:var(--fleet-line);margin-top:6px;overflow:hidden}
.fleet-live-fill{display:block;height:100%;background:var(--live-accent);border-radius:3px}
.fleet-live-meter[data-tone="warn"] .fleet-live-fill{background:var(--warn)}
.fleet-live-meter[data-tone="bad"] .fleet-live-fill{background:var(--bad)}
.fleet-tools{position:relative;flex:none;z-index:38}
.fleet-tools>summary{display:flex;align-items:center;gap:7px;list-style:none;padding:4px 7px;margin:0;border-radius:5px;color:var(--fleet-muted);font-size:11px;line-height:1.5;cursor:pointer;-webkit-tap-highlight-color:transparent}
.fleet-tools>summary::-webkit-details-marker{display:none}
.fleet-tools>summary::after{content:"⌄";font-size:13px;line-height:1}
.fleet-tools[open]>summary,.fleet-tools>summary:hover{background:var(--card);color:var(--txt)}
.fleet-tools>summary:focus-visible{outline:2px solid var(--fleet-accent);outline-offset:2px}
.fleet-tools-panel{position:absolute;right:0;top:calc(100% + 5px);width:410px;max-width:calc(100vw - 24px);max-height:min(620px,calc(100dvh - 180px));overflow:auto;padding:16px;background:var(--card);border:1px solid var(--fleet-line);border-radius:11px;box-shadow:0 18px 45px #0007;color:var(--txt)}
.fleet-tools-block+.fleet-tools-block{border-top:1px solid var(--fleet-line);padding-top:14px;margin-top:14px}
.fleet-tools-label{display:block;font-size:11px;font-weight:500;color:var(--fleet-muted);margin-bottom:10px}
.fleet-tools-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.fleet-tools-panel .hdrgear{width:auto;min-height:34px;margin:0;padding:7px 9px;border:1px solid var(--fleet-line);border-radius:6px;background:transparent;color:var(--txt);display:inline-flex;gap:7px;align-items:center;font-size:12px;max-width:100%}
.fleet-tools-panel [hidden]{display:none!important}
.fleet-tools-panel .hdrgear svg{flex:none;width:15px;height:15px}
.fleet-tools-panel #cxGear::after{content:"Настройки Codex"}
.fleet-tools-panel #rfBtn::after{content:"Обновить данные"}
.fleet-tools-panel #gear::after{content:"Общие настройки"}
.fleet-tools-panel .toolrow{display:flex;flex-wrap:wrap;gap:8px;margin:0!important;padding:0!important;min-height:0;border:0}
.fleet-tools-panel .fleet-model-label{display:none}
.fleet-tools-panel #mrow{display:flex;flex-wrap:wrap;gap:5px;max-width:100%;min-width:0;flex-basis:100%}
.fleet-tools-panel .efrow{flex-wrap:wrap;max-width:100%}
.fleet-tools-panel .cxmodbtn{flex:1 1 auto;border-radius:6px;min-width:0}
.fleet-tools-panel .cxmodn{font-size:13px;overflow:hidden;text-overflow:ellipsis}
html.conly .fleet-active-strip{display:none!important}
/* Одна тонкая строка; исходный текст целиком доступен внутри. */
#ccPause:not([hidden]):has(>.fleet-pause-fold){margin-bottom:8px}
.fleet-pause-summary{grid-template-columns:6px minmax(0,1fr) auto 12px;gap:9px;min-height:30px;padding:5px 11px;border-radius:7px}
.fleet-pause-summary .ccp-dot{width:6px;height:6px;grid-column:1;grid-row:1;align-self:center;margin:0}
.fleet-pause-summary .ccp-title{grid-column:2;grid-row:1;font-size:12px;font-weight:500;line-height:1.5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fleet-pause-summary .ccp-timer{grid-column:3;grid-row:1;justify-content:flex-end;gap:6px;flex-wrap:nowrap;white-space:nowrap;line-height:1.5}
.fleet-pause-summary .ccp-timer .t{font-size:12px;line-height:1.5}
.fleet-pause-summary .ccp-timer .l{font-size:10px;line-height:1.5}
.fleet-pause-chevron{grid-column:4;grid-row:1;width:12px;height:12px}
.fleet-pause-content .ccp-title{font-size:13px;font-weight:600;margin-bottom:7px}
@media(min-width:1100px) and (min-height:700px){html:not(.conly) #termBox{height:clamp(340px,calc(100dvh - 430px),640px)!important;min-height:340px!important}}
@media(max-width:1100px){.fleet-live-account{grid-template-columns:minmax(0,1fr) 78px 78px;gap:12px}.fleet-live-name{font-size:13px}}
@media(max-width:740px){.fleet-live-rows{grid-template-columns:minmax(0,1fr);gap:7px}.fleet-live-account{grid-template-columns:minmax(0,1fr) 78px 78px;min-height:54px;padding:8px 11px}.fleet-live-head{gap:7px}.fleet-live-label{font-size:10px}.fleet-tools>summary{font-size:11px;padding-right:3px}.fleet-pause-summary{padding:5px 9px;gap:7px}.fleet-pause-summary .ccp-timer .l{display:none}.fleet-pause-content{padding-left:24px}.fleet-tools-panel{max-height:calc(100dvh - 240px)}}
@media(max-width:380px){.fleet-live-account{grid-template-columns:minmax(0,1fr) 62px 62px;gap:9px}.fleet-live-name{font-size:12px}.fleet-live-email{font-size:10px}.fleet-live-meter-label{font-size:10px}.fleet-live-meter-label b{font-size:12px}.fleet-live-label{max-width:180px;line-height:1.4}}

/* Резерв остаётся на главной; управление относится к своей плитке провайдера. */
html:root:root:not(.conly) .hdr{gap:14px!important}
html:root:root:not(.conly) .hdr>.hdrl{order:0;flex:1;min-width:0}
html:root:root:not(.conly) .hdr>.hdrctl{order:1;flex:0 1 auto!important;flex-basis:auto!important;gap:12px!important;min-width:0}
html:root:root:not(.conly) .hdr>.hdrbtns{order:2;flex:none;margin:0;gap:7px!important}
.hdr #fleetGeneralGear,.hdr #rfBtn{width:32px;height:32px;padding:7px;border:1px solid var(--fleet-line);border-radius:7px;background:transparent;color:var(--fleet-muted)}
.hdr #fleetGeneralGear svg,.hdr #rfBtn svg{width:16px;height:16px}
.hdr #ntGrp{flex:none;margin:0;border:1px solid var(--fleet-line);border-radius:7px;overflow:hidden;background:transparent;box-shadow:none}
.hdr #ntGrp.res{border-color:var(--fleet-accent);background:var(--fleet-accent-soft)}
.hdr #ntGrp .hdrgear{height:32px;min-height:0;border:0;border-radius:0;background:transparent;box-shadow:none;margin:0;font-size:12px}
.hdr #ntInd{width:29px;padding:6px;gap:3px}.hdr #ntInd svg{width:15px;height:15px}.hdr #ntInd .cxdot{width:5px;height:5px}
.hdr #ntBtn{padding:6px 7px;gap:7px}.hdr #ntGear{width:29px;padding:7px;border-left:1px solid var(--fleet-line)!important}.hdr #ntGear svg{width:15px;height:15px}
.fleet-live-head{min-height:18px;margin-bottom:6px}
.fleet-live-account{grid-template-columns:minmax(100px,1fr) minmax(175px,210px) 90px 90px;grid-template-areas:"identity controls session week";gap:14px;cursor:default}
.fleet-live-identity{grid-area:identity;display:block;color:inherit;text-decoration:none;min-width:0;border-radius:4px}
.fleet-live-identity:focus-visible{outline:2px solid var(--live-accent);outline-offset:3px}
.fleet-live-identity:hover .fleet-live-name{color:var(--live-accent)}
.fleet-live-meter[data-window="session"]{grid-area:session}.fleet-live-meter[data-window="week"]{grid-area:week}
.fleet-provider-controls{grid-area:controls;display:flex;align-items:center;gap:6px;min-width:0}
.fleet-provider-controls .hdrgear{height:34px;min-height:0;max-height:34px;margin:0;box-shadow:none;background:var(--bg);border:1px solid var(--fleet-line);border-radius:7px;color:var(--txt);font-size:12px;display:flex;align-items:center;gap:6px;padding:7px 9px;-webkit-tap-highlight-color:transparent}
.fleet-provider-controls .hdrgear:hover{border-color:var(--fleet-muted)}
.fleet-provider-controls .hdrgear:focus-visible{outline:2px solid var(--live-accent);outline-offset:2px}
.fleet-provider-controls .hdrgear svg{width:14px;height:14px;flex:none}
.fleet-provider-controls .fleet-model-tile{flex:1;min-width:0;width:auto;max-width:100%;font-weight:550}
.fleet-provider-controls .fleet-model-tile::after{content:"⌄";color:var(--fleet-muted);margin-left:auto;font-size:12px;line-height:1;flex:none}
.fleet-provider-controls .cxmodn{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;min-width:0}
.fleet-provider-controls .cxmode{font-size:11px;font-weight:500;color:var(--live-accent);flex:none}
.fleet-provider-controls .fleet-provider-gear{width:34px;flex:none;padding:9px;justify-content:center}
.fleet-native-controls[hidden]{display:none!important}
/* Быстрый выбор и полные настройки используют общую геометрию и компоненты. */
.fleet-quick-panel{box-sizing:border-box;border:1px solid var(--fleet-line);border-radius:11px;background:var(--card);color:var(--txt);box-shadow:0 18px 50px #0006;z-index:52;overflow:hidden}
.fleet-quick-panel .cxpbody{padding:6px 14px 14px}
.fleet-quick-panel .cxqh{font-size:12px;font-weight:500;color:var(--fleet-muted);margin:13px 0 9px}
.fleet-quick-panel .cxqlist{display:grid;gap:6px}
.fleet-quick-panel .cxqm{width:100%;display:flex;align-items:center;gap:9px;padding:10px 12px;font-size:13px;border:1px solid var(--fleet-line);border-radius:7px;background:transparent;color:var(--txt);text-align:left;margin:0;box-shadow:none}
.fleet-quick-panel .cxqm.on{border-color:var(--fleet-accent);background:var(--fleet-accent-soft)}
.fleet-quick-panel .cxqm .cxqr{width:13px;height:13px;border-radius:50%;border:1px solid var(--fleet-muted);flex:none}
.fleet-quick-panel .cxqm.on .cxqr{border:4px solid var(--fleet-accent);background:var(--bg)}
.fleet-quick-panel .cxqeff{display:flex;gap:6px;flex-wrap:wrap}
.fleet-quick-panel .cxqe{margin:0;padding:7px 10px;font-size:12px;border:1px solid var(--fleet-line);border-radius:6px;color:var(--fleet-muted);background:transparent;box-shadow:none}
.fleet-quick-panel .cxqe.on{border-color:var(--fleet-accent);background:var(--fleet-accent-soft);color:var(--txt)}
.fleet-quick-panel button:focus-visible{outline:2px solid var(--fleet-accent);outline-offset:2px}
.fleet-settings-backdrop{position:fixed;inset:0;background:#06080c99;z-index:50}
.fleet-settings-backdrop[hidden]{display:none}
#scrim.fleet-settings-scrim{background:#06080c99;z-index:50}
.fleet-settings-panel{box-sizing:border-box;position:fixed;display:flex;flex-direction:column;width:min(580px,calc(100vw - 24px));max-width:calc(100vw - 24px);margin:0;padding:0;border:1px solid var(--fleet-line);border-radius:12px;background:var(--card);color:var(--txt);box-shadow:0 20px 60px #0006;overflow:hidden;z-index:51}
.fleet-settings-panel[hidden]{display:none}
.fleet-settings-panel .cxphead{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--fleet-line);min-height:58px;flex:none}
.fleet-settings-panel .cxphead h3,.fleet-settings-panel .cxphead b{font-size:15px;line-height:1.4;font-weight:600;margin:0;color:var(--txt)}
.fleet-settings-panel .cxphead h3{flex:1}
#cxPopTitle::before{content:"Настройки "}
.fleet-settings-panel .cxphead .hdrgear{display:grid;place-items:center;width:30px;height:30px;padding:7px;margin:0;border:1px solid var(--fleet-line);border-radius:6px;background:transparent;color:var(--fleet-muted);box-shadow:none;flex:none}
.fleet-settings-panel .cxphead .hdrgear svg{width:14px;height:14px}
.fleet-settings-panel>.cxpbody{padding:16px;overflow:auto;min-height:0;overscroll-behavior:contain}
.fleet-settings-group,.fleet-settings-panel .cxacc{border:1px solid var(--fleet-line);border-radius:9px;background:transparent;padding:14px;margin:0 0 12px}
.fleet-settings-panel .modalh,.fleet-settings-group-title{display:block;margin:0 0 12px;font-size:12px;font-weight:550;color:var(--txt);line-height:1.5;text-transform:none;letter-spacing:0}
.fleet-settings-panel .modalsub,.fleet-settings-panel .cxsub{font-size:12px;line-height:1.55;color:var(--fleet-muted)}
.fleet-settings-panel .cxacch{padding:0;margin:0;min-height:28px;font-size:12px;font-weight:550;color:var(--txt);background:transparent;box-shadow:none;border:0;border-radius:0;width:100%}
.fleet-settings-panel .cxsec:not([hidden]){margin-top:12px}
.fleet-settings-panel button:not(.cxacch):not(.skopt){box-shadow:none;font-size:12px;font-weight:500;border-radius:6px;padding:8px 10px;border:1px solid var(--fleet-line);background:transparent;color:var(--txt);line-height:1.4}
.fleet-settings-panel button.btn-del:not(.cxacch):not(.skopt){color:var(--bad);border-color:color-mix(in srgb,var(--bad),var(--fleet-line) 60%)}
.fleet-settings-panel button:disabled{opacity:.5}
.fleet-settings-panel input:not([type="checkbox"]),.fleet-settings-panel select{font-size:13px;border:1px solid var(--fleet-line);border-radius:6px;background:var(--bg);color:var(--txt);min-height:34px;padding:7px 9px}
.fleet-settings-panel input[type="checkbox"]{accent-color:var(--fleet-accent)}
.fleet-settings-panel .fleet-cx-options>.modalh{display:none}
.fleet-settings-panel .fleet-cx-options{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.fleet-settings-panel .fleet-cx-options label{display:flex;align-items:center;gap:7px;font-size:12px;margin:0}
.fleet-settings-panel .fleet-cx-options input{width:68px}
.fleet-settings-panel .fleet-cx-options button{flex-basis:100%;margin:0}
.fleet-settings-panel .modalfoot{gap:8px;margin-top:12px;display:flex;justify-content:flex-end}
.fleet-settings-panel #modalDone{margin:0!important}
.fleet-common-settings>summary{list-style:none;cursor:pointer;font-size:12px;font-weight:550;padding:12px 2px;margin:0;color:var(--fleet-muted)}
.fleet-common-settings>summary::-webkit-details-marker{display:none}
.fleet-common-settings>summary::after{content:"⌄";margin-left:8px}
#scrim[data-view="general"] .fleet-claude-group,#scrim[data-view="general"] .fleet-common-settings>summary{display:none}
#scrim[data-view="general"] .fleet-common-settings{display:contents}
@media(max-width:1250px){.fleet-live-account{grid-template-columns:minmax(90px,1fr) minmax(145px,190px) 72px 72px;gap:10px;padding-left:11px;padding-right:11px}}
@media(max-width:1000px){.fleet-live-rows{grid-template-columns:minmax(0,1fr)}.fleet-live-account{grid-template-columns:minmax(100px,1fr) minmax(175px,210px) 90px 90px}}
@media(max-width:640px){
 html:root:root:not(.conly) .hdr>.hdrctl{order:3;flex:1 1 100%!important;flex-basis:100%!important;width:100%;gap:6px!important;justify-content:space-between!important}
 html:root:root:not(.conly) .hdr>.hdrbtns{order:2}
 .hdr .cxgrp{flex:1;min-width:0;max-width:calc(100% - 160px)}.hdr .cxbtn{max-width:100%;min-width:0;padding-left:2px;padding-right:2px;gap:4px}
 .hdr .cxbtnname{min-width:0;max-width:100%!important;font-size:12px!important;overflow:hidden;text-overflow:ellipsis}
 .hdr #ntGrp{max-width:156px}.hdr #ntBtn{font-size:11px;gap:6px;padding:6px}
 .hdr #ntInd{width:25px}.hdr #ntGear{width:27px}.hdr #fleetGeneralGear,.hdr #rfBtn{width:29px;height:29px;padding:6px}
 .fleet-live-account{grid-template-columns:minmax(0,1fr) 72px 72px;grid-template-areas:"identity session week" "controls session week";gap:4px 12px;min-height:70px;padding:8px 11px}
 .fleet-live-email{display:none}.fleet-live-name{font-size:13px;line-height:1.3}
 .fleet-provider-controls{gap:5px;max-width:230px}
 .fleet-provider-controls .hdrgear{height:27px;max-height:27px;padding:5px 7px;border-radius:5px;gap:4px}
 .fleet-provider-controls .hdrgear svg{width:12px;height:12px}.fleet-provider-controls .fleet-provider-gear{width:27px;padding:7px}
 .fleet-provider-controls .cxmodn{font-size:11px}.fleet-provider-controls .cxmode{font-size:10px}
 .fleet-settings-panel .cxphead{padding:12px;min-height:52px}.fleet-settings-panel>.cxpbody{padding:12px}
}
@media(max-width:380px){.fleet-live-account{grid-template-columns:minmax(0,1fr) 60px 60px;gap:4px 9px}.fleet-live-name{font-size:12px}.fleet-provider-controls .fleet-model-tile>svg{display:none}.fleet-provider-controls .hdrgear{padding-left:6px;padding-right:6px}.fleet-provider-controls .cxmode{font-size:10px}}

/* Панель профилей в том же наборе компонентов, что и меню провайдеров. */
html:root:root #cxMenu.fleet-profile-palette{box-sizing:border-box;position:fixed;display:flex;flex-direction:column;width:min(940px,calc(100vw - 24px));height:auto;bottom:auto;max-width:calc(100vw - 24px);max-height:calc(100dvh - 100px);border:1px solid var(--fleet-line);border-radius:12px;background:var(--card);color:var(--txt);box-shadow:0 20px 60px #0006;z-index:55;overflow:hidden;animation:none}
html:root:root #cxMenu.fleet-profile-palette[hidden]{display:none}
html:root:root #cxMenuScrim.fleet-profile-backdrop:not([hidden]){display:block!important;z-index:54;background:#06080c99}
.fleet-palette-header{display:flex;align-items:center;gap:14px;padding:16px 18px;border-bottom:1px solid var(--fleet-line);flex:none;min-height:76px}
.fleet-palette-heading{flex:1;min-width:0}.fleet-palette-heading h2{font-size:19px;font-weight:600;letter-spacing:-.3px;margin:5px 0 0;line-height:1.3}
.fleet-palette-heading .fleet-eyebrow{font-size:9px;letter-spacing:.12em;color:var(--fleet-muted)}
.fleet-palette-current{display:flex;align-items:center;gap:7px;min-width:0;max-width:50%;font-size:12px;color:var(--fleet-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fleet-palette-current::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--fleet-accent);flex:none}
.fleet-palette-header .fleet-palette-close{display:grid;place-items:center;width:30px;height:30px;padding:7px;margin:0;border:1px solid var(--fleet-line);border-radius:6px;background:transparent;box-shadow:none;color:var(--fleet-muted);flex:none}
.fleet-palette-close svg{width:14px;height:14px}
.fleet-palette-tools{display:flex;align-items:center;gap:10px;padding:14px 18px;flex:none}
.fleet-palette-search{position:relative;display:block;min-width:0;flex:1}
.fleet-palette-search::before{content:"⌕";position:absolute;left:12px;top:9px;font-size:21px;line-height:1;color:var(--fleet-muted);pointer-events:none}
#cxMenu .fleet-profile-search{box-sizing:border-box;width:100%;margin:0;padding:10px 12px 10px 36px;min-height:40px;height:40px;font-size:14px;background:var(--bg);border:1px solid var(--fleet-line);border-radius:7px;box-shadow:none}
#cxMenu .fleet-profile-search:focus-visible{outline:2px solid var(--fleet-accent);outline-offset:1px}
.fleet-palette-tools .fleet-profile-compare{display:flex;align-items:center;justify-content:center;gap:7px;min-height:40px;margin:0;padding:9px 12px;font-size:12px;font-weight:500;border:1px solid var(--fleet-line);border-radius:7px;background:transparent;color:var(--txt);box-shadow:none;flex:none}
.fleet-profile-compare::before{content:"▥";font-size:16px;color:var(--fleet-muted)}
.fleet-palette-tools .fleet-profile-compare[aria-pressed="true"]{background:var(--fleet-accent-soft);border-color:var(--fleet-accent)}
#cxMenu.fleet-profile-palette>.cxpbody{padding:0 18px 18px;min-height:0;overflow:auto;overscroll-behavior:contain}
#cxMenu.fleet-profile-palette #cxp{gap:12px}
#cxMenu.fleet-profile-palette #cxp>.cxhead{display:none}
#cxMenu.fleet-profile-palette .cxplist{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:stretch}
#cxMenu.fleet-profile-palette .fleet-profile-card{box-sizing:border-box;position:relative;display:flex;flex-direction:column;align-items:stretch;gap:0;min-width:0;min-height:250px;margin:0;padding:15px;border:1px solid var(--fleet-line);border-radius:10px;box-shadow:none;background:var(--bg);color:var(--txt);cursor:pointer;text-align:left}
#cxMenu .fleet-profile-card::before,#cxMenu .fleet-profile-card.act .cxpn::after{display:none}
#cxMenu .fleet-profile-card:hover{border-color:var(--fleet-muted)}
#cxMenu .fleet-profile-card.act{border-color:var(--fleet-accent);background:linear-gradient(140deg,var(--fleet-accent-soft),var(--bg) 74%)}
#cxMenu .fleet-profile-card:focus-visible{outline:2px solid var(--fleet-accent);outline-offset:2px}
.fleet-profile-card-head{display:flex;align-items:center;gap:8px;min-height:34px;margin-bottom:14px}
#cxMenu .fleet-profile-card .cxpr{display:grid;place-items:center;position:static;width:32px;height:32px;border:1px solid var(--fleet-line);border-radius:8px;margin:0;background:var(--card);color:var(--fleet-accent);font:600 15px/1 ui-monospace,monospace;flex:none}
#cxMenu .fleet-profile-card .cxpr::after{display:none}#cxMenu .fleet-profile-card .cxpr::before{content:"›_"}
#cxMenu .fleet-profile-card[data-kind="team"] .cxpr{color:var(--fleet-claude)}#cxMenu .fleet-profile-card[data-kind="team"] .cxpr::before{content:"⇄"}
.fleet-profile-status{margin-left:auto;font-size:10px;color:var(--fleet-muted);line-height:1.4}
.fleet-profile-card.act .fleet-profile-status{color:var(--fleet-accent)}.fleet-profile-card.act .fleet-profile-status::before{content:"✓ ";font-size:12px}
#cxMenu .fleet-profile-card .cxpx{position:static;margin:0;padding:3px 5px;min-width:22px;min-height:22px;line-height:1;font-size:17px;background:none;border:0;border-radius:4px;color:var(--fleet-muted)}
#cxMenu .fleet-profile-card .cxpt{display:flex;flex-direction:column;flex:1;min-width:0}
#cxMenu .fleet-profile-card .cxpn{display:block;min-width:0;margin:0 0 10px;padding:0;line-height:1.35}
#cxMenu .fleet-profile-card .cxpnm{font-size:17px;font-weight:600;text-transform:none;letter-spacing:-.2px;line-height:1.35}
#cxMenu .fleet-profile-card .cxps{display:block;margin:0;overflow:visible;font-size:13px;font-weight:400;line-height:1.6;color:var(--fleet-muted);-webkit-line-clamp:unset}
.fleet-profile-meta{display:flex;flex-wrap:wrap;gap:5px;margin:13px 0 0;font-size:10px;line-height:1.4;color:var(--fleet-muted)}
.fleet-profile-meta>span:not(.cxroute){padding:4px 6px;border:1px solid var(--fleet-line);border-radius:5px;background:var(--card)}
#cxMenu .fleet-profile-meta>.cxroute{display:none}
#cxMenu .fleet-profile-card:not([data-info-open="true"]) .cxpf{display:none}
#cxMenu .fleet-profile-card[data-info-open="true"] .cxpf{display:flex;flex-wrap:wrap;gap:5px;margin-top:12px;font-size:11px;line-height:1.5}
#cxMenu .fleet-profile-card .cxpf>span{font-size:11px;padding:2px 0;color:var(--fleet-muted);background:none;border:0}
#cxMenu .fleet-profile-card .cxpf i{display:none}
#cxMenu .fleet-profile-card .cxpinfo{display:block;font-size:12px;line-height:1.6;padding:12px 0 0;margin:12px 0 0;border:0;border-top:1px solid var(--fleet-line);background:transparent;border-radius:0}
#cxMenu .fleet-profile-card .cxpinfo .cxpirow{font-size:12px;line-height:1.55}
#cxMenu .fleet-profile-card .cxw{font-size:10px;line-height:1.5;border-radius:4px;padding:1px 5px}
.fleet-profile-original{display:block;color:var(--fleet-muted);font-size:12px;line-height:1.6;margin-bottom:12px}
.fleet-profile-card-footer{display:flex;align-items:center;justify-content:space-between;gap:7px;border-top:1px solid var(--fleet-line);padding-top:11px;margin-top:16px;min-height:30px}
.fleet-profile-choose{font-size:11px;color:var(--fleet-accent);font-weight:500}
#cxMenu .fleet-profile-card .fleet-profile-more{display:flex;align-items:center;justify-content:center;gap:4px;width:auto;height:28px;min-height:28px;margin:0;padding:5px 6px;border:1px solid var(--fleet-line);border-radius:5px;background:transparent;color:var(--fleet-muted);box-shadow:none;font-size:11px;font-weight:500;line-height:1}
#cxMenu .fleet-profile-more svg{width:12px;height:12px}
#cxMenu .fleet-profile-service{grid-column:1/-1;display:grid;grid-template-columns:0 minmax(0,1fr) auto;align-items:center;gap:0 10px;margin:0;padding:12px 14px;min-height:64px;border:1px solid var(--fleet-line);border-radius:9px;background:transparent;box-shadow:none;cursor:default}
#cxMenu .fleet-profile-service::before,#cxMenu .fleet-profile-service .cxpr{display:none}
#cxMenu .fleet-profile-service .cxpt{grid-column:2;min-width:0}.fleet-profile-auto{grid-column:3;font-size:10px;color:var(--fleet-muted);padding:4px 7px;border:1px solid var(--fleet-line);border-radius:5px}
#cxMenu .fleet-profile-service .cxpnm{font-size:13px;text-transform:none;letter-spacing:0}#cxMenu .fleet-profile-service .cxroute{display:none}
#cxMenu .fleet-profile-service .cxps{font-size:11px;line-height:1.5;-webkit-line-clamp:2;margin-top:3px}
#cxMenu .cxemg{border:1px solid color-mix(in srgb,var(--bad),var(--fleet-line) 55%);border-radius:9px;background:transparent;padding:13px;margin:0}
#cxMenu .cxemg::before{display:none}#cxMenu .cxemg .cxpnm{font-size:13px;text-transform:none;letter-spacing:0}#cxMenu .cxemg .cxes{font-size:12px;line-height:1.5}
.fleet-palette-footer{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:13px 18px;border-top:1px solid var(--fleet-line);flex:none;font-size:11px;line-height:1.5;color:var(--fleet-muted)}
.fleet-palette-help{color:var(--fleet-faint)}
.fleet-profile-empty{display:grid;place-items:center;gap:10px;text-align:center;min-height:180px;color:var(--fleet-muted);font-size:13px;padding:24px}
.fleet-profile-empty strong{font-size:16px;font-weight:550;color:var(--txt)}.fleet-profile-empty button{font-size:12px;padding:8px 11px;background:transparent;border:1px solid var(--fleet-line);border-radius:6px;color:var(--txt);margin:0}
.fleet-profile-empty[hidden],.fleet-profile-index[hidden]{display:none!important}
@keyframes fleetPaletteIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
@media(max-width:900px){#cxMenu.fleet-profile-palette .cxplist{grid-template-columns:repeat(2,minmax(0,1fr))}.fleet-palette-current{font-size:11px}}
@media(max-width:600px){
 .fleet-palette-header{padding:13px 12px;gap:9px;min-height:62px;flex-wrap:wrap}.fleet-palette-heading h2{font-size:17px;margin-top:4px}.fleet-palette-heading .fleet-eyebrow{font-size:8px}.fleet-palette-current{font-size:10px;max-width:46%;line-height:1.5;white-space:normal}.fleet-palette-current::before{display:none}
 .fleet-palette-tools{padding:12px;gap:7px}#cxMenu .fleet-profile-search{font-size:16px;padding-right:8px;min-height:40px}.fleet-palette-tools .fleet-profile-compare{padding:8px;font-size:11px}.fleet-profile-compare::before{display:none}
 #cxMenu.fleet-profile-palette>.cxpbody{padding:0 12px 12px}#cxMenu.fleet-profile-palette .cxplist{grid-template-columns:minmax(0,1fr);gap:9px}
 #cxMenu.fleet-profile-palette .fleet-profile-card{padding:12px;min-height:0}.fleet-profile-card-head{margin-bottom:8px;min-height:27px}#cxMenu .fleet-profile-card .cxpr{width:27px;height:27px;font-size:14px;border-radius:6px}
 #cxMenu .fleet-profile-card .cxpnm{font-size:16px}#cxMenu .fleet-profile-card .cxpn{margin-bottom:7px}#cxMenu .fleet-profile-card .cxps{font-size:12px;line-height:1.55}.fleet-profile-meta{margin-top:10px;font-size:10px}.fleet-profile-card-footer{margin-top:11px;padding-top:9px}
 .fleet-palette-footer{padding:11px 12px;font-size:10px}.fleet-palette-help{max-width:52%;text-align:right;font-size:9px}
 #cxMenu .fleet-profile-service{padding:11px;grid-template-columns:minmax(0,1fr) auto;gap:8px}#cxMenu .fleet-profile-service .cxpt{grid-column:1}.fleet-profile-auto{grid-column:2;font-size:9px;padding:4px 5px}
}
@media(prefers-reduced-motion:reduce){html:root:root #cxMenu.fleet-profile-palette{animation:none}}

#cxMenu .fleet-profile-more[hidden],#cxMenu[data-compare="true"] .fleet-profile-card .cxpf,#cxMenu[data-compare="true"] .fleet-profile-original{display:none!important}
@media(max-width:640px){html:root:root #cxMenu.fleet-profile-palette{left:12px!important;right:auto!important}}
@media(max-width:600px){
 #cxMenu .fleet-profile-card-head{position:absolute;left:12px;right:12px;top:12px;margin:0;min-height:27px}
 #cxMenu .fleet-profile-card .cxpn{min-height:27px;margin-left:36px;padding-right:54px;display:flex;align-items:center}
 #cxMenu .fleet-profile-card .cxpnm{font-size:15px}
 #cxMenu .fleet-profile-card .cxps{margin-top:3px}
}

.fleet-profile-service-heading{grid-column:1/-1;font-size:11px;font-weight:550;color:var(--fleet-muted);margin-top:2px}
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
 document.body.classList.add('fleet-reference','fleet-wide');
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
   details.append(summary,panel);details.open=!!openAccountMenus.get(key);details.addEventListener('toggle',()=>{openAccountMenus.set(key,details.open);if(details.open){panel.classList.remove('fleet-menu-above');const r=summary.getBoundingClientRect(),h=panel.getBoundingClientRect().height;panel.classList.toggle('fleet-menu-above',r.bottom+h>innerHeight-12&&r.top>h+12)}});card.append(bottom,details);
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
 // Сводка, модель и настройки каждого провайдера собраны в одну плитку.
 const liveStrip=el('section','fleet-active-strip');liveStrip.id='fleetActiveAccounts';liveStrip.setAttribute('aria-label','Активные аккаунты и использованные лимиты');
 const liveHead=el('div','fleet-live-head');liveHead.append(el('span','fleet-live-label','Активные аккаунты · использовано лимита'));
 const liveRows=el('div','fleet-live-rows');liveStrip.append(liveHead,liveRows);term.before(liveStrip);
 const reserve=document.getElementById('ntGrp');hdr.querySelector('.hdrctl').append(reserve,document.getElementById('cxInst'));
 const gear=document.getElementById('gear'),codexGear=document.getElementById('cxGear'),codexModel=document.getElementById('cxMod');
 const generalGear=el('button','hdrgear fleet-header-icon');generalGear.id='fleetGeneralGear';generalGear.type='button';generalGear.innerHTML=gear.innerHTML;generalGear.title='Общие настройки';generalGear.setAttribute('aria-label','Общие настройки');
 headerButtons.replaceChildren(document.getElementById('rfBtn'),generalGear);hdr.append(headerButtons);
 const claudeModel=el('button','hdrgear cxmodbtn fleet-model-tile');claudeModel.id='fleetClaudeModel';claudeModel.type='button';claudeModel.setAttribute('aria-haspopup','dialog');claudeModel.setAttribute('aria-expanded','false');
 claudeModel.append(codexModel.querySelector('svg').cloneNode(true),el('span','cxmodn','Модель Claude'),el('span','cxmode'));
 const claudeQ=el('div','cxpop cxquick fleet-quick-panel');claudeQ.id='fleetClaudeQ';claudeQ.setAttribute('role','dialog');claudeQ.setAttribute('aria-label','Модель и рассуждения Claude');claudeQ.hidden=true;
 const claudeQBody=el('div','cxpbody');claudeQBody.id='fleetClaudeQBody';const nativeModelControls=el('div','fleet-native-controls');nativeModelControls.hidden=true;nativeModelControls.append(models);claudeQ.append(claudeQBody,nativeModelControls);document.body.append(claudeQ);
 const liveNodes={},liveSnapshots=new Map();
 for(const engine of ['claude','codex']){
  const tile=el('article','fleet-live-account '+engine);tile.dataset.engine=engine;
  const identity=el('a','fleet-live-identity');identity.href=engine==='claude'?'#fleetClaude':'#fleetCodex';identity.append(el('strong','fleet-live-name'),el('span','fleet-live-email'));tile.append(identity);
  const controls=el('div','fleet-provider-controls');controls.append(engine==='claude'?claudeModel:codexModel,engine==='claude'?gear:codexGear);
  for(const button of controls.children)button.classList.add(button.classList.contains('cxmodbtn')?'fleet-model-tile':'fleet-provider-gear');tile.append(controls);
  for(const kind of ['session','week']){
   const meter=el('div','fleet-live-meter');meter.dataset.window=kind;
   const caption=el('div','fleet-live-meter-label');caption.append(el('span','',kind==='session'?'5 часов':'Неделя'),el('b','','—'));
   const track=el('span','fleet-live-track');track.setAttribute('aria-hidden','true');track.append(el('span','fleet-live-fill'));meter.append(caption,track);tile.append(meter);
  }
  identity.addEventListener('click',event=>{event.preventDefault();const selected=engine==='claude'?document.querySelector('#cards .card.active'):document.querySelector('#cxcards .card.fleet-active');(selected||document.querySelector(identity.getAttribute('href')))?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'})});
  liveRows.append(tile);liveNodes[engine]=tile;
 }
 function placePanel(panel,anchor,width){
  const r=anchor.getBoundingClientRect(),w=Math.min(width,innerWidth-24),top=Math.min(r.bottom+8,Math.max(12,innerHeight-240));
  panel.style.width=w+'px';panel.style.top=Math.round(top)+'px';panel.style.left=Math.max(12,Math.min(Math.round(r.right-w),innerWidth-w-12))+'px';panel.style.right='auto';panel.style.bottom='auto';panel.style.maxHeight=Math.max(120,innerHeight-top-12)+'px';
 }
 function closeClaudeQ(){claudeQ.hidden=true;claudeModel.setAttribute('aria-expanded','false')}
 function paintClaudeModel(m){
  if(!m)return;
  const name=m.session_name||m.default_name||m.session||m.default||'Модель Claude',effort=efPending||m.effort||m.effort_default||'';
  putText(claudeModel.querySelector('.cxmodn'),name);putText(claudeModel.querySelector('.cxmode'),effort);claudeModel.title='Модель Claude: '+name+(effort?' · '+effort:'');claudeModel.setAttribute('aria-label',claudeModel.title);
  gear.title='Настройки Claude';gear.setAttribute('aria-label','Настройки Claude');
  if(claudeQ.hidden)return;
  claudeQBody.replaceChildren(el('div','cxqh','Модель Claude'));
  const list=el('div','cxqlist');list.setAttribute('role','radiogroup');list.setAttribute('aria-label','Модель Claude');
  for(const model of (m.available||[]).filter(model=>model.enabled)){
   const on=model.id===(m.default||m.session),button=el('button','cxqm'+(on?' on':''));button.type='button';button.setAttribute('role','radio');button.setAttribute('aria-checked',String(on));button.dataset.model=model.id;button.append(el('i','cxqr'),el('span','',model.name));
   button.addEventListener('click',()=>{if(!on)pickModel(model.id)});list.append(button);
  }
  claudeQBody.append(list,el('div','cxqh','Уровень рассуждений'));
  const choices=el('div','cxqeff'),supported=Array.isArray(m.effort_supported)?m.effort_supported:null;
  for(const level of EF.filter(level=>!supported||supported.includes(level))){
   const button=el('button','cxqe'+(level===effort?' on':''),level);button.type='button';button.dataset.effort=level;button.setAttribute('role','radio');button.setAttribute('aria-checked',String(level===effort));button.disabled=!!efPending;
   button.addEventListener('click',()=>{if(level===effort){closeClaudeQ();return}if(!confirm(tr('confirmEffort',level)))return;setEffort(level);closeClaudeQ()});choices.append(button);
  }
  if(!choices.children.length)choices.append(el('span','cxsub','Недоступно для этой модели'));
  choices.setAttribute('role','radiogroup');choices.setAttribute('aria-label','Уровень рассуждений Claude');claudeQBody.append(choices);
 }
 const nativeModelRender=renderModel;renderModel=function(m){nativeModelRender(m);paintClaudeModel(m)};
 claudeModel.addEventListener('click',()=>{if(!claudeQ.hidden){closeClaudeQ();return}cxQClose();cxPopClose();cxMenuClose();ntClose();document.getElementById('scrim').hidden=true;claudeQ.hidden=false;claudeModel.setAttribute('aria-expanded','true');paintClaudeModel(lastModel);placePanel(claudeQ,claudeModel,330)});
 codexModel.addEventListener('click',()=>{closeClaudeQ();document.getElementById('scrim').hidden=true});
 cxQPlace=function(){placePanel(document.getElementById('cxQ'),codexModel,330)};
 cxPopPlace=function(){placePanel(document.getElementById('cxPop'),codexGear,580)};
 document.getElementById('cxQ').classList.add('fleet-quick-panel');document.getElementById('cxPop').classList.add('fleet-settings-panel');document.getElementById('ntPop').classList.add('fleet-settings-panel');for(const id of ['cxPop','ntPop'])document.getElementById(id).setAttribute('aria-modal','true');
 // Нативные настройки Claude и общие разделы сохраняют все узлы и обработчики.
 const scrim=document.getElementById('scrim'),modal=scrim.querySelector('.modal');scrim.classList.add('fleet-settings-scrim');modal.classList.add('fleet-settings-panel');modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');modal.setAttribute('aria-labelledby','modalTitle');
 const claudeTitle=document.getElementById('modalTitle'),modalHeader=el('div','cxphead'),modalClose=el('button','hdrgear fleet-panel-close');modalClose.id='fleetClaudeSettingsClose';modalClose.type='button';modalClose.setAttribute('aria-label','Закрыть настройки');modalClose.innerHTML=document.getElementById('cxPopX').innerHTML;modalHeader.append(claudeTitle,modalClose);
 const modalBody=el('div','cxpbody');while(modal.firstChild)modalBody.append(modal.firstChild);modal.replaceChildren(modalHeader,modalBody);
 function group(label,nodes,cls){const section=el('section','fleet-settings-group '+(cls||''));if(label)section.append(el('div','fleet-settings-group-title',label));for(const node of nodes)if(node)section.append(node);return section}
 const autoTitle=document.getElementById('autoHdr'),autoRow=document.getElementById('autoWrap').closest('.switchrow'),weekly=document.getElementById('wkPause').closest('label');
 const autoGroup=group('',[autoTitle,autoRow,document.getElementById('autoNote'),weekly],'fleet-claude-group');
 const modelGroup=group('',[document.getElementById('modelsHdr'),document.getElementById('modalSub'),document.getElementById('poolList'),document.getElementById('checkNew')],'fleet-claude-group');
 const common=el('details','fleet-common-settings');common.append(el('summary','','Общие настройки'));
 for(const [title,body] of [['skinTitle','skinGrid'],['updHdr','updBox'],['bkHdr','bkBox']])common.append(group('',[document.getElementById(title),document.getElementById(body)]));
 modalBody.prepend(autoGroup,modelGroup,common);
 const codexThresholds=group('Переключение и лимиты Codex',[cxOptions]);document.querySelector('#cxPop > .cxpbody').prepend(codexThresholds);
 const backdrop=el('div','fleet-settings-backdrop');backdrop.id='fleetSettingsBackdrop';backdrop.hidden=true;document.body.append(backdrop);backdrop.addEventListener('click',()=>{cxPopClose();ntClose()});
 function paintSettingsState(){
  backdrop.hidden=document.getElementById('cxPop').hidden&&document.getElementById('ntPop').hidden;
  gear.setAttribute('aria-expanded',String(!scrim.hidden&&scrim.dataset.view==='claude'));generalGear.setAttribute('aria-expanded',String(!scrim.hidden&&scrim.dataset.view==='general'));
 }
 new MutationObserver(paintSettingsState).observe(scrim,{attributes:true,attributeFilter:['hidden']});
 for(const id of ['cxPop','ntPop'])new MutationObserver(paintSettingsState).observe(document.getElementById(id),{attributes:true,attributeFilter:['hidden']});
 gear.setAttribute('aria-haspopup','dialog');
 gear.addEventListener('click',()=>{cxPopClose();cxMenuClose();cxQClose();ntClose();closeClaudeQ();scrim.dataset.view='claude';putText(claudeTitle,'Настройки Claude');common.open=false;placePanel(modal,gear,580);paintSettingsState()});
 generalGear.addEventListener('click',()=>{if(!scrim.hidden&&scrim.dataset.view==='general'){document.getElementById('modalDone').click();return}gear.click();scrim.dataset.view='general';putText(claudeTitle,'Общие настройки');common.open=true;placePanel(modal,generalGear,580);paintSettingsState()});
 codexGear.addEventListener('click',()=>{scrim.hidden=true;closeClaudeQ()});
 document.getElementById('ntGear').addEventListener('click',()=>{scrim.hidden=true;closeClaudeQ()});
 modalClose.addEventListener('click',()=>{document.getElementById('modalDone').click();(scrim.dataset.view==='general'?generalGear:gear).focus()});
 document.addEventListener('pointerdown',event=>{if(!event.target.closest('#fleetClaudeQ,#fleetClaudeModel'))closeClaudeQ()});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!claudeQ.hidden){closeClaudeQ();claudeModel.focus()}});
 addEventListener('resize',()=>{if(!claudeQ.hidden)placePanel(claudeQ,claudeModel,330);if(!scrim.hidden)placePanel(modal,scrim.dataset.view==='general'?generalGear:gear,580)});
 if(!scrim.hidden){scrim.dataset.view='general';putText(claudeTitle,'Общие настройки');common.open=true;placePanel(modal,generalGear,580);paintSettingsState()}
 if(lastModel)paintClaudeModel(lastModel);

 function updateLiveAccount(engine,slot,account,pending){
  const node=liveNodes[engine],provider=engine==='claude'?'Claude':'Codex';
  const signature=JSON.stringify([slot,account,pending]);if(liveSnapshots.get(engine)===signature)return;liveSnapshots.set(engine,signature);
  const name=account?(account.label||account.name||slot):slot?slot:pending?'Загрузка…':'Не выбран';
  putText(node.querySelector('.fleet-live-name'),provider+' · '+name);
  const issue=account&&(account.login_required||account.lapsed||account.error)?'Нужна проверка':account&&account.stale?'Данные устарели':'';
  putText(node.querySelector('.fleet-live-email'),account?((account.email||slot)+(issue?' · '+issue:'')):slot?'Лимиты пока недоступны':pending?'Получаем сохранённые данные':'Нет активного аккаунта');
  node.dataset.state=issue?'warning':account?'ready':'empty';node.dataset.slot=slot||'';
  node.title=provider+' · '+name+(account?.email?' · '+account.email:'')+' · открыть полную карточку'+(issue?' · '+issue:'');
  const windows=engine==='claude'?[account?.five_hour,account?.seven_day]:[account?.windows?.find(w=>w.mins===300),account?.windows?.find(w=>w.mins===10080)];
  windows.forEach((window,i)=>{
   const meter=node.querySelectorAll('.fleet-live-meter')[i],pct=Number.isFinite(window?.pct)?window.pct:null;
   putText(meter.querySelector('b'),pct==null?'—':Math.round(pct)+'%');meter.querySelector('.fleet-live-fill').style.width=(pct==null?0:Math.min(100,Math.max(0,pct)))+'%';
   meter.dataset.tone=pct==null?'unknown':pct>=99?'bad':pct>=90?'warn':'normal';
   const reset=window?.resets_at?new Date(window.resets_at):null;
   meter.title=(i?'Неделя':'5 часов')+' · использовано '+(pct==null?'нет данных':Math.round(pct)+'%')+(reset&&!Number.isNaN(reset.getTime())?' · сброс '+reset.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'');
  });
 }
 function renderLiveAccounts(snapshot){
  const d=snapshot||((typeof lastSnap!=='undefined'&&lastSnap)||null),entries=Object.entries(d?.accounts||{});
  const current=d?.active?entries.find(([slot])=>slot===d.active):entries.find(([,a])=>a.active);
  updateLiveAccount('claude',current?.[0]||d?.active,current?.[1],!d);
  const accounts=(typeof cxData!=='undefined'&&cxData?.accounts)||[],slot=rotationData?.active;
  updateLiveAccount('codex',slot,slot?accounts.find(a=>a.slot===slot):null,!rotationData||!!(typeof cxData!=='undefined'&&cxData?.loading));
  codexGear.disabled=typeof cxAvail==='function'&&!cxAvail();
 }

 function refreshVisuals(snapshot){
  renderLiveAccounts(snapshot);
  const d=snapshot||((typeof lastSnap!=='undefined'&&lastSnap)||{}),rows=Object.entries(d.accounts||{});
  document.querySelectorAll('#cards > .card').forEach((card,i)=>{if(rows[i])decorateCard(card,rows[i][1],rows[i][0],'claude')});
  putText(ch.querySelector('.fleet-count'),countText(rows.length));
  const current=rows.find(([,a])=>a.active);putText(claudeNote,current?'Сейчас: '+(current[1].label||current[1].name||current[0]):'Активный аккаунт не выбран');
  const accounts=(typeof cxData!=='undefined'&&cxData?.accounts)||[];
  document.querySelectorAll('#cxcards > .card').forEach((card,i)=>{if(accounts[i])decorateCard(card,accounts[i],accounts[i].slot,'codex')});
  putText(xh.querySelector('.fleet-count'),countText(accounts.length));
  const add=document.querySelector('#cx .cxhead .hdrgear');if(add){xh.querySelector('.fleet-add-codex')?.remove();add.classList.add('fleet-add-codex');xh.append(add)}
 }
 const originalCards=renderCards;renderCards=function(d){originalCards(d);refreshVisuals(d)};
 const previousCodexRender=cxRender;cxRender=function(){previousCodexRender();refreshVisuals()};
 document.addEventListener('click',event=>{document.querySelectorAll('.fleet-card-details[open]').forEach(menu=>{if(!menu.contains(event.target))menu.open=false})});
 document.addEventListener('keydown',event=>{if(event.key==='Escape')document.querySelectorAll('.fleet-card-details[open]').forEach(menu=>menu.open=false)});
 refreshVisuals();

 // Меняется только представление; исходные кнопки паузы и живой таймер сохраняются.
 let pauseFoldOpen=false;
 function foldPauseBanner(){
  const root=document.getElementById('ccPause');
  if(!root||root.hidden){pauseFoldOpen=false;return;}
  if(root.querySelector(':scope > .fleet-pause-fold'))return;
  const title=root.querySelector('.ccp-title'),body=root.querySelector('.ccp-body');if(!title||!body)return;
  const dot=root.querySelector('.ccp-dot'),timer=root.querySelector('.ccp-timer');
  const fold=el('details','fleet-pause-fold');fold.id='fleetPauseDetails';fold.open=pauseFoldOpen;
  const summary=el('summary','fleet-pause-summary');summary.setAttribute('aria-controls','fleetPauseContent');
  const brief=el('span','ccp-title');brief.title=title.textContent;
  const pause=ccpData?.pause,english=typeof LANG!=='undefined'&&LANG==='en';
  brief.textContent=pause?.active&&pause.kind!=='reserve'?(english?'Claude paused · auto resume':'Claude на паузе · автовозобновление'):title.textContent;
  if(dot)summary.append(dot);summary.append(brief);if(timer)summary.append(timer);
  const arrow=document.createElementNS('http://www.w3.org/2000/svg','svg');arrow.setAttribute('viewBox','0 0 24 24');arrow.setAttribute('class','fleet-pause-chevron');arrow.setAttribute('aria-hidden','true');
  const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','m6 9 6 6 6-6');path.setAttribute('fill','none');path.setAttribute('stroke','currentColor');path.setAttribute('stroke-width','2');path.setAttribute('stroke-linecap','round');path.setAttribute('stroke-linejoin','round');arrow.append(path);summary.append(arrow);
  const content=el('div','fleet-pause-content');content.id='fleetPauseContent';content.append(body);fold.append(summary,content);
  fold.addEventListener('toggle',()=>{if(fold.isConnected)pauseFoldOpen=fold.open});root.replaceChildren(fold);
 }
 const previousPauseRender=ccpRender;
 ccpRender=function(){const root=document.getElementById('ccPause'),previous=root&&!root.hidden?root.querySelector(':scope > .fleet-pause-fold'):null;if(previous)pauseFoldOpen=previous.open;previousPauseRender();foldPauseBanner()};
 foldPauseBanner();

 // Заголовок начинаетcя с реальных ролей: ведущий, затем исполнитель.
 Object.assign(I18N.ru,{cxpN_orchestrator:'Codex → Claude',cxpN_codex:'Codex · самостоятельно',cxpN_codex_solo_full:'Codex Full · самостоятельно',cxpN_reserve:'Codex + Notion · резерв',cxeN:'Codex · самостоятельно · аварийный',cxeHdr:'Codex · самостоятельно · аварийный',cxeOnT:'Codex · самостоятельно · аварийный включён'});
 Object.assign(I18N.en,{cxpN_orchestrator:'Codex → Claude',cxpN_codex:'Codex · solo',cxpN_codex_solo_full:'Codex Full · solo',cxpN_reserve:'Codex + Notion · reserve',cxeN:'Codex · solo · emergency',cxeHdr:'Codex · solo · emergency',cxeOnT:'Codex · solo · emergency enabled'});
 const originalProfileDisplayName=cxpName;
 cxpName=function(profile){
  const name=originalProfileDisplayName(profile);if(profile.builtin)return name;
  const solo=profile.mode==='self',paired=['orchestrator','mediator'].includes(profile.mode);if(!solo&&!paired)return name;
  const roles=paired?'Codex → Claude':('Codex'+(profile.access==='full'?' Full':'')+(LANG==='en'?' · solo':' · самостоятельно'));
  return name?.startsWith(roles)?name:roles+(name?' · '+name:'');
 };

 // Палитра профилей: сравнение меняет только раскрытие сведений, выбор — нативный.
 const profileRoot=document.getElementById('cxp'),profileBody=menu.querySelector(':scope > .cxpbody');
 menu.classList.add('fleet-profile-palette');menu.setAttribute('aria-label','Выбор профиля');menu.setAttribute('aria-modal','true');document.getElementById('cxMenuScrim').classList.add('fleet-profile-backdrop');
 const paletteHeader=el('div','fleet-palette-header'),paletteHeading=el('div','fleet-palette-heading');paletteHeading.append(el('span','fleet-eyebrow','РЕЖИМ РАБОТЫ'),el('h2','','Выбор профиля'));
 const paletteCurrent=el('span','fleet-palette-current'),paletteClose=el('button','hdrgear fleet-palette-close');paletteClose.id='fleetProfileClose';paletteClose.type='button';paletteClose.title='Закрыть';paletteClose.setAttribute('aria-label','Закрыть профили');paletteClose.innerHTML=document.getElementById('cxPopX').innerHTML;paletteClose.addEventListener('click',()=>{cxMenuClose();document.getElementById('cxBtn').focus()});paletteHeader.append(paletteHeading,paletteCurrent,paletteClose);
 const paletteTools=el('div','fleet-palette-tools');search.placeholder='Найти по названию или возможностям…';
 const searchWrap=el('label','fleet-palette-search');searchWrap.append(search);const compareButton=el('button','fleet-profile-compare','Сравнить');compareButton.id='fleetProfileCompare';compareButton.type='button';compareButton.setAttribute('aria-pressed','false');compareButton.title='Показать состав и возможности всех профилей';paletteTools.append(searchWrap,compareButton);
 const paletteFooter=el('div','fleet-palette-footer'),paletteCount=el('span','fleet-palette-count');paletteCount.setAttribute('role','status');const paletteHelp=el('span','fleet-palette-help','Enter — выбрать · Esc — закрыть');paletteFooter.append(paletteCount,paletteHelp);
 note.remove();menu.replaceChildren(paletteHeader,paletteTools,profileBody,paletteFooter);
 const paletteEmpty=el('div','fleet-profile-empty');paletteEmpty.hidden=true;paletteEmpty.append(el('strong','','Профили не найдены'),el('span','','Попробуй другое название или возможность.'));const clearSearch=el('button','','Очистить поиск');clearSearch.type='button';clearSearch.addEventListener('click',()=>{search.value='';filterProfiles();repaintProfileResults();search.focus()});paletteEmpty.append(clearSearch);profileBody.append(paletteEmpty);
 let compareProfiles=false,normalProfileInfo=new Set();
 const profileCopy={orchestrator:'Codex ведёт задачу. Claude выполняет шаги после твоего подтверждения.',codex:'Самостоятельная работа в своей папке. Проект доступен для чтения.',codex_solo_full:'Работает самостоятельно с полной песочницей Codex и правами пользователя ОС.'};
 function repaintProfileResults(){
  const nodes=Array.from(profileRoot.querySelectorAll('.cxprof:not([data-auto])')),visible=nodes.filter(node=>!node.hidden).length;
  const services=profileRoot.querySelectorAll('.cxprof[data-auto],.cxemg').length;
  putText(paletteCount,(search.value.trim()?'Найдено: '+visible+' из '+nodes.length:nodes.length+' '+(nodes.length===1?'профиль':nodes.length>1&&nodes.length<5?'профиля':'профилей'))+(services?' · служебных режимов: '+services:''));
  paletteEmpty.hidden=visible>0||!!profileRoot.querySelector('.cxprof[data-auto]:not([hidden])');
 }
 function decorateProfilePalette(){
  const bridge=cxbData&&cxbData.bridge,profiles=bridge?.profiles||[],current=profiles.find(profile=>profile.id===bridge.profile);
  putText(paletteCurrent,cxbData?.emergency?.active?'Сейчас: '+tr('cxeHdr'):current?'Сейчас: '+cxpName(current):bridge?.profile==='reserve'?'Сейчас: '+tr('cxpN_reserve'):'Сейчас: свои настройки');
  paletteCurrent.title=current?cxpSub(current):'';menu.dataset.compare=String(compareProfiles);compareButton.setAttribute('aria-pressed',String(compareProfiles));putText(compareButton,compareProfiles?'Краткий вид':'Сравнить');compareButton.title=compareProfiles?'Вернуть краткий вид':'Показать состав и возможности всех профилей';
  for(const card of profileRoot.querySelectorAll('.cxprof:not([data-auto])')){
   const profile=profiles.find(profile=>profile.id===card.dataset.id);if(!profile)continue;
   const nameNode=card.querySelector('.cxpn');if(nameNode&&!nameNode.querySelector('.cxpnm'))nameNode.replaceChildren(el('span','cxpnm',cxpName(profile)));
   card.classList.add('fleet-profile-card');card.dataset.kind=profile.mode==='self'?'solo':'team';card.dataset.infoOpen=String(CXP_INFO.has(profile.id));
   const text=card.querySelector('.cxpt'),description=card.querySelector('.cxps'),fullText=description?.textContent||'';
   const heading=el('div','fleet-profile-card-head'),icon=card.querySelector('.cxpr');if(icon){icon.setAttribute('aria-hidden','true');heading.append(icon)}
   const status=el('span','fleet-profile-status',profile.id===bridge.profile?'Выбран':profile.builtin?'Встроенный':'Свой профиль');heading.append(status);const remove=card.querySelector('[data-del]');if(remove)heading.append(remove);card.prepend(heading);
   if(description&&profile.builtin&&profileCopy[profile.id]&&LANG!=='en')putText(description,profileCopy[profile.id]);
   if(description)description.title=fullText;
   const meta=el('span','fleet-profile-meta');meta.append(el('span','',cxoMode(profile.mode)),el('span','',profile.mode==='self'?cxoAcc(profile.access):cxoRt(profile.task_rights)));const route=text.querySelector('.cxroute');if(route)meta.append(route);description?.after(meta);
   const index=el('span','fleet-profile-index',fullText+' '+profile.id+' '+cxoAcc(profile.access)+' '+cxoRt(profile.task_rights));index.hidden=true;text.append(index);
   const details=card.querySelector('.cxpinfo');if(details&&description?.textContent!==fullText)details.prepend(el('span','fleet-profile-original',fullText));
   const footer=el('div','fleet-profile-card-footer'),info=card.querySelector('[data-info]');footer.append(el('span','fleet-profile-choose',profile.id===bridge.profile?'Работает сейчас':'Выбрать →'));
   if(info){info.hidden=compareProfiles;info.classList.add('fleet-profile-more');info.prepend(document.createTextNode('Подробнее'));info.setAttribute('aria-label','Подробнее о профиле '+cxpName(profile));footer.append(info)}card.append(footer);
  }
  const selected=profileRoot.querySelector('.cxprof.act:not([data-auto])');if(selected)selected.parentElement.prepend(selected);
  const reserveCard=profileRoot.querySelector('.cxprof[data-auto]');if(reserveCard){reserveCard.parentElement.insertBefore(el('div','fleet-profile-service-heading','Служебные режимы'),reserveCard);reserveCard.classList.add('fleet-profile-service');reserveCard.querySelector('.cxps').title=reserveCard.querySelector('.cxps').textContent;reserveCard.append(el('span','fleet-profile-auto','Автоматически'))}
  filterProfiles();repaintProfileResults();
 }
 const originalProfileRender=cxpRender;
 cxpRender=function(){
  const scroll=profileBody.scrollTop,focused=document.activeElement,focusCard=focused?.closest('#cxp .cxprof'),focusId=focusCard?.dataset.id,focusAction=focused?.closest('[data-info]')?'[data-info]':focused?.closest('[data-del]')?'[data-del]':null;
  if(compareProfiles)for(const profile of cxbData?.bridge?.profiles||[])CXP_INFO.add(profile.id);
  originalProfileRender();decorateProfilePalette();profileBody.scrollTop=scroll;if(!menu.hidden){cxMenuPlace();if(focusId){const card=Array.from(profileRoot.querySelectorAll('.cxprof')).find(card=>card.dataset.id===focusId);if(card&&!card.hidden)(focusAction?card.querySelector(focusAction):card)?.focus({preventScroll:true})}}
 };
 compareButton.addEventListener('click',()=>{
  compareProfiles=!compareProfiles;
  if(compareProfiles){normalProfileInfo=new Set(CXP_INFO);for(const profile of cxbData?.bridge?.profiles||[])CXP_INFO.add(profile.id)}
  else for(const profile of cxbData?.bridge?.profiles||[])normalProfileInfo.has(profile.id)?CXP_INFO.add(profile.id):CXP_INFO.delete(profile.id);
  cxpRender();
 });
 search.addEventListener('input',repaintProfileResults);
 search.addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();profileRoot.querySelector('.cxprof:not([data-auto]):not([hidden])')?.focus()}});
 new MutationObserver(()=>{if(!menu.hidden){if(!search.value.trim())profileBody.scrollTop=0;if(matchMedia('(pointer:fine)').matches)search.focus({preventScroll:true})}else if(document.activeElement?.closest('#cxMenu'))document.getElementById('cxBtn').focus()}).observe(menu,{attributes:true,attributeFilter:['hidden']});
 profileRoot.addEventListener('keydown',event=>{
  if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)||!event.target.matches('.cxprof:not([data-auto])'))return;
  const visible=Array.from(profileRoot.querySelectorAll('.cxprof:not([data-auto]):not([hidden])')),index=visible.indexOf(event.target);if(index<0)return;
  event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?visible.length-1:(index+(['ArrowLeft','ArrowUp'].includes(event.key)?-1:1)+visible.length)%visible.length;visible[next]?.focus();
 });
 cxMenuPlace=function(){placePanel(menu,document.getElementById('cxBtn'),940)};
 document.getElementById('cxBtn').addEventListener('click',()=>{if(!menu.hidden){scrim.hidden=true;closeClaudeQ();cxMenuPlace()}});
 cxpRender();

 loadRotation();setInterval(()=>{if(!document.hidden)loadRotation()},5000);
})();
'''


def render(page):
    return page.replace('</head>', '<style id="fleetOverviewStyle">'+CSS+'</style></head>', 1).replace(
        '</body>', '<script id="fleetOverviewScript">'+JS+'</script></body>', 1)
