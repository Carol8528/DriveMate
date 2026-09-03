# -*- coding: utf-8 -*-
"""Small, auditable Markdown knowledge-base retriever for the demo runtime."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List


KNOWLEDGE_ROOT = Path(__file__).resolve().parent.parent / "knowledge"
ROUTES = {
    "ev-emergency-rescue.md": ("故障", "报警灯", "抛锚", "搭电", "换胎", "拖车", "救援"),
    "children-ride-safety.md": ("儿童", "孩子", "安全座椅", "isofix", "童锁"),
    "traffic-safety-law.md": ("法规", "违章", "酒驾", "事故责任", "保险理赔"),
    "traffic-law-regulations.md": ("限速", "信号灯", "让行", "高速公路"),
    "ev-user-manual.md": ("充电", "续航", "辅助驾驶", "泊车", "车机", "ota"),
}


def retrieve_knowledge(query: str, max_documents: int = 2) -> List[Dict[str, str]]:
    """Retrieve matching local Markdown sections with explicit source paths."""
    normalized = str(query or "").lower()
    matches = []
    for filename, keywords in ROUTES.items():
        score = sum(1 for keyword in keywords if keyword in normalized)
        path = KNOWLEDGE_ROOT / filename
        if score and path.is_file():
            text = path.read_text(encoding="utf-8")
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
            excerpt = next(
                (part for part in paragraphs if any(k in part.lower() for k in keywords if k in normalized)),
                paragraphs[0] if paragraphs else "",
            )
            matches.append(
                {
                    "source": f"knowledge/{filename}",
                    "title": text.splitlines()[0].lstrip("# ").strip(),
                    "excerpt": excerpt[:600],
                    "score": str(score),
                }
            )
    matches.sort(key=lambda item: (-int(item["score"]), item["source"]))
    return matches[:max_documents]
