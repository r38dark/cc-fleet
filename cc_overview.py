"""Компоновка «Обзор»: существующие узлы и обработчики остаются на месте в DOM."""

# Header asset: assets/ccfleet-brand-128.webp, derived from the approved transparent PNG.
BRAND_ICON_DATA_URL = 'data:image/webp;base64,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'

CSS = r'''
.fleet-model-catalog{max-height:180px;overflow:auto;margin:10px 0}.fleet-catalog-row{display:flex;align-items:center;gap:8px;min-width:0;padding:9px 0;border-bottom:1px solid var(--fleet-line)}.fleet-catalog-name{min-width:0;flex:1;font-size:12px;overflow-wrap:anywhere}.fleet-catalog-name small{display:block;color:var(--fleet-muted);font-size:10px;margin-top:3px}.fleet-catalog-chip{flex:none;border:1px solid var(--fleet-line);border-radius:4px;padding:2px 6px;font-size:10px;color:var(--fleet-accent)}.fleet-catalog-note{font-size:11px;line-height:1.6;color:var(--fleet-muted);overflow-wrap:anywhere;margin:8px 0}.fleet-catalog-note[data-error="true"]{color:var(--warn)}#fleetCxCheckNew:disabled{opacity:.6;cursor:default}
/* Оформление первоначального «Обзора». Действующие контролы сохраняют свои ID. */
:root{--fleet-line:#25303f;--fleet-muted:#8c9bad;--fleet-faint:#647388;--fleet-accent:#45d6ab;--fleet-accent-soft:#16352e;--fleet-claude:#e7af85;--fleet-claude-soft:#372b25;--fleet-terminal:#0a0e14;--fleet-toolbar:#111722}
html:not([data-skin]){--bg:#0c1017;--card:#131923;--txt:#e8edf4;--mut:#8c9bad;--ok:#45d6ab;--warn:#ecc277;--bad:#ef969e;--acc:#45d6ab}
html:root:root:not(.conly) body{height:auto!important;min-height:100dvh;overflow:auto!important;display:block!important;max-width:1680px;margin:0 auto;padding:23px 40px 28px;background:var(--bg);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--txt)}
#cxp .cxprof[hidden]{display:none!important}
html:root:root:not(.conly) .hdr{display:flex;align-items:center;gap:24px;padding:0;margin:0 0 22px;min-height:40px}
html:not(.conly) .hdrl{flex:1;min-width:180px;display:flex;gap:13px;align-items:center}
html:not(.conly) #h1{display:flex;align-items:center;gap:11px;font-size:24px;font-weight:750;letter-spacing:-1px;line-height:1.12;margin:0;color:var(--txt);white-space:nowrap}
.fleet-brand{display:block;width:40px;height:40px;object-fit:contain;background:transparent;flex:none}
.fleet-brand-word{font-weight:400;color:var(--fleet-muted)}.fleet-brand-sub{display:block;font-size:8px;font-weight:650;letter-spacing:.17em;margin-top:5px;color:var(--fleet-faint)}
.fleet-brand-name{position:relative;display:inline-block}
html:root:root #h1 #termDot{position:absolute;top:2px;right:-9px;width:6px;height:6px;margin:0}
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
.fleet-composer button{margin:0;min-height:0;padding:0;flex:none}.fleet-composer #fleetSend{display:grid;place-items:center;width:29px;height:29px;background:#1a342d;color:#a5c6bb;border:0;border-radius:6px;font-size:19px;box-shadow:none}.fleet-composer #fleetSend svg{display:block;width:17px;height:17px;pointer-events:none}.fleet-key{background:transparent!important;color:#73869d!important;border:1px solid #2a3644!important;padding:2px 5px!important;border-radius:4px!important;font:10px ui-monospace,monospace!important}
.fleet-input-status{display:flex;align-items:center;gap:8px;padding:0 18px;min-height:32px;background:#101620;border-top:1px solid #1d2733;font-size:10px;line-height:1.5;color:#8b9bb0;flex:none}.fleet-input-status::before{content:"";width:5px;height:5px;border-radius:50%;background:#4cdbb0;flex:none}.fleet-input-status span:last-child{margin-left:auto;color:#6d839a}
html:not(.conly) .toolrow{margin:10px 0 0;padding:0 4px;border:0;background:transparent;border-radius:0;gap:8px;min-height:28px}.fleet-model-label{font-size:10px;color:var(--fleet-faint);margin:0 9px 0 0}.toolrow .mbtn,.toolrow .modelbtn,.toolrow #mrow button{font-size:10px;padding:4px 10px;background:transparent;border:1px solid var(--fleet-line);color:var(--mut);box-shadow:none}.toolrow #mrow button.on{background:var(--card);color:var(--txt);border-color:var(--fleet-muted)}.toolrow .efB{font-size:11px}
#fleetAccounts{margin-top:28px}.fleet-accounts-intro{margin:0 0 20px}.fleet-eyebrow{display:block;font-size:9px;letter-spacing:.16em;font-weight:700;color:var(--fleet-faint)}.fleet-accounts-intro h2{font-size:20px;font-weight:550;letter-spacing:-.35px;margin:4px 0 0}
.fleet-section{margin:0;min-width:0}.fleet-section+.fleet-section{margin-top:24px}.fleet-section-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 11px;min-height:28px}.fleet-section-head h2{display:flex;align-items:center;font-size:14px;font-weight:600;margin:0;gap:10px}.fleet-provider{display:grid;place-items:center;width:25px;height:25px;border-radius:7px;background:var(--fleet-claude-soft);color:var(--fleet-claude);font-size:18px;line-height:1}.fleet-provider.codex{background:var(--fleet-accent-soft);color:var(--fleet-accent);font:550 15px/1 ui-monospace,monospace}.fleet-count{font-size:10px;color:var(--fleet-faint)}
.fleet-section-head #addAcct,.fleet-section-head .fleet-add-codex{margin:0 0 0 auto!important;width:auto!important;min-width:28px;display:flex;align-items:center;gap:5px;padding:5px 8px;height:28px;font-size:11px;font-weight:450;color:var(--txt);border:1px solid var(--fleet-line);border-radius:7px;background:transparent;box-shadow:none}.fleet-section-head #addAcct::after,.fleet-section-head .fleet-add-codex::after{content:"Добавить"}.fleet-section-head #addAcct svg,.fleet-section-head .fleet-add-codex svg{width:13px;height:13px}
html:not(.conly) #cards,html:not(.conly) #cxcards{height:auto!important;max-height:none!important;min-height:0!important;overflow:visible!important;display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px!important;margin:0!important;align-items:stretch}
html:root:root .fleet-section .card{position:relative;height:auto;min-width:0;min-height:200px;margin:0!important;border:1px solid var(--fleet-line);border-radius:12px;padding:15px 17px!important;background:var(--card);box-shadow:none;display:flex;flex-direction:column;container-type:normal}
html:root:root #fleetClaude .card.active{border-color:color-mix(in srgb,var(--fleet-claude) 50%,var(--fleet-line));background:linear-gradient(120deg,var(--fleet-claude-soft),var(--card) 70%)}
html:root:root #fleetCodex .card.fleet-active{border-color:color-mix(in srgb,var(--fleet-accent) 64%,var(--fleet-line));background:linear-gradient(120deg,var(--fleet-accent-soft),var(--card) 65%);box-shadow:none}
/* На паузе выбранный аккаунт остаётся выбранным, но не изображается работающим. */
html:root:root #fleetClaude .card.active.fleet-paused,html:root:root #fleetCodex .card.fleet-active.fleet-paused{border-color:var(--fleet-line);background:var(--card);box-shadow:none}
.fleet-section .fleet-card-state.paused{background:color-mix(in srgb,var(--fleet-muted) 15%,var(--card));color:var(--txt);font-weight:650;gap:7px}
.fleet-section .fleet-card-state.paused::before{content:"";display:inline-block;flex:none;width:11px;height:13px;border-radius:1px;background:linear-gradient(90deg,currentColor 0 35%,transparent 35% 65%,currentColor 65% 100%)}
.fleet-section .fleet-paused .fleet-card-footer .btn-sw:disabled{display:none}
html:root:root .fleet-section .card:has(.fleet-card-details[open]){z-index:35}
.fleet-section .card .top{display:flex;align-items:flex-start;gap:8px;flex-wrap:nowrap;padding-right:22px;min-height:38px;margin:0 0 6px}.fleet-identity{min-width:0;flex:1}.fleet-titleline{display:flex;align-items:center;gap:6px;min-width:0}.fleet-account-name{font-size:13px;font-weight:620;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;letter-spacing:0}.fleet-section .card .email{display:block;font-size:10px;font-weight:400;color:var(--fleet-faint);line-height:1.5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:3px;max-width:100%}
html:root:root .fleet-section .tag.plan,html:root:root .fleet-section .tag.free{font-size:9px;font-weight:450;border:1px solid var(--fleet-line);border-radius:4px;padding:1px 5px;color:var(--fleet-muted);background:transparent;text-transform:capitalize;line-height:1.2;letter-spacing:0}.fleet-section .fleet-active-label{display:none}.fleet-section .tag.pin{position:static;transform:none;display:none;box-shadow:none}
.fleet-card-state{align-self:flex-start;display:inline-flex;gap:5px;align-items:center;font-size:9px;line-height:1.35;font-weight:550;border-radius:4px;color:var(--fleet-muted);background:color-mix(in srgb,var(--card),var(--fleet-line) 50%);padding:2px 5px;margin:5px 0 12px}.fleet-card-state.active{color:var(--fleet-accent);background:var(--fleet-accent-soft)}.fleet-card-state.next{color:var(--fleet-claude);background:var(--fleet-claude-soft)}.fleet-card-state.limited{color:var(--warn);background:color-mix(in srgb,var(--warn) 13%,var(--card))}.fleet-card-state.problem{color:var(--bad);background:color-mix(in srgb,var(--bad) 12%,var(--card))}
.fleet-section .card>.row{margin:0 0 11px!important;padding:0}.fleet-section .card>.row .lbl{display:grid;grid-template-columns:minmax(0,1fr) auto 112px;align-items:center;gap:7px;margin-bottom:4px;line-height:1.3;font-size:10px;font-weight:400;color:var(--fleet-muted);letter-spacing:0;text-transform:none}
.fleet-section .card>.row .lbl b{font-size:11px;font-weight:550;color:var(--txt)!important;font-variant-numeric:tabular-nums}.fleet-section .card>.row .lbl>span:last-child{font-size:9px;color:var(--fleet-faint);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fleet-section .card>.row .bar{height:4px!important;border-radius:5px;background:var(--fleet-line);box-shadow:none;margin:0;overflow:hidden}.fleet-section .card>.row .fill{height:100%;border-radius:5px;background:var(--fleet-accent)!important;box-shadow:none}.fleet-section#fleetClaude .card>.row .fill{background:var(--fleet-claude)!important}.fleet-section .card>.row[data-fleet-tone="warn"] .fill{background:var(--warn)!important}.fleet-section .card>.row[data-fleet-tone="bad"] .fill{background:var(--bad)!important}
.fleet-card-footer .fleet-footer-relogin{margin:0;flex:none;white-space:nowrap}
.fleet-card-footer{display:flex;align-items:center;gap:6px;border-top:1px solid var(--fleet-line);padding-top:9px;margin-top:auto;min-height:26px}.fleet-card-caption{font-size:9px;color:var(--fleet-faint);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fleet-card-footer .btn-sw{font-size:10px!important;font-weight:400;color:var(--fleet-muted)!important;background:transparent!important;border:0!important;box-shadow:none!important;border-radius:0!important;margin:0 0 0 auto!important;padding:0!important;white-space:nowrap;opacity:1}.fleet-card-footer .btn-sw:not(:disabled)::after{content:" →"}.fleet-card-footer .btn-sw:disabled{color:var(--fleet-faint)!important}
.fleet-card-dates{display:flex;flex-wrap:wrap;gap:5px 7px;margin:-1px 0 9px;min-width:0}
.fleet-card-date{display:inline-flex;align-items:baseline;gap:5px;min-width:0;padding:3px 8px;border:1px solid var(--fleet-line);border-radius:6px;font-size:11px;line-height:1.35;color:var(--txt);background:color-mix(in srgb,var(--fleet-muted) 6%,transparent)}
.fleet-card-date-label{color:var(--fleet-muted);font-size:10px;white-space:nowrap}.fleet-card-date b{font-weight:600;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.fleet-card-date.warn{border-color:color-mix(in srgb,var(--warn) 45%,var(--fleet-line))}.fleet-card-date.warn b{color:var(--warn)}
.fleet-card-date.urgent{border-color:color-mix(in srgb,var(--bad) 50%,var(--fleet-line));background:color-mix(in srgb,var(--bad) 9%,transparent)}.fleet-card-date.urgent b{color:var(--bad)}
.fleet-section .card:has(> .fleet-card-dates) .fleet-titleline .chip{display:none}
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

/* Управление профилем относится к своей плитке провайдера. */
html:root:root:not(.conly) .hdr{gap:14px!important}
html:root:root:not(.conly) .hdr>.hdrl{order:0;flex:1;min-width:0}
html:root:root:not(.conly) .hdr>.hdrctl{order:1;flex:0 1 auto!important;flex-basis:auto!important;gap:12px!important;min-width:0}
html:root:root:not(.conly) .hdr>.hdrbtns{order:2;flex:none;margin:0 0 0 auto;gap:7px!important}
.hdr #fleetGeneralGear,.hdr #fleetProfilesBtn,.hdr #rfBtn{width:32px;height:32px;padding:7px;border:1px solid var(--fleet-line);border-radius:7px;background:transparent;color:var(--fleet-muted)}
.hdr #fleetGeneralGear svg,.hdr #fleetProfilesBtn svg,.hdr #rfBtn svg{width:16px;height:16px}
/* кнопка общего окна «Выбор профиля» рядом с шестерёнкой; на широком экране с подписью, на узком только иконка */
.hdr #fleetProfilesBtn{display:inline-flex;align-items:center;justify-content:center;gap:7px;flex:none;box-sizing:border-box;cursor:pointer}
.hdr #fleetProfilesBtn .fleet-hdr-label{display:none;font-size:12px;font-weight:550;line-height:1;white-space:nowrap}
.hdr #fleetProfilesBtn:hover{border-color:var(--fleet-muted)}.hdr #fleetProfilesBtn[aria-expanded="true"]{color:var(--fleet-accent);border-color:var(--fleet-accent)}
@media(min-width:901px){.hdr #fleetProfilesBtn{width:auto;padding:0 11px 0 9px}.hdr #fleetProfilesBtn .fleet-hdr-label{display:inline}}
/* иконки «Обновить сейчас» в шапке нет, данные и так обновляются сами раз в минуту. Элемент остаётся в разметке: на него ссылаются скрипты страницы. */
html:root:root .hdr #rfBtn{display:none!important}
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
#scrim:not([data-view="general"]) .fleet-common-settings{display:none}
#scrim #autoHdr,#scrim #modelsHdr,#scrim #thrMinus,#scrim #thrPlus{display:none!important}
.fleet-settings-panel .fleet-limit-hint{margin:10px 0 4px}
.fleet-own-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px;font-size:12px;color:var(--txt);margin:0 0 4px}
.fleet-own-row .fleet-own-text{flex:1 1 170px;min-width:0}
.fleet-settings-group.fleet-own-sub{border:0;border-top:1px solid var(--fleet-line);border-radius:0;padding:12px 0 0;margin:10px 0 0}
#fleetCodexOwn>.cxacc{border:0;border-top:1px solid var(--fleet-line);border-radius:0;padding:10px 0 0;margin:10px 0 0}
#fleetCodexOwn>.cxwipe{margin:12px 0 0}
.fleet-pick-row .fleet-mpick{display:flex;align-items:center;gap:10px;flex:1;min-width:0;cursor:pointer;margin:0}
.fleet-pick-row .fleet-mpick input[type="checkbox"]{flex:none;width:16px;height:16px;margin:0;transform:none}
#poolList .poolrow.fleet-pick-row{display:flex;flex-direction:row;flex-wrap:wrap;align-items:center;gap:8px;padding:9px 0;font-size:12px;cursor:default;border-bottom:1px solid var(--fleet-line)}
#poolList .poolrow.is-hidden{opacity:.6}
#poolList .poolrow input.poolname[type="text"]{flex-basis:100%;margin:2px 0 0 26px;max-width:calc(100% - 26px);box-sizing:border-box}
#scrim[data-view="general"] .fleet-common-settings{display:contents}
@media(max-width:1250px){.fleet-live-account{grid-template-columns:minmax(90px,1fr) minmax(145px,190px) 72px 72px;gap:10px;padding-left:11px;padding-right:11px}}
@media(max-width:1000px){.fleet-live-rows{grid-template-columns:minmax(0,1fr)}.fleet-live-account{grid-template-columns:minmax(100px,1fr) minmax(175px,210px) 90px 90px}}
@media(max-width:640px){
 html:root:root:not(.conly) .hdr>.hdrctl{order:3;flex:1 1 100%!important;flex-basis:100%!important;width:100%;gap:6px!important;justify-content:space-between!important}
 html:root:root:not(.conly) .hdr>.hdrbtns{order:2}
 .hdr .cxgrp{flex:1;min-width:0;max-width:calc(100% - 160px)}.hdr .cxbtn{max-width:100%;min-width:0;padding-left:2px;padding-right:2px;gap:4px}
 .hdr .cxbtnname{min-width:0;max-width:100%!important;font-size:12px!important;overflow:hidden;text-overflow:ellipsis}
 .hdr #fleetGeneralGear,.hdr #fleetProfilesBtn,.hdr #rfBtn{width:29px;height:29px;padding:6px}
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
/* На ПК весь обычный каталог виден сразу, без прокрутки внутри меню. */
#cxMenu.fleet-profile-desktop .fleet-palette-header{padding:10px 14px;gap:12px;min-height:0}
#cxMenu.fleet-profile-desktop .fleet-palette-heading{display:flex;align-items:center;gap:12px}
#cxMenu.fleet-profile-desktop .fleet-palette-heading h2{font-size:16px;line-height:1.4;margin:0;white-space:nowrap}
#cxMenu.fleet-profile-desktop .fleet-palette-current{font-size:11px;max-width:46%}
#cxMenu.fleet-profile-desktop .fleet-palette-tools{padding:8px 14px;gap:8px}
#cxMenu.fleet-profile-desktop .fleet-profile-search{height:34px;min-height:34px;font-size:13px;padding-top:7px;padding-bottom:7px}
#cxMenu.fleet-profile-desktop .fleet-palette-search::before{top:6px}
#cxMenu.fleet-profile-desktop .fleet-profile-compare{height:34px;min-height:34px;padding:7px 10px;font-size:11px}
#cxMenu.fleet-profile-desktop>.cxpbody{padding:0 14px 12px}
#cxMenu.fleet-profile-desktop #cxp{gap:8px}
#cxMenu.fleet-profile-desktop .cxplist{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
#cxMenu.fleet-profile-desktop .fleet-profile-card{min-height:0;padding:12px}
#cxMenu.fleet-profile-desktop .fleet-profile-card-head{min-height:0;margin-bottom:7px}
#cxMenu.fleet-profile-desktop .fleet-profile-card-head .cxpr{display:none}
#cxMenu.fleet-profile-desktop .fleet-profile-card .cxpn{margin-bottom:6px}
#cxMenu.fleet-profile-desktop .fleet-profile-card .cxpnm{font-size:15px;line-height:1.4}
#cxMenu.fleet-profile-desktop .fleet-profile-card .cxps{font-size:12px;line-height:1.5}
#cxMenu.fleet-profile-desktop .fleet-profile-meta{margin-top:8px;gap:5px}
#cxMenu.fleet-profile-desktop .fleet-profile-meta>span{padding:3px 5px}
#cxMenu.fleet-profile-desktop .fleet-profile-card-footer{margin-top:9px;padding-top:8px;min-height:26px}
#cxMenu.fleet-profile-desktop .fleet-profile-card .fleet-profile-more{height:26px;min-height:26px;padding:5px 7px}
#cxMenu.fleet-profile-desktop .fleet-profile-service-heading{font-size:10px;margin:2px 0 0}
#cxMenu.fleet-profile-desktop .mirror-service{min-height:0;padding:10px 12px;gap:12px}
#cxMenu.fleet-profile-desktop .mirror-service .cxps{font-size:12px;line-height:1.5;margin-top:4px}
#cxMenu.fleet-profile-desktop .mirror-service-actions{gap:6px}
#cxMenu.fleet-profile-desktop .mirror-service-actions>button{min-height:27px;padding:5px 8px}
#cxMenu.fleet-profile-desktop .fleet-palette-footer{padding:8px 14px;font-size:10px}
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

/* У каждого исполнителя свой профиль; одна структура, два цвета. */
.mirror-profile-footer{grid-column:1/-1;grid-row:2;display:flex;align-items:center;gap:12px;justify-content:space-between;border-top:1px solid var(--fleet-line);padding-top:8px;min-width:0}
.mirror-profile-holder{flex:1;min-width:0;max-width:70%}.mirror-profile-holder #cxGrp{display:flex;width:100%;min-width:0;border:0;background:transparent}
.mirror-profile-footer .mirror-profile-button{display:flex;align-items:center;width:100%;max-width:100%;min-width:0;height:30px;margin:0;padding:5px 8px;gap:6px;background:var(--bg);border:1px solid var(--fleet-line);border-radius:6px;color:var(--txt);font-size:12px;box-shadow:none;justify-content:flex-start}
.mirror-profile-button .cxbtnname{font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;max-width:none}.mirror-profile-button .cxcar{margin-left:auto;width:13px;height:13px;flex:none}.mirror-profile-button>svg:first-child{width:14px;height:14px;flex:none}
.mirror-profile-footer .cxlim{display:none!important}
.fleet-live-account[data-provider="claude"]{border-color:color-mix(in srgb,var(--fleet-claude) 38%,var(--fleet-line));background:linear-gradient(120deg,var(--fleet-claude-soft),var(--card) 60%)}
.fleet-live-account[data-provider="codex"]{border-color:color-mix(in srgb,var(--fleet-accent) 38%,var(--fleet-line));background:linear-gradient(120deg,var(--fleet-accent-soft),var(--card) 60%)}
.fleet-live-account[data-provider="claude"] .mirror-profile-button{border-color:color-mix(in srgb,var(--fleet-claude) 40%,var(--fleet-line))}.fleet-live-account[data-provider="codex"] .mirror-profile-button{border-color:color-mix(in srgb,var(--fleet-accent) 40%,var(--fleet-line))}
.mirror-pair-summary{font-size:10px;color:var(--fleet-muted);margin-left:auto;line-height:1.4}
html:root:root #cxMenu[data-engine="claude"]{--fleet-accent:var(--fleet-claude);--fleet-accent-soft:var(--fleet-claude-soft);--acc:var(--fleet-claude)}
#cxMenu[data-engine="claude"] .fleet-profile-card{border-color:color-mix(in srgb,var(--fleet-claude) 40%,var(--fleet-line));background:color-mix(in srgb,var(--fleet-claude-soft) 40%,var(--bg))}
#cxMenu[data-engine="claude"] .fleet-profile-card.act{border-color:var(--fleet-claude);background:linear-gradient(140deg,var(--fleet-claude-soft),var(--bg) 85%)}
.mirror-profile-tabs{display:flex;gap:6px;align-items:center}.mirror-profile-tabs button{margin:0;padding:3px 8px;border:1px solid var(--fleet-line);border-radius:5px;background:transparent;color:var(--fleet-muted);font-size:10px;font-weight:550;letter-spacing:.04em;box-shadow:none}
.mirror-profile-tabs [data-mirror-tab="claude"][aria-selected="true"]{color:var(--fleet-claude);border-color:var(--fleet-claude);background:var(--fleet-claude-soft)}.mirror-profile-tabs [data-mirror-tab="codex"][aria-selected="true"]{color:#45d6ab;border-color:#45d6ab;background:#16352e}
#cxMenu .mirror-service{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:14px;border:1px solid var(--fleet-line);border-radius:9px;background:color-mix(in srgb,var(--fleet-accent-soft) 30%,var(--card));margin:0}
.mirror-service-copy{flex:1;min-width:0}.mirror-service-copy>strong{font-size:13px;font-weight:600;color:var(--txt)}#cxMenu .mirror-service .cxps{display:block;font-size:12px;line-height:1.55;color:var(--fleet-muted);margin:5px 0 0;-webkit-line-clamp:unset}
.mirror-service-actions{display:flex;flex-direction:column;align-items:stretch;gap:7px;flex:none}.mirror-service-actions button,#cxMenu .mirror-service .cxpinfo button{font-size:11px;padding:7px 9px;background:transparent;border:1px solid var(--fleet-line);border-radius:6px;color:var(--txt);margin:0;box-shadow:none}
#cxMenu .mirror-service .cxpinfo{font-size:12px;line-height:1.6;padding:12px 0 0;border-top:1px solid var(--fleet-line);margin-top:12px;background:transparent}
.mirror-flow{display:flex;align-items:center;gap:5px;flex-wrap:wrap;margin:0 0 10px}.mirror-flow span{padding:2px 6px;border:1px solid var(--fleet-line);border-radius:4px;font-size:10px;color:var(--fleet-accent)}.mirror-flow i{font-style:normal;color:var(--fleet-muted)}
#cxMenu .cxpinfo p{margin:8px 0;font-size:12px;line-height:1.55}.mirror-service small{display:block;color:var(--fleet-muted);font-size:11px;margin-top:7px}
#cxMenu[aria-busy="true"] .cxpbody{pointer-events:none;opacity:.7}
.mirror-confirm[data-engine="claude"]{--mirror-color:var(--fleet-claude)}.mirror-confirm[data-engine="codex"]{--mirror-color:var(--fleet-accent)}.mirror-confirm h3{color:var(--mirror-color)}.mirror-confirm #mirrorConfirmApply{background:var(--mirror-color);color:var(--bg)}
@media(min-width:1100px) and (min-height:700px){html:not(.conly) body.fleet-mirror #termBox{height:clamp(320px,calc(100dvh - 470px),610px)!important;min-height:320px!important}}
@media(max-width:640px){.mirror-profile-footer{grid-row:3;gap:7px;padding-top:7px}.mirror-profile-holder{max-width:none;flex:1}.mirror-profile-footer .mirror-profile-button{font-size:11px;padding:5px 6px;height:29px;gap:4px}.mirror-profile-button .cxbtnname{font-size:11px}.mirror-profile-button>svg:first-child{display:none}.mirror-pair-summary{max-width:55%;font-size:9px;text-align:right}#cxMenu .mirror-service{padding:11px;gap:9px}.mirror-service-copy>strong{font-size:12px}.mirror-service-actions button{font-size:10px;padding:6px}}

.mirror-profile-holder #cxGrp{border-radius:6px;overflow:visible}.mirror-profile-footer .mirror-profile-button{border-radius:6px!important}
#cxMenu .mirror-service{opacity:1;cursor:default}#cxMenu .mirror-service *{pointer-events:auto}
#cxMenu .mirror-service .mirror-service-copy{opacity:1}#cxMenu .mirror-service strong{color:var(--txt)}
#cxMenu .mirror-service-state{display:inline-block;font-size:10px;color:var(--fleet-accent);margin-left:10px}
.mirror-auto-settings{display:flex;flex-direction:column;align-items:flex-start;gap:9px;padding-top:8px}.mirror-auto-settings label{display:flex;align-items:flex-start;gap:8px;color:var(--txt);font-size:12px;line-height:1.5;cursor:pointer}.mirror-auto-settings input{width:15px;height:15px;flex:none;margin:2px 0 0;accent-color:var(--fleet-accent)}
#cxMenu .mirror-auto-settings small{margin:0;font-size:11px;line-height:1.6}
.fleet-live-account[data-provider="claude"] .mirror-profile-button .cxdot{background:var(--fleet-claude)}
@media(max-width:640px){.mirror-profile-button .cxbtnname{max-width:none!important}.mirror-service-copy>strong{display:block}.mirror-service-state{margin:5px 0!important}}

.mirror-task-button{margin:0;padding:3px 7px;min-height:23px;border:1px solid var(--fleet-line);border-radius:5px;font-size:10px;background:var(--card);color:var(--txt);box-shadow:none}.mirror-task-button[data-status="pending"]{border-color:var(--warn);color:var(--warn)}.mirror-task-button[hidden]{display:none}.mirror-task-text{white-space:pre-wrap;overflow-wrap:anywhere;max-height:45vh;overflow:auto;background:var(--bg);border:1px solid var(--fleet-line);border-radius:7px;padding:12px;font-size:12px;line-height:1.6}@media(max-width:640px){.fleet-live-head{flex-wrap:wrap}.mirror-task-button{font-size:10px;margin-left:auto}}
/* Reset times stay visible, with an explicit control in both disclosure states. */
.fleet-live-timezone{margin-left:auto;color:var(--fleet-muted);font-size:10px;white-space:nowrap}
.fleet-live-fold{border:1px solid var(--fleet-line);border-radius:9px;background:var(--card);min-width:0}
.fleet-live-summary{display:grid;grid-template-columns:minmax(0,max-content) max-content max-content minmax(0,1fr);align-items:center;gap:0 24px;position:relative;list-style:none;padding:4px 104px 4px 13px;min-height:40px;cursor:pointer;min-width:0}
.fleet-live-summary::-webkit-details-marker{display:none}
.fleet-live-heading{color:var(--fleet-muted);font-size:10px;font-weight:500;letter-spacing:.025em;line-height:1.5}
.fleet-live-toggle{flex:none;display:inline-flex;align-items:center;justify-content:center;min-height:24px;margin:0;padding:2px 0;border:0;border-radius:0;background:transparent;box-shadow:none;color:var(--fleet-muted);font-size:11px;font-weight:400;line-height:1.4;cursor:pointer;white-space:nowrap}
.fleet-live-expand{position:absolute;right:13px;top:50%;transform:translateY(-50%);margin:0}
.fleet-live-summary:hover .fleet-live-expand{color:var(--txt)}
.fleet-live-footer{display:flex;justify-content:flex-end;padding:2px 13px 0}
.fleet-live-toggle:hover{color:var(--txt);text-decoration:underline;text-underline-offset:3px}
.fleet-live-toggle:focus-visible{outline:2px solid var(--fleet-accent);outline-offset:2px}
.fleet-live-fold[open]{border:0;background:transparent}
.fleet-live-fold[open]>.fleet-live-summary{display:none}
.fleet-live-summary:hover{background:color-mix(in srgb,var(--fleet-muted) 5%,transparent)}
.fleet-live-summary:focus-visible{outline:2px solid var(--fleet-accent);outline-offset:2px;border-radius:8px}
.fleet-live-fold:not([open])>.fleet-live-rows{display:none!important}
.fleet-live-fold[open]>.fleet-live-rows{padding:0;border:0}
.fleet-live-fold[open] .fleet-live-account{grid-template-columns:minmax(100px,1fr) minmax(175px,210px) 165px 270px}
.fleet-live-reset{display:inline-flex;align-items:baseline;gap:4px;min-width:0;font-size:10px;color:var(--txt);font-variant-numeric:tabular-nums}
.fleet-live-reset-label{color:var(--fleet-muted);font-size:9px}
.fleet-live-reset time{white-space:nowrap}
/* [notion-ai] свёрнутая полоса: аккаунты всегда строками, колонки «имя · 5ч · неделя · пометка» выровнены между строками (subgrid) */
.fleet-compact-account{grid-column:1/-1;display:grid;grid-template-columns:subgrid;align-items:center;min-width:0;padding:7px 0;white-space:nowrap;font-size:12px;--live-accent:var(--fleet-claude)}
.fleet-compact-account+.fleet-compact-account{border-top:1px solid var(--fleet-line)}
.fleet-compact-account>*{grid-row:1;min-width:0}
.fleet-compact-account.codex{--live-accent:var(--fleet-accent)}
.fleet-compact-name{grid-column:1;color:var(--live-accent);font-weight:600;font-size:13px;min-width:60px;max-width:200px;overflow:hidden;text-overflow:ellipsis}
.fleet-compact-window[data-window="session"]{grid-column:4}.fleet-compact-window[data-window="week"]{grid-column:5}
.fleet-compact-model,.fleet-compact-effort{display:inline-flex;align-items:center;gap:6px;min-width:0}.fleet-compact-model{grid-column:2}.fleet-compact-effort{grid-column:3}.fleet-compact-model b,.fleet-compact-effort b{font-size:12px;font-weight:600;color:var(--txt);padding:2px 5px;border-radius:4px;background:color-mix(in srgb,var(--live-accent) 12%,transparent)}
.fleet-compact-warning{grid-column:6;color:var(--warn);font-size:10px}.fleet-compact-warning:empty{display:none}
.fleet-compact-window{display:inline-flex;align-items:center;gap:6px;flex:none}
.fleet-compact-label{color:var(--fleet-muted);font-size:11px}
.fleet-compact-used{font-size:12px;font-weight:600;font-variant-numeric:tabular-nums;color:var(--txt);padding:2px 5px;border-radius:4px;background:color-mix(in srgb,var(--live-accent) 12%,transparent)}
.fleet-compact-window[data-tone="bad"] .fleet-compact-used{color:var(--bad);background:color-mix(in srgb,var(--bad) 12%,transparent)}
.fleet-compact-window[data-tone="warn"] .fleet-compact-used{color:var(--warn)}
.fleet-compact-range{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--txt);font-variant-numeric:tabular-nums;white-space:nowrap}
.fleet-compact-arrow{font-style:normal;color:var(--fleet-muted)}
@media(max-width:900px){.fleet-live-summary{display:flex;flex-direction:column;align-items:stretch;gap:0;padding:4px 12px}.fleet-live-expand{position:static;transform:none;order:9;align-self:flex-end}.fleet-compact-account{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px}}
@media(min-width:1501px) and (max-width:1750px){.fleet-live-fold[open] .fleet-live-account{grid-template-columns:minmax(100px,1fr) minmax(160px,190px) 145px 245px;gap:10px}}
@media(max-width:1500px){.fleet-live-fold[open]>.fleet-live-rows{grid-template-columns:minmax(0,1fr)}}
@media(min-width:641px) and (max-width:900px){.fleet-live-fold[open] .fleet-live-account{grid-template-columns:minmax(90px,1fr) minmax(145px,175px) 145px 245px;gap:10px}}
@media(max-width:640px){.fleet-live-timezone{font-size:9px}.fleet-live-summary{padding:10px 30px 10px 10px}.fleet-compact-account{flex-wrap:wrap;gap:7px 10px}.fleet-compact-name{flex-basis:100%;max-width:100%}.fleet-compact-window{flex-basis:100%;gap:6px}.fleet-compact-range{font-size:11px;gap:4px}.fleet-compact-name{font-size:12px}.fleet-live-fold[open]>.fleet-live-rows{padding:0;gap:7px}.fleet-live-fold[open] .fleet-live-account{grid-template-columns:minmax(0,1fr) 82px 110px;gap:4px 10px}.fleet-live-meter-label{flex-wrap:wrap;gap:3px}.fleet-live-meter-label b{font-size:12px}.fleet-live-reset{flex-basis:100%;flex-wrap:wrap;gap:2px;font-size:10px;line-height:1.35}.fleet-live-reset time{white-space:normal}.fleet-live-reset-label{font-size:9px}}
.fleet-live-fold:not([open])>.fleet-live-footer{display:none!important}
/* [notion-ai] аккордеон активных моделей: строки в общей рамке, раскрытая строка — плитка на том же месте */
html:root:root #fleetActiveAccounts.fleet-acc-mode #fleetActiveSummary,html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-live-footer{display:none!important}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-live-fold{border:1px solid var(--fleet-line);border-radius:9px;background:var(--card)}
html:root:root #fleetActiveAccounts.fleet-acc-mode #fleetLiveRows{display:grid;grid-template-columns:minmax(0,max-content) max-content max-content max-content max-content minmax(0,1fr) auto;column-gap:20px;row-gap:0;padding:0 13px}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc{display:contents}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc>.fleet-live-account{grid-column:1/-1;margin:6px -7px}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc:not(.open)>.fleet-live-account,html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc.open>.fleet-compact-account{display:none!important}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc+.fleet-acc>.fleet-compact-account{border-top:1px solid var(--fleet-line)}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account{cursor:pointer;min-height:40px;box-sizing:border-box;border-radius:6px}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account:hover .fleet-acc-chev{color:var(--txt)}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account:focus-visible{outline:2px solid var(--live-accent);outline-offset:-2px}
.fleet-acc-chev{grid-column:7;grid-row:1;justify-self:end;color:var(--fleet-muted);font-size:14px;line-height:1;padding:0 2px}
.fleet-compact-name::before{content:"";display:inline-block;flex:none;width:6px;height:6px;border-radius:50%;background:var(--live-accent);margin-right:7px;vertical-align:2px}
.fleet-acc.open .fleet-live-identity{cursor:pointer}
.fleet-acc.open .fleet-live-name::after{content:"⌃";display:inline-block;margin-left:7px;color:var(--fleet-muted);font-weight:400;font-size:12px;vertical-align:-2px}
.fleet-acc.open .fleet-live-identity:hover .fleet-live-name::after{color:var(--txt)}
@media(max-width:900px){html:root:root #fleetActiveAccounts.fleet-acc-mode #fleetLiveRows{grid-template-columns:minmax(0,1fr);column-gap:0;padding:0 12px}html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account{position:relative;padding:9px 24px 9px 0}.fleet-acc-chev{position:absolute;right:2px;top:12px}}
@media(max-width:640px),(max-width:1000px) and (pointer:coarse){html:root:root #fleetActiveAccounts.fleet-acc-mode #fleetLiveRows{padding:0 10px}html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc>.fleet-live-account{margin:8px -4px}}
@media(max-width:640px){.fleet-live-summary{grid-template-columns:minmax(0,1fr);padding:10px}.fleet-live-expand{grid-column:1;grid-row:auto;justify-self:end;min-height:28px;padding:3px 0 0}.fleet-live-collapse{min-height:30px}.fleet-live-footer{padding-right:10px}}

/* Mobile controls belong to the terminal surface, not to the provider tabs. */
.fleet-console-viewport{display:contents}
@media(max-width:640px),(max-width:1000px) and (pointer:coarse){
 html:root:root:not(.conly) #fleetActiveAccounts{display:block!important;margin:16px 0 22px}
 html:root:root.conly #fleetActiveAccounts{display:none!important}
 html:root:root #fleetActiveSummary,html:root:root #fleetActiveAccounts .fleet-live-footer{display:none!important}
 html:root:root:not(.conly),html:root:root:not(.conly) body{height:auto!important;overflow-y:auto!important;overflow-x:clip}
 html:root:root .fleet-console-toolbar{min-height:40px;padding:0 10px;flex-wrap:nowrap;gap:0}
 html:root:root .fleet-console-toolbar #cTabs{min-height:40px;gap:16px;flex-wrap:nowrap}
 html:root:root .fleet-console-toolbar .ctab{font-size:12px!important;padding:0 4px!important;height:40px!important}
 html:root:root .fleet-console-toolbar #cTabs{flex:1 1 auto;gap:0}
 html:root:root .fleet-console-toolbar #cTabs>.ctab{flex:1 1 auto;min-width:0;justify-content:center}
 html:root:root .fleet-console-viewport{position:relative;display:flex;flex-direction:column;flex:none;width:100%;min-width:0;min-height:0;height:clamp(300px,56svh,440px);padding-top:38px;background:var(--fleet-terminal);overflow:hidden}
 html:root:root .fleet-console-viewport>#termBox{flex:1!important;width:100%;height:100%!important;min-height:0!important;max-height:none!important;margin:0!important;padding:8px 10px 16px!important;border:0;border-radius:0;overflow:auto;overscroll-behavior-y:auto;touch-action:auto;-webkit-overflow-scrolling:touch;font-size:calc(11px * var(--tz,1));line-height:1.55}
 html:root:root .fleet-console-viewport>.tzoom,html:root:root .fleet-console-viewport>.ctacts{position:absolute;top:3px;z-index:4;display:flex;align-items:center;gap:2px;margin:0;padding:0;border:0;border-radius:0;background:transparent;box-shadow:none}
 html:root:root .fleet-console-viewport>.tzoom{left:auto;right:6px}
 html:root:root .fleet-console-viewport>.ctacts{left:6px;right:auto}
 html:root:root .fleet-console-viewport .iconbtn,html:root:root .fleet-console-viewport .tzval{display:inline-flex;align-items:center;justify-content:center;flex:none;width:30px;height:30px;min-height:30px;margin:0;padding:6px;border:0!important;border-radius:0;background:transparent!important;box-shadow:none;color:#91a2b7;font-size:10px;opacity:.7;-webkit-tap-highlight-color:transparent}
 html:root:root .fleet-console-viewport .tzval{width:38px;padding:3px 0}
 html:root:root .fleet-console-viewport .iconbtn svg{width:16px;height:16px}
 html:root:root .fleet-console-viewport .iconbtn:hover,html:root:root .fleet-console-viewport .tzval:hover{opacity:1}
 html:root:root .fleet-console-viewport .iconbtn:focus-visible,html:root:root .fleet-console-viewport .tzval:focus-visible{outline:1px solid var(--fleet-accent);outline-offset:-2px;opacity:1}
 html:root:root .fleet-console-viewport .ctstop[hidden],html:root:root .termwrap:not(.hascacts) .fleet-console-viewport>.ctacts{display:none!important}
 html:root:root .fleet-composer{padding:8px 10px;min-height:54px;gap:8px}
 html:root:root .fleet-composer textarea{font-size:16px;line-height:1.4;min-height:32px;max-height:140px;resize:none}
 html:root:root .fleet-composer #fleetSend{width:32px;height:32px}
 html:root:root .fleet-input-status{min-height:24px;padding:4px 10px;font-size:10px}
 html:root:root .fleet-input-status span:last-child{display:none}
 html:root:root:not(.conly) .dock{display:none!important;pointer-events:none!important}
 /* полный экран на телефоне без нижней кнопки «Аккаунты» — панель была выключена целиком. Язычок стоит над полем ввода (--fleet-dock-lift считает fitDockLift), список открывается касанием. */
 html.conly:root:root .dockzone{pointer-events:none;height:0}
 html.conly:root:root .docktab{pointer-events:auto;bottom:calc(var(--fleet-dock-lift,0px) + 8px);padding:7px 14px;font-size:12px;opacity:.92;z-index:41}
 html.conly:root:root .dockzone:hover .docktab{opacity:.92}html.conly:root:root .dockzone.pin .docktab{opacity:0;pointer-events:none}
 html.conly:root:root .dockzone .dockpanel{max-height:calc(var(--fleet-visual-height,100dvh) - 16px);overflow:auto;padding-bottom:max(12px,env(safe-area-inset-bottom))}
 html.conly:root:root .dockzone:hover .dockpanel{transform:translateY(110%);pointer-events:none}html.conly:root:root .dockzone.pin .dockpanel{transform:none;pointer-events:auto}
 /* на телефоне окно консоли (вкладки, консоль, ввод) тянется до самого низа экрана, «Активные аккаунты» — ниже, после прокрутки.
    Высоту считает fitConsoleFill: высота экрана минус верх окна минус поле. Пока она не посчитана (класс fleet-term-fill), остаётся прежняя. */
 html.fleet-term-fill:root:root:not(.conly) .termwrap{height:var(--fleet-term-fill)!important;min-height:0}
 html.fleet-term-fill:root:root:not(.conly) .termwrap .fleet-console-viewport{flex:1 1 0;height:auto;min-height:150px}
 html:root:root.conly{height:100%;overflow:hidden}
 html:root:root.conly body{height:var(--fleet-visual-height,100dvh)!important;min-height:0!important;overflow:hidden!important;padding:0!important}
 html:root:root.conly .termwrap{flex:1;min-height:0;min-width:0;margin:0!important;overflow:hidden}
 html:root:root.conly .fleet-console-viewport{flex:1;min-height:0;height:auto}
 html:root:root.conly .fleet-console-viewport>#termBox{overscroll-behavior-y:contain}
 html:root:root.conly .fleet-input-status{padding-bottom:max(4px,env(safe-area-inset-bottom))}
}
@media(max-width:640px){
 html:root:root #fleetActiveAccounts .fleet-live-account{grid-template-columns:repeat(2,minmax(0,1fr));grid-template-areas:"identity identity" "controls controls" "session week" "profile profile";gap:10px 12px;padding:12px}
 html:root:root #fleetActiveAccounts .fleet-provider-controls{max-width:none;width:100%}
 html:root:root #fleetActiveAccounts .fleet-provider-controls .fleet-model-tile{flex:1;min-width:0}
 html:root:root #fleetActiveAccounts .fleet-provider-controls .cxmodn{display:block;flex:1;max-width:none;min-width:0}
 html:root:root #fleetActiveAccounts .mirror-profile-footer{grid-area:profile;grid-column:1/-1}
}
@media(max-width:640px),(max-width:1000px) and (pointer:coarse){
 html:root:root #cxMenu.fleet-profile-palette{position:fixed!important;top:var(--fleet-visual-top,0px)!important;left:0!important;right:0!important;bottom:auto!important;width:100%!important;max-width:none!important;height:var(--fleet-visual-height,100dvh)!important;max-height:var(--fleet-visual-height,100dvh)!important;margin:0;border:0;border-radius:0;z-index:1001}
 html:root:root #cxMenuScrim.fleet-profile-backdrop:not([hidden]){position:fixed;inset:0;z-index:1000;touch-action:none}
 html:root:root #cxMenu.fleet-profile-palette>.cxpbody{flex:1 1 auto;min-height:0;overflow-x:hidden;overflow-y:auto;overscroll-behavior:contain;touch-action:pan-y pinch-zoom;-webkit-overflow-scrolling:touch;padding-left:max(12px,env(safe-area-inset-left));padding-right:max(12px,env(safe-area-inset-right));padding-bottom:max(12px,env(safe-area-inset-bottom))}
 html:root:root #cxMenu .fleet-palette-header{padding-top:max(12px,env(safe-area-inset-top));padding-left:max(12px,env(safe-area-inset-left));padding-right:max(12px,env(safe-area-inset-right))}
 html:root:root #cxMenu .fleet-palette-close{width:36px;height:36px}
 html:root:root.fleet-profile-locked{overflow:hidden!important;overscroll-behavior:none}
 html:root:root.fleet-profile-locked body{position:fixed!important;top:var(--fleet-profile-page-top,0px)!important;left:0;right:0;width:100%;overflow:hidden!important}
}
/* Один общий монолит вместо боковых меню. */
#cxMenu.mono-profile-window{width:min(1040px,calc(100vw - 24px));border-radius:12px}
#cxMenu.mono-profile-window .mirror-profile-tabs,#cxMenu.mono-profile-window .fleet-profile-compare,#cxMenu.mono-profile-window .fleet-profile-service-heading{display:none!important}
#cxMenu.mono-profile-window .fleet-palette-header{padding:14px 18px;border-bottom:1px solid var(--fleet-line);background:var(--card)}
#cxMenu.mono-profile-window .fleet-palette-tools{padding:12px 18px}
#cxMenu.mono-profile-window .fleet-palette-tools[hidden]{display:none}
#cxMenu.mono-profile-window>.cxpbody{padding:0;min-height:0}
#cxMenu.mono-profile-window #cxp{display:block;gap:0}
.mono-provider-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}
.mono-provider{min-width:0;--fleet-accent:#45d6ab;--fleet-accent-soft:#16352e}
.mono-provider[data-engine="claude"]{--fleet-accent:var(--fleet-claude);--fleet-accent-soft:var(--fleet-claude-soft)}
.mono-provider+.mono-provider{border-left:1px solid var(--fleet-line)}
.mono-provider-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 18px;background:color-mix(in srgb,var(--fleet-accent) 5%,var(--card));border-top:1px solid var(--fleet-line);border-bottom:1px solid var(--fleet-line)}
.mono-provider-head strong{font-size:15px;color:var(--fleet-accent)}.mono-provider-head span{font-size:10px;color:var(--fleet-muted);text-align:right;line-height:1.5}
#cxMenu.mono-profile-window .cxplist{display:block}
#cxMenu.mono-profile-window .fleet-profile-card{border:0;border-bottom:1px solid var(--fleet-line);border-radius:0;min-height:0;padding:13px 18px;background:transparent}
#cxMenu.mono-profile-window .fleet-profile-card.act{border:0;border-bottom:1px solid var(--fleet-line);box-shadow:inset 3px 0 var(--fleet-accent);background:color-mix(in srgb,var(--fleet-accent) 6%,var(--card))}
.mono-mode-head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:7px}.mono-mode-kind{color:var(--fleet-accent);font-size:9px;letter-spacing:.1em}.mono-mode-status{font-size:10px;color:var(--fleet-muted)}
#cxMenu.mono-profile-window .fleet-profile-card .cxpn{margin:0 0 5px;padding:0}
#cxMenu.mono-profile-window .fleet-profile-card .cxpnm{font-size:15px}
#cxMenu.mono-profile-window .fleet-profile-card .cxps{font-size:12px;line-height:1.55}
#cxMenu.mono-profile-window .fleet-profile-card-footer{border:0;padding:0;margin-top:8px;min-height:26px}
#cxMenu.mono-profile-window .fleet-profile-more{min-height:26px;font-size:11px;padding:5px 8px}
.mono-window-note{border-top:1px solid var(--fleet-line);padding:10px 18px;font-size:10px;line-height:1.6;color:var(--fleet-muted)}
.mono-agent .dlginp{height:34px;min-height:34px;font-size:12px;padding:7px 9px;margin:0}.mono-agent .cxbrow button{height:34px;min-height:34px;padding:7px 10px;font-size:11px;margin:0}
.mono-notion-help{grid-column:1/-1;font-size:11px;color:var(--fleet-muted);margin-top:5px}.mono-notion-help>summary{cursor:pointer}.mono-notion-help .ntsteps{font-size:11px;line-height:1.6}.mono-notion-help .ntnote{font-size:11px}
@media(max-width:700px){
 .mono-provider-grid{grid-template-columns:minmax(0,1fr)}.mono-provider+.mono-provider{border-left:0;border-top:1px solid var(--fleet-line)}
 #cxMenu.mono-profile-window .fleet-palette-current{font-size:10px;max-width:46%}#cxMenu.mono-profile-window .fleet-palette-heading h2{font-size:16px;white-space:normal}
 .mono-provider-head{padding:11px 13px}#cxMenu.mono-profile-window .fleet-profile-card,#cxMenu.mono-profile-window .mono-reserve{padding:12px 13px}.mono-reserve-config,.mono-agent{padding:13px}
 .mono-agent>header,.mono-reserve-status{align-items:flex-start;flex-wrap:wrap}.mono-auto{font-size:13px}
}


.mono-agent>header span{min-width:0;max-width:100%;overflow-wrap:anywhere}.mono-notion-help code{white-space:normal;overflow-wrap:anywhere}
@media(max-width:700px){.mono-agent .dlginp{font-size:16px;min-height:38px;height:38px}}

/* Ручная сборка одного сценария без автоматического назначения второй роли. */
#cxMenu.mono-profile-window .manual-role{transition:background .15s ease}
#cxMenu.mono-profile-window .manual-role[aria-disabled="true"]{background:color-mix(in srgb,var(--card) 90%,var(--fleet-line));cursor:not-allowed}
#cxMenu.mono-profile-window .manual-role[aria-disabled="true"] .mono-mode-head,
#cxMenu.mono-profile-window .manual-role[aria-disabled="true"] .cxpt,
#cxMenu.mono-profile-window .manual-role[aria-disabled="true"] .mono-reserve-copy,
#cxMenu.mono-profile-window .manual-role[aria-disabled="true"] .fleet-profile-choose{opacity:.55}
#cxMenu.mono-profile-window .manual-role[aria-disabled="true"] .fleet-profile-more{opacity:1}
#cxMenu.mono-profile-window .manual-role.act{background:color-mix(in srgb,var(--fleet-accent) 7%,var(--card));box-shadow:inset 3px 0 var(--fleet-accent)}
#cxMenu.mono-profile-window .manual-role:focus-visible{outline:2px solid var(--fleet-accent);outline-offset:-3px}
#cxMenu.mono-profile-window .manual-role.fleet-profile-card{padding:10px 16px}
#cxMenu.mono-profile-window .manual-role .mono-mode-head{margin-bottom:4px;min-height:14px}
#cxMenu.mono-profile-window .manual-role .cxpnm{font-size:14px}
#cxMenu.mono-profile-window .manual-role .cxps{font-size:11px;line-height:1.5;min-height:33px}
#cxMenu.mono-profile-window .manual-role .fleet-profile-card-footer{min-height:23px;margin-top:3px}
#cxMenu.mono-profile-window .manual-role .fleet-profile-more{min-height:23px;font-size:10px;padding:3px 7px}
#cxMenu.mono-profile-window .manual-role .fleet-profile-choose{font-size:10px}
.manual-compatibility{margin:0;padding:8px 16px;font-size:11px;line-height:1.5;min-height:33px;color:var(--fleet-muted);border-bottom:1px solid var(--fleet-line)}
.manual-compatibility[data-blocked="true"]{color:var(--fleet-accent)}
.manual-apply-bar{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:15px;padding:13px 16px;border-top:1px solid var(--fleet-line);background:var(--card)}
.manual-selection-summary{display:flex;flex-direction:column;gap:5px;min-width:0;font-size:11px;line-height:1.5;color:var(--fleet-muted)}
.manual-selection-summary strong{font-size:12px;font-weight:600;color:var(--txt)}
.manual-scenario-actions{display:flex;align-items:center;gap:7px;flex-wrap:wrap;justify-content:flex-end}
.manual-scenario-actions button{font-size:11px;padding:8px 10px;border-radius:6px;min-height:33px;margin:0;box-shadow:none}
.manual-scenario-actions .ghostbtn{color:var(--fleet-muted);background:transparent;border:1px solid var(--fleet-line)}
.manual-scenario-actions .manual-apply{background:#45d6ab;color:#0c1816;border:1px solid #45d6ab}
.manual-scenario-actions .manual-apply:disabled{background:transparent;color:var(--fleet-muted);border-color:var(--fleet-line);opacity:.65;cursor:default}
@media(max-width:700px){
 #cxMenu.mono-profile-window .manual-provider-grid .mono-provider-head{padding:10px 13px;flex-wrap:wrap}
 #cxMenu.mono-profile-window .manual-provider-grid .mono-provider-head span{font-size:9px}
 .manual-compatibility{padding:8px 13px;min-height:0}
 #cxMenu.mono-profile-window .manual-role.fleet-profile-card,#cxMenu.mono-profile-window .mono-reserve.manual-role{padding:11px 13px}
 #cxMenu.mono-profile-window .manual-role .fleet-profile-more{min-height:30px;padding:6px 9px}
 .manual-apply-bar{grid-template-columns:minmax(0,1fr);padding:12px 13px;gap:10px}
 .manual-scenario-actions{justify-content:stretch}.manual-scenario-actions button{flex:1;min-height:36px}
 .manual-scenario-actions .manual-apply{flex-basis:100%}
}

/* One complete scenario fits a desktop viewport without shrinking mobile touch controls. */
#cxMenu.mono-profile-window.fleet-profile-desktop .fleet-palette-header{padding:8px 14px}
#cxMenu.mono-profile-window.fleet-profile-desktop .mono-provider-head{padding:8px 14px}
#cxMenu.mono-profile-window.fleet-profile-desktop .manual-compatibility{padding:6px 14px;min-height:0}
#cxMenu.mono-profile-window.fleet-profile-desktop .manual-role.fleet-profile-card{padding:7px 14px}
#cxMenu.mono-profile-window.fleet-profile-desktop .manual-role .mono-mode-head{margin-bottom:2px;min-height:12px}
#cxMenu.mono-profile-window.fleet-profile-desktop .manual-role .cxpnm{font-size:14px;line-height:1.3}
#cxMenu.mono-profile-window.fleet-profile-desktop .manual-role .fleet-profile-card-footer{margin-top:2px;min-height:23px}
#cxMenu.mono-profile-window.fleet-profile-desktop .manual-role .cxps{min-height:0}
#cxMenu.mono-profile-window.fleet-profile-desktop .manual-role .fleet-profile-more{height:23px;min-height:23px}
#cxMenu.mono-profile-window.fleet-profile-desktop .manual-role .cxpn{margin-bottom:3px}
#cxMenu.mono-profile-window.fleet-profile-desktop .manual-apply-bar{padding:10px 14px}
#cxMenu.mono-profile-window .manual-apply-bar{position:sticky;bottom:0;z-index:2}
#cxMenu.mono-profile-window .manual-selection-summary strong{line-height:1.4}

/* Два профиля Full с однозначным выбранным состоянием. */
#cxMenu.mono-profile-window .full-choice{position:relative;width:calc(100% - 28px)!important;max-width:calc(100% - 28px);min-height:190px;margin:14px!important;padding:18px!important;border:2px solid var(--fleet-line);border-radius:10px;background:var(--bg);box-shadow:none;cursor:pointer}
#cxMenu.mono-profile-window .full-choice.act{border:2px solid var(--fleet-accent);background:color-mix(in srgb,var(--fleet-accent) 16%,var(--bg));box-shadow:inset 4px 0 var(--fleet-accent),0 0 0 1px color-mix(in srgb,var(--fleet-accent) 25%,transparent)}
.full-choice-top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}
.full-choice-check{display:grid;place-items:center;width:26px;height:26px;border:2px solid var(--fleet-muted);border-radius:50%;color:transparent;font-size:17px;font-weight:750;line-height:1;flex:none}
.full-choice.act .full-choice-check{background:var(--fleet-accent);border-color:var(--fleet-accent);color:#0b1714}
.full-choice-badge{font-size:11px;line-height:1.4;color:var(--fleet-muted);padding:4px 8px;border-radius:5px}
.full-choice.act .full-choice-badge{background:var(--fleet-accent);color:#0b1714;font-weight:700}
#cxMenu.mono-profile-window .manual-role.full-choice .cxpnm{font-size:19px;line-height:1.35;font-weight:650}
#cxMenu.mono-profile-window .full-choice .cxps{font-size:12px;line-height:1.6;min-height:0}
#cxMenu.mono-profile-window .full-choice .fleet-profile-card-footer{margin-top:16px;padding-top:10px;border-top:1px solid var(--fleet-line)}
#cxMenu.mono-profile-window .full-choice.act .fleet-profile-card-footer{border-color:color-mix(in srgb,var(--fleet-accent) 40%,var(--fleet-line))}
#cxMenu.mono-profile-window .full-choice.act .fleet-profile-choose{font-weight:650;color:var(--fleet-accent)}
@media(max-width:700px){#cxMenu.mono-profile-window .full-choice{width:calc(100% - 24px)!important;max-width:calc(100% - 24px);margin:12px!important;min-height:0;padding:15px!important}.full-choice-top{margin-bottom:10px}#cxMenu.mono-profile-window .full-choice .cxpnm{font-size:18px}}

/* Full другой модели недоступен при выбранном оркестраторе. */
#cxMenu.mono-profile-window .full-choice[aria-disabled="true"]{border-color:var(--fleet-line);background:var(--bg);cursor:not-allowed}
#cxMenu.mono-profile-window .full-choice[aria-disabled="true"] .cxpt,#cxMenu.mono-profile-window .full-choice[aria-disabled="true"] .full-choice-top,#cxMenu.mono-profile-window .full-choice[aria-disabled="true"] .fleet-profile-choose{opacity:.48}
.manual-companion{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px;margin:6px 14px 10px;padding:8px 10px;border:1px solid var(--fleet-accent);border-radius:7px;background:color-mix(in srgb,var(--fleet-accent) 7%,var(--bg));font-size:11px;line-height:1.4;color:var(--fleet-muted)}
.manual-companion button{margin:0;padding:5px 8px;min-height:27px;background:transparent;border:1px solid var(--fleet-accent);border-radius:5px;color:var(--fleet-accent);font-size:11px;box-shadow:none}
.manual-companion button[aria-pressed="true"]{background:var(--fleet-accent);color:#0b1714}
#cxMenu.mono-profile-window.fleet-profile-desktop .full-choice{min-height:0;margin:8px 14px!important;padding:10px 14px!important}
#cxMenu.mono-profile-window.fleet-profile-desktop .full-choice-top{margin-bottom:6px}
#cxMenu.mono-profile-window.fleet-profile-desktop .full-choice-check{width:22px;height:22px;font-size:15px}
#cxMenu.mono-profile-window.fleet-profile-desktop .manual-role.full-choice .cxpnm{font-size:16px;line-height:1.3}
#cxMenu.mono-profile-window.fleet-profile-desktop .full-choice .cxps{font-size:11.5px;line-height:1.5}
#cxMenu.mono-profile-window.fleet-profile-desktop .full-choice .fleet-profile-card-footer{padding-top:6px}
@media(max-width:700px){#cxMenu.mono-profile-window .full-choice{padding:13px!important}.full-choice-top{margin-bottom:7px}.manual-companion{margin:6px 12px 12px}.manual-companion button{min-height:34px}}



html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account{padding-left:8px}
/* Ровная рамка по всей ширине и одинаковые компактные шевроны. */
html:root:root #fleetActiveAccounts.fleet-acc-mode #fleetLiveRows{padding-left:0;padding-right:0}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account{padding-left:14px;padding-right:14px}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc>.fleet-live-account{margin:6px 0}
.fleet-acc-chev{display:block;width:7px;height:7px;padding:0;margin:0 3px 4px 0;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:rotate(45deg);font-size:0}
.fleet-acc.open .fleet-live-name::after{content:"";width:6px;height:6px;margin-left:9px;border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:rotate(225deg);vertical-align:0}
@media(max-width:900px){html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account{padding-left:14px;padding-right:32px}.fleet-acc-chev{right:18px;top:16px}}
/* Управление аккаунтами свёрнуто до явного открытия. */
.fleet-accounts-fold>.fleet-accounts-intro{display:flex;justify-content:space-between;align-items:center;gap:12px;min-height:48px;padding:10px 14px;margin:0;cursor:pointer;list-style:none;border:1px solid var(--fleet-line);border-radius:9px;background:var(--card)}
.fleet-accounts-fold>.fleet-accounts-intro::-webkit-details-marker{display:none}
.fleet-accounts-fold>.fleet-accounts-intro:focus-visible{outline:2px solid var(--fleet-accent);outline-offset:2px}
.fleet-accounts-fold[open]>.fleet-accounts-intro{margin-bottom:18px}
.fleet-accounts-heading{display:block;color:var(--txt);font-size:18px;font-weight:550;line-height:1.35;margin-top:3px}
.fleet-accounts-chevron{flex:none;width:8px;height:8px;margin:0 4px 5px 0;color:var(--fleet-muted);border-right:1.5px solid currentColor;border-bottom:1.5px solid currentColor;transform:rotate(45deg)}
.fleet-accounts-fold[open] .fleet-accounts-chevron{transform:rotate(225deg);margin-bottom:0}
html:root:root.ag-live-claude #fleetActiveAccounts .fleet-compact-account.claude,html:root:root.ag-live-codex #fleetActiveAccounts .fleet-compact-account.codex,html:root:root.ag-live-notion #fleetActiveAccounts .fleet-compact-account.notion{box-shadow:inset 0 0 0 1px #49d6aa}
html:root:root.ag-live-claude #fleetActiveAccounts .fleet-live-account.claude,html:root:root.ag-live-codex #fleetActiveAccounts .fleet-live-account.codex,html:root:root.ag-live-notion #fleetActiveAccounts .fleet-live-account.notion{border-color:#49d6aa}

/* Сверху только название и аккаунт; все показатели и управление — ниже. */
html:root:root #fleetActiveAccounts .fleet-live-account{grid-template-columns:minmax(0,1fr);grid-template-areas:"identity" "profile"}
html:root:root #fleetActiveAccounts .mirror-profile-footer{grid-area:profile;grid-column:1/-1;display:flex;justify-content:flex-start;gap:10px;min-width:0}
html:root:root #fleetActiveAccounts .mirror-profile-holder{flex:0 1 360px;max-width:360px;min-width:0}
html:root:root #fleetActiveAccounts .mirror-profile-footer .fleet-provider-controls{flex:0 1 210px;width:210px;max-width:210px;min-width:0}
html:root:root #fleetActiveAccounts .mirror-profile-footer .fleet-live-meter{flex:1 1 170px;min-width:0}
html:root:root #fleetActiveAccounts .mirror-profile-footer .fleet-live-meter[data-window="week"]{flex-basis:240px}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-live-account.notion .nai-live-note{flex:1 1 260px;min-width:0}
@media(max-width:900px){
 html:root:root #fleetActiveAccounts .mirror-profile-footer{flex-wrap:wrap;gap:10px}
 html:root:root #fleetActiveAccounts .mirror-profile-holder{flex:1 1 calc(50% - 5px);max-width:none}
 html:root:root #fleetActiveAccounts .mirror-profile-footer .fleet-provider-controls{flex:1 1 calc(50% - 5px);width:auto;max-width:none}
 html:root:root #fleetActiveAccounts .mirror-profile-footer .fleet-live-meter,html:root:root #fleetActiveAccounts .mirror-profile-footer .fleet-live-meter[data-window="week"]{flex:1 1 calc(50% - 5px)}
 html:root:root #fleetActiveAccounts .mirror-profile-footer .mirror-profile-button{height:auto;min-height:34px}
 html:root:root #fleetActiveAccounts .mirror-profile-button .cxbtnname{white-space:normal;line-height:1.25;overflow-wrap:anywhere}
 html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-live-account.notion .nai-live-note{flex:1 1 100%}
}

/* ===== Активные аккаунты: полоса =====
   Ячейки в ряд, у каждой: статус и имя | Модель, Effort, 5ч, Неделя, дата сброса, стрелка. Рамка активного лежит на границе своей ячейки:
   без внешней тени и отрицательных отступов, поэтому ничего не перекрывает. Две ячейки в ряд — от 1260 px (см. ниже), уже — по одной. */
#fleetActiveAccounts{--cal:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='none' stroke='black' stroke-width='1.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='2' y='3' width='12' height='11' rx='2'/%3E%3Cpath d='M2 6.5h12M5.5 1.8v2.4M10.5 1.8v2.4'/%3E%3C/svg%3E")}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode #fleetLiveRows{display:grid;grid-template-columns:minmax(0,1fr);gap:6px;padding:6px}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc{display:block;min-width:0}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc.open{grid-column:1/-1}
/* в одну строку идут только аккаунты Claude (Claude DEV и PROD); Codex и Notion AI — каждый на всю ширину */
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc:has(>.fleet-compact-account.codex),
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc:has(>.fleet-compact-account.notion){grid-column:1/-1}
/* второй сервер не подключён (Claude PROD скрыт) — строка Claude одна и занимает всю ширину; появится второй — обе встанут рядом */
html.no-prod:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc[data-engine="claude"]{grid-column:1/-1}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc>.fleet-live-account{margin:0}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc+.fleet-acc>.fleet-compact-account{border-top:1px solid var(--fleet-line)}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account{box-sizing:border-box;min-height:42px;padding:0 14px;border:1px solid var(--fleet-line);border-radius:8px;background:rgba(8,10,14,.35);box-shadow:none}
html:root:root:root.ag-live-claude #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.claude,
html:root:root:root.ag-live-prod #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.prod,
html:root:root:root.ag-live-codex #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.codex,
html:root:root:root.ag-live-notion #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.notion{border-color:#49d6aa;box-shadow:none}
html:root:root:root.ag-live-claude #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.claude .fleet-compact-name::before,
html:root:root:root.ag-live-prod #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.prod .fleet-compact-name::before,
html:root:root:root.ag-live-codex #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.codex .fleet-compact-name::before,
html:root:root:root.ag-live-notion #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.notion .fleet-compact-name::before{background:#49d6aa}
/* «пауза» словом в строке аккаунта не пишем: состояние показывает значок ⏸ перед именем */
html:root:root:root.ag-pause-notion #fleetActiveAccounts .fleet-compact-account.notion .nai-cs{display:none}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="session"] .fleet-compact-range{display:inline-flex;margin-left:2px;color:var(--fleet-muted)}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-model .fleet-compact-label::after,
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-effort .fleet-compact-label::after,
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="week"] .fleet-compact-label::after,
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="model"] .fleet-compact-label::after,
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="effort"] .fleet-compact-label::after{content:":"}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="week"] .fleet-compact-range::before{content:"";flex:none;width:13px;height:13px;background:var(--fleet-muted);-webkit-mask:var(--cal) center/contain no-repeat;mask:var(--cal) center/contain no-repeat}
@media(min-width:901px){
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account{display:flex;flex-wrap:nowrap;align-items:center;gap:0 14px;overflow:hidden;white-space:nowrap}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-name{flex:none;display:inline-flex;align-items:center;max-width:none;height:20px;padding-right:14px;border-right:1px solid var(--fleet-line);font-size:13px}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-warning{flex:none}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-model,
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-effort,
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window{flex:none;display:inline-flex;align-items:center;gap:6px}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="week"] .fleet-compact-range{margin-left:12px;gap:7px}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account .nai-cs{flex:0 1 auto;min-width:0}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc-chev{flex:none;margin:0 3px 4px auto}
}
/* Нижняя панель полного экрана: подсказки PROD, Codex и Notion AI */
.dpop .dsub{margin-top:6px;font-size:11.5px;font-weight:500;color:var(--mut)}
.dchip.dx.paused .dmail,.dchip.paused .dmail{color:var(--mut)}
.dchip.paused:not(.dx) .dmail::after{content:" · пауза";font-weight:500}
/* Стрелка «свернуть» у раскрытой плитки стоит там же, где стрелка «развернуть» у свёрнутой ячейки: у правого края, на той же высоте.
   Отступы повторяют ячейку при тех же границах ширины: 1260–1579 px плотнее, до 900 px — как на телефоне. Клик по стрелке — это клик по названию, плитка сворачивается. «^» повёрнута на 225°, её видимая часть выше центра коробки, поэтому top на 4.5 px больше, чем у «⌄» (замер по снимку 61912). */
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc.open>.fleet-live-account{position:relative}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc.open .fleet-live-name{padding-right:34px}
html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc.open .fleet-live-name::after{position:absolute;right:17px;top:19px;width:7px;height:7px;margin:0;vertical-align:baseline}
@media(min-width:1260px) and (max-width:1579px){html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc.open .fleet-live-name::after{right:14px}}
@media(max-width:900px){html:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc.open .fleet-live-name::after{right:21px;top:20.5px}}
/* Две ячейки (Claude DEV и PROD) в одной строке, пока хватает места (референс владельца: обе ячейки при ширине окна ~1280). Ширина ячейки = (окно − 62) / 2.
   от 1580 px — как есть; 1260–1579 px — плотнее (меньше зазоры и шрифт); 1260–1379 px — ещё и без подписей «Модель:» и «Effort:»; уже — по одной в строке. */
@media(min-width:1260px){html:root:root:root #fleetActiveAccounts.fleet-acc-mode #fleetLiveRows{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(min-width:1260px) and (max-width:1579px){
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account{padding:0 11px;gap:0 9px}
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-name{padding-right:10px;font-size:12.5px}
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-model,
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-effort,
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window{gap:5px}
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-label{font-size:10.5px}
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-model b,
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-effort b,
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-used{font-size:11.5px;padding:2px 4px}
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-range{font-size:11.5px}
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="week"] .fleet-compact-range{margin-left:8px;gap:5px}
}
@media(min-width:1260px) and (max-width:1379px){
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account:not(.notion) .fleet-compact-model .fleet-compact-label,
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account:not(.notion) .fleet-compact-effort .fleet-compact-label{display:none}
  /* есть пометка «проверить»/«устарело» — места на дату сброса не хватает, она остаётся в раскрытой плитке */
  html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account:has(.fleet-compact-warning:not(:empty)) .fleet-compact-window[data-window="week"] .fleet-compact-range{display:none}
}

/* какой профиль выбран — мелкой строкой под именем в свёрнутой строке аккаунта */
.fleet-compact-id{display:flex;flex-direction:column;justify-content:center;gap:2px;min-width:0;grid-column:1}
.fleet-compact-prof{display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding-left:13px;font-size:11px;line-height:13px;font-weight:500;color:var(--fleet-muted)}
.fleet-compact-prof:empty{display:none}
@media(min-width:901px){
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-id{flex:0 0 var(--cid);box-sizing:border-box;max-width:none;padding-right:14px;border-right:1px solid var(--fleet-line)}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-id>.fleet-compact-name{flex:none;max-width:none;padding-right:0;border-right:0}
}
@media(max-width:900px){
 .fleet-compact-id{flex:0 0 100%;max-width:100%}
 .fleet-compact-id>.fleet-compact-name{max-width:100%}
 .fleet-compact-prof::before{content:"Профиль: "}
}

/* колонки свёрнутых строк одной ширины у всех аккаунтов: разделитель после имени и колонки Модель / Effort / 5ч стоят ровно, длинная подпись обрезается многоточием.
   Ширины — по самым длинным значениям (имя + «пауза», GPT-6.1-Sol, «Модель:» у Notion AI), три диапазона плотности как у ячеек выше. */
#fleetActiveAccounts.fleet-acc-mode{--cid:172px;--cmod:130px;--ceff:80px;--cses:112px}
@media(min-width:1380px) and (max-width:1579px){
 #fleetActiveAccounts.fleet-acc-mode{--cid:160px;--cmod:120px;--ceff:74px;--cses:92px}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account{column-gap:7px}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-id{padding-right:10px}
}
/* у Codex сброс 5ч бывает завтра («08.11 00:28»), строка у него на всю ширину, колонке даём место */
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.codex{--cses:128px}
@media(min-width:1260px) and (max-width:1379px){#fleetActiveAccounts.fleet-acc-mode{--cid:156px;--cmod:76px;--ceff:42px;--cses:86px}}
/* DEV и PROD делят строку пополам; после % окна 5ч стоит время сброса, поэтому подписи колонок убираем и здесь */
@media(min-width:1380px) and (max-width:1899px){
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.claude .fleet-compact-model .fleet-compact-label,
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.claude .fleet-compact-effort .fleet-compact-label,
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.prod .fleet-compact-model .fleet-compact-label,
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.prod .fleet-compact-effort .fleet-compact-label{display:none}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.claude,
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.prod{--cmod:80px;--ceff:42px}
}
@media(min-width:1380px) and (max-width:1499px){
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account:has(.fleet-compact-warning:not(:empty)) .fleet-compact-window[data-window="week"] .fleet-compact-range{display:none}
}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-model b,
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-effort b{min-width:0;overflow:hidden;text-overflow:ellipsis}
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-model,
html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-effort{overflow:hidden}
@media(min-width:901px){
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-model,
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="model"]{flex:0 0 var(--cmod)}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-effort,
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="effort"]{flex:0 0 var(--ceff)}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="session"]{flex:0 0 var(--cses)}
}
@media(max-width:900px){
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-model,
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="model"]{flex:0 0 138px}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-effort,
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="effort"]{flex:0 0 90px}
}
@media(min-width:641px) and (max-width:900px){
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="session"]{flex:0 0 54px}
}

/* время сброса окна 5ч («08.11 00:29») налезало на подпись «Неделя»: колонка 5ч была уже своего содержимого (112/92/86/54 px при 120 px текста).
   Теперь колонка не уже содержимого (min-width = запас под «100%» и самое широкое время), остальное сдвигается вправо. Телефон (до 640 px) не затронут. */
@media(min-width:641px){
 #fleetActiveAccounts.fleet-acc-mode{--cses:128px}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="session"]{flex:0 0 auto;min-width:var(--cses)}
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-window[data-window="session"] .fleet-compact-range{white-space:nowrap}
}
@media(min-width:1260px) and (max-width:1579px){#fleetActiveAccounts.fleet-acc-mode{--cses:118px}}
@media(min-width:641px) and (max-width:900px){#fleetActiveAccounts.fleet-acc-mode{--cses:0px}}
/* две плитки в ряд при 1260–1379 px: дата сброса недели остаётся в раскрытой плитке, иначе плитка не помещается */
@media(min-width:1260px) and (max-width:1379px){
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.claude .fleet-compact-window[data-window="week"] .fleet-compact-range,
 html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-compact-account.prod .fleet-compact-window[data-window="week"] .fleet-compact-range{display:none}
}

/* единое окно «Точно? Отмена / Да» для кнопок быстрого доступа (window.fleetAsk) */
.fleet-ask{z-index:100000}.fleet-ask[hidden]{display:none}  /* выше окон плиток агентов (z-index 99999): раньше подтверждение пряталось под ними */
.fleet-ask .cxpbody{padding:14px 16px 16px}
.fleet-ask h3{margin:0 0 6px;font-size:14px;font-weight:600;color:var(--txt)}
.fleet-ask p{margin:0;font-size:12px;line-height:1.5;color:var(--fleet-muted)}
.fleet-ask .fa-btns{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}
.fleet-ask .fa-btns button{height:34px;min-width:80px;padding:0 14px;border-radius:7px;border:1px solid var(--fleet-line);background:var(--bg);color:var(--txt);font:inherit;font-size:12px;font-weight:600;cursor:pointer}
.fleet-ask .fa-btns .fa-yes{border-color:var(--fleet-accent);background:var(--fleet-accent-soft)}
.fleet-ask .fa-btns button:focus-visible{outline:2px solid var(--fleet-accent);outline-offset:2px}

/* ===== Единые окна шестерёнок и моделей: одна прокрутка, окно не сжимается без нужды ===== */
html:root:root:root .fleet-quick-panel:not([hidden]),html:root:root:root .fleet-settings-panel:not([hidden]){display:flex;flex-direction:column;overflow:hidden}
html:root:root:root .fleet-quick-panel[hidden],html:root:root:root .fleet-settings-panel[hidden]{display:none}
html:root:root:root .fleet-quick-panel>.cxpbody,html:root:root:root .fleet-settings-panel>.cxpbody{flex:1 1 auto;min-height:0;overflow-x:hidden;overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:var(--fleet-line) transparent}
html:root:root:root .fleet-quick-panel .cxqlist{max-height:none;overflow:visible}
/* списки моделей внутри окон не прокручиваются сами: прокручивается только окно целиком (раньше — полоса в полосе) */
html:root:root:root .fleet-settings-panel .fleet-model-catalog{max-height:none;overflow:visible}
html:root:root:root #naiModelQ{overflow:hidden}

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
 const menu=document.getElementById('cxMenu');const search=el('input','fleet-profile-search');search.placeholder='Найти профиль…';search.setAttribute('aria-label','Поиск профилей');search.type='search';search.name='profile-filter';search.autocomplete='off';search.spellcheck=false;search.setAttribute('autocapitalize','none');search.setAttribute('autocorrect','off');search.enterKeyHint='search';
 let profileQuery='';
 const note=el('p','fleet-profile-note','Профиль определяет права и способ работы. Аккаунт определяет подписку и лимиты. Активный профиль отмечен галочкой.');menu.prepend(search,note);
 function filterProfiles(){if(search.value!==profileQuery)search.value=profileQuery;const q=profileQuery.trim().toLocaleLowerCase('ru');menu.querySelectorAll('.cxprof').forEach(n=>n.hidden=!!q&&!n.textContent.toLocaleLowerCase('ru').includes(q))}
 search.addEventListener('input',filterProfiles);new MutationObserver(filterProfiles).observe(document.getElementById('cxp'),{childList:true});
 const cxOptions=el('div','fleet-cx-options');cxOptions.innerHTML='<div class="modalh">Codex · пороги оптимизации</div><label>Сессия, % <input id="fleetCxThreshold" type="number" min="50" max="100" value="90"></label><label>Неделя, % <input id="fleetCxCap" type="number" min="50" max="100" value="99"></label><button type="button" id="fleetCxSave">Сохранить</button>';
 document.getElementById('autoNote').after(cxOptions);
 document.getElementById('fleetCxSave').addEventListener('click',async e=>{e.target.disabled=true;try{const d=await post('chatgpt/rotation/config',{threshold:Number(document.getElementById('fleetCxThreshold').value),weekly_cap:Number(document.getElementById('fleetCxCap').value)});toast(d.message);await loadRotation()}catch(err){toast('⚠ '+err.message)}finally{e.target.disabled=false}});
 const stateNode=document.getElementById('fleetInputState'),input=document.getElementById('fleetInput'),send=document.getElementById('fleetSend');
 let rotationData=null;
 async function post(path,body){const r=await fetch(API+path,{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':TOKEN},body:JSON.stringify(body)});const d=await r.json();if(!r.ok||!d.ok){const er=Error(d.message||'Не удалось выполнить действие');er.data=d;throw er}return d}
 // окно ввода: этот же код обслуживает общее окно и окна отдельных частей разделённой консоли (cc_limits.py берёт window.fleetBindComposer); sessionOf() — в какую консоль писать
 function bindComposer(form,input,send,stateNode,sessionOf){
  let sending=false,lastRequest=null;
  form.addEventListener('submit',async e=>{e.preventDefault();if(sending||!input.value.trim())return;const text=input.value;const session=sessionOf();const rid=(lastRequest&&lastRequest.text===text&&lastRequest.session===session?lastRequest.id:(lastRequest={text,session,id:crypto.randomUUID()}).id);const go=async side=>{sending=true;send.disabled=true;stateNode.textContent='Отправляю в '+(session==='codex'?'Codex':session==='prod'?'Claude PROD':'Claude DEV')+'…';let ask='';try{const body={session,text,request_id:rid};if(side)body.side=true;const d=await post('console/input',body);if(input.value===text)input.value='';lastRequest=null;stateNode.textContent=d.message||'Ввод передан в консоль';ccConsole()}catch(err){if(!side&&err.data&&err.data.ask==='side'){ask=err.data.message||'Вкладка на паузе. Написать ей всё равно?';stateNode.textContent=''}else{stateNode.textContent=err.message;toast('⚠ '+err.message)}}finally{sending=false;send.disabled=false}if(ask){const yes=typeof window.fleetAsk==='function'?await window.fleetAsk(send,ask,'Да, написать'):confirm(ask);if(yes)return go(true);stateNode.textContent='Отменено'}};go(false)});
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();form.requestSubmit()}});
  form.querySelector('[data-console-key]').addEventListener('click',async()=>{try{const d=await post('console/key',{session:sessionOf(),key:'escape'});stateNode.textContent=d.message;ccConsole()}catch(e){toast('⚠ '+e.message)}});
 }
 window.fleetBindComposer=bindComposer;
 bindComposer(form,input,send,stateNode,()=>typeof consCur==='function'?consCur():'claude');
 function renderRotation(d){rotationData=d;if(!document.querySelector('.fleet-cx-options:focus-within')){document.getElementById('fleetCxThreshold').value=d.threshold||90;document.getElementById('fleetCxCap').value=d.weekly_cap||99;}document.getElementById('fleetCxOpt').checked=!!d.optimize;rotation.replaceChildren();const text=el('span','',d.message||'Проверка лимитов');rotation.append(text);if(d.next_label)rotation.append(el('span','','Следующий: '+d.next_label));if(d.last_error)rotation.append(el('span','err',d.last_error));
  document.querySelectorAll('#cxcards .card').forEach((c,i)=>{const a=typeof cxData!=='undefined'&&cxData.accounts&&cxData.accounts[i];c.classList.toggle('fleet-active',!!a&&a.slot===d.active);if(!a)return;const top=c.querySelector('.top .email');if(top&&a.slot!==d.active)top.querySelector('.fleet-active-label')?.remove();if(top&&a.slot===d.active&&!top.querySelector('.fleet-active-label'))top.append(el('span','fleet-active-label','Выбран'));const existing=c.querySelector('.fleet-pick');if(existing){existing.textContent=a.slot===d.active?'Выбран':'Выбрать';existing.disabled=a.slot===d.active||!!d.optimize;existing.title=d.optimize?'Ручной выбор доступен при выключенной оптимизации':'';}if(!existing){const b=el('button','btn-sw fleet-pick',a.slot===d.active?'Выбран':'Выбрать');b.disabled=a.slot===d.active||!!d.optimize;b.title=d.optimize?'Ручной выбор доступен при выключенной оптимизации':'';b.onclick=async()=>{b.disabled=true;try{const r=await post('chatgpt/rotation/switch',{slot:a.slot});toast(r.message);loadRotation()}catch(e){toast('⚠ '+e.message);loadRotation()}};const acts=c.querySelector('.acts');if(acts)acts.prepend(b)}});
  refreshVisuals();
 }
 let refreshing=false;async function loadRotation(){if(refreshing)return;refreshing=true;try{const r=await fetch(API+'chatgpt/rotation',{headers:{'X-CC-Token':TOKEN}});if(r.ok)renderRotation(await r.json())}catch(e){}finally{refreshing=false}}
 document.getElementById('fleetCxOpt').addEventListener('change',async e=>{const box=e.target,on=box.checked;box.checked=!on;if(!await window.fleetAsk(box,(on?'Включить':'Выключить')+' оптимизацию переключений лимитов Codex?',on?'Включить':'Выключить'))return;box.checked=on;box.disabled=true;try{await post('chatgpt/rotation/config',{optimize:on});await loadRotation()}catch(err){box.checked=!on;toast('⚠ '+err.message)}finally{box.disabled=false}});
 const oldCxRender=cxRender;cxRender=function(){oldCxRender();if(rotationData)renderRotation(rotationData);if(typeof cxData!=='undefined'&&cxData&&cxData.loading&&!cxData.accounts.length)document.getElementById('cx').textContent='Загружаем сохранённые аккаунты…'};
 const accLink=document.querySelector('#cxAccW>.cxacch');if(accLink)accLink.title='Аккаунты показаны на главной странице';
 document.getElementById('cxAccW').classList.add('open');
  // Только оформление: переносим существующие узлы, не заменяя обработчики действий.
 document.body.classList.add('fleet-reference','fleet-wide');
 const openAccountMenus=new Map();
 const brand=document.getElementById('h1');
 brand.innerHTML='<img class="fleet-brand" src="__FLEET_BRAND_ICON__" width="40" height="40" alt="" aria-hidden="true" draggable="false"><span><span class="fleet-brand-name">cc<span class="fleet-brand-word">fleet</span></span><small class="fleet-brand-sub">БАЛАНСЕР АККАУНТОВ</small></span>';
 brand.querySelector('.fleet-brand-name').append(document.getElementById('termDot'));
 hdr.querySelector('.hdrctl').prepend(profilebar);
 const headerButtons=hdr.querySelector('.hdrbtns');if(headerButtons)hdr.querySelector('.hdrctl').append(headerButtons);
 const toolbar=el('div','fleet-console-toolbar');toolbar.append(document.getElementById('cTabs'),term.querySelector('.tzoom'));term.prepend(toolbar);
 const consoleFrame=el('div','fleet-console-viewport'),consoleBox=document.getElementById('termBox'),consoleTabs=document.getElementById('cTabs'),consoleZoom=toolbar.querySelector('.tzoom'),consoleActions=consoleTabs.querySelector('.ctacts');
 consoleBox.before(consoleFrame);consoleFrame.append(consoleBox);
 const mobileConsole=matchMedia('(max-width:640px), (max-width:1000px) and (pointer:coarse)'),legacyDock=document.querySelector('.dock');
 function placeConsoleControls(){
  if(mobileConsole.matches){consoleFrame.append(consoleActions,consoleZoom);input.placeholder='Сообщение в консоль…'}
  else{consoleTabs.append(consoleActions);toolbar.append(consoleZoom);input.placeholder='Сообщение или команда в выбранную консоль…'}
  syncLegacyDock();
 }
 function syncLegacyDock(){
  const off=mobileConsole.matches&&!document.documentElement.classList.contains('conly');
  legacyDock.inert=off;
  if(off){legacyDock.setAttribute('aria-hidden','true');document.getElementById('dockZone').classList.remove('pin')}
  else legacyDock.removeAttribute('aria-hidden');
  fitDockLift();
 }
 function fitDockLift(){
  const root=document.documentElement,c=document.querySelector('.fleet-composer');
  if(!mobileConsole.matches||!root.classList.contains('conly')||!c){root.style.removeProperty('--fleet-dock-lift');return}
  const vh=window.visualViewport?.height||innerHeight;root.style.setProperty('--fleet-dock-lift',Math.max(0,Math.round(vh-c.getBoundingClientRect().top))+'px');
 }
 function fitMobileViewport(){const root=document.documentElement;root.style.setProperty('--fleet-visual-height',Math.round(window.visualViewport?.height||innerHeight)+'px');root.style.setProperty('--fleet-visual-top',Math.round(window.visualViewport?.offsetTop||0)+'px')}
 placeConsoleControls();fitMobileViewport();
 let fillShown=0;
 function fitConsoleFill(){
  const root=document.documentElement,wrap=document.querySelector('.termwrap');
  if(!wrap||!mobileConsole.matches||root.classList.contains('conly')){if(root.classList.contains('fleet-term-fill')){root.classList.remove('fleet-term-fill');root.style.removeProperty('--fleet-term-fill')}fillShown=0;return}
  const vh=window.visualViewport?.height||innerHeight,top=wrap.getBoundingClientRect().top+window.scrollY,h=Math.max(380,Math.round(vh-top-12));
  if(document.activeElement===input&&fillShown&&h<fillShown)return; // экранная клавиатура сжала экран: окно не прыгает, пока человек печатает
  if(h===fillShown&&root.classList.contains('fleet-term-fill'))return;
  fillShown=h;root.style.setProperty('--fleet-term-fill',h+'px');root.classList.add('fleet-term-fill');
 }
 fitConsoleFill();
 addEventListener('resize',fitConsoleFill);addEventListener('orientationchange',fitConsoleFill);addEventListener('load',fitConsoleFill);window.visualViewport?.addEventListener('resize',fitConsoleFill);
 mobileConsole.addEventListener('change',()=>{fillShown=0;fitConsoleFill()});
 if(window.ResizeObserver)new ResizeObserver(fitConsoleFill).observe(hdr);
 new MutationObserver(()=>{fitConsoleFill();syncLegacyDock()}).observe(document.documentElement,{attributes:true,attributeFilter:['class']});
 {const comp=document.querySelector('.fleet-composer');if(comp&&window.ResizeObserver)new ResizeObserver(fitDockLift).observe(comp);addEventListener('resize',fitDockLift);window.visualViewport?.addEventListener('resize',fitDockLift)}
 mobileConsole.addEventListener('change',placeConsoleControls);
 addEventListener('resize',fitMobileViewport);window.visualViewport?.addEventListener('resize',fitMobileViewport);window.visualViewport?.addEventListener('scroll',fitMobileViewport);
 // Nested terminal scroll must not trap a page gesture at either history edge.
 let consoleTouch=null;
 consoleBox.addEventListener('touchstart',event=>{
  const touch=event.touches.length===1&&event.touches[0];
  consoleTouch=touch?{x:touch.clientX,y:touch.clientY,last:touch.clientY,top:consoleBox.scrollTop<=2,bottom:consoleBox.scrollTop+consoleBox.clientHeight>=consoleBox.scrollHeight-2}:null;
 },{passive:true});
 consoleBox.addEventListener('touchmove',event=>{
  if(!consoleTouch||event.touches.length!==1||!mobileConsole.matches||document.documentElement.classList.contains('conly'))return;
  const touch=event.touches[0],dy=consoleTouch.last-touch.clientY,total=consoleTouch.y-touch.clientY;
  consoleTouch.last=touch.clientY;
  if(Math.abs(total)<6||Math.abs(touch.clientX-consoleTouch.x)>Math.abs(total))return;
  if((consoleTouch.bottom&&total>0)||(consoleTouch.top&&total<0)){
   if(event.cancelable){event.preventDefault();window.scrollBy(0,dy)}
  }
 },{passive:false});
 for(const name of ['touchend','touchcancel'])consoleBox.addEventListener(name,()=>{consoleTouch=null},{passive:true});
 // A saved desktop focus mode must not hide the mobile account page on load.
 if(mobileConsole.matches&&document.documentElement.classList.contains('conly')&&!document.fullscreenElement)setConly(false,false);
 send.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/></svg>';send.title='Отправить в выбранную консоль · Enter';send.setAttribute('aria-label','Отправить в выбранную консоль');
 input.title='Enter — отправить · Shift+Enter — новая строка';
 const accFold=el('details','fleet-accounts-fold');accFold.id='fleetAccountsFold';
 const intro=el('summary','fleet-accounts-intro');intro.innerHTML='<span class="fleet-accounts-title"><span class="fleet-eyebrow">УПРАВЛЕНИЕ АККАУНТАМИ</span><span class="fleet-accounts-heading">Лимиты и переключения</span></span><span class="fleet-accounts-chevron" aria-hidden="true"></span>';
 accFold.append(intro,claude,codex);accountArea.append(accFold);
 try{accFold.open=localStorage.getItem('cc_accounts_open')==='1'}catch(e){}
 accFold.addEventListener('toggle',()=>{try{localStorage.setItem('cc_accounts_open',accFold.open?'1':'0')}catch(e){}});
 const claudeFoot=el('div','fleet-group-footer'),claudeNote=el('span','fleet-group-note');claudeFoot.append(claudeNote,document.getElementById('optWrap'));claude.append(claudeFoot);
 const codexFoot=el('div','fleet-group-footer');codexFoot.append(rotation,xh.querySelector('.switchrow'));codex.append(codexFoot);
 const noteFooter=el('div','fleet-design-note');noteFooter.innerHTML='<span aria-hidden="true">ⓘ</span><p>Проценты показывают использованный лимит. Плановая смена аккаунта — между ответами.</p>';accFold.append(noteFooter);
 for(const head of [ch,xh]){const count=el('span','fleet-count');head.querySelector('h2').after(count)}
 function countText(n){const k=n%100,m=n%10;return n+' '+(k>=11&&k<=14?'аккаунтов':m===1?'аккаунт':m>=2&&m<=4?'аккаунта':'аккаунтов')}
 function putText(node,value){if(node.textContent!==value)node.textContent=value}
 // число плиток блока Claude: локальные аккаунты + плитка второго сервера (если она есть)
 function paintClaudeCount(local){putText(ch.querySelector('.fleet-count'),countText(local+(document.querySelector('#cards > .fleet-remote-card')?1:0)))}
 window.fleetClaudeCount=function(){const d=(typeof lastSnap!=='undefined'&&lastSnap)||{};paintClaudeCount(Object.keys(d.accounts||{}).length)};
 // [notion-ai] сроки на виду: до какого числа оплачена подписка и до какого числа действует вход (раньше — в чипах и в меню «⋯»)
 function dayWord(n){const k=n%100,m=n%10;return k>=11&&k<=14?'дней':m===1?'день':m>=2&&m<=4?'дня':'дней'}
 function dateLeft(iso){const t=new Date(iso),ms=t-Date.now();if(!iso||isNaN(ms))return null;const days=Math.floor(ms/86400000);
  return{ms,days,date:t.toLocaleDateString('ru',{day:'2-digit',month:'2-digit'}),full:t.toLocaleString('ru',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}),left:ms<=0?'сегодня':days>=1?days+' '+dayWord(days):Math.max(1,Math.floor(ms/3600000))+' ч'}}
 function cardDateItem(label,value,tone,title){const item=el('span','fleet-card-date'+(tone?' '+tone:''));item.append(el('span','fleet-card-date-label',label),el('b','',value));if(title)item.title=title;return item}
 // даты Claude (подписка до / вход до): одна функция и для локальных плиток, и для плитки PROD
 function claudeDateItems(a){
  const items=[];
   const sub=dateLeft(a.renewal_next);
   if(a.lapsed||a.plan==='free')items.push(cardDateItem('Подписка','не активна (FREE)','urgent','Аккаунт на бесплатном плане — продли подписку и нажми «Я продлил» в меню ⋯'));
   else if(sub)items.push(cardDateItem('Подписка до',sub.date+' · '+(sub.ms<=0?'продление сегодня':sub.left),sub.days<3?'urgent':sub.days<=7?'warn':'','Ожидаемое продление (по прошлому списанию): '+sub.full+'. Если не продлится — аккаунт станет FREE'));
   else items.push(cardDateItem('Подписка','дата не известна','','Дата появится после первого продления, замеченного панелью'));
   const login=dateLeft(a.login_expires);
   if(login)items.push(login.ms<=0?cardDateItem('Вход','истёк — «Войти заново» в меню ⋯','urgent','Вход истёк '+login.full):cardDateItem('Вход до',login.date+' · '+login.left,login.days<=3?'urgent':login.days<=7?'warn':'','Вход действует до '+login.full+'. Обновлением токена не продлевается — до этой даты нажми «Войти заново» в меню ⋯'));
   else items.push(cardDateItem('Вход','срок не известен','','Срок появится после входа через панель'));
  return items}
 window.fleetClaudeDates=claudeDateItems;
 function paintCardDates(card,a,engine){
  let box=card.querySelector(':scope > .fleet-card-dates');
  if(!box){box=el('div','fleet-card-dates');const top=card.querySelector(':scope > .top');if(!top)return;top.after(box)}
  const items=[];
  if(engine==='claude'){
   items.push(...claudeDateItems(a));
  }else{
   const sub=dateLeft(a.sub_until);
   if(a.lapsed)items.push(cardDateItem('Подписка','закончилась (FREE)','urgent','Подписка не продлена — аккаунт на бесплатном плане'));
   else if(sub)items.push(cardDateItem('Подписка до',sub.date+' · '+(sub.ms<=0?'сегодня':sub.left),sub.ms<=0||sub.days<=3?'urgent':sub.days<=7?'warn':'','Подписка активна до '+sub.full));
   else items.push(cardDateItem('Подписка','дата не известна','','OpenAI не сообщил дату окончания подписки'));
   const ref=a.last_refresh?Math.max(0,Math.floor((Date.now()-new Date(a.last_refresh))/86400000)):null;
   if(a.login_required)items.push(cardDateItem('Вход','нужно войти заново','urgent','Codex потерял вход — «Войти заново» в меню ⋯'));
   else items.push(cardDateItem('Вход','продлевается сам'+(ref==null?'':' · обновлён '+(ref===0?'сегодня':ref+' '+dayWord(ref)+' назад')),ref!=null&&ref>=10?'warn':'',ref==null?'Codex сам обновляет токен входа, пока аккаунтом пользуются':'Токен обновлён '+new Date(a.last_refresh).toLocaleString('ru')+'. Codex продлевает его сам, пока аккаунтом пользуются; долгий простой может потребовать «Войти заново»'));
  }
  const sig=items.map(i=>i.className+i.textContent+i.title).join('|');
  if(box.dataset.sig!==sig){box.dataset.sig=sig;box.replaceChildren(...items)}
 }
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
  paintCardDates(card,a,engine);
  const footer=card.querySelector('.fleet-card-footer');
  const pick=card.querySelector('.fleet-pick')||card.querySelector('.acts .btn-sw');if(pick&&pick.parentElement!==footer)footer.append(pick);
  // у карточки Claude DEV кнопка «Войти заново» на виду, как у карточки PROD (раньше — только в меню ⋯)
  if(engine==='claude'&&footer&&!footer.querySelector('.fleet-footer-relogin')){const rb=el('button','btn-relogin fleet-footer-relogin','🔑 Войти заново');rb.type='button';rb.title='Новый вход в этот аккаунт Claude: ссылка и код';rb.addEventListener('click',e=>{e.stopPropagation();if(typeof reloginAsk==='function')reloginAsk(slot,rb)});footer.append(rb)}
  const windows=engine==='codex'?a.windows||[]:[{mins:300,...a.five_hour},{mins:10080,...a.seven_day}];
  const session=windows.find(w=>w.mins===300),week=windows.find(w=>w.mins===10080);
  const ordered=engine==='codex'?[session,week,...windows.filter(w=>w!==session&&w!==week)].filter(Boolean):windows;
  card.querySelectorAll(':scope > .row').forEach((row,i)=>{
   const reset=row.querySelector('.lbl')?.lastElementChild;if(!reset)return;
   paintWindowReset(reset,ordered[i],ordered[i]?.mins===10080?1:0);reset.title=reset.textContent;
  });
  const paused=isActive&&document.documentElement.classList.contains('ag-pause-'+engine);card.classList.toggle('fleet-paused',paused);
  let text='В ожидании',tone='',caption='Запас лимита';
  if(a.loading){text='Проверка данных';caption='Обновляем лимиты'}
  else if(a.error||a.login_required||a.stale||a.lapsed){text='Нужна проверка';tone='problem';caption='Подробности в меню ⋯'}
  else if(isActive){text='Выбран';tone='active';caption='Сейчас в работе'}
  else if(a.reached||session?.pct>=100||week?.pct>=100){text='Лимит '+(week?.pct>=100?'недели':'сессии');tone='limited';caption='Время сброса указано выше'}
  else if(engine==='codex'&&rotationData?.next===slot){text='Следующий';tone='next';caption='Кандидат для переключения'}
  else if(session?.pct==null&&week?.pct==null){text='Нет данных';caption='Ожидаем данные лимитов'}
  if(paused){const issue=!!(a.error||a.login_required||a.stale||a.lapsed);text=issue?'На паузе · нужна проверка':'На паузе · выбран';tone='paused';caption=issue?'Проверь данные в меню ⋯':'Агент на паузе';}
  const state=card.querySelector('.fleet-card-state');state.className='fleet-card-state'+(tone?' '+tone:'');putText(state,text);putText(card.querySelector('.fleet-card-caption'),caption);
 }
 // Сводка, модель и настройки каждого провайдера собраны в одну плитку.
 const liveStrip=el('section','fleet-active-strip');liveStrip.id='fleetActiveAccounts';liveStrip.setAttribute('aria-label','Активные аккаунты и использованные лимиты');
 const liveHead=el('div','fleet-live-head'),liveHeading=el('span','fleet-live-label fleet-live-heading','Активные аккаунты');liveHeading.id='fleetActiveHeading';
 liveHead.append(liveHeading);
 const liveFold=el('details','fleet-live-fold');liveFold.id='fleetActiveFold';
 const liveSummary=el('summary','fleet-live-summary');liveSummary.id='fleetActiveSummary';liveSummary.setAttribute('aria-controls','fleetLiveRows');liveSummary.setAttribute('aria-label','Развернуть активные аккаунты');
 const liveExpand=el('span','fleet-live-toggle fleet-live-expand','Развернуть');liveExpand.setAttribute('aria-hidden','true');liveSummary.append(liveExpand);
 const liveCollapse=el('button','fleet-live-toggle fleet-live-collapse','Свернуть');liveCollapse.id='fleetActiveCollapse';liveCollapse.type='button';liveCollapse.setAttribute('aria-controls','fleetLiveRows');liveCollapse.setAttribute('aria-expanded','true');
 const liveFooter=el('div','fleet-live-footer');liveFooter.append(liveCollapse);
 const liveRows=el('div','fleet-live-rows');liveRows.id='fleetLiveRows';liveFold.append(liveSummary,liveRows,liveFooter);liveStrip.append(liveHead,liveFold);term.after(liveStrip);

 // Нижняя панель полного экрана консоли: старый код рисует в ней только аккаунты Claude (список написан, когда движок был один).
 // PROD, Codex и Notion AI достраиваем из ячеек полосы «Активные аккаунты»: тот же вид, та же подсказка при наведении.
 let dockSig='';
 function dockExtras(){
  const panel=document.getElementById('dockPanel');if(!panel||typeof col!=='function'||typeof tone!=='function')return;
  const root=document.documentElement,esc=t=>String(t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const txt=(n,q)=>{const e=n.querySelector(q);return e?e.textContent.trim():''};
  const items=[...liveRows.querySelectorAll('.fleet-compact-account')].filter(c=>c.dataset.engine&&c.dataset.engine!=='claude').map(c=>{
   const eng=c.dataset.engine,nameEl=c.querySelector('.fleet-compact-name'),parts=((nameEl&&nameEl.title)||'').split(' · ');
   const win=k=>{const w=c.querySelector('.fleet-compact-window[data-window="'+k+'"]');if(!w)return null;const m=/(\d+)\s*%/.exec(txt(w,'.fleet-compact-used'));return {pct:m?+m[1]:null,reset:txt(w,'.fleet-compact-range')}};
   return {eng,name:nameEl?nameEl.textContent.trim():eng,email:parts.find(x=>x.includes('@'))||'',plan:parts.length>2&&/^[A-Z]{2,6}$/.test(parts[parts.length-1])?parts[parts.length-1]:'',
    live:root.classList.contains('ag-live-'+eng),pause:root.classList.contains('ag-pause-'+eng),
    model:txt(c,'.fleet-compact-model b')||txt(c,'[data-window="model"] b'),effort:txt(c,'.fleet-compact-effort b')||txt(c,'[data-window="effort"] b'),ses:win('session'),wk:win('week')}});
  const claudeLive=root.classList.contains('ag-live-claude'),claudePause=root.classList.contains('ag-pause-claude');
  panel.querySelectorAll('.dchip:not(.dx)').forEach(c=>{if(c.classList.contains('act'))c.dataset.cur='1';const cur=c.dataset.cur==='1';c.classList.toggle('act',cur&&claudeLive);c.classList.toggle('paused',cur&&claudePause);const pa=c.querySelector('.dpa');if(pa){if(!pa.dataset.t)pa.dataset.t=pa.textContent;pa.textContent=claudeLive?pa.dataset.t:claudePause?'на паузе':'';pa.style.display=claudeLive||claudePause?'':'none';pa.style.color=claudePause&&!claudeLive?'var(--mut)':''}});
  const sig=JSON.stringify(items);
  if(sig===dockSig&&panel.querySelector('.dchip.dx'))return;
  dockSig=sig;panel.querySelectorAll('.dchip.dx').forEach(n=>n.remove());
  const met=(l,o)=>o&&o.pct!=null?'<span class="dmet"><span class="dtop"><span class="dml">'+l+'</span><b style="color:'+col(o.pct)+'">'+o.pct+'%</b></span><span class="bar dbar"><span class="fill" data-t="'+tone(o.pct)+'" style="width:'+o.pct+'%"></span></span></span>':'';
  const row=(l,o)=>o&&o.pct!=null?'<div class="row"><div class="lbl"><span>'+l+': <b style="color:'+col(o.pct)+'">'+o.pct+'%</b></span><span>'+esc(o.reset)+'</span></div><div class="bar"><div class="fill" data-t="'+tone(o.pct)+'" style="width:'+o.pct+'%"></div></div></div>':'';
  panel.insertAdjacentHTML('beforeend',items.map(a=>{
   const st=a.pause?'на паузе':a.live?'работает':'';
   return '<div class="dchip dx '+esc(a.eng)+(a.live&&!a.pause?' act':'')+(a.pause?' paused':'')+'"><span class="ddot"></span><span class="dmail">'+esc(a.name)+(a.pause?' · пауза':'')+'</span>'+met(tr('dockSes'),a.ses)+met(tr('dockWeek'),a.wk)
    +'<div class="dpop"><div class="dpt"><span class="dpe">'+esc(a.email||a.name)+'</span>'+(a.plan?'<span class="tag plan">'+esc(a.plan)+'</span>':'')+(st?'<span class="dpa"'+(a.pause?' style="color:var(--mut)"':'')+'>'+st+'</span>':'')+'</div>'
    +(a.email?'<div class="dsub">'+esc(a.name)+'</div>':'')+(a.model?'<div class="dsub">Модель: '+esc(a.model)+(a.effort&&a.effort!=='—'?' · Effort: '+esc(a.effort):'')+'</div>':'')+row(tr('session5'),a.ses)+row(tr('week'),a.wk)+'</div></div>'}).join(''));
 }
 {const rd=window.renderDock;if(typeof rd==='function')window.renderDock=function(){const r=rd.apply(this,arguments);try{dockExtras()}catch(e){}return r}}
 {let t=0;const soon=()=>{clearTimeout(t);t=setTimeout(()=>{try{dockExtras()}catch(e){}},300)};
  new MutationObserver(soon).observe(liveRows,{childList:true,subtree:true,characterData:true});
  new MutationObserver(soon).observe(document.documentElement,{attributes:true,attributeFilter:['class']});soon()}
 {const cut=t=>t.replace(/\s*·\s*(самостоятельно|только он)\s*$/,'');let tp=0;
  const paintProfiles=()=>{for(const c of liveRows.querySelectorAll('.fleet-compact-account')){
   const nm=c.querySelector('.fleet-compact-name');if(!nm)continue;
   let id=nm.parentElement;if(!id.classList.contains('fleet-compact-id')){id=el('span','fleet-compact-id');nm.before(id);id.append(nm)}
   let pf=id.querySelector('.fleet-compact-prof');if(!pf){pf=el('span','fleet-compact-prof');id.append(pf)}
   const full=(liveRows.querySelector('.fleet-live-account.'+c.dataset.engine+' .cxbtnname')?.textContent||'').trim(),short=cut(full),ttl=full?'Профиль: '+full:'';
   if(pf.textContent!==short)pf.textContent=short;if(pf.title!==ttl)pf.title=ttl}};
  new MutationObserver(()=>{clearTimeout(tp);tp=setTimeout(()=>{try{paintProfiles()}catch(e){}},60)}).observe(liveRows,{childList:true,subtree:true,characterData:true});paintProfiles()}
 liveCollapse.addEventListener('click',()=>{liveFold.open=false;liveSummary.focus({preventScroll:true})});
 liveFold.addEventListener('toggle',()=>{if(!liveFold.open)liveFold.open=true});  // [notion-ai] общий «Свернуть» убран: сворачивается каждая строка (аккордеон ниже)
 // [notion-ai] полоса активных моделей — под консолью и на компьютере, и на телефоне
 function placeActiveAccounts(){term.after(liveStrip);liveFold.open=true}
 placeActiveAccounts();mobileConsole.addEventListener('change',placeActiveAccounts);
 hdr.querySelector('.hdrctl').append(document.getElementById('cxInst'));
 const gear=document.getElementById('gear'),codexGear=document.getElementById('cxGear'),codexModel=document.getElementById('cxMod');
 const generalGear=el('button','hdrgear fleet-header-icon');generalGear.id='fleetGeneralGear';generalGear.type='button';generalGear.innerHTML=gear.innerHTML;generalGear.title='Общие настройки';generalGear.setAttribute('aria-label','Общие настройки');
 const profilesBtn=el('button','hdrgear fleet-header-icon');profilesBtn.id='fleetProfilesBtn';profilesBtn.type='button';profilesBtn.title='Выбор профиля';profilesBtn.setAttribute('aria-label','Выбор профиля');profilesBtn.setAttribute('aria-haspopup','dialog');profilesBtn.setAttribute('aria-expanded','false');
 profilesBtn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/></svg><span class="fleet-hdr-label">Профили</span>';
 headerButtons.replaceChildren(document.getElementById('rfBtn'),profilesBtn,generalGear);hdr.append(headerButtons);
 let profileOpener=null;
 const claudeModel=el('button','hdrgear cxmodbtn fleet-model-tile');claudeModel.id='fleetClaudeModel';claudeModel.type='button';claudeModel.setAttribute('aria-haspopup','dialog');claudeModel.setAttribute('aria-expanded','false');
 claudeModel.append(codexModel.querySelector('svg').cloneNode(true),el('span','cxmodn','Модель Claude'),el('span','cxmode'));
 const claudeQ=el('div','cxpop cxquick fleet-quick-panel');claudeQ.id='fleetClaudeQ';claudeQ.setAttribute('role','dialog');claudeQ.setAttribute('aria-label','Модель и рассуждения Claude');claudeQ.hidden=true;
 const claudeQBody=el('div','cxpbody');claudeQBody.id='fleetClaudeQBody';const nativeModelControls=el('div','fleet-native-controls');nativeModelControls.hidden=true;nativeModelControls.append(models);claudeQ.append(claudeQBody,nativeModelControls);document.body.append(claudeQ);
 const liveNodes={},liveSnapshots=new Map(),compactNodes={};
 for(const engine of ['claude','codex']){
  const compact=el('span','fleet-compact-account '+engine);compact.dataset.engine=engine;
  compact.append(el('strong','fleet-compact-name'),el('span','fleet-compact-warning'));
  const modelBrief=el('span','fleet-compact-model'),effortBrief=el('span','fleet-compact-effort');
  modelBrief.append(el('span','fleet-compact-label','Модель'),el('b','','—'));effortBrief.append(el('span','fleet-compact-label','Effort'),el('b','','—'));compact.append(modelBrief,effortBrief);
  for(const kind of ['session','week']){
   const window=el('span','fleet-compact-window');window.dataset.window=kind;
   window.append(el('span','fleet-compact-label',kind==='session'?'5ч':'Неделя'),el('b','fleet-compact-used','—'),el('span','fleet-compact-range','Время не получено'));compact.append(window);
  }
  liveSummary.append(compact);compactNodes[engine]=compact;
  const tile=el('article','fleet-live-account '+engine);tile.dataset.engine=engine;
  const identity=el('a','fleet-live-identity');identity.href=engine==='claude'?'#fleetClaude':'#fleetCodex';identity.append(el('strong','fleet-live-name'),el('span','fleet-live-email'));tile.append(identity);
  const controls=el('div','fleet-provider-controls');controls.append(engine==='claude'?claudeModel:codexModel,engine==='claude'?gear:codexGear);
  for(const button of controls.children)button.classList.add(button.classList.contains('cxmodbtn')?'fleet-model-tile':'fleet-provider-gear');tile.append(controls);
  for(const kind of ['session','week']){
   const meter=el('div','fleet-live-meter');meter.dataset.window=kind;
   const caption=el('div','fleet-live-meter-label');caption.append(el('span','',kind==='session'?'5 часов':'Неделя'),el('b','','—'),el('span','fleet-live-reset','Время не получено'));
   const track=el('span','fleet-live-track');track.setAttribute('aria-hidden','true');track.append(el('span','fleet-live-fill'));meter.append(caption,track);tile.append(meter);
  }
  identity.addEventListener('click',event=>{event.preventDefault();const selected=engine==='claude'?document.querySelector('#cards .card.active'):document.querySelector('#cxcards .card.fleet-active');(selected||document.querySelector(identity.getAttribute('href')))?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'})});
  liveRows.append(tile);liveNodes[engine]=tile;
 }
 // Значения в свёрнутой строке повторяют существующие элементы выбора; на переключение не влияют.
 function syncCompactModel(engine){
  const source=engine==='claude'?claudeModel:codexModel,compact=compactNodes[engine];
  const model=source.querySelector('.cxmodn')?.textContent?.trim(),effort=source.querySelector('.cxmode')?.textContent?.trim();
  putText(compact.querySelector('.fleet-compact-model b'),model&&model!=='Модель Claude'?model:'—');
  putText(compact.querySelector('.fleet-compact-effort b'),effort||'—');
 }
 for(const engine of ['claude','codex']){const source=engine==='claude'?claudeModel:codexModel;new MutationObserver(()=>syncCompactModel(engine)).observe(source,{childList:true,characterData:true,subtree:true});syncCompactModel(engine)}
 // [notion-ai] Аккордеон: у каждой модели своя строка; щелчок по строке раскрывает её плитку на том же месте,
 // щелчок по имени в плитке (⌃) сворачивает обратно. Общие «Развернуть/Свернуть» убраны; что раскрыто — localStorage cc_acc_open.
 // Строку и плитку Notion AI cc_notion_ai добавляет позже — их раскладывает MutationObserver.
 const ACC_ORDER=['claude','prod','codex','notion'];let accOpen={};
 try{accOpen=JSON.parse(localStorage.getItem('cc_acc_open')||'{}')||{}}catch(e){accOpen={}}
 liveStrip.classList.add('fleet-acc-mode');liveFold.open=true;
 function accWrap(engine){
  let wrap=liveRows.querySelector(':scope>.fleet-acc[data-engine="'+engine+'"]');
  if(!wrap){wrap=el('div','fleet-acc');wrap.dataset.engine=engine;const next=ACC_ORDER.slice(ACC_ORDER.indexOf(engine)+1).map(e=>liveRows.querySelector(':scope>.fleet-acc[data-engine="'+e+'"]')).find(Boolean);liveRows.insertBefore(wrap,next||null)}
  return wrap;
 }
 function accPaint(wrap){
  const open=!!accOpen[wrap.dataset.engine],compact=wrap.querySelector(':scope>.fleet-compact-account'),identity=wrap.querySelector(':scope>.fleet-live-account .fleet-live-identity');
  wrap.classList.toggle('open',open);
  if(compact){compact.setAttribute('aria-expanded',String(open));compact.setAttribute('aria-label','Развернуть: '+compact.querySelector('.fleet-compact-name')?.textContent)}
  if(identity){identity.setAttribute('aria-expanded',String(open));identity.title='Свернуть строку'}
 }
 function accOrganize(){
  for(const compact of liveFold.querySelectorAll('.fleet-compact-account[data-engine]')){
   const engine=compact.dataset.engine;if(!ACC_ORDER.includes(engine))continue;
   const wrap=accWrap(engine);if(compact.parentNode!==wrap)wrap.prepend(compact);
   if(!compact.dataset.acc){compact.dataset.acc='1';compact.setAttribute('role','button');compact.tabIndex=0;const chev=el('span','fleet-acc-chev');chev.setAttribute('aria-hidden','true');compact.append(chev)}
   accPaint(wrap);
  }
  for(const tile of liveRows.querySelectorAll('.fleet-live-account[data-engine]')){
   const engine=tile.dataset.engine;if(!ACC_ORDER.includes(engine))continue;
   const wrap=accWrap(engine);if(tile.parentNode!==wrap)wrap.append(tile);accPaint(wrap);
  }
 }
 function accSet(engine,open,focus){
  accOpen[engine]=open;try{localStorage.setItem('cc_acc_open',JSON.stringify(accOpen))}catch(e){}
  const wrap=liveRows.querySelector(':scope>.fleet-acc[data-engine="'+engine+'"]');if(!wrap)return;accPaint(wrap);
  if(focus)(open?wrap.querySelector('.fleet-live-identity'):wrap.querySelector('.fleet-compact-account'))?.focus({preventScroll:true});
 }
 // capture: щелчок по имени плитки только сворачивает — прежние переходы (к карточке, на вкладку Notion AI) не срабатывают
 liveRows.addEventListener('click',event=>{
  const compact=event.target.closest('.fleet-compact-account[data-acc]');if(compact){accSet(compact.dataset.engine,true,event.detail===0);return}
  const identity=event.target.closest('.fleet-live-identity'),tile=identity&&identity.closest('.fleet-acc>.fleet-live-account');
  if(tile){event.preventDefault();event.stopPropagation();accSet(tile.dataset.engine,false,event.detail===0)}
 },true);
 liveRows.addEventListener('keydown',event=>{const compact=event.target.closest&&event.target.closest('.fleet-compact-account[data-acc]');if(compact&&(event.key==='Enter'||event.key===' ')){event.preventDefault();accSet(compact.dataset.engine,true,true)}});
 const accObserver=new MutationObserver(accOrganize);accObserver.observe(liveSummary,{childList:true});accObserver.observe(liveRows,{childList:true});
 accOrganize();
 // Единое размещение окон у шестерёнок, моделей и настроек: окно НИКОГДА не режется до «остатка под кнопкой».
 // Высота — по содержимому, но не больше экрана; ставим под кнопкой, если помещается целиком, иначе над ней, иначе сдвигаем вверх.
 // Содержимое выросло или уменьшилось после открытия — окно ставится заново (ResizeObserver).
 const placeState=new WeakMap();
 window.fleetPlace=function(panel,anchor,width){
  if(!panel||!anchor||!anchor.getBoundingClientRect)return;
  const gap=12,vh=innerHeight,vw=innerWidth,r=anchor.getBoundingClientRect(),w=Math.min(width,vw-gap*2);
  panel.style.width=w+'px';panel.style.right='auto';panel.style.bottom='auto';panel.style.maxHeight=(vh-gap*2)+'px';
  const h=Math.min(panel.getBoundingClientRect().height,vh-gap*2),below=r.bottom+8,above=r.top-8-h;
  const top=below+h<=vh-gap?below:above>=gap?above:Math.max(gap,vh-gap-h);
  panel.style.top=Math.round(top)+'px';panel.style.left=Math.max(gap,Math.min(Math.round(r.right-w),vw-w-gap))+'px';
  let o=placeState.get(panel);
  if(!o){o={};placeState.set(panel,o);if(window.ResizeObserver)new ResizeObserver(()=>{if(panel.hidden)return;const hh=panel.getBoundingClientRect().height;if(hh&&Math.abs(hh-o.h)>1)window.fleetPlace(panel,o.a,o.w)}).observe(panel)}
  o.a=anchor;o.w=width;o.h=h;
 };
 function placePanel(panel,anchor,width){window.fleetPlace(panel,anchor,width)}
 // кнопка быстрого доступа без «Сохранить» не срабатывает от одного клика. fleetAsk(якорь, вопрос, подпись «Да») → Promise<true|false>.
 let askEl=null,askRes=null,askAnc=null;
 function askPlace(){if(!askEl||askEl.hidden)return;const a=askAnc;
  const ar=a&&a.isConnected?a.getBoundingClientRect():null;
  if(ar&&ar.width>0&&ar.bottom>0&&ar.top<innerHeight){window.fleetPlace(askEl,a,320);return}
  const w=Math.min(320,innerWidth-24);askEl.style.width=w+'px';askEl.style.left=Math.max(12,Math.round((innerWidth-w)/2))+'px';askEl.style.top=Math.max(12,Math.round(innerHeight/4))+'px';askEl.style.right='auto';askEl.style.bottom='auto'}
 function askClose(ok){if(askEl&&!askEl.hidden)askEl.hidden=true;const r=askRes;askRes=null;if(r)r(!!ok)}
 window.fleetAsk=function(anchor,text,yes){return new Promise(resolve=>{
  if(askRes)askClose(false);
  if(!askEl){askEl=document.createElement('div');askEl.className='cxpop fleet-ask';askEl.setAttribute('role','dialog');askEl.setAttribute('aria-label','Подтверждение');askEl.hidden=true;
   askEl.innerHTML='<div class="cxpbody"><h3>Точно?</h3><p></p><div class="fa-btns"><button type="button" class="fa-no">Отмена</button><button type="button" class="fa-yes">Да</button></div></div>';document.body.appendChild(askEl);
   askEl.addEventListener('click',e=>{if(e.target.closest('.fa-no'))askClose(false);else if(e.target.closest('.fa-yes'))askClose(true)});
   askEl.addEventListener('pointerdown',e=>e.stopPropagation());
   document.addEventListener('pointerdown',e=>{if(askEl&&!askEl.hidden&&!askEl.contains(e.target))askClose(false)},true);
   document.addEventListener('keydown',e=>{if(e.key==='Escape'&&askEl&&!askEl.hidden){e.stopPropagation();askClose(false)}},true);
   addEventListener('resize',askPlace)}
  askRes=resolve;askAnc=anchor||null;askEl.querySelector('p').textContent=text||'';askEl.querySelector('.fa-yes').textContent=yes||'Да';
  askEl.hidden=false;askPlace();askPlace();askEl.querySelector('.fa-yes').focus({preventScroll:true})})};
 function placeProfilePalette(anchor){
  menu.classList.toggle('fleet-profile-desktop',!mobileConsole.matches);
  if(mobileConsole.matches){menu.style.top='var(--fleet-visual-top,0px)';menu.style.left='0';menu.style.right='0';menu.style.bottom='auto';menu.style.width='100%';menu.style.height=menu.style.maxHeight='var(--fleet-visual-height,100dvh)'}
  else{
   const gap=12,rect=anchor.getBoundingClientRect(),width=Math.min(880,innerWidth-gap*2),available=innerHeight-gap*2;
   menu.style.height='';menu.style.width=width+'px';menu.style.maxHeight=available+'px';menu.style.right='auto';menu.style.bottom='auto';
   const height=menu.getBoundingClientRect().height,below=rect.bottom+8,above=rect.top-height-8;
   const top=below+height<=innerHeight-gap?below:above>=gap?above:Math.max(gap,Math.min(below,innerHeight-height-gap));
   menu.style.top=Math.round(top)+'px';menu.style.left=Math.max(gap,Math.min(Math.round(rect.right-width),innerWidth-width-gap))+'px';
  }
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
 claudeModel.addEventListener('click',()=>{if(!claudeQ.hidden){closeClaudeQ();return}cxQClose();cxPopClose();cxMenuClose();document.getElementById('scrim').hidden=true;claudeQ.hidden=false;claudeModel.setAttribute('aria-expanded','true');paintClaudeModel(lastModel);placePanel(claudeQ,claudeModel,330)});
 codexModel.addEventListener('click',()=>{closeClaudeQ();document.getElementById('scrim').hidden=true});
 cxQPlace=function(){placePanel(document.getElementById('cxQ'),codexModel,330)};
 cxPopPlace=function(){placePanel(document.getElementById('cxPop'),codexGear,580)};
 document.getElementById('cxQ').classList.add('fleet-quick-panel');document.getElementById('cxPop').classList.add('fleet-settings-panel');document.getElementById('cxPop').setAttribute('aria-modal','true');
 // Нативные настройки Claude и общие разделы сохраняют все узлы и обработчики.
 const scrim=document.getElementById('scrim'),modal=scrim.querySelector('.modal');scrim.classList.add('fleet-settings-scrim');modal.classList.add('fleet-settings-panel');modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');modal.setAttribute('aria-labelledby','modalTitle');
 const claudeTitle=document.getElementById('modalTitle'),modalHeader=el('div','cxphead'),modalClose=el('button','hdrgear fleet-panel-close');modalClose.id='fleetClaudeSettingsClose';modalClose.type='button';modalClose.setAttribute('aria-label','Закрыть настройки');modalClose.innerHTML=document.getElementById('cxPopX').innerHTML;modalHeader.append(claudeTitle,modalClose);
 const modalBody=el('div','cxpbody');while(modal.firstChild)modalBody.append(modal.firstChild);modal.replaceChildren(modalHeader,modalBody);
 function group(label,nodes,cls){const section=el('section','fleet-settings-group '+(cls||''));if(label)section.append(el('div','fleet-settings-group-title',label));for(const node of nodes)if(node)section.append(node);return section}
 // [notion-ai] Одна схема у Claude, Codex и Notion AI: 1) переключение и лимиты, 2) модели в быстром меню, 3) свои настройки агента.
 const autoTitle=document.getElementById('autoHdr'),autoRow=document.getElementById('autoWrap').closest('.switchrow'),weekly=document.getElementById('wkPause').closest('label');
 autoTitle.hidden=true;document.getElementById('modelsHdr').hidden=true;for(const id of ['thrMinus','thrPlus'])document.getElementById(id).hidden=true;  // заголовки — у групп, пороги — полями
 const LIMIT_HINT='Сессия — с какого % окна 5 часов переключать аккаунт. Неделя — потолок недели: выше него аккаунт не берётся в работу.';
 const clLimits=el('div','fleet-cx-options');clLimits.id='fleetClLimits';clLimits.innerHTML='<label>Сессия, % <input id="fleetClThreshold" type="number" min="50" max="99" value="90"></label><label>Неделя, % <input id="fleetClCap" type="number" min="50" max="100" value="99"></label><button type="button" id="fleetClSave">Сохранить</button>';
 const autoGroup=group('Переключение и лимиты',[clLimits,el('div','fleet-catalog-note fleet-limit-hint',LIMIT_HINT),autoRow,document.getElementById('autoNote'),weekly,autoTitle],'fleet-claude-group');autoGroup.id='fleetClaudeLimits';
 const modelGroup=group('Модели в быстром меню',[document.getElementById('modelsHdr'),document.getElementById('modalSub'),document.getElementById('poolList'),document.getElementById('checkNew')],'fleet-claude-group');modelGroup.id='fleetClaudeModels';
 const claudeOwnAccounts=el('div','fleet-own-row');claudeOwnAccounts.id='fleetClOwnAcc';
 const claudeBackups=group('',[document.getElementById('bkHdr'),document.getElementById('bkBox')],'fleet-own-sub');
 const claudeOwn=group('Свои настройки Claude',[claudeOwnAccounts,el('div','fleet-catalog-note','Telegram — общий бот, плагин telegram в Claude Code; настраивается в консоли Claude. Шаги — в «Общие настройки» → «Telegram · общий чат».'),claudeBackups],'fleet-claude-group');claudeOwn.id='fleetClaudeOwn';
 const common=el('details','fleet-common-settings');common.append(el('summary','','Общие настройки'));
 common.append(group('',[document.getElementById('updHdr'),document.getElementById('updBox')]));
 modalBody.prepend(autoGroup,modelGroup,claudeOwn,common);
 const clThreshold=document.getElementById('fleetClThreshold'),clCap=document.getElementById('fleetClCap');
 function paintClaudeLimits(){if(clLimits.contains(document.activeElement))return;clThreshold.value=typeof THR!=='undefined'?THR:90;clCap.value=typeof WCAP!=='undefined'?WCAP:99}
 document.getElementById('fleetClSave').addEventListener('click',async e=>{
  const thr=Math.round(Number(clThreshold.value)),cap=Math.round(Number(clCap.value));
  if(!(thr>=50&&thr<=99)||!(cap>=50&&cap<=100)){toast('⚠ Сессия — от 50 до 99 %, неделя — от 50 до 100 %');return}
  e.target.disabled=true;
  try{await post('config',{threshold:thr,weekly_cap:cap});THR=thr;WCAP=cap;renderAutoLbl();toast('Пороги Claude сохранены: сессия '+thr+' %, неделя '+cap+' %');load()}
  catch(err){toast('⚠ '+err.message)}finally{e.target.disabled=false}
 });
 function ownButton(text,action){const button=el('button','ghostbtn',text);button.type='button';button.addEventListener('click',action);return button}
 function toCards(selector,close){close();accFold.open=true;setTimeout(()=>(document.querySelector(selector+' .card')||document.querySelector(selector))?.scrollIntoView({behavior:'smooth',block:'center'}),80)}
 function paintOwnAccounts(){
  const accounts=Object.keys(lastSnap?.accounts||{}),active=lastSnap?.active;
  claudeOwnAccounts.replaceChildren(el('span','fleet-own-text',accounts.length?'Аккаунты: '+accounts.length+' · сейчас '+(active||'—'):'Аккаунтов пока нет'),
   ownButton('+ Добавить аккаунт',()=>{document.getElementById('modalDone').click();setTimeout(()=>acctAdd(),80)}),
   ownButton('Управление аккаунтами ↓',()=>toCards('#cards',()=>document.getElementById('modalDone').click())));
  const cx=(typeof cxData!=='undefined'&&cxData?.accounts)||[],current=typeof cxLimAcc==='function'?cxLimAcc():null;
  codexOwnAccounts.replaceChildren(el('span','fleet-own-text',cx.length?'Аккаунты: '+cx.length+' · сейчас '+(current?.label||current?.slot||'—'):'Аккаунтов пока нет'),
   ownButton('+ Добавить аккаунт',()=>{cxPopClose();setTimeout(()=>cxAdd(),80)}),
   ownButton('Управление аккаунтами ↓',()=>toCards('#cxcards',cxPopClose)));
 }
 const codexThresholds=group('Переключение и лимиты',[cxOptions,el('div','fleet-catalog-note fleet-limit-hint',LIMIT_HINT+' Автовыбор аккаунта по этим порогам — переключатель «Автовыбор» в «Управление аккаунтами».')]);codexThresholds.id='fleetCxLimits';document.querySelector('#cxPop > .cxpbody').prepend(codexThresholds);
 // Каталог моделей: ручная проверка в фоне, без изменения выбранной модели.
 const catalogAccount=el('div','fleet-catalog-note'),catalogList=el('div','fleet-model-catalog'),catalogStatus=el('div','fleet-catalog-note'),catalogCheck=el('button','ghostbtn','🔄 Проверить новые модели');
 catalogAccount.id='fleetCxCatalogAccount';catalogList.id='fleetCxModelList';catalogStatus.id='fleetCxModelStatus';catalogStatus.setAttribute('role','status');catalogStatus.setAttribute('aria-live','polite');catalogCheck.id='fleetCxCheckNew';catalogCheck.type='button';
 const catalogGroup=group('Модели в быстром меню',[el('div','modalsub','Отмеченные модели показываются в быстром меню плитки Codex. Применяется сразу.'),catalogAccount,catalogList,catalogStatus,catalogCheck]);catalogGroup.id='fleetCxModels';codexThresholds.after(catalogGroup);
 const codexOwnAccounts=el('div','fleet-own-row');codexOwnAccounts.id='fleetCxOwnAcc';
 const codexOwn=group('Свои настройки Codex',[codexOwnAccounts,document.getElementById('cxBrW'),document.getElementById('cxWipeW')]);codexOwn.id='fleetCodexOwn';catalogGroup.after(codexOwn);
 function codexHidden(){return (typeof lastSnap!=='undefined'&&lastSnap?.config?.codex_hidden)||[]}
 catalogList.addEventListener('change',async event=>{
  const box=event.target.closest('.fleet-cx-show');if(!box)return;
  const shown=[...catalogList.querySelectorAll('.fleet-cx-show')],ids=shown.map(b=>b.closest('[data-model]').dataset.model);
  const hidden=[...codexHidden().filter(id=>!ids.includes(id)),...shown.filter(b=>!b.checked).map(b=>b.closest('[data-model]').dataset.model)];
  shown.forEach(b=>b.disabled=true);
  try{const d=await post('config',{codex_hidden:hidden});if(lastSnap){lastSnap.config={...(lastSnap.config||{}),codex_hidden:d.codex_hidden||hidden}}catalogSignature='';paintCodexCatalog();if(!document.getElementById('cxQ').hidden)cxQRender();toast(box.checked?'Модель снова в быстром меню Codex':'Модель убрана из быстрого меню Codex')}
  catch(err){box.checked=!box.checked;toast('⚠ '+err.message)}finally{shown.forEach(b=>b.disabled=false)}
 });
 let catalogState=null,catalogTimer=0,catalogBusy=false,catalogApplied='',catalogSignature='',catalogFailures=0;
 function paintCodexCatalog(){
  const account=cxLimAcc(),same=!!account&&catalogState?.slot===account.slot;
  catalogCheck.disabled=!!catalogState?.checking||!account;
  putText(catalogCheck,catalogState?.checking?'⏳ Проверяем модели…':'🔄 Проверить новые модели');
  putText(catalogAccount,account?'Активный аккаунт: '+(account.label||account.email||account.slot)+' · '+account.slot:'Сначала добавь и выбери аккаунт Codex.');
  const models=account?.models||[],hidden=codexHidden(),signature=JSON.stringify([account?.slot,account?.model,models,hidden,same?catalogState:null]);
  if(signature!==catalogSignature){
   catalogSignature=signature;catalogList.replaceChildren();
   for(const model of models){
    const row=el('div','fleet-catalog-row fleet-pick-row'),pick=el('label','fleet-mpick'),box=el('input','fleet-cx-show'),name=el('span','fleet-catalog-name',model.name||model.id);
    box.type='checkbox';box.checked=!hidden.includes(model.id);box.title='Показывать в быстром меню Codex';name.append(el('small','',model.id));pick.append(box,name);row.append(pick);row.dataset.model=model.id;
    if(same&&catalogState.new_ids?.includes(model.id))row.append(el('span','fleet-catalog-chip','Новая'));
    if(account.model===model.id)row.append(el('span','fleet-catalog-chip','Выбрана'));
    catalogList.append(row);
   }
  }
  let note=same?catalogState.message:'';
  if(catalogState?.checking&&!same)note='Идёт проверка аккаунта '+catalogState.slot+'…';
  if(!note)note=models.length?'Моделей: '+models.length+', в быстром меню: '+models.filter(m=>!hidden.includes(m.id)).length+'. Выбор модели — в плитке Codex.':'Каталог пока не загружен. Нажми «Проверить новые модели».';
  putText(catalogStatus,note);catalogStatus.dataset.error=String(same&&catalogState.ok===false);
 }
 function acceptCodexCatalog(data){
  catalogState=data;
  const key=data.slot+':'+data.checked_at;
  if(!data.checking&&data.ok&&data.checked_at&&data.models?.length&&catalogApplied!==key){
   catalogApplied=key;
   if(cxData){cxData={...cxData,accounts:cxData.accounts.map(a=>a.slot===data.slot?{...a,models:data.models}:a)};cxRender();cxAll();if(!document.getElementById('cxQ').hidden)cxQRender()}
  }
  paintCodexCatalog();clearTimeout(catalogTimer);
  if(data.checking)catalogTimer=setTimeout(loadCodexCatalog,900);
 }
 async function loadCodexCatalog(){
  if(catalogBusy)return;catalogBusy=true;
  try{const response=await fetch(API+'chatgpt/models',{headers:{'X-CC-Token':TOKEN},signal:AbortSignal.timeout(10000)});if(!response.ok)throw Error();catalogFailures=0;acceptCodexCatalog(await response.json())}
  catch(e){if(catalogState?.checking){if(++catalogFailures<4)catalogTimer=setTimeout(loadCodexCatalog,2000);else{catalogState={...catalogState,ok:false,checking:false,message:'Не удалось получить результат проверки. Попробуй ещё раз.'};paintCodexCatalog()}}}
  finally{catalogBusy=false}
 }
 catalogCheck.addEventListener('click',async()=>{
  if(catalogBusy||catalogState?.checking)return;catalogBusy=true;catalogCheck.disabled=true;
  try{catalogFailures=0;acceptCodexCatalog(await acctPost('chatgpt/models/check',{}))}
  catch(e){putText(catalogStatus,'Не удалось запустить проверку. Попробуй ещё раз.');catalogStatus.dataset.error='true'}
  finally{catalogBusy=false;catalogCheck.disabled=!!catalogState?.checking||!cxLimAcc()}
 });
 const catalogCxRender=cxRender;cxRender=function(){catalogCxRender();paintCodexCatalog()};
 const catalogRotation=renderRotation;renderRotation=function(data){catalogRotation(data);paintCodexCatalog()};
 const catalogOpen=cxPopOpen;cxPopOpen=function(){catalogOpen();paintCodexCatalog();paintOwnAccounts();loadCodexCatalog()};
 // [notion-ai] Модели Claude: те же строки, что у Codex — галочка «в быстром меню», имя, id, «Новая»/«Выбрана»
 function escText(value){return String(value==null?'':value).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
 renderPool=function(){
  const m=typeof lastModel!=='undefined'?lastModel:null,current=m&&(m.default||m.session),rows=unifiedRows(m,lastCandidates).filter(r=>poolScanned||!r.hidden);
  document.getElementById('poolList').innerHTML=rows.map(r=>'<div class="poolrow fleet-catalog-row fleet-pick-row'+(r.hidden?' is-hidden':'')+'" data-id="'+escText(r.id)+'" data-known="'+(r.known?1:0)+'"><label class="fleet-mpick"><input type="checkbox" class="poolchk"'+(r.enabled?' checked':'')+' title="Показывать в быстром меню Claude"><span class="fleet-catalog-name">'+escText(r.name)+'<small>'+escText(r.id)+'</small></span></label>'
   +(r.isNew?'<span class="fleet-catalog-chip">Новая</span>':'')+(r.id===current?'<span class="fleet-catalog-chip">Выбрана</span>':'')
   +(r.known?'<input type="hidden" class="poolname" value="'+escText(r.name)+'">':'<input type="text" class="poolname" value="'+escText(r.name)+'" aria-label="Название новой модели в меню" title="Как назвать модель в меню">')+'</div>').join('')
   ||'<div class="fleet-catalog-note">Список моделей пока пуст — нажми «Проверить новые модели».</div>';
 };
 if(typeof lastModel!=='undefined'&&lastModel)renderPool();
 paintCodexCatalog();
 const backdrop=el('div','fleet-settings-backdrop');backdrop.id='fleetSettingsBackdrop';backdrop.hidden=true;document.body.append(backdrop);backdrop.addEventListener('click',()=>{cxPopClose()});
 function paintSettingsState(){
  backdrop.hidden=document.getElementById('cxPop').hidden;
  gear.setAttribute('aria-expanded',String(!scrim.hidden&&scrim.dataset.view==='claude'));generalGear.setAttribute('aria-expanded',String(!scrim.hidden&&scrim.dataset.view==='general'));
 }
 new MutationObserver(paintSettingsState).observe(scrim,{attributes:true,attributeFilter:['hidden']});
 new MutationObserver(paintSettingsState).observe(document.getElementById('cxPop'),{attributes:true,attributeFilter:['hidden']});
 gear.setAttribute('aria-haspopup','dialog');
 profilesBtn.addEventListener('click',()=>{if(!menu.hidden){cxMenuClose();return}cxPopClose();cxQClose();closeClaudeQ();if(!scrim.hidden)document.getElementById('modalDone').click();profileOpener=profilesBtn;cxMenuOpen()});
 gear.addEventListener('click',()=>{cxPopClose();cxMenuClose();cxQClose();closeClaudeQ();scrim.dataset.view='claude';putText(claudeTitle,'Настройки Claude');common.open=false;paintClaudeLimits();paintOwnAccounts();placePanel(modal,gear,580);paintSettingsState()});
 generalGear.addEventListener('click',()=>{if(!scrim.hidden&&scrim.dataset.view==='general'){document.getElementById('modalDone').click();return}gear.click();scrim.dataset.view='general';putText(claudeTitle,'Общие настройки');common.open=true;placePanel(modal,generalGear,580);paintSettingsState()});
 codexGear.addEventListener('click',()=>{scrim.hidden=true;closeClaudeQ()});
 modalClose.addEventListener('click',()=>{document.getElementById('modalDone').click();(scrim.dataset.view==='general'?generalGear:gear).focus()});
 document.addEventListener('pointerdown',event=>{if(!event.target.closest('#fleetClaudeQ,#fleetClaudeModel'))closeClaudeQ()});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!claudeQ.hidden){closeClaudeQ();claudeModel.focus()}});
 addEventListener('resize',()=>{if(!claudeQ.hidden)placePanel(claudeQ,claudeModel,330);if(!scrim.hidden)placePanel(modal,scrim.dataset.view==='general'?generalGear:gear,580)});
 if(!scrim.hidden){scrim.dataset.view='general';putText(claudeTitle,'Общие настройки');common.open=true;placePanel(modal,generalGear,580);paintSettingsState()}
 if(lastModel)paintClaudeModel(lastModel);

 const liveDateOptions={timeZone:window.FLEET_TZ,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'};
 const liveDateFormats=[new Intl.DateTimeFormat('ru-RU',liveDateOptions),new Intl.DateTimeFormat('ru-RU',{...liveDateOptions,weekday:'short'})];
 const liveYearFormat=new Intl.DateTimeFormat('ru-RU',{timeZone:window.FLEET_TZ,year:'numeric'});
 const liveClockFormat=new Intl.DateTimeFormat('ru-RU',{timeZone:window.FLEET_TZ,hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
 const liveDayFormat=new Intl.DateTimeFormat('ru-RU',{timeZone:window.FLEET_TZ,day:'2-digit',month:'2-digit'});
 // время сброса 5-часового окна по Иркутску сразу после процентов; если сброс не сегодня, перед временем стоит дата.
 function fiveHourClock(date){const clock=liveClockFormat.format(date),day=liveDayFormat.format(date);return day===liveDayFormat.format(new Date())?clock:day+' '+clock}
 function resetDate(win){
  if(!win?.resets_at)return null;
  const end=new Date(win.resets_at);if(Number.isNaN(end.getTime()))return null;
  return end;
 }
 function compactDate(date,withYear,index){
  return liveDateFormats[index].format(date).replaceAll(',','')+(withYear?' '+liveYearFormat.format(date):'');
 }
 function paintWindowReset(root,win,index,short){
  const end=resetDate(win);if(!end){putText(root,'Время не получено');root.removeAttribute('aria-label');return;}
  let text;
  if(!index&&short){
   text=end.getTime()>Date.now()?fiveHourClock(end):'сброс';
   if(root.firstElementChild?.tagName==='TIME'&&root.firstElementChild.dateTime===end.toISOString()&&root.textContent===text)return;
   const time=el('time','',text);time.dateTime=end.toISOString();root.replaceChildren(time);root.setAttribute('aria-label','Окно 5 часов обновится в '+text+' по Иркутску');root.title='Окно 5 часов обновится в '+text+' (время иркутское)';return;
  }
  if(index){
   const withYear=liveYearFormat.format(end)!==liveYearFormat.format(new Date());text=compactDate(end,withYear,1);
  }else{
   const minutes=Math.ceil((end.getTime()-Date.now())/60000),hours=Math.floor(minutes/60),rest=minutes%60;
   text=minutes<=0?'сброс ожидается':fiveHourClock(end)+' · через '+(hours?hours+' ч'+(rest?' ':''):'')+(rest?rest+' мин':'');
  }
  if(root.firstElementChild?.tagName==='TIME'&&root.firstElementChild.dateTime===end.toISOString()&&root.textContent===text)return;
  const time=el('time','',text);time.dateTime=end.toISOString();root.replaceChildren(time);
  root.setAttribute('aria-label','Сброс '+text+'; время иркутское');
 }
 function paintCompactWindow(root,win,index){
  const pct=Number.isFinite(win?.pct)?win.pct:null;
  putText(root.querySelector('.fleet-compact-used'),pct==null?'—':Math.round(pct)+'%');
  root.dataset.tone=pct==null?'unknown':pct>=99?'bad':pct>=90?'warn':'normal';
  paintWindowReset(root.querySelector('.fleet-compact-range'),win,index,true);
 }
 function updateLiveAccount(engine,slot,account,pending){
  const node=liveNodes[engine],provider=engine==='claude'?'Claude DEV':'Codex';
  const windows=engine==='claude'?[account?.five_hour,account?.seven_day]:[account?.windows?.find(w=>w.mins===300),account?.windows?.find(w=>w.mins===10080)];
  const end=resetDate(windows[0]),remaining=end?Math.max(0,Math.ceil((end.getTime()-Date.now())/60000)):null;
  const signature=JSON.stringify([slot,account,pending,remaining,liveYearFormat.format(new Date())]);if(liveSnapshots.get(engine)===signature)return;liveSnapshots.set(engine,signature);
  const name=account?(account.label||account.name||slot):slot?slot:pending?'Загрузка…':'Не выбран';
  putText(node.querySelector('.fleet-live-name'),provider+' · '+name);
  const issue=account&&(account.login_required||account.lapsed||account.error)?'Нужна проверка':account&&account.stale?'Данные устарели':'';
  putText(node.querySelector('.fleet-live-email'),account?((account.email||slot)+(issue?' · '+issue:'')):slot?'Лимиты пока недоступны':pending?'Получаем сохранённые данные':'Нет активного аккаунта');
  node.dataset.state=issue?'warning':account?'ready':'empty';node.dataset.slot=slot||'';
  const compact=compactNodes[engine];compact.dataset.state=node.dataset.state;compact.dataset.slot=slot||'';
  putText(compact.querySelector('.fleet-compact-name'),provider+' · '+name);
  compact.querySelector('.fleet-compact-name').title=provider+' · '+name+(account?.email?' · '+account.email:'');
  putText(compact.querySelector('.fleet-compact-warning'),issue?(account.stale?'устарело':'проверить'):'');
  node.title=provider+' · '+name+(account?.email?' · '+account.email:'')+(issue?' · '+issue:'');
  windows.forEach((window,i)=>{
   paintCompactWindow(compact.querySelectorAll('.fleet-compact-window')[i],window,i);
   const meter=node.querySelectorAll('.fleet-live-meter')[i],pct=Number.isFinite(window?.pct)?window.pct:null;
   putText(meter.querySelector('b'),pct==null?'—':Math.round(pct)+'%');meter.querySelector('.fleet-live-fill').style.width=(pct==null?0:Math.min(100,Math.max(0,pct)))+'%';
   meter.dataset.tone=pct==null?'unknown':pct>=99?'bad':pct>=90?'warn':'normal';
   const resetLabel=meter.querySelector('.fleet-live-reset');paintWindowReset(resetLabel,window,i);
   meter.title=(i?'Неделя':'5 часов')+' · использовано '+(pct==null?'нет данных':Math.round(pct)+'%')+' · '+resetLabel.textContent;
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
  paintClaudeCount(rows.length);
  const current=rows.find(([,a])=>a.active);putText(claudeNote,current?(document.documentElement.classList.contains('ag-pause-claude')?'Выбран: ':'Сейчас: ')+(current[1].label||current[1].name||current[0]):'Активный аккаунт не выбран');
  const accounts=(typeof cxData!=='undefined'&&cxData?.accounts)||[];
  document.querySelectorAll('#cxcards > .card').forEach((card,i)=>{if(accounts[i])decorateCard(card,accounts[i],accounts[i].slot,'codex')});
  putText(xh.querySelector('.fleet-count'),countText(accounts.length));
  const add=document.querySelector('#cx .cxhead .hdrgear');if(add){xh.querySelector('.fleet-add-codex')?.remove();add.classList.add('fleet-add-codex');xh.append(add)}
 }
 window.addEventListener('nai-state',()=>refreshVisuals()); // состояние паузы меняется независимо от данных аккаунтов
 const originalCards=renderCards;renderCards=function(d){originalCards(d);refreshVisuals(d)};
 const previousCodexRender=cxRender;cxRender=function(){previousCodexRender();refreshVisuals()};
 document.addEventListener('click',event=>{document.querySelectorAll('.fleet-card-details[open]').forEach(menu=>{if(!menu.contains(event.target))menu.open=false})});
 document.addEventListener('keydown',event=>{if(event.key==='Escape')document.querySelectorAll('.fleet-card-details[open]').forEach(menu=>menu.open=false)});
 refreshVisuals();
 setInterval(()=>{if(!document.hidden)refreshVisuals()},15000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshVisuals()});

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
 Object.assign(I18N.ru,{cxpN_orchestrator:'Codex → Claude',cxpN_codex:'Codex · самостоятельно',cxpN_codex_solo_full:'Codex Full · самостоятельно',cxeN:'Codex · самостоятельно · аварийный',cxeHdr:'Codex · самостоятельно · аварийный',cxeOnT:'Codex · самостоятельно · аварийный включён'});
 Object.assign(I18N.en,{cxpN_orchestrator:'Codex → Claude',cxpN_codex:'Codex · solo',cxpN_codex_solo_full:'Codex Full · solo',cxeN:'Codex · solo · emergency',cxeHdr:'Codex · solo · emergency',cxeOnT:'Codex · solo · emergency enabled'});
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
 const paletteCurrent=el('span','fleet-palette-current'),paletteClose=el('button','hdrgear fleet-palette-close');paletteClose.id='fleetProfileClose';paletteClose.type='button';paletteClose.title='Закрыть';paletteClose.setAttribute('aria-label','Закрыть профили');paletteClose.innerHTML=document.getElementById('cxPopX').innerHTML;paletteClose.addEventListener('click',()=>{cxMenuClose();document.getElementById(menu.dataset.returnEngine==='claude'?'mirrorClaudecxBtn':'cxBtn').focus()});paletteHeader.append(paletteHeading,paletteCurrent,paletteClose);
 const paletteTools=el('div','fleet-palette-tools');search.placeholder='Найти по названию или возможностям…';
 const searchWrap=el('form','fleet-palette-search');searchWrap.setAttribute('role','search');searchWrap.autocomplete='off';searchWrap.append(search);searchWrap.addEventListener('submit',event=>{event.preventDefault();filterProfiles();repaintProfileResults()});const compareButton=el('button','fleet-profile-compare','Сравнить');compareButton.id='fleetProfileCompare';compareButton.type='button';compareButton.setAttribute('aria-pressed','false');compareButton.title='Показать состав и возможности всех профилей';paletteTools.append(searchWrap,compareButton);
 const paletteFooter=el('div','fleet-palette-footer'),paletteCount=el('span','fleet-palette-count');paletteCount.setAttribute('role','status');const paletteHelp=el('span','fleet-palette-help','Enter — выбрать · Esc — закрыть');paletteFooter.append(paletteCount,paletteHelp);
 note.remove();menu.replaceChildren(paletteHeader,paletteTools,profileBody,paletteFooter);
 let profilePageLock=null;
 function syncProfileModal(){
  const lock=mobileConsole.matches&&!menu.hidden,root=document.documentElement;
  if(lock&&!profilePageLock){
   profilePageLock={x:scrollX,y:scrollY,inert:new Map()};
   for(const node of document.body.children){if(node===menu||node.id==='cxMenuScrim'||!(node instanceof HTMLElement))continue;profilePageLock.inert.set(node,node.inert);node.inert=true}
   root.style.setProperty('--fleet-profile-page-top',-profilePageLock.y+'px');root.classList.add('fleet-profile-locked');paletteClose.focus({preventScroll:true});
  }else if(!lock&&profilePageLock){
   const saved=profilePageLock;profilePageLock=null;root.classList.remove('fleet-profile-locked');root.style.removeProperty('--fleet-profile-page-top');
   for(const [node,inert] of saved.inert)node.inert=inert;
   window.scrollTo(saved.x,saved.y);
   const anotherDialog=['acctScrim','scrim','cxPop'].some(id=>{const node=document.getElementById(id);return node&&!node.hidden&&node.getClientRects().length});
   if(menu.hidden&&!anotherDialog)(profileOpener||document.getElementById((menu.dataset.returnEngine||menu.dataset.engine)==='claude'?'mirrorClaudecxBtn':'cxBtn'))?.focus({preventScroll:true});
  }
  if(!menu.hidden)cxMenuPlace();
 }
 new MutationObserver(syncProfileModal).observe(menu,{attributes:true,attributeFilter:['hidden']});
 mobileConsole.addEventListener('change',syncProfileModal);
 menu.addEventListener('keydown',event=>{
  if(!profilePageLock||event.key!=='Tab')return;
  const nodes=[...menu.querySelectorAll('button,a[href],input,select,textarea,[tabindex]:not([tabindex="-1"])')].filter(node=>!node.disabled&&!node.hidden&&node.getClientRects().length);
  const target=event.shiftKey?nodes.at(-1):nodes[0],edge=event.shiftKey?nodes[0]:nodes.at(-1);
  if(document.activeElement===edge&&target){event.preventDefault();target.focus()}
 });
 const paletteEmpty=el('div','fleet-profile-empty');paletteEmpty.hidden=true;paletteEmpty.append(el('strong','','Профили не найдены'),el('span','','Попробуй другое название или возможность.'));const clearSearch=el('button','','Очистить поиск');clearSearch.type='button';clearSearch.addEventListener('click',()=>{resetProfileSearch();search.focus()});paletteEmpty.append(clearSearch);profileBody.append(paletteEmpty);
 let compareProfiles=false,normalProfileInfo=new Set();
 const profileCopy={orchestrator:'Codex ведёт задачу. Claude выполняет шаги после твоего подтверждения.',codex:'Самостоятельная работа в своей папке. Проект доступен для чтения.',codex_solo_full:'Работает самостоятельно с полной песочницей Codex и правами пользователя ОС.'};
 function repaintProfileResults(){
  const nodes=Array.from(profileRoot.querySelectorAll('.cxprof:not([data-auto])')),visible=nodes.filter(node=>!node.hidden).length;
  const services=profileRoot.querySelectorAll('.cxprof[data-auto],.cxemg').length;
  putText(paletteCount,(profileQuery.trim()?'Найдено: '+visible+' из '+nodes.length:nodes.length+' '+(nodes.length===1?'профиль':nodes.length>1&&nodes.length<5?'профиля':'профилей'))+(services?' · служебных режимов: '+services:''));
  paletteEmpty.hidden=visible>0||!!profileRoot.querySelector('.cxprof[data-auto]:not([hidden])');
 }
 function decorateProfilePalette(){
  const bridge=cxbData&&cxbData.bridge,profiles=bridge?.profiles||[],current=profiles.find(profile=>profile.id===bridge.profile);
  putText(paletteCurrent,cxbData?.emergency?.active?'Сейчас: '+tr('cxeHdr'):current?'Сейчас: '+cxpName(current):'Сейчас: свои настройки');
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
 // Автозаполнение браузера не считается запросом пользователя.
 let profileSearchEdited=false;
 function profileSearchAutofilled(){try{return search.matches(':autofill')||search.matches(':-webkit-autofill')}catch(_){return false}}
 search.addEventListener('keydown',event=>{if(event.isTrusted&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&(event.key.length===1||['Backspace','Delete'].includes(event.key)))profileSearchEdited=true});
 for(const kind of ['paste','cut','drop','compositionstart'])search.addEventListener(kind,event=>{if(event.isTrusted)profileSearchEdited=true});
 search.addEventListener('input',event=>{
  const deliberate=profileSearchEdited||(event.isTrusted&&!profileSearchAutofilled()&&event.inputType!=='insertReplacementText');
  if(!search.value||deliberate)profileQuery=search.value;
  else search.value=profileQuery;
  profileSearchEdited=false;
 },true);
 function resetProfileSearch(){profileQuery='';search.value='';profileSearchEdited=false;filterProfiles();repaintProfileResults()}

 search.addEventListener('input',repaintProfileResults);
 search.addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();profileRoot.querySelector('.cxprof:not([data-auto]):not([hidden])')?.focus()}});
 new MutationObserver(()=>{if(!menu.hidden){resetProfileSearch();profileBody.scrollTop=0;if(matchMedia('(pointer:fine)').matches)profileRoot.querySelector('.cxprof.act:not([data-auto])')?.focus({preventScroll:true})}else if(document.activeElement?.closest('#cxMenu'))document.getElementById(menu.dataset.returnEngine==='claude'?'mirrorClaudecxBtn':'cxBtn').focus()}).observe(menu,{attributes:true,attributeFilter:['hidden']});
 profileRoot.addEventListener('keydown',event=>{
  if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)||!event.target.matches('.cxprof:not([data-auto])'))return;
  const visible=Array.from(profileRoot.querySelectorAll('.cxprof:not([data-auto]):not([hidden])')),index=visible.indexOf(event.target);if(index<0)return;
  event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?visible.length-1:(index+(['ArrowLeft','ArrowUp'].includes(event.key)?-1:1)+visible.length)%visible.length;visible[next]?.focus();
 });
 cxMenuPlace=function(){placeProfilePalette(document.getElementById('cxBtn'))};
 document.getElementById('cxBtn').addEventListener('click',()=>{if(!menu.hidden){scrim.hidden=true;closeClaudeQ();cxMenuPlace()}});
 cxpRender();

 // Общий компонент профилей двух сторон включается только при наличии API профилей.
 let mirrorState=null,mirrorMounted=false,mirrorEngine='codex',mirrorBusy=false,mirrorTaskTimer=null,mirrorUpdateTimer=null;
 const mirrorInfo={claude:new Set(),codex:new Set()},mirrorNames={claude:'Claude',codex:'Codex'},mirrorButtons={};
 function mirrorAccept(state){if(!state?.available||!state.engines?.claude||!state.engines?.codex)return;if(mirrorState&&state.revision<mirrorState.revision)return;if(mirrorState&&state.revision===mirrorState.revision&&state.snapshot_ts&&mirrorState.snapshot_ts&&state.snapshot_ts<mirrorState.snapshot_ts)return;mirrorState=state;clearTimeout(mirrorUpdateTimer);if(state.updating)mirrorUpdateTimer=setTimeout(mirrorLoad,1000);if(['approved','running'].includes(state.task?.status)){if(!mirrorTaskTimer)mirrorTaskTimer=setTimeout(()=>{mirrorTaskTimer=null;if(!document.hidden)mirrorLoad()},2500)}else{clearTimeout(mirrorTaskTimer);mirrorTaskTimer=null}if(!mirrorMounted)mountMirrorProfiles();paintMirrorWorkplace();if(!menu.hidden)cxpRender()}
 async function mirrorLoad(){try{const response=await fetch(API+'profiles',{headers:{'X-CC-Token':TOKEN}});if(response.ok)mirrorAccept(await response.json())}catch(_){}}
 function mirrorTheme(){menu.dataset.engine=mirrorEngine;putText(paletteHeading.querySelector('h2'),'Профили '+mirrorNames[mirrorEngine]);menu.setAttribute('aria-label','Выбор профиля '+mirrorNames[mirrorEngine]);for(const tab of paletteHeading.querySelectorAll('[data-mirror-tab]'))tab.setAttribute('aria-selected',String(tab.dataset.mirrorTab===mirrorEngine))}
 function mirrorOpen(engine,info){
  mirrorEngine=engine;compareProfiles=false;if(info)mirrorInfo[engine].add(info);resetProfileSearch();mirrorTheme();
  if(menu.hidden)nativeMirrorOpen();else cxpRender();cxMenuPlace();
  if(info)requestAnimationFrame(()=>profileRoot.querySelector('[data-profile-id="'+info+'"]')?.scrollIntoView({block:'nearest'}));
 }
 let nativeMirrorOpen=null;
 function mountMirrorProfiles(){
  mirrorMounted=true;nativeMirrorOpen=cxMenuOpen;document.body.classList.add('fleet-mirror');
  new MutationObserver(()=>{paintMirrorWorkplace();if(menu.hidden)(profileOpener||mirrorButtons[mirrorEngine])?.focus({preventScroll:true})}).observe(menu,{attributes:true,attributeFilter:['hidden']});
  const profileTabs=el('div','mirror-profile-tabs');profileTabs.setAttribute('role','tablist');profileTabs.setAttribute('aria-label','Исполнитель');
  for(const e of ['claude','codex']){const b=el('button','',mirrorNames[e]);b.type='button';b.dataset.mirrorTab=e;b.setAttribute('role','tab');b.addEventListener('click',()=>mirrorOpen(e));b.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=['ArrowLeft','Home'].includes(event.key)?'claude':'codex';mirrorOpen(next);profileTabs.querySelector('[data-mirror-tab="'+next+'"]').focus()}});profileTabs.append(b)}paletteHeading.querySelector('.fleet-eyebrow').replaceWith(profileTabs);
  for(const e of ['claude','codex']){
   const tile=liveNodes[e],footer=el('div','mirror-profile-footer'),holder=el('div','mirror-profile-holder');tile.dataset.provider=e;
   let group,button;
   if(e==='codex'){group=document.getElementById('cxGrp');button=document.getElementById('cxBtn');holder.append(group)}
   else{button=document.getElementById('cxBtn').cloneNode(true);for(const node of [button,...button.querySelectorAll('[id]')])if(node.id)node.id='mirrorClaude'+node.id;button.addEventListener('click',()=>{if(!menu.hidden&&mirrorEngine==='claude')cxMenuClose();else mirrorOpen('claude')});holder.append(button)}
   button.classList.add('mirror-profile-button');button.setAttribute('aria-label','Выбор профиля '+mirrorNames[e]);button.setAttribute('aria-controls','cxMenu');mirrorButtons[e]=button;
   footer.append(holder,tile.querySelector('.fleet-provider-controls'),...tile.querySelectorAll('.fleet-live-meter'));tile.append(footer);
  }
  const summary=el('span','mirror-pair-summary');summary.id='mirrorPairSummary';liveHead.append(summary);const taskButton=el('button','mirror-task-button');taskButton.id='mirrorTaskButton';taskButton.type='button';taskButton.hidden=true;taskButton.onclick=mirrorShowTask;liveHead.append(taskButton);
  const savedCxbRender=cxbRender;cxbRender=function(force){savedCxbRender(force);if(cxbData?.profile_system)mirrorAccept(cxbData.profile_system)};
  /* [notion-ai] 06.11: кнопку профиля Codex рисовали двое: cxHdr() — профилем моста Codex («Codex Full · самостоятельно»), paintMirrorWorkplace() — профилем системы («Codex · на паузе (работает Notion AI)»); строка скакала. Подпись одна — из системы профилей. */
  const savedCxHdr=cxHdr;cxHdr=function(){savedCxHdr();paintMirrorWorkplace()};
  cxMenuOpen=function(){mirrorEngine='codex';mirrorTheme();nativeMirrorOpen()};
  cxMenuPlace=function(){placeProfilePalette(mirrorButtons[mirrorEngine])};
  cxpRender=paintMirrorPalette;
  profileRoot.addEventListener('click',mirrorProfileClick,true);
  profileRoot.addEventListener('change',event=>{if(!event.target.matches('[data-mirror-setting=auto]'))return;event.stopImmediatePropagation();mirrorRequest(event.target.dataset.engine||mirrorEngine,'config',{enabled:event.target.checked,emergency:false})},true);
  profileRoot.addEventListener('keydown',event=>{const card=event.target.closest('.cxprof[data-profile-id]:not([data-auto])');if(!card||event.target!==card)return;if(['Enter',' '].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();mirrorApply(card.dataset.engine||mirrorEngine,card.dataset.profileId)}else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();const cards=[...profileRoot.querySelectorAll('.cxprof[data-profile-id]:not([data-auto]):not([hidden])')],i=cards.indexOf(card),j=event.key==='Home'?0:event.key==='End'?cards.length-1:(i+(['ArrowLeft','ArrowUp'].includes(event.key)?-1:1)+cards.length)%cards.length;cards[j]?.focus()}},true);
  paintMirrorPalette();
 }
 function paintMirrorWorkplace(){
  if(!mirrorState||!mirrorMounted)return;
  for(const e of ['claude','codex']){const state=mirrorState.engines[e],button=mirrorButtons[e];putText(button.querySelector('.cxbtnname'),state.label);button.title='Профиль '+mirrorNames[e]+': '+state.label;button.setAttribute('aria-label',button.title);button.setAttribute('aria-expanded',String(!menu.hidden&&mirrorEngine===e));button.dataset.role=state.role;}
  {const ps=document.getElementById('mirrorPairSummary');if(ps){ps.hidden=true;ps.style.display='none';putText(ps,'')}}const task=mirrorState.task,taskButton=document.getElementById('mirrorTaskButton');taskButton.hidden=!task;taskButton.dataset.status=task?.status||'';putText(taskButton,task?({pending:'Подтвердить шаг',approved:'Шаг подтверждён',running:'Шаг выполняется',done:'Результат шага',cancelled:'Шаг отклонён',uncertain:'Проверить исполнителя'}[task.status]||'Шаг')+' · '+mirrorNames[task.leader]+' → '+mirrorNames[task.follower]:'');
 }
 function mirrorDetails(p){
  const state=mirrorState.engines[mirrorEngine],other=mirrorNames[mirrorEngine==='claude'?'codex':'claude'];
  return '<div class="cxpinfo"><div class="mirror-flow">'+p.flow.map(x=>'<span>'+acctEsc(x)+'</span>').join('<i>→</i>')+'</div><p><b>Может:</b> '+acctEsc(p.can)+'</p><p><b>Ограничения:</b> '+acctEsc(p.cannot)+'</p><p><b>Когда выбрать:</b> '+acctEsc(p.when)+'</p></div>';
 }
 function paintMirrorPalette(){
  if(!mirrorState)return;mirrorTheme();const scroll=profileBody.scrollTop,state=mirrorState.engines[mirrorEngine],e=mirrorEngine,focus=document.activeElement,focusCard=focus?.closest('[data-profile-id]'),focusId=focusCard?.dataset.profileId,focusAction=focus?.dataset.mirrorAction,focusSetting=focus?.dataset.mirrorSetting;menu.dataset.compare=String(compareProfiles);
  putText(paletteCurrent,'Сейчас: '+state.label);paletteCurrent.title=state.label;compareButton.setAttribute('aria-pressed',String(compareProfiles));putText(compareButton,compareProfiles?'Краткий вид':'Сравнить');
  const normal=state.profiles.filter(p=>!['reserve','emergency'].includes(p.kind)).sort((a,b)=>Number(b.id===state.base_selected)-Number(a.id===state.base_selected));
  const cards=normal.map(p=>{const selected=p.id===state.base_selected,expanded=compareProfiles||mirrorInfo[e].has(p.id),status=selected?(state.applied===false?'Текущие права':!['solo','leader'].includes(state.role)?'Базовый профиль':'Выбран'):(p.builtin?'Встроенный':'Свой профиль');return '<div class="cxprof fleet-profile-card'+(selected?' act':'')+'" role="radio" tabindex="0" aria-checked="'+selected+'" data-id="'+acctEsc(p.id)+'" data-profile-id="'+acctEsc(p.id)+'" data-kind="'+(p.kind==='orchestrator'?'team':'solo')+'" data-info-open="'+expanded+'"><div class="fleet-profile-card-head"><span class="cxpr" aria-hidden="true"></span><span class="fleet-profile-status">'+status+'</span>'+(p.builtin?'':'<button type="button" class="cxpx" data-mirror-action="delete" aria-label="Удалить профиль">×</button>')+'</div><span class="cxpt"><span class="cxpn"><span class="cxpnm">'+acctEsc(p.title)+'</span></span><span class="cxps">'+acctEsc(p.description)+'</span><span class="fleet-profile-index" hidden>'+acctEsc(p.can+' '+p.cannot+' '+p.when+' '+(p.kind==='orchestrator'?'Оркестратор':''))+'</span><span class="fleet-profile-meta"><span>'+(p.kind==='orchestrator'?'Ведущий → исполнитель':'Самостоятельно')+'</span><span>'+({read:'С подтверждением шагов',write:'Рабочая папка',full:'Полный доступ'}[p.access]||'')+'</span></span>'+(expanded?mirrorDetails(p):'')+'</span><div class="fleet-profile-card-footer"><span class="fleet-profile-choose">'+(selected&&['solo','leader'].includes(state.role)&&state.applied!==false?'Работает сейчас':'Выбрать →')+'</span><button type="button" class="cxpi fleet-profile-more" data-mirror-action="info" aria-expanded="'+expanded+'" '+(compareProfiles?'hidden':'')+'>Подробнее ⌄</button></div></div>'}).join('');
  const services=state.profiles.filter(p=>['reserve','emergency'].includes(p.kind));
  const serviceHtml=services.map(p=>{const active=state.role===p.kind,expanded=compareProfiles||mirrorInfo[e].has(p.id);return '<section class="mirror-service '+(p.kind==='emergency'?'cxemg':'cxprof rsv fleet-profile-service')+'" '+(p.kind==='reserve'?'data-auto="1"':'')+' data-profile-id="'+p.id+'"><div class="mirror-service-copy"><strong>'+acctEsc(p.title)+'</strong><div class="cxps">'+acctEsc(p.description)+'</div>'+(active?'<span class="mirror-service-state">Включён'+(mirrorState.service.source==='auto'?' автоматически':' вручную')+'</span>':'')+(active&&state.until?'<small>До отключения: '+new Date(state.until*1000).toLocaleTimeString('ru-RU')+'</small>':'')+(expanded?mirrorDetails(p):'')+'</div><div class="mirror-service-actions"><button type="button" data-mirror-action="'+(active?'stop':'apply')+'">'+(active?'Выключить':'Включить…')+'</button><button type="button" data-mirror-action="info" aria-expanded="'+expanded+'">Подробнее ⌄</button></div></section>'}).join('');
  profileRoot.innerHTML='<div class="cxplist">'+cards+'</div>'+(serviceHtml?'<div class="fleet-profile-service-heading">Служебные режимы '+mirrorNames[e]+'</div>'+serviceHtml:'');
  filterProfiles();repaintProfileResults();profileBody.scrollTop=scroll;paintMirrorWorkplace();if(!menu.hidden){cxMenuPlace();if(focusId){const card=profileRoot.querySelector('[data-profile-id="'+focusId+'"]'),target=focusAction?card?.querySelector('[data-mirror-action="'+focusAction+'"]'):focusSetting?card?.querySelector('[data-mirror-setting="'+focusSetting+'"]'):card;target?.focus({preventScroll:true})}}
 }
 function mirrorProfileClick(event){
  const card=event.target.closest('[data-profile-id]');if(!card)return;event.stopImmediatePropagation();if(event.target.closest('.mirror-auto-settings label'))return;const action=event.target.closest('[data-mirror-action]')?.dataset.mirrorAction,id=card.dataset.profileId;
  if(action==='info'){mirrorInfo[mirrorEngine].has(id)?mirrorInfo[mirrorEngine].delete(id):mirrorInfo[mirrorEngine].add(id);cxpRender();return}
  if(action==='delete'){if(confirm('Удалить этот свой профиль?'))mirrorRequest(mirrorEngine,'delete',{id});return}
  if(action==='stop'){mirrorStop(mirrorEngine);return}
  if(action==='apply'||(!card.classList.contains('mirror-service')&&!event.target.closest('.cxpinfo')))mirrorApply(mirrorEngine,id);
 }
 async function mirrorRequest(engine,action,body,revision=mirrorState.revision){
  if(mirrorBusy)return;
  mirrorBusy=true;menu.setAttribute('aria-busy','true');
  try{const send=b=>fetch(API+'profiles/'+engine+'/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':TOKEN},body:JSON.stringify({...b,revision})}).then(r=>r.json());let result=await send(body);if(result.confirmation_required&&(action==='apply'||action==='config')&&result.word)result=await send({...body,confirm:result.word});if(result.state)mirrorAccept(result.state);if(result.confirmation_required){cxMenuClose();mirrorConfirm(engine,body.id,result.word,action,body,revision);return}if(!result.ok){toast(result.message||'Не удалось применить профиль');if(result.conflict)await mirrorLoad();return}if(action==='apply'||action==='stop')cxMenuClose();toast(result.message||'Действие выполнено');cxbLoad(true)}catch(_){toast('Не удалось обновить профиль. Повтори после обновления данных.')}finally{mirrorBusy=false;menu.removeAttribute('aria-busy')}
 }
 function mirrorApply(engine,id,confirmation=''){return mirrorRequest(engine,'apply',{id,confirm:confirmation})}
 function mirrorStop(engine){if(mirrorState.service?.kind==='emergency'&&!confirm('Выключить аварийный режим '+mirrorNames[engine]+' и восстановить прежний сценарий?'))return;return mirrorRequest(engine,'stop',{})}
 function mirrorShowTask(){const task=mirrorState.task;if(!task)return;cxMenuClose();acctShow('<h3>'+acctEsc(mirrorNames[task.leader]+' → '+mirrorNames[task.follower])+'</h3><p>Права шага: '+acctEsc({read:'чтение',dev:'дев',full:'полные'}[task.rights]||task.rights)+'</p><pre class="mirror-task-text">'+acctEsc(task.text)+'</pre>'+(task.result?'<h4>Результат</h4><pre class="mirror-task-text">'+acctEsc(task.result)+'</pre>':'')+(task.error?'<p>'+acctEsc(task.error)+'</p>':'')+(task.status==='pending'?(task.rights==='full'?'<label>Для полных прав введи «подтверждаю»<input id="mirrorTaskWord" class="dlginp" autocomplete="off"></label>':'')+'<div class="modalfoot"><button id="mirrorTaskReject" class="ghostbtn">Отклонить</button><button id="mirrorTaskApprove">Отправить исполнителю</button></div>':'<div class="modalfoot"><button id="mirrorTaskClose">Закрыть</button></div>'));document.getElementById('mirrorTaskClose')?.addEventListener('click',acctClose);for(const [id,approve] of [['mirrorTaskReject',false],['mirrorTaskApprove',true]])document.getElementById(id)?.addEventListener('click',async()=>{try{const response=await fetch(API+'profiles/task/confirm',{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':TOKEN},body:JSON.stringify({id:task.id,approve,confirm:document.getElementById('mirrorTaskWord')?.value||''})}),result=await response.json();if(result.state)mirrorAccept(result.state);toast(result.message);if(result.ok)acctClose()}catch(_){toast('Не удалось подтвердить шаг. Обнови данные перед повтором.')}})}
 function mirrorConfirm(engine,id,word,action='apply',body={id},revision=mirrorState.revision){
  const p=mirrorState.engines[engine].profiles.find(p=>p.id===id),impact='Full работает самостоятельно со всеми доступными инструментами, командами и файлами.';acctShow('<div class="mirror-confirm" data-engine="'+engine+'"><h3>'+acctEsc(p.title)+(action==='config'?' · автоматически':'')+'</h3><p>'+impact+'</p><p>Введи <b>'+acctEsc(word)+'</b>, чтобы подтвердить изменение сценария для '+mirrorNames[engine]+'.</p><input id="mirrorConfirmWord" class="dlginp" autocomplete="off" spellcheck="false" aria-label="Слово подтверждения"><div class="modalfoot"><button type="button" id="mirrorConfirmCancel" class="ghostbtn">Отмена</button><button type="button" id="mirrorConfirmApply" disabled>Применить</button></div></div>');
  const input=document.getElementById('mirrorConfirmWord'),apply=document.getElementById('mirrorConfirmApply');input.addEventListener('input',()=>apply.disabled=input.value.trim().toLocaleLowerCase('ru')!==word);input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!apply.disabled)apply.click()});document.getElementById('mirrorConfirmCancel').onclick=()=>{acctClose();mirrorButtons[engine].focus()};apply.onclick=()=>{const text=input.value;acctClose();mirrorRequest(engine,action,{...body,confirm:text},revision)};setTimeout(()=>input.focus(),30);
 }
 // Единое центральное окно двух исполнителей. [notion-ai] Настроек резерва больше нет.
 let monoView='profiles',monoSignature='';
 const monoRawOpen=cxMenuOpen;let monoPendingOpen=null;
 cxMenuOpen=function(){if(!mirrorMounted){monoPendingOpen=['codex'];mirrorLoad();return}mirrorOpen('codex')};

 const monoOriginalFilter=filterProfiles,monoOriginalResults=repaintProfileResults;
 filterProfiles=function(){
  if(!mirrorMounted)return monoOriginalFilter();if(search.value!==profileQuery)search.value=profileQuery;
  if(monoView!=='profiles')return;
  const query=profileQuery.trim().toLocaleLowerCase('ru');
  profileRoot.querySelectorAll('.fleet-profile-card,.mono-reserve').forEach(node=>node.hidden=!!query&&!node.textContent.toLocaleLowerCase('ru').includes(query));
  for(const section of profileRoot.querySelectorAll('.mono-provider'))section.hidden=![...section.querySelectorAll('.fleet-profile-card,.mono-reserve')].some(node=>!node.hidden);if(!menu.hidden)monoCenter();
 }
 repaintProfileResults=function(){
  if(!mirrorMounted)return monoOriginalResults();
  if(monoView!=='profiles'){paletteEmpty.hidden=true;return}
  const cards=[...profileRoot.querySelectorAll('.fleet-profile-card')],reserves=[...profileRoot.querySelectorAll('.mono-reserve')],visible=cards.filter(node=>!node.hidden).length,services=reserves.filter(node=>!node.hidden).length;
  paletteEmpty.hidden=visible+services>0;putText(paletteCount,profileQuery.trim()?'Найдено: '+visible+' из '+cards.length:cards.length+' рабочих профиля');
 }

 function monoCenter(){
  menu.classList.toggle('fleet-profile-desktop',!mobileConsole.matches);
  if(mobileConsole.matches){menu.style.top='var(--fleet-visual-top,0px)';menu.style.left='0';menu.style.right='0';menu.style.bottom='auto';menu.style.width='100%';menu.style.height=menu.style.maxHeight='var(--fleet-visual-height,100dvh)';return}
  const w=innerWidth,h=innerHeight,width=Math.min(monoView==='reserve'?960:880,w-24);
  menu.style.height='';menu.style.width=width+'px';menu.style.maxHeight=(h-24)+'px';menu.style.left=Math.round((w-width)/2)+'px';menu.style.right='auto';menu.style.bottom='auto';menu.style.top=Math.max(12,Math.round((h-menu.getBoundingClientRect().height)/2))+'px';
 }
 cxMenuPlace=monoCenter;
 mirrorTheme=function(){
  menu.dataset.engine='both';menu.dataset.view=monoView;menu.classList.add('mono-profile-window');
  putText(paletteHeading.querySelector('h2'),'Профили работы');
  menu.setAttribute('aria-label','Профили Claude и Codex');
  paletteHeading.querySelector('.mirror-profile-tabs')?.setAttribute('hidden','');
  paletteTools.hidden=monoView!=='profiles';compareButton.hidden=true;
 }
 mirrorOpen=function(engine,info){
  mirrorEngine=engine;menu.dataset.returnEngine=engine;monoView='profiles';compareProfiles=false;resetProfileSearch();monoSignature='';mirrorTheme();
  if(menu.hidden)nativeMirrorOpen();else cxpRender();monoCenter();
 }
 function monoDetails(profile){
  return '<div class="cxpinfo"><p><b>Может:</b> '+acctEsc(profile.can)+'</p><p><b>Ограничения:</b> '+acctEsc(profile.cannot)+'</p><p>'+acctEsc(profile.when)+'</p></div>';
 }
 function monoCard(engine,profile,state){
  const selected=profile.id===state.base_selected,info=mirrorInfo[engine].has(profile.id);
  const effective=selected&&['solo','leader'].includes(state.role)&&state.applied!==false;
  const status=selected?(state.applied===false?'Текущие права':effective?'Работает сейчас':'Базовый профиль'):profile.kind==='full'?'Полный доступ':'Чтение + папка обмена';
  return '<div class="cxprof fleet-profile-card'+(selected?' act':'')+'" data-engine="'+engine+'" data-profile-id="'+profile.id+'" data-id="'+profile.id+'" role="radio" aria-checked="'+selected+'" tabindex="0"><div class="mono-mode-head"><span class="mono-mode-kind">'+(profile.kind==='full'?'FULL':'ОРКЕСТРАТОР')+'</span><span class="mono-mode-status">'+status+'</span></div><div class="cxpt"><span class="cxpn"><span class="cxpnm">'+acctEsc(profile.title)+'</span></span><span class="cxps">'+acctEsc(profile.description)+'</span><span class="fleet-profile-index" hidden>'+acctEsc(profile.can+' '+profile.cannot+' '+profile.when)+'</span>'+(info?monoDetails(profile):'')+'</div><div class="fleet-profile-card-footer"><span class="fleet-profile-choose">'+(effective?'Выбран':'Выбрать →')+'</span><button type="button" class="fleet-profile-more" aria-disabled="false" data-mirror-action="info" aria-expanded="'+info+'">'+(info?'Свернуть':'Подробнее')+'</button></div></div>';
 }
 paintMirrorPalette=function(){
  if(!mirrorState)return;mirrorTheme();
  const signature=JSON.stringify([monoView,mirrorState.revision,mirrorState.service,mirrorState.engines]);
  if(signature===monoSignature){monoCenter();return}monoSignature=signature;
  const focus=document.activeElement,focusId=focus?.id,focusCard=focus?.closest('[data-profile-id]'),focusEngine=focus?.dataset.engine||focusCard?.dataset.engine,focusProfile=focusCard?.dataset.profileId,action=focus?.dataset.mirrorAction,setting=focus?.dataset.mirrorSetting;
  
  let html='<div class="mono-provider-grid">';
  for(const engine of ['claude','codex']){
   const state=mirrorState.engines[engine];html+='<section class="mono-provider" data-engine="'+engine+'" aria-label="Профили '+mirrorNames[engine]+'"><header class="mono-provider-head"><strong>'+mirrorNames[engine]+'</strong><span>'+acctEsc(state.label)+'</span></header>';
   html+='<div class="cxplist" role="radiogroup" aria-label="Рабочий профиль '+mirrorNames[engine]+'">'+state.profiles.map(p=>monoCard(engine,p,state)).join('')+'</div>';
   html+='</section>';
  }
  html+='</div>';
  html+='<div class="mono-window-note">'+'Ведущая указана первой. В оркестраторе каждый шаг подтверждает человек.'+'</div>';
  profileRoot.innerHTML=html;
  putText(paletteCurrent,'У каждой модели: Full и Оркестратор');putText(paletteCount,'Claude + Codex · единый выбор');putText(paletteHelp,'Esc — закрыть');
  paletteEmpty.hidden=true;if(monoView==='profiles')filterProfiles();repaintProfileResults();
  if(focusId&&document.getElementById(focusId))document.getElementById(focusId).focus({preventScroll:true});
  else if(focusEngine&&focusProfile){const card=profileRoot.querySelector('[data-engine="'+focusEngine+'"][data-profile-id="'+focusProfile+'"]'),target=action?card?.querySelector('[data-mirror-action="'+action+'"]'):setting?card?.querySelector('[data-mirror-setting="'+setting+'"]'):card;target?.focus({preventScroll:true})}
  paintMirrorWorkplace();monoCenter();
 }
 mirrorProfileClick=function(event){
  const card=event.target.closest('[data-profile-id]');if(!card)return;event.stopImmediatePropagation();if(event.target.closest('.mono-auto'))return;
  const engine=card.dataset.engine||mirrorEngine,action=event.target.closest('[data-mirror-action]')?.dataset.mirrorAction,id=card.dataset.profileId;
  if(action==='info'){mirrorInfo[engine].has(id)?mirrorInfo[engine].delete(id):mirrorInfo[engine].add(id);monoSignature='';cxpRender();return}
  if(action==='stop'){mirrorStop(engine);return}
  if(action==='apply'||card.matches('.fleet-profile-card')&&!event.target.closest('.cxpinfo'))mirrorApply(engine,id);
 }
 const monoMount=mountMirrorProfiles;mountMirrorProfiles=function(){
  monoMount();nativeMirrorOpen=monoRawOpen;cxMenuPlace=monoCenter;cxMenuOpen=function(){mirrorOpen('codex')};
  const originalWorkplace=paintMirrorWorkplace;paintMirrorWorkplace=function(){originalWorkplace();for(const engine of ['claude','codex']){mirrorButtons[engine].setAttribute('aria-expanded',String(!menu.hidden&&monoView==='profiles'))}profilesBtn.setAttribute('aria-expanded',String(!menu.hidden&&monoView==='profiles'))};
  for(const engine of ['claude','codex']){
   mirrorButtons[engine].addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();profileOpener=null;if(!menu.hidden&&monoView==='profiles')cxMenuClose();else mirrorOpen(engine)},true);
  }
  const close=cxMenuClose;cxMenuClose=function(...args){monoSignature='';close(...args)};
  new MutationObserver(()=>{if(!menu.hidden&&monoView==='profiles'&&matchMedia('(pointer:fine)').matches)profileRoot.querySelector('.fleet-profile-card.act[data-engine="'+mirrorEngine+'"]')?.focus({preventScroll:true})}).observe(menu,{attributes:true,attributeFilter:['hidden']});
  monoSignature='';paintMirrorPalette();if(monoPendingOpen){const pending=monoPendingOpen;monoPendingOpen=null;mirrorOpen(...pending)}
 }
 addEventListener('resize',()=>{if(!menu.hidden)monoCenter()});window.visualViewport?.addEventListener('resize',()=>{if(!menu.hidden)monoCenter()});

 // Роли — черновик пользователя. До общей кнопки применения API не вызывается.
 let manualDraft=null,manualRevision=-1,manualDirty=false;
 const manualEngines=['claude','codex'];
 const manualOther=engine=>engine==='claude'?'codex':'claude';
 const manualSame=(a,b)=>manualEngines.every(engine=>a?.[engine]===b?.[engine]);
 const manualCurrent=()=>mirrorState?.manual_scenario?.choices||{claude:null,codex:null};
 const manualProdNote=()=>{try{return window.fleetRemote&&window.fleetRemote.mode().active?' · Claude работает на PROD':''}catch(_){return ''}};
 paletteTools.remove();paletteFooter.remove();
 const manualThemeBefore=mirrorTheme;
 mirrorTheme=function(){manualThemeBefore();putText(paletteCurrent,'Full или Оркестратор');if(monoView==='profiles')putText(paletteHeading.querySelector('h2'),'Выбор профиля')};
 function manualSync(){
  if(!manualDraft||!manualDirty){manualDraft={...manualCurrent()};manualRevision=mirrorState.revision;manualDirty=false}
 }
 function manualReason(engine,role){
  const other=manualOther(engine);
  if(manualDraft[other]==='orchestrator')return role==='full'?mirrorNames[other]+' выбрана оркестратором. Full '+mirrorNames[engine]+' заблокирован.':'Ведущая уже выбрана: '+mirrorNames[other]+'. Сними её выбор, чтобы сменить оркестратора.';
  return '';
 }
 function manualStatus(){
  if(mirrorState.updating)return {valid:false,text:'Завершается обновление панели. Профиль можно применить после проверки.'};
  if(manualRevision!==mirrorState.revision)return {valid:false,text:'Профиль изменился в другом окне. Верни текущий выбор перед применением.',stale:true};
  const leader=manualEngines.find(engine=>manualDraft[engine]==='orchestrator'),full=manualEngines.find(engine=>manualDraft[engine]==='full'),roles=manualEngines.filter(engine=>manualDraft[engine]);
  if(leader){const other=manualOther(leader);return manualDraft[other]==='executor'?{valid:true,text:mirrorNames[leader]+' → '+mirrorNames[other]+' · выполнение шагов подключено'+manualProdNote()}:{valid:false,text:mirrorNames[leader]+' — оркестратор. Подключи '+mirrorNames[other]+' для выполнения подтверждённых шагов.'}}
  if(full&&roles.length===1)return {valid:true,text:mirrorNames[full]+' Full · самостоятельно; '+mirrorNames[manualOther(full)]+' не участвует'};
  return {valid:false,text:'Выбери Full или Оркестратор. До применения текущая работа продолжается.'};
 }
 function manualSelect(engine,role){
  if(mirrorBusy||!['full','orchestrator'].includes(role))return;manualSync();
  const reason=manualReason(engine,role);if(reason){toast(reason);return}
  if(role==='orchestrator'&&manualDraft[engine]===role)manualDraft={claude:null,codex:null};
  else manualDraft={claude:null,codex:null,[engine]:role};
  manualDirty=!manualSame(manualDraft,manualCurrent());monoSignature='';cxpRender();
 }
 function manualCompanion(engine){
  if(mirrorBusy||manualDraft[manualOther(engine)]!=='orchestrator')return;
  manualDraft={...manualDraft,[engine]:manualDraft[engine]==='executor'?null:'executor'};
  manualDirty=!manualSame(manualDraft,manualCurrent());monoSignature='';cxpRender();
 }
 function manualCardTitle(engine,role){return mirrorNames[engine]+(role==='orchestrator'?' · оркестратор':' Full · самостоятельно');}
 function manualRoleCard(engine,role){
  const state=mirrorState.engines[engine],id=role==='full'?engine+'_solo_full':'orchestrator',p=state.profiles.find(profile=>profile.id===id),selected=manualDraft[engine]===role,reason=manualReason(engine,role),info=mirrorInfo[engine].has(id),current=state.selected===id&&['solo','leader'].includes(state.role),label=role==='full'?mirrorNames[engine]+' Full':mirrorNames[engine]+' · оркестратор';
  const copy=role==='full'?'Самостоятельно планирует, выполняет и проверяет задачу. Полные доступные права.':'Планирует и проверяет работу. Вторая модель выполняет шаги после твоего подтверждения.';
  return '<div class="cxprof fleet-profile-card manual-role full-choice'+(role==='orchestrator'?' orchestrator-choice':'')+(selected?' act':'')+'" data-engine="'+engine+'" data-profile-id="'+id+'" data-id="'+id+'" data-manual-role="'+role+'" role="radio" aria-checked="'+selected+'" aria-disabled="'+!!reason+'" tabindex="0"'+(reason?' title="'+acctEsc(reason)+'"':'')+'><div class="full-choice-top"><span class="full-choice-check" aria-hidden="true">'+(selected?'✓':'')+'</span><span class="full-choice-badge">'+(reason?'Заблокирован':selected?'Выбран':current?'Текущая сессия':role==='full'?'Full':'Оркестратор')+'</span></div><div class="cxpt"><span class="cxpn"><span class="cxpnm">'+acctEsc(label)+'</span></span><span class="cxps">'+copy+'</span>'+(info?monoDetails(p):'')+'</div><div class="fleet-profile-card-footer"><span class="fleet-profile-choose">'+(reason?'Недоступен при выбранном оркестраторе':selected?(role==='orchestrator'?'Нажми повторно, чтобы снять':manualDirty?'Выбран для применения':'Действующий профиль'):'Нажми, чтобы выбрать')+'</span><button type="button" class="fleet-profile-more" aria-disabled="false" data-mirror-action="info" aria-expanded="'+info+'">'+(info?'Свернуть':'Подробнее')+'</button></div></div>';
 }
 function manualCompanionPanel(engine){
  const leader=manualOther(engine);if(manualDraft[leader]!=='orchestrator')return '';
  const selected=manualDraft[engine]==='executor';
  return '<section class="manual-companion" data-engine="'+engine+'"><span>'+acctEsc(mirrorNames[engine]+' выполняет подтверждённые шаги '+mirrorNames[leader]+'.')+'</span><button type="button" data-manual-action="companion" data-companion-engine="'+engine+'" aria-pressed="'+selected+'">'+(selected?'✓ Подключён · нажми, чтобы отключить':'Подключить '+mirrorNames[engine]+' для выполнения шагов')+'</button></section>';
 }
 const manualPaletteBefore=paintMirrorPalette;
 paintMirrorPalette=function(){
  if(!mirrorState)return;manualSync();mirrorTheme();
  const scroll=profileBody.scrollTop,focused=document.activeElement,focusedCard=focused?.closest('[data-manual-role]'),focusEngine=focusedCard?.dataset.engine,focusRole=focusedCard?.dataset.manualRole,focusInfo=focused?.dataset.mirrorAction==='info',focusAction=focused?.dataset.manualAction;
  const status=manualStatus(),recovering=!!mirrorState.recovery?.blocked,dirty=manualDirty||recovering,signature=JSON.stringify([mirrorState.revision,mirrorState.updating,recovering,manualDraft,mirrorInfo.claude.size,mirrorInfo.codex.size,mirrorBusy]);
  if(recovering)status.text='Автоматические перезапуски остановлены. Выбери профиль и повтори восстановление подключения.';
  if(signature===monoSignature){monoCenter();return}monoSignature=signature;
  let html='<div class="mono-provider-grid manual-provider-grid" role="radiogroup" aria-label="Full или Оркестратор">';
  for(const engine of manualEngines){
   const selected=manualDraft[engine];
   html+='<section class="mono-provider" data-engine="'+engine+'" aria-label="Профили '+mirrorNames[engine]+'"><header class="mono-provider-head"><strong>'+mirrorNames[engine]+'</strong><span>'+(selected?acctEsc(selected==='executor'?'Выполнение шагов подключено':manualCardTitle(engine,selected)):acctEsc(mirrorState.engines[engine].label))+'</span></header>'+manualRoleCard(engine,'full')+manualRoleCard(engine,'orchestrator')+manualCompanionPanel(engine)+'</section>';
  }
  html+='</div><div class="manual-apply-bar"><div class="manual-selection-summary" role="status"><strong>'+(!dirty?(status.valid?'Действующий профиль':'Текущие сессии работают'):status.valid?'Готово к применению':'Выбери профиль')+'</strong><span>'+acctEsc(status.text)+'</span></div><div class="manual-scenario-actions">'+(dirty?'<button type="button" class="ghostbtn" data-manual-action="restore">Вернуть текущий</button>':'')+'<button type="button" class="manual-apply" data-manual-action="apply" '+(!status.valid||!dirty||mirrorBusy?'disabled':'')+'>'+(mirrorBusy?'Применение…':recovering?'Повторить восстановление':!dirty?(status.valid?'Профиль применён':'Выбери профиль'):'Применить профиль')+'</button></div></div>';
  profileRoot.innerHTML=html;paletteEmpty.hidden=true;profileBody.scrollTop=scroll;
  if(focusEngine&&focusRole){const node=profileRoot.querySelector('[data-engine="'+focusEngine+'"][data-manual-role="'+focusRole+'"]');(focusInfo?node?.querySelector('[data-mirror-action="info"]'):node)?.focus({preventScroll:true})}
  else if(focusAction)profileRoot.querySelector('[data-manual-action="'+focusAction+'"]')?.focus({preventScroll:true});
  paintMirrorWorkplace();monoCenter();
 }
 const manualClickBefore=mirrorProfileClick;
 mirrorProfileClick=function(event){
  if(monoView!=='profiles')return manualClickBefore(event);
  const action=event.target.closest('[data-manual-action]')?.dataset.manualAction;
  if(action){event.stopImmediatePropagation();if(mirrorBusy)return;if(action==='apply'){manualApplyScenario();return}if(action==='companion'){manualCompanion(event.target.closest('[data-companion-engine]').dataset.companionEngine);return}manualDraft=action==='restore'?{...manualCurrent()}:{claude:null,codex:null};manualRevision=mirrorState.revision;manualDirty=!manualSame(manualDraft,manualCurrent());monoSignature='';cxpRender();return}
  const card=event.target.closest('[data-manual-role]');if(!card)return;event.stopImmediatePropagation();const engine=card.dataset.engine,role=card.dataset.manualRole,sub=event.target.closest('[data-mirror-action]')?.dataset.mirrorAction;
  if(sub==='info'){const id=card.dataset.profileId;mirrorInfo[engine].has(id)?mirrorInfo[engine].delete(id):mirrorInfo[engine].add(id);monoSignature='';cxpRender();return}
  if(!event.target.closest('.cxpinfo'))manualSelect(engine,role);
 }
 const manualApplyBefore=mirrorApply;
 mirrorApply=function(engine,id,confirmation=''){if(monoView==='profiles'&&!menu.hidden){manualSelect(engine,id.endsWith('_solo_full')?'full':id);return Promise.resolve()}return manualApplyBefore(engine,id,confirmation)};
 async function manualApplyScenario(confirmation='',choices={...manualDraft},revision=manualRevision){
  if(mirrorBusy||!manualStatus().valid)return;mirrorBusy=true;menu.setAttribute('aria-busy','true');
  try{
   const send=word=>fetch(API+'profiles/scenario/apply',{method:'POST',headers:{'Content-Type':'application/json','X-CC-Token':TOKEN},body:JSON.stringify({choices,revision,confirm:word})}).then(r=>r.json());
   let result=await send(confirmation);
   if(result.confirmation_required&&result.word)result=await send(result.word);
   if(!result.ok){toast(result.message||'Не удалось применить сценарий');if(result.conflict)await mirrorLoad();return}
   manualDirty=false;manualDraft=null;monoSignature='';mirrorAccept(result.state);toast(result.message);cxbLoad(true);
  }catch(_){toast('Не удалось применить профиль. Текущая работа продолжается.')}
  finally{mirrorBusy=false;menu.removeAttribute('aria-busy');monoSignature='';if(!menu.hidden)cxpRender()}
 }

 mirrorLoad();

 loadRotation();setInterval(()=>{if(!document.hidden)loadRotation()},5000);
})();
'''


def render(page):
    return page.replace('</head>', '<style id="fleetOverviewStyle">'+CSS+'</style></head>', 1).replace(
        '</body>', '<script id="fleetOverviewScript">'+JS.replace('__FLEET_BRAND_ICON__', BRAND_ICON_DATA_URL)+'</script></body>', 1)
