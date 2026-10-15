"""Author the manually calculated scenario fixture (not a controller oracle).

All assertion times/states below are explicitly chosen from CONTRACT.md. This file
does not import the implementation or derive expected states from a state machine.
Run it only when intentionally updating data/scenarios.json.
"""
import json
from pathlib import Path


def vehicle(at, speed=10, ignition=True, period=None, until=None):
    event = dict(at_ms=at, kind="vehicle", speed_kmh=speed, ignition=ignition)
    if period is not None:
        event.update(period_ms=period, until_ms=until)
    return event


def doors(at, mask=1, period=None, until=None):
    event = dict(at_ms=at, kind="doors", door_mask=mask)
    if period is not None:
        event.update(period_ms=period, until_ms=until)
    return event


def raw(at, message_id, hex_data, period=None, until=None):
    event = dict(at_ms=at, kind="raw", arbitration_id=message_id, data_hex=hex_data)
    if period is not None:
        event.update(period_ms=period, until_ms=until)
    return event


def checks(*values):
    # Tuple columns: timestamp, warning, data_fault, reason. Values are hand-set.
    return [dict(at_ms=t, warning=bool(w), data_fault=bool(f), reason=r)
            for t, w, f, r in values]


SCENARIOS = [
    dict(
        id="SC01", title="初始缺数与首次完整输入", requirements=["REQ-03", "REQ-04", "REQ-08"],
        duration_ms=400,
        events=[vehicle(20, period=100, until=320), doors(20, period=100, until=320)],
        assertions=checks((0, 0, 1, 1), (10, 0, 1, 1), (20, 0, 0, 5),
                          (210, 0, 0, 5), (220, 1, 0, 6), (400, 1, 0, 6)),
    ),
    dict(
        id="SC02", title="5 km/h触发与200 ms精确边界", requirements=["REQ-01", "REQ-08"],
        duration_ms=400,
        events=[vehicle(0, 4.99, period=50, until=50),
                vehicle(100, 5.00, period=50, until=400), doors(0, period=100, until=400)],
        assertions=checks((0, 0, 0, 4), (90, 0, 0, 4), (100, 0, 0, 5),
                          (290, 0, 0, 5), (300, 1, 0, 6), (400, 1, 0, 6)),
    ),
    dict(
        id="SC03", title="3.01保持与3.00解除", requirements=["REQ-01", "REQ-09"],
        duration_ms=500,
        events=[vehicle(0, 6, period=100, until=200), vehicle(250, 3.01),
                vehicle(300, 3, period=100, until=500), doors(0, period=100, until=500)],
        assertions=checks((190, 0, 0, 5), (200, 1, 0, 6), (250, 1, 0, 6),
                          (290, 1, 0, 6), (300, 0, 0, 4), (500, 0, 0, 4)),
    ),
    dict(
        id="SC04", title="3到5 km/h滞回区依赖既有状态", requirements=["REQ-08", "REQ-09"],
        duration_ms=800,
        events=[vehicle(0, 4, period=100, until=100), vehicle(200, 5, period=100, until=400),
                vehicle(450, 4, period=100, until=650), vehicle(700, 3), vehicle(800, 4),
                doors(0, period=100, until=800)],
        assertions=checks((0, 0, 0, 4), (100, 0, 0, 4), (200, 0, 0, 5),
                          (390, 0, 0, 5), (400, 1, 0, 6), (450, 1, 0, 6),
                          (650, 1, 0, 6), (700, 0, 0, 4), (800, 0, 0, 4)),
    ),
    dict(
        id="SC05", title="关门立即消警再开门重新去抖", requirements=["REQ-07", "REQ-10"],
        duration_ms=600,
        events=[vehicle(0, 30, period=100, until=600), doors(0, 1, period=100, until=200),
                doors(250, 0, period=100, until=350), doors(400, 2, period=100, until=600)],
        assertions=checks((190, 0, 0, 5), (200, 1, 0, 6), (250, 0, 0, 3),
                          (390, 0, 0, 3), (400, 0, 0, 5), (590, 0, 0, 5), (600, 1, 0, 6)),
    ),
    dict(
        id="SC06", title="熄火立即消警再点火重新去抖", requirements=["REQ-06", "REQ-10"],
        duration_ms=600,
        events=[vehicle(0, 20, True, period=100, until=200),
                vehicle(250, 20, False, period=100, until=350),
                vehicle(400, 20, True, period=100, until=600), doors(0, period=100, until=600)],
        assertions=checks((200, 1, 0, 6), (250, 0, 0, 2), (390, 0, 0, 2),
                          (400, 0, 0, 5), (590, 0, 0, 5), (600, 1, 0, 6)),
    ),
    dict(
        id="SC07", title="车速帧丢失300 ms仍新鲜310 ms故障", requirements=["REQ-05", "REQ-10"],
        duration_ms=650,
        events=[vehicle(0), vehicle(400, period=100, until=600), doors(0, period=100, until=600)],
        assertions=checks((200, 1, 0, 6), (300, 1, 0, 6), (310, 0, 1, 1),
                          (390, 0, 1, 1), (400, 0, 0, 5), (590, 0, 0, 5),
                          (600, 1, 0, 6), (650, 1, 0, 6)),
    ),
    dict(
        id="SC08", title="车门帧独立超时与恢复", requirements=["REQ-05", "REQ-10"],
        duration_ms=650,
        events=[vehicle(0, period=100, until=600), doors(0), doors(400, period=100, until=600)],
        assertions=checks((200, 1, 0, 6), (300, 1, 0, 6), (310, 0, 1, 1),
                          (390, 0, 1, 1), (400, 0, 0, 5), (590, 0, 0, 5), (600, 1, 0, 6)),
    ),
    dict(
        id="SC09", title="未知ID和其任意DLC不改变有效输入", requirements=["REQ-02", "REQ-08"],
        duration_ms=500,
        events=[vehicle(0, period=100, until=500), doors(0, period=100, until=500),
                raw(150, 0x555, "ff", period=100, until=450)],
        assertions=checks((0, 0, 0, 5), (150, 0, 0, 5), (190, 0, 0, 5),
                          (200, 1, 0, 6), (250, 1, 0, 6), (500, 1, 0, 6)),
    ),
    dict(
        id="SC10", title="250.01 km/h非法速度立即失效并恢复", requirements=["REQ-01", "REQ-02", "REQ-10"],
        duration_ms=600,
        events=[vehicle(0, period=100, until=200), raw(250, 0x100, "a961010000000000"),
                vehicle(400, period=100, until=600), doors(0, period=100, until=600)],
        assertions=checks((200, 1, 0, 6), (250, 0, 1, 1), (300, 0, 1, 1),
                          (390, 0, 1, 1), (400, 0, 0, 5), (590, 0, 0, 5), (600, 1, 0, 6)),
    ),
    dict(
        id="SC11", title="非法点火值2立即失效并恢复", requirements=["REQ-02", "REQ-10"],
        duration_ms=600,
        events=[vehicle(0, period=100, until=200), raw(250, 0x100, "e803020000000000"),
                vehicle(400, period=100, until=600), doors(0, period=100, until=600)],
        assertions=checks((200, 1, 0, 6), (250, 0, 1, 1), (390, 0, 1, 1),
                          (400, 0, 0, 5), (590, 0, 0, 5), (600, 1, 0, 6)),
    ),
    dict(
        id="SC12", title="车门高位非法立即失效并恢复", requirements=["REQ-02", "REQ-10"],
        duration_ms=600,
        events=[vehicle(0, period=100, until=600), doors(0, period=100, until=200),
                raw(250, 0x101, "1000000000000000"), doors(400, period=100, until=600)],
        assertions=checks((200, 1, 0, 6), (250, 0, 1, 1), (390, 0, 1, 1),
                          (400, 0, 0, 5), (590, 0, 0, 5), (600, 1, 0, 6)),
    ),
    dict(
        id="SC13", title="短帧长帧均失效且分别恢复", requirements=["REQ-02", "REQ-10"],
        duration_ms=700,
        events=[vehicle(0, period=100, until=200), doors(0, period=100, until=200),
                raw(250, 0x100, "e80301"), vehicle(300, period=100, until=700),
                raw(350, 0x101, "010000000000000000"), doors(400, period=100, until=700)],
        assertions=checks((200, 1, 0, 6), (250, 0, 1, 1), (300, 0, 0, 5),
                          (340, 0, 0, 5), (350, 0, 1, 1), (400, 0, 0, 5),
                          (590, 0, 0, 5), (600, 1, 0, 6), (700, 1, 0, 6)),
    ),
    dict(
        id="SC14", title="间断条件不能累加为200 ms", requirements=["REQ-08", "REQ-10"],
        duration_ms=500,
        events=[vehicle(0, 5, period=50, until=100), vehicle(150, 4.99),
                vehicle(200, 5, period=50, until=500), doors(0, period=100, until=500)],
        assertions=checks((0, 0, 0, 5), (140, 0, 0, 5), (150, 0, 0, 4),
                          (190, 0, 0, 4), (200, 0, 0, 5), (390, 0, 0, 5),
                          (400, 1, 0, 6), (500, 1, 0, 6)),
    ),
    dict(
        id="SC15", title="同刻最后报文优先且先收后算", requirements=["REQ-02", "REQ-03", "REQ-10", "REQ-12"],
        duration_ms=700,
        events=[vehicle(0), doors(0, period=100, until=300),
                vehicle(200, 10, False), vehicle(200, 10, True), doors(200, 0), doors(200, 1),
                vehicle(250), raw(250, 0x100, "e803020000000000"),
                raw(300, 0x100, "e803020000000000"), vehicle(300, period=100, until=700),
                doors(400, 1), doors(400, 0), doors(450, 0), doors(450, 1),
                doors(500, period=100, until=700)],
        assertions=checks((0, 0, 0, 5), (190, 0, 0, 5), (200, 1, 0, 6),
                          (250, 0, 1, 1), (300, 0, 0, 5), (390, 0, 0, 5),
                          (400, 0, 0, 3), (450, 0, 0, 5), (640, 0, 0, 5),
                          (650, 1, 0, 6), (700, 1, 0, 6)),
    ),
    dict(
        id="SC16", title="缺数点火车门优先级与重复触发", requirements=["REQ-05", "REQ-06", "REQ-07", "REQ-10", "REQ-11"],
        duration_ms=1000,
        events=[vehicle(0, 10, False), doors(0, 0, period=100, until=100),
                vehicle(100, period=100, until=400), doors(200, period=100, until=400),
                vehicle(450, 10, False), doors(450, 0),
                vehicle(500, period=100, until=800), doors(500),
                vehicle(900, 10, False), doors(900, 0), vehicle(1000)],
        assertions=checks((0, 0, 0, 2), (100, 0, 0, 3), (200, 0, 0, 5),
                          (390, 0, 0, 5), (400, 1, 0, 6), (450, 0, 0, 2),
                          (500, 0, 0, 5), (690, 0, 0, 5), (700, 1, 0, 6),
                          (800, 1, 0, 6), (810, 0, 1, 1), (900, 0, 0, 2), (1000, 0, 0, 3)),
    ),
]


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[1] / "data" / "scenarios.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(SCENARIOS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(SCENARIOS)} manually specified scenarios to {destination}")
