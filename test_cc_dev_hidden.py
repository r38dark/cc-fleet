# Claude DEV прячется в панели, когда в снимке нет ни одного аккаунта основного сервера.
# python3 -m unittest test_cc_dev_hidden -v
import os
import re
import shutil
import subprocess
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="ccdevhid_")
os.environ["CC_LIMITS_BASE"] = os.path.join(TMP, "base")
os.environ["CC_LIMITS_PROFILES"] = os.path.join(TMP, "profiles")
os.makedirs(os.environ["CC_LIMITS_BASE"])

import cc_limits as L  # noqa: E402

JS = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", L.PAGE, re.S))


def grab(name):
    i = JS.index("function %s(" % name)
    end = JS.index("\n", i)
    first = JS[i:end]
    return first if first.count("{") == first.count("}") else JS[i:JS.index("\n}", i) + 2]


class Page(unittest.TestCase):
    def test_hooks_present(self):
        for token in ("function devAvail(", "function devSync(", "'cc_has_dev'", ".no-dev"):
            self.assertIn(token, L.PAGE, token)
        self.assertIn('html.no-dev:root #wkAgents .wk-seg[data-ag="claude"]', L.PAGE)
        self.assertIn("html:root:root .ctab[hidden]{display:none!important}", L.PAGE)

    def test_accounts_strip_gives_the_width_to_prod(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "cc_overview.py"), encoding="utf-8").read()
        self.assertIn('html.no-dev:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc[data-engine="claude"]{display:none}', src)
        self.assertIn('html.no-dev:root:root:root #fleetActiveAccounts.fleet-acc-mode .fleet-acc[data-engine="prod"]{grid-column:1/-1}', src)

    @unittest.skipUnless(shutil.which("node"), "нужен node")
    def test_logic_in_node(self):
        funcs = "\n".join(grab(n) for n in ("devAvail", "baseCur", "consCur", "splitKeysAvail", "consTabs"))
        test = """
let lastSnap=null, CONS='claude', cxd=false, pvd=false;
const store={};
global.localStorage={getItem:k=>store[k]===undefined?null:store[k],setItem:(k,v)=>{store[k]=String(v)}};
const els={};
function $(s){return els[s]||(els[s]={hidden:null,classList:{toggle(){},contains(){return false}},setAttribute(){},title:'',draggable:false})}
global.document={documentElement:{classList:{contains:()=>false,toggle(){}}},querySelectorAll:()=>[]};
function prodAvail(){return pvd} function cxAvail(){return cxd} function splitEff(){return null} function splitActIdx(){return 0}
function splitBtnSync(){} function ctActsSync(){} function syncPanes(){}
const splitMq={matches:false}; function tr(){return ''}
%s
const bad=[]; const t=(n,c)=>{ if(!c) bad.push(n) };
t('no snapshot: DEV tab shown', devAvail()===true);
lastSnap={accounts:{}}; t('no accounts: DEV hidden', devAvail()===false); consTabs(); t('tab hidden', $('#ctClaude').hidden===true);
pvd=true; t('PROD becomes main', baseCur()==='prod');
pvd=false; cxd=true; t('Codex becomes main', baseCur()==='codex');
cxd=false; t('nothing: stays claude', baseCur()==='claude'); t('split keys never empty', splitKeysAvail().length>=1);
lastSnap={accounts:{a:{}}}; t('account back: DEV shown', devAvail()===true); consTabs(); t('tab visible', $('#ctClaude').hidden===false);
if(bad.length){console.log('FAIL '+bad.join('; ')); process.exit(1)} console.log('ok');
""" % funcs
        p = os.path.join(TMP, "t.js")
        with open(p, "w") as f:
            f.write(test)
        r = subprocess.run(["node", p], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
