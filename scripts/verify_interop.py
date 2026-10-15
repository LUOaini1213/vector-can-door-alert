"""Optional independent DBC and ASC checks; requires cantools and python-can."""

import importlib.metadata
import json
from pathlib import Path
import random
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from door_alert.protocol import encode_vehicle, encode_doors, encode_alert
import cantools
import can


def main():
    db=cantools.database.load_file(str(ROOT/"data/body_control.dbc"),strict=True)
    assert sorted(m.frame_id for m in db.messages)==[256,257,512]
    vectors=0
    rng=random.Random(20261015)
    speeds=[0,1,299,300,301,499,500,501,25000]+[rng.randrange(25001) for _ in range(1000)]
    for raw in speeds:
        for ignition in [False,True]:
            frame=encode_vehicle(0,raw/100,ignition)
            expected={"VehicleSpeed":raw/100,"IgnitionOn":int(ignition)}
            encoded=db.encode_message("VehicleStatus",expected)
            assert encoded==frame.data
            decoded=db.decode_message(256,frame.data,decode_choices=False)
            assert abs(decoded["VehicleSpeed"]-expected["VehicleSpeed"])<1e-9
            assert decoded["IgnitionOn"]==int(ignition)
            vectors+=1
    for mask in range(16):
        values={name:(mask>>i)&1 for i,name in enumerate(["DoorFL","DoorFR","DoorRL","DoorRR"])}
        data=encode_doors(0,mask).data
        assert db.encode_message("DoorStatus",values)==data
        assert db.decode_message(257,data,decode_choices=False)==values
        vectors+=1
    for warning in [False,True]:
        for fault in [False,True]:
            for reason in range(1,7):
                values={"Warning":int(warning),"DataFault":int(fault),"Reason":reason}
                data=encode_alert(0,warning,fault,reason).data
                assert db.encode_message("AlertStatus",values)==data
                assert db.decode_message(512,data,decode_choices=False)==values
                vectors+=1
    report=json.loads((ROOT/"reports/demo/report.json").read_text(encoding="utf-8"))
    asc_counts={}
    for result in report["scenarios"]:
        expected=[]
        for n,frame in enumerate(result["input_frames"]):
            data=bytes.fromhex(frame["data_hex"])
            if len(data)<=8:
                expected.append((frame["timestamp_ms"],0,n,frame["arbitration_id"],data,True))
        for n,state in enumerate(result["trace"]):
            frame=encode_alert(state["timestamp_ms"],state["warning"],state["data_fault"],state["reason"])
            expected.append((frame.timestamp_ms,1,n,frame.arbitration_id,frame.data,False))
        expected.sort(key=lambda r:r[:3])
        with can.ASCReader(str(ROOT/"reports/demo/traces"/f"{result['id']}.asc"),relative_timestamp=True) as reader:
            actual=list(reader)
        assert len(actual)==len(expected),(result["id"],len(actual),len(expected))
        for got,want in zip(actual,expected):
            assert abs(got.timestamp-want[0]/1000)<1e-8
            assert got.arbitration_id==want[3]
            assert bytes(got.data)==want[4]
            assert got.is_rx==want[5]
            assert not got.is_extended_id and not got.is_fd
        asc_counts[result["id"]]=len(actual)
    evidence={"cantools_version":importlib.metadata.version("cantools"),
              "python_can_version":importlib.metadata.version("python-can"),
              "dbc_messages":len(db.messages),"independent_encoding_vectors":vectors,
              "asc_files_verified":len(asc_counts),"asc_messages_verified":sum(asc_counts.values()),
              "asc_message_counts":asc_counts,
              "scope":"Independent open-source DBC and ASC parsers. This is not a CANoe import or CAPL execution test."}
    (ROOT/"reports/demo/interop_check.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(evidence,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":raise SystemExit(main())
