from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
        cls.css = (ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
        cls.compact_app = "".join(cls.app.split())
        cls.compact_css = "".join(cls.css.split())
        cls.server = (ROOT / "frontend" / "server.mjs").read_text(encoding="utf-8")
        cls.startup = (ROOT / "start_demo.py").read_text(encoding="utf-8")

    def test_streamlit_frontend_is_removed(self):
        self.assertFalse((ROOT / "app.py").exists())
        self.assertFalse((ROOT / "ui_chrome.py").exists())
        self.assertFalse(list((ROOT / "views").glob("*.py")))
        self.assertNotIn("streamlit", (ROOT / "requirements.txt").read_text(encoding="utf-8").lower())

    def test_browser_never_receives_api_token(self):
        self.assertIn("process.env.DRIVEMATE_API_TOKEN", self.server)
        self.assertIn("authorization: `Bearer ${token}`", self.server)
        self.assertNotIn("DRIVEMATE_API_TOKEN", self.app)

    def test_core_interactions_are_present(self):
        for term in ("Enter", "SpeechRecognition", "speechSynthesis", "pending_tools", "api.confirm", "api.cancel", "api.audit", "state_diff"):
            self.assertIn(term, self.compact_app)

    def test_external_engine_uses_user_facing_label(self):
        self.assertIn(">外接模型</button>", self.compact_app)
        self.assertNotIn(">百炼应用</button>", self.compact_app)

    def test_chrome_prefers_locally_installed_microsoft_yahei(self):
        self.assertIn('@font-face{font-family:"DriveMateYaHei"', self.compact_css)
        self.assertIn('local("MicrosoftYaHeiUI")', self.compact_css)
        self.assertIn('local("MicrosoftYaHei")', self.compact_css)
        self.assertIn(
            'html,body,#root{font-family:"DriveMateYaHei","MicrosoftYaHeiUI","MicrosoftYaHei",sans-serif;}',
            self.compact_css,
        )

    def test_route_confirmation_uses_current_plan_context(self):
        self.assertIn('if(item.title)returnitem.title;', self.compact_app)
        self.assertIn('args.preference==="comfort"?"平稳优先":""', self.compact_app)
        self.assertNotIn('plan_route:"开始导航至建议的安全休息点"', self.compact_app)

    def test_route_receipt_uses_executed_route_arguments(self):
        self.assertIn('if(tool!=="plan_route")returnactionLabels[tool]||call.title;', self.compact_app)
        self.assertIn('`已生成前往${destination||"当前目的地"}的${preference}路线${deadline}`', self.compact_app)
        self.assertNotIn('plan_route:"已生成前往安全休息点的路线"', self.compact_app)

    def test_route_map_keeps_complete_route_visible_at_every_resolution(self):
        self.assertIn(
            'alt="从上海虹桥火车站到上海外滩的完整导航路线"',
            self.compact_app,
        )
        self.assertIn(".route-mapimg{", self.compact_css)
        self.assertIn("object-fit:contain", self.compact_css)
        self.assertIn("object-position:center", self.compact_css)
        self.assertIn("aspect-ratio:12/5", self.compact_css)
        self.assertIn("flex:00auto", self.compact_css)
        self.assertNotIn(".route-map::before{", self.compact_css)
        self.assertNotIn(
            ".route-map{position:relative;min-height:210px;flex:1",
            self.compact_css,
        )

    def test_confirmation_receipt_and_vehicle_readback_follow_run_evidence(self):
        self.assertIn('failed:["执行未完成，已安全阻断"', self.compact_app)
        self.assertIn('waiting_confirmation:["阶段执行完成，等待下一步确认"', self.compact_app)
        self.assertIn('["error","cancelled"].includes(tone)?"×"', self.compact_app)
        self.assertIn('outcome.status==="blocked"?"failed"', self.compact_app)
        self.assertIn('outcome.status==="advisory"?"advisory"', self.compact_app)
        self.assertIn('`阻断原因：${uniqueBlockedReasons.join("；")}`', self.compact_app)
        self.assertIn("step.status_raw||step.status", self.compact_app)
        self.assertIn("call.summary", self.compact_app)
        self.assertIn("/上游步骤未成功|等待依赖|waiting_dependency|blocked_dependency/.test(reason)", self.compact_app)
        self.assertIn(".receipt-card-errorheaderi{background:var(--danger)", self.compact_css)
        self.assertIn('"vehicle_motion.speed_kmh":"speed"', self.compact_app)
        self.assertIn('gear:vehicle.gear', self.compact_app)

    def test_confirmation_cannot_submit_duplicate_receipts(self):
        self.assertIn("constactionInFlight=useRef(false);", self.compact_app)
        self.assertIn("if(actionInFlight.current)return;", self.compact_app)
        self.assertIn("actionInFlight.current=true;", self.compact_app)
        self.assertIn("actionInFlight.current=false;", self.compact_app)
        self.assertIn("<buttononClick={confirm}disabled={busy}>确认执行</button>", self.compact_app)
        self.assertIn(
            '<buttonclassName="secondary"onClick={cancel}disabled={busy}>',
            self.compact_app,
        )

    def test_safety_score_has_no_fixed_risk_level_fallback(self):
        self.assertIn('constscore=run?.safety_score;', self.compact_app)
        self.assertIn('动态安全评分', self.app)
        self.assertNotIn('{L0:94,L1:82,L2:62,L3:38}', self.compact_app)

    def test_safety_ring_tracks_score_value_and_color(self):
        self.assertIn('constnormalizedScore=Math.max(0,Math.min(100,Number(score)||0));', self.compact_app)
        self.assertIn('"--score":normalizedScore', self.compact_app)
        self.assertIn('"--risk-tone":scoreTone', self.compact_app)
        self.assertIn('var(--risk-tone)0calc(var(--score)*1%)', self.compact_css)

    def test_memory_view_reuses_icon_navigation(self):
        self.assertIn('memory:<Memorymessages={messages}/>', self.compact_app)
        self.assertIn('<i>{viewIcons[key]}</i><span>{label}</span>', self.compact_app)
        self.assertEqual(self.app.count('className="tabs"'), 1)

    def test_empty_backend_lists_render_waiting_content(self):
        self.assertIn(
            "functionnonEmptyList(value,fallback){returnArray.isArray(value)&&value.length>0?value:fallback;}",
            self.compact_app,
        )
        for expression in (
            "nonEmptyList(fusion?.modalities",
            "nonEmptyList(run?.risk_reasons",
            "nonEmptyList(run?.policies_hit",
            "nonEmptyList(run?.evidence",
        ):
            self.assertIn(expression, self.compact_app)

    def test_chat_scrolls_to_latest_content(self):
        self.assertIn('ref={threadRef}', self.compact_app)
        self.assertIn('thread.scrollTo({top:thread.scrollHeight,behavior:"smooth"})', self.compact_app)
        self.assertIn('thread.closest(".chat")?.scrollIntoView({', self.compact_app)
        self.assertIn('block:"end"', self.compact_app)
        self.assertIn('[messages,busy,run?.pending_tools?.length]', self.compact_app)

    def test_chat_bubbles_stay_between_avatar_gutters(self):
        self.assertGreaterEqual(
            self.compact_css.count("max-width:calc(100%-60px)"), 2
        )
        self.assertIn(
            ".bubble.assistant{position:relative;margin-left:30px;margin-right:30px",
            self.compact_css,
        )
        self.assertIn(
            ".bubble.user{position:relative;margin-left:30px;margin-right:30px",
            self.compact_css,
        )
        self.assertIn(
            ".bubble.receipt{position:relative;max-width:calc(100%-60px);padding:0;margin-left:30px;margin-right:30px",
            self.compact_css,
        )
        self.assertNotIn(".bubble{max-width:90%", self.compact_css)
        self.assertNotIn(".bubble.receipt{position:relative;max-width:95%", self.compact_css)

    def test_target_desktop_is_single_screen(self):
        self.assertIn("height:100dvh", self.compact_css)
        self.assertIn("grid-template-columns:30fr45fr25fr", self.compact_css)
        self.assertIn("overflow:hidden", self.compact_css)

    def test_startup_uses_web_frontend_only(self):
        self.assertIn("npm", self.startup)
        self.assertIn("server.mjs", self.startup)
        self.assertNotIn("streamlit", self.startup.lower())


if __name__ == "__main__":
    unittest.main()
