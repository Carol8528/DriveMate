import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";

const LOCAL_ENGINE = "融合编排引擎（本地可审计）";
const EXTERNAL_LLM_ENGINE = "外接模型（语义理解）";

const ownerActions = [
  ["我有点困", "我连续驾驶有些困倦，请先评估安全并给我建议"],
  ["困但想继续开", "我很困，但我还能坚持，继续导航，帮我把空调调低一点让我清醒。"],
  ["带孩子长途出行", "带孩子去上海，下午五点前到。孩子容易晕车，我不想中途没电，路上最好还能吃个饭。"],
  ["赶飞机不迟到", "我六点半的航班，现在去机场。路上我要开个会，尽量走平稳一点的路线，别让我迟到。"],
  ["调节车内温度", "车内有点热，请帮我把温度调得舒适一些"],
  ["规划沿途补能", "请根据当前电量规划沿途补能"],
  ["带孩子出行", "带孩子出行，请帮我检查并设置舒适安全的座舱环境"],
  ["查看车辆状态", "请告诉我当前车辆和行驶状态"],
  ["开始路线导航", "请根据当前目的地规划路线"],
];
const taxiActions = [
  ["就在这里下车", "不用到目的地了，就这里停，我要下车。"],
  ["我找不到车", "我找不到接驾车辆，请帮我定位"],
  ["修改上车点", "我需要修改上车点"],
  ["修改目的地", "我需要修改本次行程目的地"],
  ["车内不舒服", "我在车内感觉不舒服，需要帮助"],
  ["联系人工客服", "请帮我联系人工客服"],
  ["查看行程状态", "请查询当前 Robotaxi 订单状态与车辆位置"],
];
const viewLabels = {
  navigation: "路线导航",
  control: "座舱控制",
  perception: "融合感知",
  orchestration: "服务编排",
  safety: "安全评估",
  memory: "指令记录",
};
const viewIcons = {
  navigation: "⌖",
  control: "◫",
  perception: "◎",
  orchestration: "⌘",
  safety: "◇",
  memory: "≡",
};
const modalityIcons = {
  video: "◉",
  audio: "≋",
  telemetry: "⌁",
  position: "⌖",
  environment: "◎",
};

function nonEmptyList(value, fallback) {
  return Array.isArray(value) && value.length > 0 ? value : fallback;
}
function executionStatusTone(status) {
  if (
    [
      "failed",
      "blocked",
      "blocked_dependency",
      "safety_blocked",
      "schema_invalid",
      "unauthorized",
    ].includes(status)
  ) {
    return "error";
  }
  if (
    [
      "pending_confirm",
      "pending_user_confirmation",
      "waiting",
      "waiting_dependency",
      "degraded",
    ].includes(status)
  ) {
    return "warning";
  }
  if (status === "cancelled") return "cancelled";
  if (["done", "success", "executed", "app_side"].includes(status)) return "success";
  return "neutral";
}
const riskLabels = {
  L0: "低风险",
  L1: "需要关注",
  L2: "高风险",
  L3: "紧急风险",
};
const initialVehicle = {
  speed: 80,
  soc: 80,
  range: 450,
  hours: 3.5,
  gear: "D",
  trip: 0,
  temperature: 24,
  fan: 2,
  seat: 105,
  window: 0,
  ambient: 60,
  match: 88,
  distress: 18,
  distance: 22,
  curb: 24,
  destination: "上海外滩",
  order: "无订单",
  weather: "晴",
  traffic: "畅通",
};

function snapshot(mode, vehicle) {
  return {
    identity: {
      mode: mode === "owner" ? "OWNER_DRIVE" : "ROBOTAXI_RIDE",
      user_id: "frontend_preview_user",
      auth_level: mode === "owner" ? "vin_bound" : "order_token",
    },
    vehicle_state: {
      speed_kmh: vehicle.speed,
      gear: vehicle.gear,
      soc_percent: vehicle.soc,
      range_km: vehicle.range,
      driving_hours: vehicle.hours,
      child_seat_detected: false,
    },
    order_state: {
      status: vehicle.order,
      passenger_location: "上海虹桥火车站 2F 出发层",
      vehicle_location: "上海虹桥火车站",
      destination: vehicle.destination,
      passenger_coordinates: { lat: 31.1969, lng: 121.3268 },
      vehicle_coordinates: { lat: 31.197, lng: 121.327 },
    },
    environment_state: {
      weather: vehicle.weather,
      traffic: vehicle.traffic,
      time_of_day: "日间",
      area_type: "高速",
      parking_policy: "允许临停",
    },
    perception_controls: {
      passenger_match: vehicle.match,
      distress_probability: vehicle.distress,
      distance_m: vehicle.distance,
      curb_risk: vehicle.curb,
    },
  };
}

function applyDiff(vehicle, diff = {}) {
  const next = { ...vehicle };
  const map = {
    "climate.temperature": "temperature",
    "climate.fan_level": "fan",
    "climate.fan": "fan",
    "seat.driver_backrest_angle": "seat",
    "seat.driver_angle": "seat",
    "seat.angle": "seat",
    "window.open_percent": "window",
    "ambient_light.brightness": "ambient",
    "navigation.destination": "destination",
    "vehicle_motion.speed_kmh": "speed",
    "vehicle_motion.gear": "gear",
  };
  Object.entries(map).forEach(([path, key]) => {
    if (diff[path]?.after !== undefined) next[key] = diff[path].after;
  });
  return next;
}

function executionReceipt(data) {
  const actionLabels = {
    get_vehicle_status: "已读取车辆状态",
    set_climate: "已完成座舱温度调节",
    set_seat: "已完成座椅调节",
    play_music: "已播放舒缓音乐",
    find_rest_area: "已找到附近安全休息点",
    create_crm_ticket: "已通知人工安全专员",
    contact_human_support: "已转接人工服务",
  };
  const describeCall = (call) => {
    const tool = call.name || call.tool;
    if (tool !== "plan_route") return actionLabels[tool] || call.title;
    const args = call.arguments || {};
    const rawDestination = args.destination;
    const destination =
      typeof rawDestination === "object"
        ? rawDestination?.address || rawDestination?.name
        : rawDestination;
    const preference = args.preference === "comfort" ? "平稳优先" : "";
    const deadline = args.arrive_by ? `（${args.arrive_by} 前到达）` : "";
    return `已生成前往${destination || "当前目的地"}的${preference}路线${deadline}`;
  };
  const stateLabels = {
    "climate.temperature": ["座舱温度", "℃"],
    "climate.fan_level": ["空调风量", "档"],
    "climate.fan": ["空调风量", "档"],
    "seat.driver_backrest_angle": ["座椅靠背角度", "°"],
    "seat.driver_angle": ["座椅角度", "°"],
    "seat.angle": ["座椅角度", "°"],
    "window.open_percent": ["车窗开度", "%"],
    "ambient_light.brightness": ["氛围灯亮度", "%"],
    "navigation.destination": ["导航目的地", ""],
  };
  const completed = [
    ...new Set(
      (data.calls || [])
        .filter((x) =>
          ["success", "done", "app_side"].includes(x.result || x.status),
        )
        .map((x) => describeCall(x))
        .filter(Boolean),
    ),
  ];
  const changes = Object.entries(data.state_diff || {})
    .map(([key, value]) => {
      const [label, unit] = stateLabels[key] || [];
      if (!label || value?.after === undefined) return null;
      return { label, before: value?.before, after: value.after, unit };
    })
    .filter(Boolean);
  const failedStatuses = new Set([
    "failed",
    "blocked",
    "safety_blocked",
    "schema_invalid",
    "unauthorized",
  ]);
  const concreteBlockedReasons = [
    ...(data.steps || [])
      .filter((step) =>
        failedStatuses.has(step.status_raw || step.status),
      )
      .map((step) => {
        const reason = String(step.note || "").trim();
        if (
          (step.status_raw || step.status) === "blocked_dependency" ||
          /上游步骤未成功|等待依赖|waiting_dependency|blocked_dependency/.test(reason)
        ) {
          return "";
        }
        return reason || step.title || step.tool;
      }),
    ...(data.calls || [])
      .filter((call) =>
        failedStatuses.has(call.result || call.status),
      )
      .map((call) => call.summary),
    data.error?.message,
  ].filter(Boolean);
  const policyBlockedReasons = (data.constraint_shield?.candidates || [])
    .flatMap((candidate) => candidate.hard_violations || [])
    .filter(Boolean);
  const comparableReason = (reason) =>
    String(reason).replace(/[，。；：:、\s]/g, "");
  const uniqueBlockedReasons = (
    concreteBlockedReasons.length ? concreteBlockedReasons : policyBlockedReasons
  ).reduce((reasons, reason) => {
    const normalized = comparableReason(reason);
    if (
      !normalized ||
      reasons.some((current) => {
        const existing = comparableReason(current);
        return existing === normalized ||
          existing.includes(normalized) ||
          normalized.includes(existing);
      })
    ) {
      return reasons;
    }
    return [...reasons, String(reason).trim()];
  }, []).slice(0, 3);
  const outcome = data.action_outcome || {};
  const rawStatus = data.run_status || outcome.status;
  const status = rawStatus === "cancelled"
    ? "cancelled"
    : data.pending_tools?.length || ["waiting", "waiting_confirmation"].includes(rawStatus)
      ? "waiting_confirmation"
      : rawStatus === "failed" || outcome.status === "blocked"
        ? "failed"
        : rawStatus === "degraded"
          ? "degraded"
          : outcome.status === "advisory"
            ? "advisory"
            : "completed";
  const receiptCopy = {
    completed: ["已按确认完成执行", "以下操作已经执行，最新状态已同步到驾驶舱。"],
    degraded: ["部分操作已完成", "部分操作降级执行，请查看服务编排中的实际回执。"],
    failed: ["执行未完成，已安全阻断", "系统未宣称执行成功，请查看被阻断步骤及原因。"],
    cancelled: ["已取消待确认操作", "未继续执行车辆或订单操作。"],
    waiting_confirmation: ["阶段执行完成，等待下一步确认", "已同步最新车辆状态，后续高风险动作需要再次确认。"],
    advisory: ["已完成安全判断", "本轮仅提供建议，没有执行车辆或订单操作。"],
  };
  const [title, defaultSummary] = receiptCopy[status] ||
    (data.pending_tools?.length
      ? receiptCopy.waiting_confirmation
      : [outcome.title || "已返回执行结果", outcome.detail || "请查看本轮服务编排回执。"]);
  const summary = status === "failed" && uniqueBlockedReasons.length
    ? `阻断原因：${uniqueBlockedReasons.join("；")}`
    : defaultSummary;
  const tone = status === "failed"
    ? "error"
    : status === "cancelled"
      ? "cancelled"
      : ["degraded", "waiting_confirmation"].includes(status)
        ? "warning"
        : status === "advisory"
          ? "info"
        : "success";
  return {
    status,
    tone,
    icon: tone === "success"
      ? "✓"
      : ["error", "cancelled"].includes(tone)
        ? "×"
        : tone === "info"
          ? "i"
          : "!",
    title,
    summary,
    actions: completed,
    changes,
    note: "你可以继续告诉我下一步需求。",
  };
}

function ExecutionReceipt({ receipt }) {
  return (
    <div className={`receipt-card receipt-card-${receipt.tone}`}>
      <header>
        <i aria-label={receipt.tone === "error" ? "执行失败" : "执行状态"}>
          {receipt.icon}
        </i>
        <strong>{receipt.title}</strong>
      </header>
      <p>{receipt.summary}</p>
      {receipt.changes.length > 0 && (
        <div className="receipt-changes">
          {receipt.changes.map((change) => (
            <span key={change.label}>
              <small>{change.label}</small>
              <strong>
                {change.before !== undefined && (
                  <>
                    {change.before}
                    {change.unit} <b>→</b>{" "}
                  </>
                )}
                {change.after}
                {change.unit}
              </strong>
            </span>
          ))}
        </div>
      )}
      {receipt.actions.length > 0 && (
        <div className="receipt-actions">
          {receipt.actions.map((action) => (
            <span key={action}>✓ {action}</span>
          ))}
        </div>
      )}
      <footer>{receipt.note}</footer>
    </div>
  );
}

function confirmationText(pending = []) {
  const labels = {
    modify_destination: "修改本次行程目的地",
    set_climate: "调整座舱温度",
    set_seat: "调整座椅位置",
    open_window: "调整车窗开度",
    create_crm_ticket: "联系人工安全专员",
    contact_human_support: "转接人工服务",
  };
  const describe = (item) => {
    if (item.title) return item.title;
    const tool = item.name || item.tool;
    if (tool === "plan_route") {
      const args = item.arguments || {};
      const destination = args.destination || "当前目的地";
      const preference = args.preference === "comfort" ? "平稳优先" : "";
      return `开始导航至${destination}${preference ? `（${preference}）` : ""}`;
    }
    return labels[tool] || "执行建议操作";
  };
  const actions = pending.map(
    (item) => describe(item),
  );
  return actions.join("、");
}

function Header({ mode, setMode, theme, setTheme, health, meta }) {
  return (
    <header className="topbar">
      <div className="brand">
        <img src="/assets/figma-hmi/drivemate-logo-css.webp" />
        <div>
          <strong>DriveMate</strong>
          <span>智能出行服务管家</span>
        </div>
      </div>
      <div className="switch" aria-label="使用模式">
        <button
          className={mode === "owner" ? "active" : ""}
          onClick={() => setMode("owner")}
        >
          车主自驾
        </button>
        <button
          className={mode === "taxi" ? "active" : ""}
          onClick={() => setMode("taxi")}
        >
          Robotaxi
        </button>
      </div>
      <div className="topbar-right">
        <button
          className="theme"
          onClick={() => setTheme(theme === "light" ? "dark" : "light")}
        >
          {theme === "light" ? "☀ 日间" : "☾ 夜间"}
        </button>
        <div className="connection">
          <i className={health ? "ok" : ""} />
          <div>
            <strong>{health ? "Agent 在线" : "后端离线"}</strong>
            <span>API v1 · {meta.tool_count || 0} 工具</span>
          </div>
        </div>
      </div>
    </header>
  );
}

function PanelHead({ eyebrow, title, status }) {
  return (
    <div className="panel-head">
      <div>
        <span>{eyebrow}</span>
        <h2>{title}</h2>
      </div>
      {status && <small>{status}</small>}
    </div>
  );
}
function Metric({ label, value, unit }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>
        {value}
        <small>{unit}</small>
      </strong>
    </div>
  );
}

function EditableMetric({ label, value, unit, min, max, step, onChange }) {
  return (
    <div className="metric editable">
      <span>{label}</span>
      <strong>
        <input
          className="metric-input"
          type="number"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => {
            const next = Number(e.target.value);
            if (!Number.isNaN(next)) {
              onChange(Math.min(max, Math.max(min, next)));
            }
          }}
        />
        <small>{unit}</small>
      </strong>
      <input
        className="metric-slider"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}
function Cockpit({ mode, vehicle, setVehicle }) {
  const adjustables = [
    ["剩余电量", "soc", 0, 100, 1, "%"],
    ["预计续航", "range", 0, 800, 1, " km"],
    ["连续驾驶", "hours", 0, 12, 0.5, " h"],
    ["本程里程", "trip", 0, 999, 0.1, " km"],
  ];
  return (
    <section className="panel cockpit">
      <PanelHead
        eyebrow="LIVE COCKPIT"
        title="实时驾驶舱"
        status={`${vehicle.weather} · ${vehicle.traffic}`}
      />
      <div className="road">
        <span>ADAS ACTIVE</span>
        <div
          className="speed-gauge"
          style={{ "--gauge": `${Math.min(vehicle.speed / 1.6, 100)}%` }}
        >
          <div>
            <strong>{vehicle.speed}</strong>
            <small>km/h</small>
            <p>{mode === "taxi" ? "接驾行驶" : "巡航稳定"}</p>
          </div>
        </div>
        <div className="drive-indicators">
          <span>
            <i />
            车道保持
          </span>
          <span>
            <i />
            自适应巡航
          </span>
          <span>
            <i />
            前向感知
          </span>
        </div>
      </div>
      <div className="metrics">
        {adjustables.map(([label, key, min, max, step, unit]) => (
          <EditableMetric
            key={key}
            label={label}
            unit={unit}
            min={min}
            max={max}
            step={step}
            value={vehicle[key]}
            onChange={(next) => setVehicle((v) => ({ ...v, [key]: next }))}
          />
        ))}
      </div>
      <div className="cabin-state">
        <div>
          <span>座舱温度</span>
          <strong>{vehicle.temperature}℃</strong>
        </div>
        <div>
          <span>座椅角度</span>
          <strong>{vehicle.seat}°</strong>
        </div>
        <div>
          <span>车窗开度</span>
          <strong>{vehicle.window}%</strong>
        </div>
      </div>
      {mode === "taxi" && (
        <div className="order">
          <span>ROBOTAXI ORDER</span>
          <strong>{vehicle.order}</strong>
          <p>上车点 · 上海虹桥火车站 2F 出发层</p>
          <p>目的地 · {vehicle.destination}</p>
        </div>
      )}
    </section>
  );
}

function Navigation({ vehicle, setVehicle }) {
  return (
    <div className="view">
      <ViewHead title="实时路线导航" text="结合车辆状态与道路环境持续更新" />
      <figure className="route-map">
        <img
          src="/assets/figma-hmi/shanghai-route-map.svg"
          alt="从上海虹桥火车站到上海外滩的完整导航路线"
        />
      </figure>
      <div className="route-info">
        <label>
          当前位置<strong>上海虹桥火车站</strong>
        </label>
        <label>
          目的地
          <input
            value={vehicle.destination}
            onChange={(e) =>
              setVehicle((v) => ({ ...v, destination: e.target.value }))
            }
          />
        </label>
      </div>
      <div className="metrics three">
        <Metric label="预计时间" value="36" unit=" min" />
        <Metric label="剩余里程" value="24.8" unit=" km" />
        <Metric label="路况" value={vehicle.traffic} />
      </div>
      <div className="notice">
        下一步 · 沿迎宾一路向东行驶，前方进入城市快速路
      </div>
    </div>
  );
}
function Control({ vehicle, setVehicle }) {
  const controls = [
    ["座舱温度", "temperature", 16, 30, "℃"],
    ["座椅角度", "seat", 90, 125, "°"],
    ["车窗开度", "window", 0, 100, "%"],
    ["氛围灯", "ambient", 0, 100, "%"],
  ];
  return (
    <div className="view">
      <ViewHead
        title="座舱控制"
        text="所有调整先在本地预览，再由 Agent 安全执行"
      />
      <div className="control-grid">
        {controls.map(([label, key, min, max, unit]) => (
          <label className="control" key={key}>
            <span>
              {label}
              <strong>
                {vehicle[key]}
                {unit}
              </strong>
            </span>
            <input
              type="range"
              min={min}
              max={max}
              value={vehicle[key]}
              onChange={(e) =>
                setVehicle((v) => ({ ...v, [key]: Number(e.target.value) }))
              }
            />
          </label>
        ))}
      </div>
      <div className="notice">
        本页控制仅更新演示状态；涉及车辆动作时仍经过安全策略与确认流程。
      </div>
    </div>
  );
}
function Perception({ run, vehicle, setVehicle }) {
  const adjustables = [
    ["视觉匹配", "match", 0, 100, 1, "%"],
    ["求助声学线索", "distress", 0, 100, 1, "%"],
    ["人车距离", "distance", 0, 500, 1, " m"],
    ["路缘风险", "curb", 0, 100, 1, "%"],
  ];
  const fusion = run?.perception_fusion;
  const items = nonEmptyList(fusion?.modalities, [
    {
      label: "驾驶员监测",
      source: "DMS-01",
      signal: "疲劳状态稳定",
      value: "稳定",
      confidence: 96,
      contribution: 26,
    },
    {
      label: "座舱语音",
      source: "MIC-ARRAY",
      signal: "等待用户输入",
      value: "待命",
      confidence: 89,
      contribution: 22,
    },
    {
      label: "车辆总线",
      source: "CAN-GW",
      signal: "车辆数据在线",
      value: "在线",
      confidence: 99,
      contribution: 30,
    },
    {
      label: "环境感知",
      source: "ENV-GNSS",
      signal: "晴 · 日间 · 道路畅通",
      value: "可见度 92%",
      confidence: 94,
      contribution: 22,
    },
  ]);
  return (
    <div className="view">
      <ViewHead
        title="多模态融合感知"
        text="视觉、语音与车辆信号联合形成可解释判断"
      />
      <div className="sensor-grid">
        {items.slice(0, 4).map((x, i) => (
          <div className="sensor" key={i}>
            <header>
              <span className="sensor-label">
                <i>{modalityIcons[x.modality] || ["◉", "≋", "⌁", "◎"][i]}</i>
                {x.label || x.modality || "感知输入"}
              </span>
              <small>{x.source || "演示输入"}</small>
            </header>
            <strong>{x.signal || x.value || "在线"}</strong>
            <div>
              <i
                style={{ width: `${x.contribution || x.confidence || 80}%` }}
              />
            </div>
            <footer>
              <span>{x.value || "在线"}</span>
              <small>
                输入置信度 {x.confidence || 80}% · 融合贡献{" "}
                {x.contribution || 0}%
              </small>
            </footer>
          </div>
        ))}
      </div>
      <div className="control-grid perception-controls">
        {adjustables.map(([label, key, min, max, step, unit]) => (
          <label className="control" key={key}>
            <span>
              {label}
              <strong>
                {vehicle[key]}
                {unit}
              </strong>
            </span>
            <input
              type="range"
              min={min}
              max={max}
              step={step}
              value={vehicle[key]}
              onChange={(e) =>
                setVehicle((v) => ({ ...v, [key]: Number(e.target.value) }))
              }
            />
          </label>
        ))}
      </div>
      <div className="notice">
        拖动滑块可手动调整四项感知输入，下一次对话将按调整后的数值重新融合。
      </div>
      <div className="fusion-pipeline" aria-label="融合处理流程">
        <span>四路输入</span>
        <i />
        <span>时空同步</span>
        <i />
        <span>交叉验证</span>
        <i />
        <span>融合判断</span>
      </div>
      <div className="fusion-summary">
        <Metric
          label="在线通道"
          value={fusion?.online_count ?? 4}
          unit=" / 4"
        />
        <Metric
          label="融合置信度"
          value={fusion?.fusion_confidence ?? 92}
          unit="%"
        />
        <Metric label="风险分值" value={fusion?.risk_score ?? 8} unit="" />
        <Metric label="最大时延" value={fusion?.latency_ms ?? 61} unit=" ms" />
      </div>
      <div className="decision">
        <span>融合结论</span>
        <strong>
          {fusion?.primary_finding || "当前环境稳定，等待新的用户意图"}
        </strong>
        <p>
          {run?.action_outcome?.detail ||
            "所有数据为可复现演示输入，不代表量产实车数据。"}
        </p>
      </div>
    </div>
  );
}
function Orchestration({ run, audit, loadAudit }) {
  const phaseLabels = {
    perceive: "感知",
    understand: "理解",
    adjudicate: "裁决",
    plan: "规划",
    execute: "执行",
    readback: "回读",
    output: "输出",
  };
  const fallbackPhases = Object.keys(phaseLabels).map((name) => ({
    name,
    status: "pending",
  }));
  const phases = run?.phases?.length ? run.phases : fallbackPhases;
  const steps = run?.steps || [];
  const plan = nonEmptyList(
    run?.execution_plan,
    steps.map((step) => step.title || step.tool).filter(Boolean),
  );
  const calls = run?.calls || [];
  const completed = phases.filter((phase) => phase.status === "done").length;
  const stoppedPhase = phases.find((phase) =>
    ["failed", "cancelled"].includes(phase.status),
  );
  const activePhase = phases.find((phase) =>
    ["active", "waiting", "pending_confirm"].includes(phase.status),
  );
  const isWaiting = Boolean(run?.pending_tools?.length);
  const currentPhase = activePhase
    ? phaseLabels[activePhase.name] || activePhase.name
    : stoppedPhase
      ? `${phaseLabels[stoppedPhase.name] || stoppedPhase.name}未完成`
      : completed === phases.length && run
      ? "流程已完成"
      : "等待任务";
  const statusLabels = {
    completed: "执行完成",
    waiting_confirmation: "等待确认",
    failed: "执行失败",
    degraded: "降级完成",
    blocked: "已阻断",
    cancelled: "已取消",
  };
  const runStatusKey = isWaiting
    ? "waiting_confirmation"
    : run?.run_status || run?.status || "running";
  const runStatus = statusLabels[runStatusKey] || "运行中";
  const runStatusTone = ["failed", "blocked"].includes(runStatusKey)
    ? "error"
    : ["waiting_confirmation", "degraded"].includes(runStatusKey)
      ? "warning"
      : runStatusKey === "cancelled"
        ? "cancelled"
        : "success";
  const outcome = run?.action_outcome;
  return (
    <div className="view orchestration-view">
      <ViewHead
        title="服务编排"
        text="阶段、方案、工具回执与状态回读均来自本轮 Run"
      />
      {run ? (
        <>
          <section className="orchestration-progress">
            <div>
              <span>当前阶段</span>
              <strong>{currentPhase}</strong>
              <small>
                {completed} / {phases.length} 个阶段已有完成证据
              </small>
            </div>
            <div className="orchestration-run-meta">
              <span className={`status-${runStatusTone}`}>{runStatus}</span>
              <small>{run.run_id || "当前任务"}</small>
            </div>
            <div className="orchestration-progress-track">
              <i style={{ width: `${(completed / phases.length) * 100}%` }} />
            </div>
          </section>
          <div className="phases orchestration-phases">
            {phases.map((phase, i) => (
              <span className={phase.status || "pending"} key={phase.name || i}>
                <i>{String(i + 1).padStart(2, "0")}</i>
                {phaseLabels[phase.name] || phase.name}
              </span>
            ))}
          </div>
          <div className="result-card orchestration-summary">
            <span>本轮决策</span>
            <strong>{run.plan_summary || run.intent || "任务已受理"}</strong>
            <p>{run.reply || "已生成可审计的服务执行方案。"}</p>
          </div>
          <div className="orchestration-evidence">
            <section>
              <header>
                <span>编排方案</span>
                <small>{plan.length || steps.length} 步</small>
              </header>
              <ol>
                {(plan.length ? plan : ["后端未返回执行计划"]).map((item, i) => (
                  <li key={`${item}-${i}`}>
                    <i>{String(i + 1).padStart(2, "0")}</i>
                    <span>{item}</span>
                    {steps[i]?.status && (
                      <em className={`status-${executionStatusTone(steps[i].status_raw || steps[i].status)}`}>
                        {steps[i].status}
                      </em>
                    )}
                  </li>
                ))}
              </ol>
            </section>
            <section>
              <header>
                <span>工具回执</span>
                <small>{calls.length} 条</small>
              </header>
              <ol>
                {(calls.length ? calls : [{ tool: "暂无工具调用" }]).map(
                  (call, i) => (
                    <li key={call.call_id || `${call.tool}-${i}`}>
                      <i>{String(i + 1).padStart(2, "0")}</i>
                      <span>
                        <strong>{call.tool || "工具调用"}</strong>
                        <small>
                          {call.receipt_id || call.summary || call.result || "已记录"}
                        </small>
                      </span>
                      {(call.status || call.result) && (
                        <em className={`status-${executionStatusTone(call.status || call.result)}`}>
                          {call.status || call.result}
                        </em>
                      )}
                    </li>
                  ),
                )}
              </ol>
            </section>
          </div>
          <section className="orchestration-readback">
            <div>
              <span>状态回读</span>
              <strong>
                {outcome
                  ? `${outcome.summary || outcome.status || "已有返回"} · ${outcome.detail || "车辆状态已形成闭环证据"}`
                  : "等待执行回读 · 工具执行后的车辆状态将在此形成闭环证据"}
              </strong>
            </div>
            <button className="secondary" onClick={loadAudit}>
              {audit ? "刷新审计链" : "读取完整审计链"}
            </button>
          </section>
          {audit && <Audit audit={audit} />}
        </>
      ) : (
        <div className="orchestration-empty">
          <div className="empty">发送需求后，此处展示可审计的执行计划与回执。</div>
          <div className="phases orchestration-phases">
            {fallbackPhases.map((phase, i) => (
              <span className="pending" key={phase.name}>
                <i>{String(i + 1).padStart(2, "0")}</i>
                {phaseLabels[phase.name]}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
function Safety({ run, vehicle }) {
  const risk = run?.risk_level || "L0";
  const score = run?.safety_score;
  const normalizedScore = Math.max(0, Math.min(100, Number(score) || 0));
  const scoreTone = `hsl(${Math.round(normalizedScore * 1.2)} 76% 40%)`;
  const phases =
    run?.phases ||
    [
      "perceive",
      "understand",
      "adjudicate",
      "plan",
      "execute",
      "readback",
      "output",
    ].map((name) => ({ name, status: "pending" }));
  const phaseLabels = {
    perceive: "感知",
    understand: "理解",
    adjudicate: "裁决",
    plan: "规划",
    execute: "执行",
    readback: "回读",
    output: "输出",
  };
  const completed = phases.filter((x) => x.status === "done").length;
  const runState = !run
    ? "等待需求"
    : run.pending_tools?.length
      ? "等待确认"
      : run.run_status === "completed"
        ? "执行完成"
        : "已有返回";
  const evidenceGroups = [
    [
      "风险依据",
      nonEmptyList(run?.risk_reasons, ["当前未检测到高风险触发信号"]),
    ],
    [
      "策略约束",
      nonEmptyList(run?.policies_hit, ["车辆动作须经过安全策略校验"]),
    ],
    [
      "验证证据",
      nonEmptyList(run?.evidence, ["等待任务执行后的状态回读"]),
    ],
  ];
  return (
    <div className="view">
      <ViewHead
        title="主动安全守护"
        text="融合环境、驾驶员和任务风险给出安全结论"
      />
      <div
        className={`safety-console ${risk}`}
        style={{ "--score": normalizedScore, "--risk-tone": scoreTone }}
      >
        <div className="safety-stage">
          <div className="safety-halo">
            <div>
              <span title="由融合风险、任务等级与执行状态动态计算">动态安全评分</span>
              <strong>{score ?? "--"}</strong>
              <em>
                {risk} · {riskLabels[risk]}
              </em>
            </div>
          </div>
          <div className="safety-support">
            <section>
              <span>场景上下文</span>
              <strong>{vehicle.destination || "当前道路"}</strong>
              <p>
                {vehicle.weather} · {vehicle.traffic} · 日间
              </p>
              <div className="scene-signals">
                <i>高速道路</i>
                <i>{vehicle.weather}</i>
                <i>{vehicle.traffic}</i>
              </div>
            </section>
            <section>
              <span>评估进度</span>
              <strong>
                {completed}
                <small> / {phases.length}</small>
              </strong>
              <div className="safety-progress">
                <i style={{ width: `${(completed / phases.length) * 100}%` }} />
              </div>
              <p>{runState} · 仅统计已有返回证据</p>
            </section>
          </div>
        </div>
        <div className="safety-phases">
          {phases.map((phase) => (
            <span
              className={phase.status === "done" ? "done" : ""}
              key={phase.name}
            >
              {phaseLabels[phase.name] || phase.name}
            </span>
          ))}
        </div>
      </div>
      <div className="safety-evidence">
        {evidenceGroups.map(([title, rows]) => (
          <section key={title}>
            <span>{title}</span>
            <ul>
              {rows.slice(0, 3).map((row, i) => (
                <li key={i}>{row}</li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <div className="decision safety-verdict">
        <span>安全结论</span>
        <strong>{run?.safety_tip || "未发现需要立即处置的高风险事件"}</strong>
        <p>
          当前速度 {vehicle.speed} km/h · {runState}
        </p>
      </div>
    </div>
  );
}
function Memory({ messages }) {
  return (
    <div className="view">
      <ViewHead
        title="本次指令记录"
        text="仅展示当前浏览器会话，不推断长期偏好"
      />
      {messages.length ? (
        <ol className="memory-list">
          {messages
            .filter((x) => x.role === "user")
            .map((x, i) => (
              <li key={i}>
                <i>{String(i + 1).padStart(2, "0")}</i>
                <span>{x.content}</span>
              </li>
            ))}
        </ol>
      ) : (
        <Empty text="当前会话尚无用户指令。" />
      )}
    </div>
  );
}
function ViewHead({ title, text }) {
  return (
    <div className="view-head">
      <div>
        <span>MISSION VIEW</span>
        <h3>{title}</h3>
        <p>{text}</p>
      </div>
      <small>实时</small>
    </div>
  );
}
function Empty({ text }) {
  return <div className="empty">{text}</div>;
}
function Audit({ audit }) {
  const run = audit.run || {};
  const rows = [
    ...(audit.decision_events || []).map((x) => [x.stage, x.created_at]),
    ...(audit.tool_calls || []).map((x) => [x.tool, x.status]),
  ];
  return (
    <details className="audit">
      <summary>完整审计链 · {run.run_id || "当前任务"}</summary>
      {rows.map((x, i) => (
        <div key={i}>
          <strong>{x[0]}</strong>
          <span>
            {String(x[1] || "已记录")
              .replace("T", " ")
              .slice(0, 23)}
          </span>
        </div>
      ))}
      <button
        onClick={() => {
          const a = document.createElement("a");
          a.href = URL.createObjectURL(
            new Blob([JSON.stringify(audit, null, 2)], {
              type: "application/json",
            }),
          );
          a.download = `audit_${run.run_id || "run"}.json`;
          a.click();
        }}
      >
        下载审计链
      </button>
    </details>
  );
}

function Command({
  view,
  setView,
  run,
  vehicle,
  setVehicle,
  audit,
  loadAudit,
  messages,
}) {
  const content = {
    navigation: <Navigation vehicle={vehicle} setVehicle={setVehicle} />,
    control: <Control vehicle={vehicle} setVehicle={setVehicle} />,
    perception: <Perception run={run} vehicle={vehicle} setVehicle={setVehicle} />,
    orchestration: (
      <Orchestration run={run} audit={audit} loadAudit={loadAudit} />
    ),
    safety: <Safety run={run} vehicle={vehicle} />,
    memory: <Memory messages={messages} />,
  };
  return (
    <section className="panel command">
      <PanelHead
        eyebrow="MISSION CONTROL"
        title="智能中控"
        status={view === "memory" ? "当前会话" : `当前风险 ${run?.risk_level || "L0"}`}
      />
      <nav className="tabs">
        {Object.entries(viewLabels).map(([key, label]) => (
          <button
            className={view === key ? "active" : ""}
            onClick={() => setView(key)}
            key={key}
          >
            <i>{viewIcons[key]}</i>
            <span>{label}</span>
          </button>
        ))}
      </nav>
      {content[view]}
    </section>
  );
}

function Chat({
  mode,
  run,
  messages,
  busy,
  error,
  send,
  confirm,
  cancel,
  engine,
  setEngine,
  availableEngines = [LOCAL_ENGINE],
}) {
  const [input, setInput] = useState("");
  const threadRef = useRef(null);
  const externalAvailable = availableEngines.includes(EXTERNAL_LLM_ENGINE);
  const actions = mode === "owner" ? ownerActions : taxiActions;
  useEffect(() => {
    const thread = threadRef.current;
    if (!thread) return;
    const frame = requestAnimationFrame(() => {
      thread.scrollTo({ top: thread.scrollHeight, behavior: "smooth" });
      if (thread.scrollHeight <= thread.clientHeight) {
        thread.closest(".chat")?.scrollIntoView({
          behavior: "smooth",
          block: "end",
        });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [messages, busy, run?.pending_tools?.length]);
  const submit = (text = input) => {
    if (!text.trim() || busy) return;
    send(text.trim());
    setInput("");
  };
  const listen = () => {
    const Recognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition)
      return alert("当前浏览器不支持语音识别，请使用键盘输入。");
    const recognition = new Recognition();
    recognition.lang = "zh-CN";
    recognition.onresult = (e) => setInput(e.results[0][0].transcript);
    recognition.onerror = () => alert("未能识别语音，请重试或使用键盘输入。");
    recognition.start();
  };
  const speak = () => {
    if (!run?.reply || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(run.reply);
    utterance.lang = "zh-CN";
    window.speechSynthesis.speak(utterance);
  };
  return (
    <section className="panel chat">
      <PanelHead eyebrow="AI COPILOT" title="DriveMate Agent" />
      <div className="quick">
        {actions.map(([label, text]) => (
          <button onClick={() => submit(text)} key={label}>
            {label}
          </button>
        ))}
      </div>
      <div className="thread" ref={threadRef}>
        {messages.length === 0 && (
          <div className="assistant bubble">
            你好呀，我是小D，有任何需要都可以和我说~
          </div>
        )}
        {messages.map((m, i) => (
          <div
            className={`${m.role} bubble ${
              m.role === "receipt" ? `receipt-${m.content.tone}` : ""
            }`}
            key={i}
          >
            {m.role === "receipt" ? (
              <ExecutionReceipt receipt={m.content} />
            ) : (
              m.content
            )}
          </div>
        ))}
        {busy && (
          <div className="assistant bubble loading">正在调用安全编排能力</div>
        )}
        {run?.pending_tools?.length > 0 && (
          <div className="confirm">
            <div className="confirm-copy">
              <i>!</i>
              <div>
                <strong>需要你的确认</strong>
                <span>{confirmationText(run.pending_tools)}</span>
                <small>该操作可能改变当前行程，确认后立即执行。</small>
              </div>
            </div>
            <div className="confirm-actions">
              <button onClick={confirm} disabled={busy}>确认执行</button>
              <button className="secondary" onClick={cancel} disabled={busy}>
                取消
              </button>
            </div>
          </div>
        )}
        {error && <div className="error">{error}</div>}
      </div>
      <div className="composer">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="输入需求，Enter 发送"
        />
        <div className="voice-tools">
          <button onClick={listen}>🎙 语音输入</button>
          <button onClick={speak}>🔊 播报回复</button>
        </div>
        <div className="model-row">
          <div className="engine-switch" aria-label="Agent 引擎">
            <button
              className={
                engine === LOCAL_ENGINE ? "active" : ""
              }
              onClick={() => setEngine(LOCAL_ENGINE)}
              title={LOCAL_ENGINE}
            >
              融合编排
            </button>
            <button
              className={engine === EXTERNAL_LLM_ENGINE ? "active" : ""}
              onClick={() => externalAvailable && setEngine(EXTERNAL_LLM_ENGINE)}
              title={externalAvailable ? "外接模型仅参与语义理解" : "配置 API_KEY 后启用"}
              disabled={!externalAvailable}
            >
              外接模型
            </button>
          </div>
          <button onClick={() => submit()} disabled={busy}>
            发送
          </button>
        </div>
      </div>
    </section>
  );
}

export default function App() {
  const [mode, setModeState] = useState("owner"),
    [theme, setTheme] = useState("light"),
    [view, setView] = useState("navigation");
  const [vehicle, setVehicle] = useState(initialVehicle),
    [run, setRun] = useState(null),
    [messages, setMessages] = useState([]),
    [audit, setAudit] = useState(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [health, setHealth] = useState(false),
    [meta, setMeta] = useState({}),
    [engine, setEngine] = useState(LOCAL_ENGINE),
    [toast, setToast] = useState("");
  const session = useRef(null);
  const actionInFlight = useRef(false);
  const snap = useMemo(() => snapshot(mode, vehicle), [mode, vehicle]);
  useEffect(() => {
    Promise.all([api.health(), api.meta()])
      .then(([h, m]) => {
        setHealth(Boolean(h.ok));
        setMeta(m);
        if (!Array.isArray(m.engines) || !m.engines.includes(EXTERNAL_LLM_ENGINE)) {
          setEngine((current) => current === EXTERNAL_LLM_ENGINE ? LOCAL_ENGINE : current);
        }
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    const id = setInterval(
      () =>
        setVehicle((v) => ({
          ...v,
          trip: Math.round((v.trip + v.speed / 7200) * 10) / 10,
        })),
      2000,
    );
    return () => clearInterval(id);
  }, []);
  const setMode = (value) => {
    setModeState(value);
    setRun(null);
    setMessages([]);
    setAudit(null);
    session.current = null;
    setView("navigation");
    setVehicle({
      ...initialVehicle,
      speed: value === "taxi" ? 72 : 80,
      gear: "D",
      order: value === "taxi" ? "arriving（即将到达）" : "无订单",
    });
  };
  const accept = (data, responseRole = "assistant") => {
    setRun(data);
    setView("safety");
    session.current = data.session_id || session.current;
    setVehicle((v) => applyDiff(v, data.state_diff));
    setMessages((m) => [
      ...m,
      {
        role: responseRole,
        content:
          responseRole === "receipt"
            ? executionReceipt(data)
            : data.reply || "任务已完成。",
      },
    ]);
    setToast(
      data.pending_tools?.length
        ? "等待你的安全确认"
        : data.run_status === "completed"
          ? "任务处理完成"
          : data.run_status === "failed"
            ? "执行未完成，已安全阻断"
            : "任务状态已更新",
    );
  };
  const action = async (work, responseRole = "assistant") => {
    if (actionInFlight.current) return;
    actionInFlight.current = true;
    setBusy(true);
    setError("");
    try {
      accept(await work(), responseRole);
    } catch (e) {
      setError(e.message);
    } finally {
      actionInFlight.current = false;
      setBusy(false);
    }
  };
  const send = (text) => {
    if (actionInFlight.current) return;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setView("orchestration");
    action(() =>
      api.run({
        message: text,
        mode: mode === "owner" ? "车主自驾" : "Robotaxi 乘客",
        engine,
        snapshot: snap,
        ...(session.current ? { session_id: session.current } : {}),
      }),
    );
  };
  const loadAudit = () =>
    run &&
    api
      .audit(run.run_id)
      .then(setAudit)
      .catch((e) => setError(e.message));
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(""), 2600);
    return () => clearTimeout(id);
  }, [toast]);
  return (
    <main data-theme={theme}>
      <Header
        mode={mode}
        setMode={setMode}
        theme={theme}
        setTheme={setTheme}
        health={health}
        meta={meta}
      />
      <div className="workspace">
        <Cockpit mode={mode} vehicle={vehicle} setVehicle={setVehicle} />
        <Command
          view={view}
          setView={setView}
          run={run}
          vehicle={vehicle}
          setVehicle={setVehicle}
          audit={audit}
          loadAudit={loadAudit}
          messages={messages}
        />
        <Chat
          mode={mode}
          run={run}
          messages={messages}
          busy={busy}
          error={error}
          send={send}
          confirm={() => action(() => api.confirm(run.run_id, snap), "receipt")}
          cancel={() => action(() => api.cancel(run.run_id), "receipt")}
          engine={engine}
          setEngine={setEngine}
          availableEngines={Array.isArray(meta.engines) ? meta.engines : [LOCAL_ENGINE]}
        />
      </div>
      {toast && <div className="toast">{toast}</div>}
    </main>
  );
}
