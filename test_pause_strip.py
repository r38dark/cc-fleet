"""Обратный отсчёт лимитов в центре консолей Claude DEV, Claude PROD и Codex:
настоящий JS из cc_limits.py под node с подделкой документа."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
SRC = (HERE / "cc_limits.py").read_text(encoding="utf-8")


def cut(pattern, what):
    m = re.search(pattern, SRC, re.S | re.M)
    assert m, "в cc_limits.py не найдено: " + what
    return m.group(0)


def node(js):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.js")
        Path(p).write_text(js, encoding="utf-8")
        r = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise AssertionError(r.stderr[-800:])
        return json.loads(r.stdout)


# от ccpsHtml до ccpPartStrip включительно: правило лимита (limx*), иконки, бейджи плиток и сама полоса — одним куском, как в странице
FUNC = cut(r"^function ccpsHtml\(k\)\{.*?^function ccpPartStrip\(\)\{.*?^\}$", "ccpsHtml … ccpPartStrip")
POLICY_STRINGS = cut(r"^  ccpaWeek:.*?\n  ccpaWait:.*?$", "переводы нормализованного бюджета")
TIMER_STRINGS = cut(r"^  ccpsReset5h:.*?$", "переводы обратного отсчёта")

HARNESS = r'''
const els={};let box=null;
let clockNow=NOW_JSON;Date.now=()=>clockNow;
const mkEl=()=>({hidden:false,style:{},dataset:{},className:'',innerHTML:'',title:'',appendChild(c){}});
const wrap={classList:{contains:c=>SPLIT&&c==='tsplit'},getBoundingClientRect:()=>({left:100,top:50}),appendChild(c){box=c}};
const document={querySelector:()=>wrap,getElementById:id=>id==='ccps'?box:(els[id]||null),
  createElement:()=>{const e=mkEl();Object.defineProperty(e,'id',{set(v){this._id=v;els[v]=this},get(){return this._id}});return e}};
const window={innerWidth:1400,FLEET_TZ:'Asia/Irkutsk'};const setInterval=()=>0,matchMedia=()=>({matches:false});const LANG='ru';
const PANES=PANES_JSON.map(p=>({k:p.k,hid:!!p.hid,box:{offsetParent:p.off?null:{},getBoundingClientRect:()=>({left:p.l,top:p.t,width:p.w,height:p.h||400})}}));
const T={ccpsTitle:'Claude на паузе по лимитам',ccpsTitleCx:'Codex на паузе по лимитам',ccpsBody:'Сообщения в Telegram встают в очередь.',ccpsBodyCx:'Сообщения из Telegram ждут в очереди.',
  ccpsUntil:(at,left)=>' до '+at+' (осталось '+left+')',cxlpWin:m=>m===300?'окно 5 ч':'окно неделя',
  limxPause:at=>'пауза по лимитам'+(at?' до '+at:''),limxOutWeek:at=>'лимит недели исчерпан'+(at?' до '+at:''),limxOut5h:at=>'лимит 5 ч исчерпан'+(at?' до '+at:''),limxOut:at=>'лимит исчерпан'+(at?' до '+at:''),
  limxTipPause:'Новые действия ждут сброса.',limxTipOut:'Настоящий лимит исчерпан.',
  POLICY_STRINGS_HERE
  TIMER_STRINGS_HERE};
const tr=(k,...a)=>typeof T[k]==='function'?T[k](...a):T[k];
const ccpAt=ms=>'23:10', ccpLeft=ms=>'12 мин 00 с', ccpEsc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let ccpData=DATA_JSON, cxlpData=CX_JSON, lastSnap=SNAP_JSON;
FUNC_HERE
ccpPartStrip();
clockNow+=ADVANCE_JSON;if(ADVANCE_JSON)ccpPartStrip();
console.log(JSON.stringify(Object.keys(els).filter(k=>k!=='ccps').map(k=>({id:k,hidden:els[k].hidden,html:els[k].innerHTML,kind:els[k].dataset.kind,title:els[k].title,top:els[k].style.top,left:els[k].style.left,width:els[k].style.width,height:els[k].style.height}))));
'''


def run(data, panes, split=False, cx=None, snap=None, now=1800000000000, advance=0):
    js = (HARNESS.replace("FUNC_HERE", FUNC).replace("POLICY_STRINGS_HERE", POLICY_STRINGS).replace("TIMER_STRINGS_HERE", TIMER_STRINGS).replace("DATA_JSON", json.dumps(data)).replace("CX_JSON", json.dumps(cx)).replace("SNAP_JSON", json.dumps(snap)).replace('NOW_JSON',str(now)).replace('ADVANCE_JSON',str(advance))
          .replace("PANES_JSON", json.dumps(panes)).replace("SPLIT", "true" if split else "false"))
    return node(js)


BLOCKED = {"remote_pause": {"enabled": True, "applied": True, "blocked": True, "resume_at": 1794324600, "reasons": ["5 ч: 90% (порог 90%)"]}}
CODEX = {"active": True, "paused": True, "resume_at": 1794324600, "windows": [300]}
PANES = [{"k": "claude", "l": 100, "t": 50, "w": 600}, {"k": "prod", "l": 720, "t": 50, "w": 600}]
PANES_CX = [{"k": "claude", "l": 100, "t": 50, "w": 600}, {"k": "codex", "l": 720, "t": 50, "w": 600}]
FUTURE = 4102444800   # 2100 год: сброс ещё не прошёл


@unittest.skipUnless(shutil.which("node"), "нет node")
class PauseStrip(unittest.TestCase):
    def test_current_claude_weekly_states_draw_distinct_icons_in_their_own_panes(self):
        data = {'claude_limits': {
            'claude': {'window': 'week', 'pct': 100, 'threshold': 99, 'resume_at': FUTURE, 'waiting': True},
            'prod': {'window': 'week', 'pct': 99, 'threshold': 99, 'resume_at': FUTURE+3600, 'waiting': True}},
            'pause': {'active': True, 'resume_at': FUTURE}, 'remote_pause': {}}
        r = run(data, PANES, split=True)
        self.assertEqual([(x['id'],x['kind']) for x in r], [('ccps0','out'),('ccps1','pause')])
        self.assertIn('Неделя · до сброса',r[0]['html'])
        self.assertNotIn('<svg',r[0]['html'])
        self.assertIn('Claude DEV: лимит недели исчерпан',r[0]['title'])
        self.assertIn('role="timer"',r[1]['html'])
        self.assertIn('Claude PROD',r[1]['title'])
        # A configured quota hold is not proof of an active Telegram queue.
        self.assertNotIn('очеред',r[1]['title'])
        self.assertEqual((r[0]['left'],r[1]['left']),('0px','620px'))

    def test_recovered_claude_budget_hides_both_icons(self):
        data = {'claude_limits': {}, 'pause': {'active': True},
                'remote_pause': {'enabled': True, 'applied': True, 'blocked': True}}
        self.assertEqual(run(data,PANES),[])

    def test_prod_icon_over_prod_part_with_time_reason_and_queue_note_in_title(self):
        r = run(BLOCKED, PANES)
        self.assertEqual([x["id"] for x in r], ["ccps1"])                # только часть PROD, у Claude DEV иконки нет
        x = r[0]
        self.assertFalse(x["hidden"])
        self.assertIn('class="ccps-value', x["html"])
        self.assertNotIn("Claude на паузе", x["html"])
        for part in ("Claude на паузе по лимитам", "до 23:10", "осталось 12 мин", "5 ч: 90% (порог 90%)", "очередь"):
            self.assertIn(part, x["title"])                              # подробный текст — подсказка (и сверху в баннере)
        self.assertNotIn("<b>", x["title"])
        self.assertEqual((x["top"], x["left"], x["width"], x["height"]), ("0px", "620px", "600px", "400px"))   # на всю часть: иконка по центру

    def test_codex_pause_icon_only_when_codex_is_paused_on_limits(self):
        r = run({}, PANES_CX, cx=CODEX)
        self.assertEqual([x["id"] for x in r], ["ccps1"])
        self.assertIn('5 часов · до сброса', r[0]["html"])
        self.assertEqual(r[0]["kind"], "pause")
        for part in ("Codex на паузе по лимитам", "до 23:10", "окно 5 ч", "очереди"):
            self.assertIn(part, r[0]["title"])
        for cx in (None, {"active": False}):
            self.assertEqual(run({}, PANES_CX, cx=cx), [], cx)           # лимита нет — иконки нет

    def test_codex_limit_used_up_without_pause_shows_a_countdown(self):
        r = run({}, PANES_CX, cx={"active": True, "paused": False, "single": True, "windows": [10080], "resume_at": FUTURE, "resets": {"10080": FUTURE}})
        self.assertEqual([x["id"] for x in r], ["ccps1"])
        x = r[0]
        self.assertEqual(x["kind"], "out")
        self.assertIn('Неделя · до сброса', x["html"])
        self.assertNotIn('<svg', x["html"])
        self.assertIn("Codex: лимит недели исчерпан до ", x["title"])
        self.assertEqual((x["top"], x["left"], x["width"], x["height"]), ("0px", "620px", "600px", "400px"))   # вся часть Codex: крестик по центру
        r = run({}, PANES_CX, cx={"active": True, "paused": False, "windows": [], "resume_at": None})
        self.assertEqual((r[0]["kind"], r[0]["title"].split(".")[0]), ("out", "Codex: лимит исчерпан"))   # сервис сказал «лимит» без окна

    def test_pause_wins_over_used_up_limit(self):
        snap = {"remote": {"prod": {"five_hour": {"pct": 100, "resets_at": "2099-01-01T00:00:00Z"}, "seven_day": {"pct": 40}}}}
        r = run(BLOCKED, PANES, snap=snap)
        self.assertEqual([(x["id"], x["kind"]) for x in r], [("ccps1", "pause")])
        self.assertIn("Claude на паузе по лимитам", r[0]["title"])
        r = run({}, PANES, snap=snap)                                    # паузы нет — крестик «лимит 5 ч исчерпан»
        self.assertEqual([(x["id"], x["kind"]) for x in r], [("ccps1", "out")])
        self.assertIn("Claude PROD: лимит 5 ч исчерпан до ", r[0]["title"])

    def test_claude_dev_pause_and_used_up_week_in_its_own_part(self):
        dev = {"pause": {"active": True, "override": False, "resume_at": 1794324600, "reason": "сессия 93%"}}
        r = run(dev, PANES)
        self.assertEqual([(x["id"], x["kind"]) for x in r], [("ccps0", "pause")])   # часть Claude DEV, не PROD
        self.assertIn("Claude на паузе по лимитам", r[0]["title"])
        for off in ({"pause": dict(dev["pause"], override=True)}, dict(dev, stale=True), {"pause": dict(dev["pause"], active=False)}):
            self.assertEqual(run(off, PANES), [], off)                   # пауза отключена вручную / снимок устарел — паузы нет
        snap = {"active": "acc1", "accounts": {"acc1": {"five_hour": {"pct": 20}, "seven_day": {"pct": 100, "resets_at": "2099-01-01T00:00:00Z"}}}}
        r = run({"pause": dict(dev["pause"], override=True)}, PANES, snap=snap)
        self.assertEqual([(x["id"], x["kind"]) for x in r], [("ccps0", "out")])   # пауза отключена, неделя на 100 % — крестик
        self.assertIn("Claude DEV: лимит недели исчерпан до ", r[0]["title"])
        old = {"active": "acc1", "accounts": {"acc1": {"seven_day": {"pct": 100, "resets_at": "2020-01-01T00:00:00Z"}}}}
        self.assertEqual(run({}, PANES, snap=old), [])                   # сброс уже прошёл — окно свободно, цифры старые

    def test_each_strip_goes_only_over_its_own_part(self):
        r = run(BLOCKED, PANES_CX, cx=CODEX)                             # у PROD-части нет, у Codex-части есть
        self.assertEqual([x["id"] for x in r], ["ccps1"])
        self.assertIn("Codex на паузе", r[0]["title"])
        both = [{"k": "prod", "l": 100, "t": 50, "w": 600}, {"k": "codex", "l": 720, "t": 50, "w": 600}]
        r = run(BLOCKED, both, cx=CODEX)
        self.assertEqual({x["id"]: ("Claude на паузе" in x["title"], "Codex на паузе" in x["title"]) for x in r},
                         {"ccps0": (True, False), "ccps1": (False, True)})

    def test_split_mode_icon_still_covers_the_whole_part(self):
        r = run(BLOCKED, PANES, split=True)
        self.assertEqual((r[0]["top"], r[0]["height"]), ("0px", "400px"))     # иконка по центру части, сдвигов под надпись больше нет

    def test_not_shown_when_not_blocked_or_state_missing(self):
        for data in ({}, {"remote_pause": {}}, {"remote_pause": dict(BLOCKED["remote_pause"], blocked=False)},
                     {"remote_pause": dict(BLOCKED["remote_pause"], applied=False)}, {"remote_pause": dict(BLOCKED["remote_pause"], enabled=False)}):
            self.assertEqual(run(data, PANES), [], data)                 # полосы нет и не создаётся

    def test_hidden_when_part_is_not_visible_and_reason_is_escaped(self):
        r = run(BLOCKED, [{"k": "prod", "l": 0, "t": 0, "w": 600, "off": 1}])
        self.assertEqual(r, [])                                          # часть скрыта — полоса не создаётся
        data = {"remote_pause": dict(BLOCKED["remote_pause"], reasons=["<b>x</b>"])}
        r = run(data, PANES)
        self.assertIn("<b>x</b>", r[0]["title"])                         # title — обычный текст: сущности раскодированы, разметки в нём нет
        self.assertNotIn("<b>x</b>", r[0]["html"])

    def test_no_until_time_still_explains(self):
        data = {"remote_pause": dict(BLOCKED["remote_pause"], resume_at=0)}
        r = run(data, PANES)
        self.assertNotIn("до 23:10", r[0]["title"])
        self.assertIn("очередь", r[0]["title"])

    def test_texts_in_both_languages_styles_and_timer_are_in_place(self):
        for key in ("ccpsTitle:", "ccpsTitleCx:", "ccpsUntil:", "ccpsBody:", "ccpsBodyCx:"):
            self.assertEqual(SRC.count(key), 2, key)                     # по одному разу в ru и en
        for part in (".ccps-box{", ".ccps{", ".ccps-value{", "setInterval(ccpPartStrip,1000)", "addEventListener('resize',ccpPartStrip)"):
            self.assertIn(part, SRC, part)

    def test_top_banner_carries_the_console_text_and_its_countdown_ticks(self):
        # 63532: два текста паузы → один. Верхний баннер Claude PROD берёт тексты консольной полосы (до часа, осталось, причина, очередь Telegram)
        i = SRC.index("const rp=d&&d.remote_pause;")
        j = SRC.index("const fleet=d&&d.fleet;", i)
        part = SRC[i:j]
        for need in ("tr('ccpsTitle')", "tr('ccpsUntil'", "tr('ccpsBody')", "ccp-left", "(rp.reasons||[])"):
            self.assertIn(need, part, need)
        self.assertNotIn("Claude на втором сервере: пауза по лимитам", SRC)
        self.assertNotIn("Новые действия ждут сброса лимита.", SRC)
        tick = SRC[SRC.index("function ccpTick(){"):]
        self.assertIn("#ccPause .ccp-left", tick[:400])               # «осталось …» в тексте идёт каждую секунду
        style=SRC[SRC.index('.ccps{'):SRC.index('.ccps-clock{')]
        self.assertIn('pointer-events:none',style)
        self.assertIn('rgba(185,194,212,.82)',style)
        self.assertNotIn('const PAUSE_ICO=',SRC)
        self.assertNotIn('const OUT_ICO=',SRC)

    def test_two_distinct_resets_tick_independently_in_the_same_pane(self):
        now=1800000000000
        data={'claude_limits':{'prod':{'window':'week','pct':99,'waiting':True,'resume_at':now/1000+3*86400,
            'windows':[{'window':'5h','resume_at':now/1000+3000},
                       {'window':'week','resume_at':now/1000+3*86400+7384}]}}}
        first=run(data,PANES,now=now)[0]['html']
        second=run(data,PANES,now=now,advance=1000)[0]['html']
        for value in ('00:50:00','3 д 02:03:04','5 часов · до сброса','Неделя · до сброса'):
            self.assertIn(value,first)
        for value in ('00:49:59','3 д 02:03:03'):
            self.assertIn(value,second)
        self.assertEqual(first.count('role="timer"'),2)

    def test_unknown_reset_is_not_fabricated_and_expired_clock_is_zero(self):
        now=1800000000000
        data={'claude_limits':{'prod':{'window':'week','pct':100,'resume_at':now/1000+1000,
            'windows':[{'window':'5h','resume_at':0},{'window':'week','resume_at':now/1000-10}]}}}
        html=run(data,PANES,now=now)[0]['html']
        self.assertIn('Время уточняется',html)
        self.assertIn('00:00:00',html)
        self.assertNotIn('-00:',html)

    def test_codex_uses_each_window_reset_and_never_reuses_an_aggregate_for_both(self):
        now=1800000000000
        cx={'active':True,'paused':False,'windows':[10080,300],
            'resets':{'300':now/1000+61,'10080':now/1000+86400},'resume_at':now/1000+86400}
        html=run({},PANES_CX,cx=cx,now=now)[0]['html']
        self.assertIn('00:01:01',html);self.assertIn('1 д 00:00:00',html)
        self.assertLess(html.index('5 часов'),html.index('Неделя'))
        cx['resets']={}
        html=run({},PANES_CX,cx=cx,now=now)[0]['html']
        self.assertEqual(html.count('Время уточняется'),2)


if __name__ == "__main__":
    unittest.main()
