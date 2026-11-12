"""Бейдж «пауза по лимитам до …» / «лимит … исчерпан до …» на верхней рамке строки «Активных аккаунтов» и единое правило лимита
(limxPick/limxState в cc_limits.py — то же, что рисует иконку в консоли): настоящий JS под node, разметка и стили страницы."""
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
OVERVIEW = (HERE / "cc_overview.py").read_text(encoding="utf-8")
REMOTE = (HERE / "cc_remote_ui.py").read_text(encoding="utf-8")


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


PURE = cut(r"/\*LIMX-PURE-START\*/.*?/\*LIMX-PURE-END\*/", "limxPick")
REGION = cut(r"^function ccpsHtml\(k\)\{.*?^function ccpPartStrip\(\)\{.*?^\}$", "ccpsHtml … ccpPartStrip")
def strings(first):
    """Строки limx* словаря (две строки подряд, как в странице) — тело объекта JS."""
    i = SRC.index(first)
    j = SRC.index("\n", SRC.index("\n", i) + 1)
    return SRC[i:j]


RU = strings("  limxPause:at=>'пауза")
EN = strings("  limxPause:at=>'paused")

# поддельные «сейчас» и словарь: время сброса по Иркутску (UTC+8), «сегодня» — 12.11.2026 12:00 по Иркутску
HARNESS = r'''
const NOW=Date.parse('2026-11-12T04:00:00Z');const RealDate=Date;
globalThis.Date=class extends RealDate{constructor(...a){super(...(a.length?a:[NOW]))}static now(){return NOW}static parse(s){return RealDate.parse(s)}};
const window={FLEET_TZ:'Asia/Irkutsk'};const setInterval=()=>0;let NARROW=false;const matchMedia=()=>({get matches(){return NARROW}});
let LANG='LANG_HERE';
const T={TR_HERE};
const tr=(k,...a)=>typeof T[k]==='function'?T[k](...a):T[k];
const ccpAt=ms=>'x',ccpLeft=ms=>'y',ccpEsc=s=>String(s);
let ccpData=DATA,cxlpData=CX,lastSnap=SNAP;
const document={getElementById:()=>null,querySelector:()=>null};
REGION_HERE
const out={};
for(const k of ['claude','prod','codex']){const s=limxState(k);out[k]=s&&{kind:s.kind,win:s.win,text:limxText(s),short:limxText(s,true),title:limxTitle(k,s)};}
console.log(JSON.stringify(out));
'''

def state(data=None, cx=None, snap=None, lang="ru"):
    js = (HARNESS.replace("REGION_HERE", REGION).replace("LANG_HERE", lang).replace("TR_HERE", RU if lang == "ru" else EN)
          .replace("DATA", json.dumps(data)).replace("CX", json.dumps(cx)).replace("SNAP", json.dumps(snap)))
    return node(js)


W_UP = "2026-11-12T09:59:00Z"     # чт 12.11 17:59 по Иркутску (сегодня)
H_UP = "2026-11-12T18:29:00Z"     # пт 13.11 02:29 по Иркутску (завтра)
TS = lambda s: __import__("datetime").datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


@unittest.skipUnless(shutil.which("node"), "нет node")
class Pick(unittest.TestCase):
    """limxPick: одно правило для бейджа и для иконки."""

    def pick(self, pause, wins, reported=False, now=1000_000):
        return node(PURE + "\nconsole.log(JSON.stringify(limxPick(%s,%s,%s,%d)))" % (json.dumps(pause), json.dumps(wins), json.dumps(reported), now))

    def test_rules(self):
        w = lambda win, pct, until: {"win": win, "pct": pct, "until": until}
        self.assertIsNone(self.pick(None, [w("5h", 99.9, 2e6), w("week", 99, 3e6)]))                       # 99,9 % — ещё не исчерпан
        self.assertEqual(self.pick(None, [w("5h", 100, 2e6), w("week", 40, 3e6)]), {"kind": "out", "win": "5h", "until": 2e6})
        self.assertEqual(self.pick(None, [w("5h", 100, 2e6), w("week", 100, 3e6)])["win"], "week")          # оба — то, что кончается позже
        self.assertEqual(self.pick(None, [w("5h", 100, 4e6), w("week", 100, 3e6)])["win"], "5h")
        self.assertEqual(self.pick(None, [w("5h", 100, 3e6), w("week", 100, 3e6)])["win"], "week")          # одинаково — неделя
        self.assertEqual(self.pick({"until": 5e6}, [w("week", 100, 3e6)]), {"kind": "pause", "win": "", "until": 5e6})   # пауза важнее
        self.assertIsNone(self.pick(None, [w("week", 100, 1000_000 - 121_000)]))                           # сброс прошёл больше 2 мин назад
        self.assertEqual(self.pick(None, [w("week", 100, 1000_000 - 119_000)])["kind"], "out")
        self.assertEqual(self.pick(None, [w("week", 100, 0)])["until"], 0)                                   # время сброса неизвестно
        self.assertEqual(self.pick(None, [], True), {"kind": "out", "win": "", "until": 0})                  # сервис сказал «лимит»
        self.assertIsNone(self.pick(None, [{"win": "week", "pct": None, "until": 0}]))


@unittest.skipUnless(shutil.which("node"), "нет node")
class Text(unittest.TestCase):
    def test_codex_single_account_week_used_up(self):
        cx = {"active": True, "paused": False, "single": True, "windows": [10080], "resets": {"10080": TS(W_UP)}, "resume_at": TS(W_UP)}
        r = state(cx=cx)
        self.assertEqual(r["codex"]["text"], "лимит недели исчерпан до Чт 12.11 17:59")
        self.assertEqual(r["codex"]["short"], "лимит недели исчерпан до 17:59")       # телефон: без дня недели, сегодня — только время
        self.assertTrue(r["codex"]["title"].startswith("Codex: лимит недели исчерпан до Чт 12.11 17:59. "))
        self.assertIsNone(r["claude"]); self.assertIsNone(r["prod"])

    def test_codex_both_windows_shows_the_later_one_from_per_window_resets(self):
        cx = {"active": True, "paused": False, "windows": [300, 10080], "resets": {"300": TS(H_UP), "10080": TS(W_UP)}, "resume_at": TS(H_UP)}
        self.assertEqual(state(cx=cx)["codex"]["text"], "лимит 5 ч исчерпан до 13.11 02:29")    # 5 ч кончается позже недели
        cx["resets"] = {}
        self.assertEqual(state(cx=cx)["codex"]["text"], "лимит недели исчерпан до Пт 13.11 02:29")   # старый сервер без resets: общий срок, неделя

    def test_codex_pause_text_like_before(self):
        cx = {"active": True, "paused": True, "windows": [300], "resume_at": TS("2026-11-12T06:50:00Z")}
        self.assertEqual(state(cx=cx)["codex"]["text"], "пауза по лимитам до 14:50")          # сегодня — только время

    def test_claude_dev_and_prod(self):
        snap = {"active": "acc1", "accounts": {"acc1": {"five_hour": {"pct": 100, "resets_at": H_UP}, "seven_day": {"pct": 30, "resets_at": W_UP}}},
                "remote": {"prod": {"five_hour": {"pct": 12, "resets_at": H_UP}, "seven_day": {"pct": 100, "resets_at": W_UP}}}}
        r = state(snap=snap)
        self.assertEqual(r["claude"]["text"], "лимит 5 ч исчерпан до 13.11 02:29")
        self.assertEqual(r["prod"]["text"], "лимит недели исчерпан до Чт 12.11 17:59")
        data = {"remote_pause": {"enabled": True, "applied": True, "blocked": True, "resume_at": TS(H_UP)},
                "pause": {"active": True, "resume_at": TS("2026-11-12T06:50:00Z")}}
        r = state(data=data, snap=snap)
        self.assertEqual((r["claude"]["kind"], r["claude"]["text"]), ("pause", "пауза по лимитам до 14:50"))
        self.assertEqual((r["prod"]["kind"], r["prod"]["text"]), ("pause", "пауза по лимитам до 13.11 02:29"))
        self.assertTrue(r["prod"]["title"].startswith("Claude PROD: пауза по лимитам до 13.11 02:29. "))

    def test_english(self):
        cx = {"active": True, "paused": False, "windows": [10080], "resets": {"10080": TS(W_UP)}, "resume_at": TS(W_UP)}
        self.assertEqual(state(cx=cx, lang="en")["codex"]["text"], "weekly limit used up until Thu 12.11 17:59")

    def test_both_languages_have_the_strings(self):
        for key in ("limxPause:", "limxOutWeek:", "limxOut5h:", "limxOut:", "limxTipPause:", "limxTipOut:"):
            self.assertEqual(SRC.count(key), 2, key)                     # по разу в ru и en
        for block in (RU, EN):
            self.assertEqual(set(re.findall(r"(limx\w+):", block)), {"limxPause", "limxOutWeek", "limxOut5h", "limxOut", "limxTipPause", "limxTipOut"})


class Layout(unittest.TestCase):
    """Бейдж ничего не сдвигает: он вне потока (absolute) на верхней рамке строки; старая надпись в строке PROD убрана."""

    def test_badge_is_absolute_on_the_top_border(self):
        i = OVERVIEW.index("#fleetActiveAccounts .fleet-acc-badge{")
        rule = OVERVIEW[i:OVERVIEW.index("}", i)]
        for need in ("position:absolute", "top:0", "transform:translateY(-50%)", "white-space:nowrap", "border-radius:999px", "--b:var(--warn)"):
            self.assertIn(need, rule, need)
        self.assertIn("html:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc{position:relative}", OVERVIEW)
        self.assertIn('#fleetActiveAccounts .fleet-acc-badge[data-kind="out"]{--b:var(--bad)}', OVERVIEW)
        painter = cut(r"^function limxBadges\(\)\{.*?^\}$", "limxBadges")
        for need in ("acc.appendChild(b)", "b.style.top", "b.style.maxWidth", "limxText(s,LIMX_NARROW.matches)"):
            self.assertIn(need, painter, need)
        self.assertIn("setInterval(limxBadges,1000);", SRC)

    def test_prod_row_no_longer_writes_the_pause_into_the_row(self):
        self.assertNotIn("pauseText", REMOTE)
        self.assertNotIn("'\\u23f8 пауза по лимитам'", REMOTE)
        self.assertIn("pz=!!pauseInfo();cwn.textContent=!pz&&m&&(!m.online||m.error)?st:''", REMOTE)   # во время паузы «лимиты не обновились» тоже не пишем

    def test_console_got_the_freed_row_height(self):
        # строка третьего агента (42 + зазор 6) отдана консоли: и одна часть, и разделённая консоль
        for need in ("height:clamp(388px,calc(100dvh - 382px),688px)", "height:clamp(368px,calc(100dvh - 422px),658px)", "height:clamp(408px,calc(41dvh + 48px),558px)"):
            self.assertIn(need, OVERVIEW, need)
        for need in ("calc(clamp(388px,calc(100dvh - 382px),688px) + 39px)", "calc(clamp(368px,calc(100dvh - 422px),658px) + 39px)", "calc(clamp(408px,calc(41dvh + 48px),558px) + 39px)"):
            self.assertIn(need, SRC, need)

    def test_no_dead_service_profile_branches_in_overview(self):
        for gone in ("'reserve','emergency'", "mono-reserve", "mono-agent", "mono-auto", "monoView==='reserve'", "mirrorStop", "mirror-service", "fleet-profile-service", "serviceHtml"):
            self.assertNotIn(gone, OVERVIEW, gone)
        self.assertIn("#cxMenu .cxemg{", OVERVIEW)   # аварийный режим Codex — рабочий, его оформление осталось


class Page(unittest.TestCase):
    """Страница целиком: меню профиля плиток живёт в обзоре, следов третьего агента нет."""

    @classmethod
    def setUpClass(cls):
        import sys
        if 'cc_limits' not in sys.modules:
            tmp = tempfile.mkdtemp(prefix='cclx_')
            os.environ.setdefault('CC_LIMITS_BASE', os.path.join(tmp, 'base'))
            os.environ.setdefault('CC_LIMITS_PROFILES', os.path.join(tmp, 'profiles'))
            os.makedirs(os.environ['CC_LIMITS_BASE'], exist_ok=True)
        import cc_limits
        cls.page = cc_limits.PAGE

    def test_no_third_agent_in_the_page(self):
        self.assertEqual(re.findall(r"notion|nagent|\bnai[A-Z_]|nai_|nai-", self.page, re.I), [])
        # лиловый цвет третьего агента (167,139,250) остался только у баннера паузы — он был до агента (бэкапы 03.10.26)
        hits = [m.start() for m in re.finditer(r"a78bfa|167,139,250", self.page)]
        self.assertTrue(all(".ccpause.lvl-pause{" in self.page[max(0, h - 160):h] for h in hits), hits)

    def test_tile_profile_menu_lives_in_the_overview(self):
        import cc_overview, cc_workers
        self.assertFalse(hasattr(cc_workers, "PICKER_JS") or hasattr(cc_workers, "PICKER_ANCHOR"))
        self.assertIn("const TPN={claude:'Claude DEV',codex:'Codex'}", cc_overview.JS)
        self.assertIn(".tp-pop{--tp-c:var(--fleet-claude)}", cc_overview.CSS)
        self.assertEqual(self.page.count("const TPN="), 1)
        self.assertLess(self.page.index("const TPN="), self.page.index("\n mirrorLoad();\n\n loadRotation();"))   # до первой загрузки профилей

    def test_codex_tab_visibility_has_one_owner(self):
        import cc_workers
        self.assertNotIn("showCodex", cc_workers.UI)
        self.assertNotIn("hidden=false", cc_workers.UI[cc_workers.UI.index("function pickWorking"):])
        self.assertIn("$('#ctProd').hidden=!pv;$('#ctCodex').hidden=!av;", self.page)


if __name__ == "__main__":
    unittest.main()
