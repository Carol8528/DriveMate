# -*- coding: utf-8 -*-
"""IntentGraph 2.1: 证据加权、否定作用域、多意图裁决、状态证据与低置信澄清。

该模块由 test-main/server/intent.mjs 的设计移植而来，并适配 V5 的真实 StateSnapshot。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple


SCENARIO_LABELS = {
    "medical": "乘客紧急求助",
    "fatigue": "疲劳驾驶",
    "parent_child": "儿童安全",
    "charging": "长途补能",
    "find_car": "人车会合",
    "modify_pickup": "危险/变更上车点",
    "reroute": "目的地/途经点变更",
    "cancel_order": "取消订单",
    "climate": "座舱温度调节",
    "commute": "抵达服务",
    "route_plan": "路线导航",
    "vehicle_status": "车辆状态",
    "human_support": "人工客服",
    "trip_status": "行程状态",
}

# (证据名, 正则, 权重)
DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "medical": {
        "mode": "robotaxi",
        "signals": [
            ("急性呼吸/胸部信号", r"胸(口)?(很|好)?(闷|痛)|喘不上(气)?|呼吸(困|不顺|急)难?", 8.0),
            ("失去意识风险", r"失去(意识|回应)|没反应|晕倒|昏迷", 9.0),
            ("显式求救", r"救命|急救|叫救护车|120|\bhelp\b", 8.0),
            ("身体不适", r"不舒服|难受|头晕|心慌|恶心|疼得厉害", 4.5),
        ],
        "anti": [("症状被明确否定", r"没(有)?(胸闷|胸痛|头晕|不适)|不(胸闷|胸痛|头晕)", -10.0)],
    },
    "fatigue": {
        "mode": "driver",
        "signals": [
            ("显著疲劳表现", r"眼皮|睁不开|打哈欠|打瞌睡|犯困|想睡|困得|脑袋发木", 7.0),
            ("驾驶稳定性下降", r"开(了)?\s*[三四五六七八九\d]+\s*(个)?小时|方向(有点)?飘|反应变慢", 5.0),
            ("一般疲劳表达", r"疲劳|困倦|清醒(一下)?|有点困|太困|困了|太累|休息区|眯一会", 4.0),
        ],
        "anti": [("疲劳被明确否定", r"一(点|丝)也不困|完全不困|并不困|不是困|没有疲劳|不累", -9.0)],
    },
    "parent_child": {
        "mode": "driver",
        "signals": [
            ("儿童约束异常", r"孩子|儿童|宝宝|小朋友|儿童座椅|后排.*(站|闹|哭)", 4.5),
            ("安全带异常", r"安全带.*(解|松|没|未|报警)|卡扣.*(解|开|松)|没扣(住|好)?", 7.0),
            ("驾驶员回头风险", r"回头(看|哄|处理)|边开边哄|伸手.*后排", 7.0),
            ("儿童锁请求", r"儿童锁|后排车门|车窗锁", 4.0),
        ],
        "anti": [("儿童状态被明确排除", r"孩子没事|宝宝没事|儿童没问题|安全带没问题", -8.0)],
    },
    "modify_pickup": {
        "mode": "robotaxi",
        "signals": [
            ("临时停车请求", r"这里停|这儿停|就停|停一下|靠边接|马上上车|接我", 5.0),
            ("高风险停车位置", r"路口|交叉口|消防通道|非机动车道|主路|禁停|不能停", 7.0),
            ("上车点变更", r"上车点|接客点|改(到|个).*上车", 4.0),
        ],
        "anti": [("明确拒绝危险停车", r"别在(路口|这里|这儿)停|不要在(路口|这里|这儿)停", -8.0)],
    },
    "find_car": {
        "mode": "robotaxi",
        "signals": [
            ("人车会合失败", r"找不到(车|你们|司机)?|没(有)?看到(车|你们)?|哪辆车|车到底在哪|你们在哪|到你们车(那里)?", 8.0),
            ("场站迷失", r"绕(了)?[两三\d]圈|定位不准|会合|迎宾灯|车牌尾号|几号柱", 5.0),
            ("焦虑等待", r"等了.*分钟|还没来|走到哪", 3.0),
        ],
        "anti": [],
    },
    "reroute": {
        "mode": "robotaxi",
        "signals": [
            ("目的地/途经点变化", r"改(一下)?目的地|修改.*目的地|变更.*目的地|换(个)?目的地|新增途经|加(一?个)?途经|绕(一下|过去)?|顺路", 6.0),
            ("同行人接送", r"接(个|一下)?朋友|接人|同行人上车", 5.0),
            ("赶航班约束", r"机场|航班|飞机|赶得上|来得及", 5.0),
            ("订单费用约束", r"加多少钱|费用会变|订单变更", 3.5),
        ],
        "anti": [("明确否定改点", r"不是要改目的地|不改目的地|不用绕|不要途经", -8.0)],
    },
    "charging": {
        "mode": "driver",
        "signals": [
            ("补能需求", r"充电|补能|充电桩|充电站|快充|电池预热", 7.0),
            ("续航约束", r"续航|电量|剩余里程|跑不到|没电|电(快)?没了", 6.0),
            ("排队与长途", r"排队充电|等位|长途|服务区.*充", 4.0),
            ("乘员舒适", r"带(爸妈|老人|家人)|老人休息", 3.0),
        ],
        "anti": [("补能需求被否定", r"不用充电|不需要充电|电量足够|续航没问题", -7.0)],
    },
    "cancel_order": {
        "mode": "robotaxi",
        "signals": [("取消订单请求", r"取消(订单|行程)?|不坐了|不打了|结束订单", 7.0)],
        "anti": [("明确否定取消", r"不取消|别取消|不要取消", -9.0)],
    },
    "climate": {
        "mode": "driver",
        "signals": [
            ("温度/空调调节", r"空调|温度|好热|太热|好冷|太冷|风量|制冷|制热", 6.0),
        ],
        "anti": [("明确拒绝空调调节", r"别动空调|不要调空调|不用调温度", -8.0)],
    },
    "commute": {
        "mode": "driver",
        "signals": [
            ("抵达服务", r"快到|到达|抵达|下车|离车|停车入口|找车位", 6.0),
            ("通勤目的地", r"公司|单位|上班|通勤|办公楼", 4.0),
            ("抵达例程", r"关空调|折后视镜|带伞|提醒.*物品|发.*到达", 4.0),
        ],
        "anti": [],
    },
    "route_plan": {
        "mode": "driver",
        "signals": [
            ("路线导航请求", r"规划.*路线|路线规划|导航(?:到|去|至)|开始导航|前往.*路线", 7.0),
        ],
        "anti": [("明确拒绝导航", r"不要导航|不用导航|取消导航", -8.0)],
    },
    "vehicle_status": {
        "mode": "driver",
        "signals": [
            ("车辆状态查询", r"车辆.*状态|行驶状态|查看车况|当前车速|剩余电量", 7.0),
        ],
        "anti": [],
    },
    "human_support": {
        "mode": "robotaxi",
        "signals": [
            ("人工客服请求", r"人工客服|联系人工|转人工|客服帮助|找客服", 8.0),
        ],
        "anti": [("明确拒绝转人工", r"不要转人工|不用人工|别联系人工", -9.0)],
    },
    "trip_status": {
        "mode": "robotaxi",
        "signals": [
            ("行程状态查询", r"robotaxi.*订单状态|订单状态|行程状态|预计到达|还有多久到", 7.0),
        ],
        "anti": [],
    },
}

MODE_SIGNALS = {
    "driver": re.compile(r"我(的)?车|自己开|开车|驾驶|车主|续航|充电|公司|后排|孩子", re.I),
    "robotaxi": re.compile(r"乘客|订单|上车|接我|你们车|无人车|robotaxi|网约车|改目的地", re.I),
}

NEGATION_PREFIX = re.compile(r"(?:不|没|没有|并不|并没有|不是|别|无需|不用)\s*$")


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[，。！？、；：,.!?;:]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _match(text: str, pattern: str) -> Optional[re.Match]:
    return re.search(pattern, text, re.I)


def _locally_negated(text: str, match: re.Match) -> bool:
    prefix = text[max(0, match.start() - 5):match.start()]
    return bool(NEGATION_PREFIX.search(prefix))


def _state_evidence(intent: str, snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    v = snapshot.get("vehicle_state") or {}
    o = snapshot.get("order_state") or {}
    env = snapshot.get("environment_state") or {}
    evidence: List[Dict[str, Any]] = []

    def add(label: str, phrase: str, contribution: float, source: str):
        evidence.append({"scenario_id": intent, "label": label, "phrase": phrase,
                         "contribution": contribution, "negated": contribution < 0, "source": source})

    if intent == "fatigue":
        hours = float(v.get("driving_hours") or 0)
        if hours >= 4:
            add("连续驾驶时长高", f"{hours:g}h", 3.0, "vehicle_state")
        elif hours >= 2.5:
            add("连续驾驶时长偏高", f"{hours:g}h", 1.5, "vehicle_state")
        if env.get("time_of_day") == "夜间":
            add("夜间驾驶先验", "夜间", 0.8, "environment_state")
    elif intent == "charging":
        soc = float(v.get("soc_percent") or 100)
        rng = float(v.get("range_km") or 9999)
        if soc <= 20:
            add("低电量", f"SOC {soc:g}%", 3.5, "vehicle_state")
        elif soc <= 35:
            add("电量偏低", f"SOC {soc:g}%", 1.5, "vehicle_state")
        if rng <= 80:
            add("剩余续航偏低", f"{rng:g}km", 2.0, "vehicle_state")
    elif intent == "find_car":
        status = str(o.get("status") or "")
        if "arriv" in status.lower() or "到达" in status or "即将" in status:
            add("订单处于会合阶段", status, 1.2, "order_state")
    elif intent == "trip_status":
        status = str(o.get("status") or "")
        if status:
            add("当前订单状态", status, 1.0, "order_state")
    elif intent == "modify_pickup":
        parking = str(env.get("parking_policy") or "")
        if any(k in parking for k in ("禁停", "禁止", "不允许")):
            add("环境停车策略禁止", parking, 3.0, "environment_state")
    elif intent == "parent_child" and v.get("child_seat_detected"):
        add("检测到儿童座椅", "child_seat_detected=true", 1.0, "vehicle_state")
    return evidence


def _score_definition(text: str, scenario_id: str, definition: Dict[str, Any], snapshot: Dict[str, Any], mode: str) -> Dict[str, Any]:
    evidence: List[Dict[str, Any]] = []
    score = 0.0
    for label, pattern, weight in definition["signals"]:
        match = _match(text, pattern)
        if not match:
            continue
        negated = _locally_negated(text, match)
        contribution = -abs(weight) * 0.9 if negated else weight
        score += contribution
        evidence.append({"scenario_id": scenario_id, "label": label, "phrase": match.group(0),
                         "contribution": round(contribution, 2), "negated": negated, "source": "utterance"})
    for label, pattern, weight in definition.get("anti", []):
        match = _match(text, pattern)
        if not match:
            continue
        score += weight
        evidence.append({"scenario_id": scenario_id, "label": label, "phrase": match.group(0),
                         "contribution": weight, "negated": True, "source": "anti_signal"})

    mode_match = MODE_SIGNALS[definition["mode"]].search(text)
    if mode_match:
        score += 0.6
        evidence.append({"scenario_id": scenario_id, "label": f"{definition['mode']} 模式先验",
                         "phrase": mode_match.group(0), "contribution": 0.6, "negated": False, "source": "utterance_mode_prior"})

    current_mode = "driver" if mode == "车主自驾" else "robotaxi"
    if definition["mode"] == current_mode:
        score += 0.35
        evidence.append({"scenario_id": scenario_id, "label": "当前运行模式匹配", "phrase": mode,
                         "contribution": 0.35, "negated": False, "source": "identity_state"})

    # 状态证据只用于“佐证”已由用户表达触发的候选，不能仅凭低电量/夜间等状态替用户猜意图。
    has_utterance_support = any(e.get("source") == "utterance" and float(e.get("contribution") or 0) > 0
                                for e in evidence)
    state_ev = _state_evidence(scenario_id, snapshot) if has_utterance_support else []
    score += sum(float(x["contribution"]) for x in state_ev)
    evidence.extend(state_ev)
    return {"scenario_id": scenario_id, "label": SCENARIO_LABELS[scenario_id], "mode": definition["mode"],
            "score": max(-12.0, round(score, 2)), "evidence": evidence}


def _confidence(top_score: float, margin: float, status: str) -> int:
    if status == "explicit":
        return 100
    if top_score <= 0:
        return 18
    raw = 43 + min(38, top_score * 4.2) + min(14, max(0, margin) * 4)
    return max(24, min(97, round(raw)))


def resolve_intent(message: str, snapshot: Optional[Dict[str, Any]] = None, mode: str = "车主自驾",
                   requested_id: Optional[str] = None) -> Dict[str, Any]:
    snapshot = snapshot or {}
    normalized = normalize_text(message)
    if requested_id and requested_id in DEFINITIONS:
        return {"algorithm": "IntentGraph", "version": "2.1.0", "status": "explicit", "selected": requested_id,
                "selected_label": SCENARIO_LABELS[requested_id], "confidence": 100, "margin": 100,
                "normalized": normalized, "alternatives": [],
                "signals": [{"scenario_id": requested_id, "label": "显式场景选择", "phrase": requested_id,
                             "contribution": 100, "negated": False, "source": "request"}],
                "negations": [], "needs_clarification": False, "safety_override": False}

    ranked = sorted((_score_definition(normalized, sid, definition, snapshot, mode)
                     for sid, definition in DEFINITIONS.items()), key=lambda x: (-x["score"], x["scenario_id"]))
    top, second = ranked[0], ranked[1]
    margin = round(top["score"] - second["score"], 2)
    safety_override = top["scenario_id"] == "medical" and top["score"] >= 4.5
    resolved = top["score"] >= 3.5 and (margin >= 1.0 or safety_override)
    status = "resolved" if resolved else "clarify"
    selected = top["scenario_id"] if resolved else None
    all_signals = sorted((ev for item in ranked for ev in item["evidence"]),
                         key=lambda x: -abs(float(x["contribution"])))
    return {
        "algorithm": "IntentGraph", "version": "2.1.0", "status": status, "selected": selected,
        "selected_label": SCENARIO_LABELS[selected] if selected else "需要澄清",
        "confidence": _confidence(top["score"], margin, status), "margin": margin, "normalized": normalized,
        "alternatives": [{k: item[k] for k in ("scenario_id", "label", "mode", "score")} for item in ranked[:3]],
        "signals": [x for x in all_signals if x["contribution"] > 0][:7],
        "negations": [x for x in all_signals if x["negated"] or x["contribution"] < 0][:5],
        "needs_clarification": not resolved, "safety_override": safety_override,
    }


def clarification_reply(resolution: Dict[str, Any]) -> str:
    alternatives = [x for x in resolution.get("alternatives", []) if x.get("score", 0) > 0][:2]
    if not alternatives:
        return "我还不能确定你希望我处理什么。请补充是车辆控制、补能、订单变更、找车，还是安全求助。"
    labels = "、".join(x["label"] for x in alternatives)
    return f"当前信息不足以安全执行操作。我更接近理解为“{labels}”，请补充你希望完成的具体动作。"
