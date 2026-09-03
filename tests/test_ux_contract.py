from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


class UxContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app_root = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.views = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "views").glob("*.py"))
        )
        cls.app = cls.app_root + "\n" + cls.views
        cls.chrome = (ROOT / "ui_chrome.py").read_text(encoding="utf-8")
        cls.ui_source = cls.app + "\n" + cls.chrome
        style_root = ROOT / "assets" / "figma-hmi" / "styles"
        cls.style_files = [
            "shared.css",
            "topbar.css",
            "cockpit.css",
            "command.css",
            "chat.css",
            "responsive.css",
        ]
        cls.styles = {
            filename: (style_root / filename).read_text(encoding="utf-8")
            for filename in cls.style_files
        }
        cls.css = "\n".join(cls.styles.values())
        cls.design = (ROOT / "docs" / "design.md").read_text(encoding="utf-8")
        cls.map_path = ROOT / "assets" / "figma-hmi" / "shanghai-route-map.svg"

    def test_theme_picker_exposes_day_and_night_modes(self) -> None:
        self.assertIn("st.segmented_control(", self.chrome)
        self.assertIn('"选择界面主题"', self.chrome)
        for theme in ("日间", "夜间"):
            self.assertIn(f'"{theme}": {{', self.app)
        for retired_theme in ("浅蓝", "浅粉", "浅绿", "浅紫"):
            self.assertNotIn(f'"{retired_theme}": {{', self.app)
        self.assertIn('"bg": "#f2f8fc"', self.app)
        self.assertIn("--bg: #f2f8fc;", self.styles["shared.css"])
        self.assertIn("theme_options", self.chrome)
        self.assertNotIn("engine_labels", self.chrome)

    def test_app_remains_the_composition_root(self) -> None:
        self.assertLessEqual(len(self.app_root.splitlines()), 1600)
        self.assertIn("from views.workspace import", self.app_root)
        self.assertIn("WORKSPACE = WorkspaceContext(", self.app_root)
        self.assertNotIn("def render_", self.app_root)
        for path in (ROOT / "views").glob("*.py"):
            self.assertNotIn("from app import", path.read_text(encoding="utf-8"))

    def test_shared_grid_and_header_contract(self) -> None:
        self.assertIn("[30, 45, 25], gap=\"small\"", self.app)
        self.assertIn("[1.0, 2.1, 0.24, 0.75], gap=\"small\"", self.chrome)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", self.css)
        self.assertIn("min-height: 54px;", self.css)
        self.assertIn("min-height: 36px;", self.styles["topbar.css"])
        self.assertIn("max-width: 360px;", self.styles["topbar.css"])
        self.assertIn("width: 84px;", self.styles["topbar.css"])
        self.assertIn("max-width: 84px;", self.styles["topbar.css"])
        self.assertIn("max-width: 84px;", self.styles["responsive.css"])
        self.assertIn("margin: 0 auto;", self.styles["topbar.css"])
        self.assertIn("grid-auto-rows: 72px;", self.styles["responsive.css"])
        self.assertIn("height: 72px;", self.styles["responsive.css"])
        self.assertIn("justify-content: center;", self.styles["responsive.css"])
        self.assertIn("@media (min-width: 1200px)", self.css)
        self.assertIn("@media (max-width: 1199px)", self.css)
        self.assertIn("30 / 45 / 25", self.design)
        for filename in self.style_files:
            self.assertIn(f'"{filename}"', self.app)
        self.assertNotIn("flex: 0 0 230px !important;", self.css)
        self.assertNotIn("flex: 0 0 198px !important;", self.css)

    def test_cockpit_removes_basis_panel_and_compacts_for_order(self) -> None:
        self.assertNotIn('st.expander("调整本次判断依据"', self.app)
        self.assertIn('order_layout_class = " has-order"', self.app)
        self.assertIn('<section class="cockpit-instruments{order_layout_class}">', self.app)
        self.assertIn('<section class="dm-card order-card">', self.app)
        self.assertIn(".cockpit-instruments", self.css)
        self.assertIn(".order-card", self.css)

    def test_cockpit_uses_static_realistic_road_scene(self) -> None:
        self.assertIn("cockpit-road-static-v1.png", self.app)
        self.assertIn('class="dm-card cockpit-static-scene"', self.app)
        self.assertNotIn("render_traffic_scene(", self.app)
        self.assertIn('url("__COCKPIT_SCENE__")', self.css)

    def test_navigation_map_contains_landmarks_without_moving_vehicle(self) -> None:
        tree = ET.parse(self.map_path)
        animations = tree.findall(".//{http://www.w3.org/2000/svg}animate")
        motion = tree.findall(".//{http://www.w3.org/2000/svg}animateMotion")
        primary_road = tree.find(".//*[@id='primary-road']")
        primary_route = tree.find(".//*[@id='primary-route']")
        road_network = tree.find(".//*[@id='road-network']")
        route_layer = tree.find(".//*[@id='route-layer']")
        people_square = tree.find(".//*[@id='people-square']")
        bund_destination = tree.find(".//*[@id='bund-destination']")
        self.assertTrue(
            any(node.get("attributeName") == "stroke-dashoffset" for node in animations)
        )
        self.assertFalse(motion)
        self.assertIsNotNone(primary_road)
        self.assertIsNotNone(primary_route)
        self.assertEqual(primary_road.get("d"), primary_route.get("d"))
        self.assertEqual(road_network.get("clip-path"), "url(#west-bank-clip)")
        self.assertEqual(route_layer.get("clip-path"), "url(#west-bank-clip)")
        self.assertIsNotNone(people_square)
        self.assertIsNotNone(bund_destination)
        namespace = "{http://www.w3.org/2000/svg}"

        def label_box(group):
            match = re.fullmatch(
                r"translate\(([-\d.]+) ([-\d.]+)\)",
                str(group.get("transform")),
            )
            self.assertIsNotNone(match)
            rect = group.find(f"{namespace}rect")
            self.assertIsNotNone(rect)
            offset_x, offset_y = map(float, match.groups())
            left = offset_x + float(rect.get("x"))
            top = offset_y + float(rect.get("y"))
            return (
                left,
                top,
                left + float(rect.get("width")),
                top + float(rect.get("height")),
            )

        people_box = label_box(people_square)
        bund_box = label_box(bund_destination)
        labels_overlap = not (
            bund_box[2] <= people_box[0]
            or bund_box[0] >= people_box[2]
            or bund_box[3] <= people_box[1]
            or bund_box[1] >= people_box[3]
        )
        self.assertFalse(labels_overlap)
        map_text = self.map_path.read_text(encoding="utf-8")
        for landmark in ("上海虹桥火车站", "中山公园", "静安寺", "人民广场", "上海外滩"):
            self.assertIn(landmark, map_text)
        self.assertIn('data-zone="west-bank"', map_text)
        self.assertIn('transform="translate(988 169)"', map_text)
        self.assertNotIn("1006 166", map_text)
        self.assertNotIn('st.form("route_planner"', self.app)
        self.assertNotIn("navigation-form-marker", self.css)

    def test_chat_uses_brand_avatar_compact_feedback_and_orchestration(self) -> None:
        self.assertIn("DRIVEMATE_AVATAR", self.app)
        self.assertIn("USER_AVATAR", self.app)
        self.assertIn('"user-avatar-v4-transparent.png"', self.app)
        self.assertIn('"drivemate-logo.png"', self.app)
        self.assertIn('"data:image/png;base64,"', self.app)
        self.assertNotIn('class="robot-smile"', self.app)
        self.assertIn("execution-feedback-panel", self.app)
        self.assertIn("execution-action-tag", self.app)
        self.assertNotIn("execution-feedback-anchor", self.app)
        self.assertIn('requested_center_view = "服务编排"', self.app)
        self.assertIn("orchestration-progress-track", self.app)
        self.assertIn('也可呼唤“小D小D”', self.app)
        self.assertIn("SpeechRecognition", self.app)
        self.assertIn("speechSynthesis", self.app)
        self.assertIn("quick_columns = st.columns(3, gap=\"small\")", self.app)
        self.assertIn('img[alt="user avatar"]', self.css)
        self.assertIn('img[alt="assistant avatar"]', self.css)
        self.assertIn('aria-label="语音输入"', self.app)
        self.assertNotIn("<span>语音输入", self.app)
        self.assertNotIn("def render_header(", self.app)
        self.assertIn("from ui_chrome import", self.app)
        self.assertIn('with st.container(key="chat_thread", border=False):', self.app)
        self.assertNotIn("st.container(height=330", self.app)
        self.assertIn(".st-key-chat_thread", self.css)
        self.assertIn('img[alt="assistant avatar"]', self.css)
        self.assertIn('key="chat_model_picker"', self.app)
        self.assertIn("st.segmented_control(", self.app)
        self.assertIn('key="engine"', self.app)
        self.assertIn("ENGINE_LABELS = dict(ALL_ENGINE_LABELS)", self.app)
        self.assertIn('BAILIAN_ENGINE: "外接模型"', self.app)
        self.assertIn(
            "BAILIAN_AVAILABLE = BAILIAN_ENGINE in AVAILABLE_ENGINES",
            self.app,
        )
        self.assertIn("on_change=context.handle_engine_change", self.app)
        self.assertIn('"engine": st.session_state.engine', self.app)
        self.assertIn('with st.container(key="agent_composer"', self.app)
        self.assertNotIn('with st.form("agent_composer"', self.app)
        self.assertIn(".st-key-chat_model_picker", self.styles["chat.css"])
        self.assertNotIn(
            ':has(> button:only-child)::after',
            self.styles["chat.css"],
        )
        self.assertNotIn('content: "百炼应用";', self.styles["chat.css"])
        self.assertIn(
            'button [data-testid="stMarkdownContainer"] '
            "{ width: 100%; height: 100%; display: grid; "
            "place-items: center; margin: 0; }",
            self.styles["chat.css"],
        )
        self.assertIn(".dm-chat-title", self.styles["chat.css"])
        self.assertNotIn("chat_model_picker", self.styles["topbar.css"])
        self.assertNotIn(".dm-chat-title", self.styles["topbar.css"])
        self.assertIn('"SAFETY STATUS ASSESSMENT"', self.app)
        self.assertIn('"安全状态评估"', self.app)
        self.assertIn('"安全守护": "安全评估"', self.app)
        self.assertIn("def render_audit_trace(", self.app)
        self.assertIn('"decision_events"', self.app)
        self.assertIn('"tool_calls"', self.app)
        self.assertIn('"confirmations"', self.app)
        self.assertIn('"tickets"', self.app)
        for section in (
            "完整审计链",
            "运行上下文与最终结果",
            "决策事件（",
            "工具调用（",
            "确认记录（",
            "工单记录（",
        ):
            self.assertIn(section, self.app)
        self.assertIn(".audit-timeline", self.styles["command.css"])
        self.assertIn(".audit-detail-head", self.styles["command.css"])
        orchestration = self.app[
            self.app.index("def render_orchestration_console(") :
            self.app.index("def render_safety_guard_console(")
        ]
        memory = self.app[
            self.app.index("def render_memory_console(") :
            self.app.index("def render_command_workspace(")
        ]
        self.assertIn("render_audit_trace(context, result)", orchestration)
        self.assertNotIn("render_audit_trace(context, result)", memory)

    def test_agent_request_does_not_block_the_streamlit_page(self) -> None:
        process = self.app_root[
            self.app_root.index("def process_pending_request(") :
            self.app_root.index("def update_run(")
        ]
        self.assertIn("_get_agent_executor().submit(", process)
        self.assertIn("if not future.done():", process)
        self.assertIn("result = future.result()", process)
        self.assertNotIn("with st.spinner", process)
        self.assertIn("@st.fragment(run_every=0.5)", self.app_root)
        self.assertIn("st.session_state.pending_future = None", process)

    def test_simulation_and_critical_safety_routes_are_live(self) -> None:
        self.assertNotIn("@st.fragment(run_every=1)", self.app)
        self.assertIn("window.setInterval", self.app)
        self.assertIn('id="dm-speed-value"', self.app)
        self.assertIn('id="dm-scene-speed-value"', self.app)
        self.assertIn('setText("dm-scene-speed-value", speedText)', self.app)
        self.assertIn('target_speed = 72.0 if st.session_state.mode == "Robotaxi 乘客" else 96.0', self.app)
        self.assertIn("st.session_state.trip_km", self.app)
        self.assertIn('st.toast("检测到严重安全事件，已切换至安全守护。"', self.app)
        self.assertIn('st.session_state.center_view = "安全守护"', self.app)

    def test_conditional_controls_keep_persistent_domain_state(self) -> None:
        for key in (
            "cabin_temp_control",
            "seat_angle_control",
            "window_percent_control",
            "ambient_light_control",
        ):
            self.assertIn(f'key="{key}"', self.app)
        self.assertIn("key=control_key", self.app)
        self.assertNotRegex(
            self.app,
            re.compile(r"st\.slider\([^)]*key=\"(?:seat_angle|window_percent)\"", re.S),
        )

    def test_stylesheet_is_rebuilt_with_bounded_streamlit_bridges(self) -> None:
        sections = [
            "/* 1. Design tokens */",
            "/* 2. Global framework */",
            "/* 3. Main panels */",
            "/* 4. Functional cards */",
            "/* 5. Information units */",
            "/* 6. Page and component styles */",
            "/* 7. Responsive layout */",
        ]
        self.assertEqual(sections, sorted(sections, key=self.css.index))
        self.assertLess(len(self.css.splitlines()), 3000)
        self.assertLessEqual(self.css.count("!important"), 20)
        self.assertLessEqual(self.css.count(":has("), 80)
        self.assertNotRegex(self.css, r"margin(?:-(?:top|right|bottom|left))?\s*:\s*-\d")
        self.assertNotIn("Final browser-feedback overrides", self.css)

    def test_glass_hierarchy_uses_one_blur_and_three_surfaces(self) -> None:
        self.assertIn("--glass-blur: 12px;", self.css)
        self.assertIn("--glass-panel: rgba(255, 255, 255, 0.22);", self.css)
        self.assertIn("--glass-card: rgba(255, 255, 255, 0.15);", self.css)
        self.assertIn("--glass-unit: rgba(255, 255, 255, 0.09);", self.css)
        self.assertNotIn("backdrop-filter: blur(16px)", self.css)
        self.assertNotIn("backdrop-filter: blur(8px)", self.css)


if __name__ == "__main__":
    unittest.main()
