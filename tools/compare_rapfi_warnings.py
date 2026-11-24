#!/usr/bin/env python3
"""Compare old/new Rapfi with deterministic search limits and identical builds.

Positions retain actual alternating move histories. Timing is secondary evidence;
exact move/value/PV/node/state fingerprints are compared independently of time.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
INITIAL = [5*12+6, 5*12+5, 6*12+5, 6*12+6]


def fingerprint(path):
    path=Path(path).resolve()
    data=path.read_bytes()
    return {"path":str(path),"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}


def has_five(board,p,side):
    row,col=divmod(p,12)
    for dr,dc in [(1,0),(0,1),(1,1),(1,-1)]:
        count=1
        for sign in [-1,1]:
            r,c=row+sign*dr,col+sign*dc
            while 0<=r<12 and 0<=c<12 and board[r*12+c]==side:
                count+=1;r+=sign*dr;c+=sign*dc
        if count>=5:return True
    return False


def fixtures():
    cases=[];seen=set()
    def add(label,moves,origin):
        board=[0]*144
        for index,p in enumerate(moves):
            assert 0<=p<144 and not board[p]
            board[p]=1+index%2
            assert not has_five(board,p,board[p])
        key=(tuple(board),len(moves)%2)
        if key in seen:return
        seen.add(key)
        cases.append({"id":label,"moves":list(moves),"side":1+len(moves)%2,"origin":origin})
    for filename in ["trained_vs_v3.json","trained_vs_reference.json"]:
        path=ROOT/"results/rapfi"/filename
        report=json.loads(path.read_text(encoding="utf-8"))
        for game in report["games"]:
            history=INITIAL+[m["row"]*12+m["col"] for m in game["moves"]]
            # Prefixes only; final move is excluded to keep positions nonterminal.
            plies=sorted(set([0,1,3,6,10,14,min(len(game["moves"])-2,20)]))
            for n in plies:
                add(f"{filename[:-5]}_g{game['game']}_p{n}",history[:4+n],
                    {"report":str(path.relative_to(ROOT)),"game":game["game"],"extra_plies":n})
    rng=random.Random(0x20261109)
    # Generate independent legal continuations with many local interactions and
    # occasional distant stones, without an engine's move generator or evaluator.
    serial=0
    while len(cases)<32:
        history=list(INITIAL);board=[0]*144
        for i,p in enumerate(history):board[p]=1+i%2
        target=12+(serial*7)%31
        while len(history)<target:
            empties=[p for p,v in enumerate(board) if not v]
            local=[p for p in empties if any(
                board[r*12+c] for r in range(max(0,p//12-2),min(12,p//12+3))
                for c in range(max(0,p%12-2),min(12,p%12+3)))]
            choices=list(local if local and rng.random()<0.85 else empties)
            rng.shuffle(choices)
            side=1+len(history)%2
            for p in choices:
                board[p]=side
                if not has_five(board,p,side):
                    history.append(p);break
                board[p]=0
            else:raise RuntimeError("could not extend random fixture")
        add(f"random_{serial:02}",history,{"seed":"0x20261109","serial":serial})
        serial+=1
    assert {x["side"] for x in cases}=={1,2}
    return cases


def pin(process):
    if os.name=="nt":
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.GetProcessAffinityMask.argtypes=[wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)]
        kernel.GetProcessAffinityMask.restype=wintypes.BOOL
        kernel.SetProcessAffinityMask.argtypes=[wintypes.HANDLE,ctypes.c_size_t]
        kernel.SetProcessAffinityMask.restype=wintypes.BOOL
        allowed,system=ctypes.c_size_t(),ctypes.c_size_t()
        handle=wintypes.HANDLE(int(process._handle))
        if not kernel.GetProcessAffinityMask(handle,ctypes.byref(allowed),ctypes.byref(system)):
            raise ctypes.WinError(ctypes.get_last_error())
        mask=allowed.value&-allowed.value
        if not kernel.SetProcessAffinityMask(handle,mask):raise ctypes.WinError(ctypes.get_last_error())
        return {"windows_affinity_mask":mask}
    cpu=min(os.sched_getaffinity(0))
    os.sched_setaffinity(process.pid,{cpu})
    return {"linux_cpu":cpu}


def run(executable,cases,depth,nodes,timeout):
    text="".join(f"{case['id']} {len(case['moves'])} "+" ".join(map(str,case['moves']))+"\n" for case in cases)
    start=time.perf_counter()
    process=subprocess.Popen([str(executable),str(depth),str(nodes)],stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8")
    affinity=pin(process)
    try:out,err=process.communicate(text,timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill();out,err=process.communicate()
        raise RuntimeError(f"probe timed out: {executable}\n{out[-2000:]}\n{err[-2000:]}")
    if process.returncode:raise RuntimeError(f"probe failed code={process.returncode}: {executable}\n{out[-2000:]}\n{err[-2000:]}")
    rows=[json.loads(line) for line in out.splitlines() if line.strip()]
    assert len(rows)==len(cases)+1 and rows[0]["kind"]=="metadata"
    assert [r["id"] for r in rows[1:]]==[c["id"] for c in cases]
    return {"wall_seconds":time.perf_counter()-start,"affinity":affinity,"stderr":err,"rows":rows}


def semantics(run):
    return [{k:v for k,v in row.items() if k!="milliseconds"} for row in run["rows"]]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source",type=Path,default=ROOT/"main.cpp")
    parser.add_argument("--candidate-source",type=Path,default=ROOT/"rapfi_port/rapfi_warning_clean.cpp")
    parser.add_argument("--compiler",type=Path,default=ROOT/"tmp/rapfi_tools/w64devkit/bin/g++.exe")
    parser.add_argument("--output-dir",type=Path,default=ROOT/"results/rapfi_warnings")
    parser.add_argument("--depth",type=int,default=10)
    parser.add_argument("--nodes",type=int,default=30000)
    parser.add_argument("--rounds",type=int,default=3)
    parser.add_argument("--timeout",type=float,default=180)
    parser.add_argument("--prepare-only",action="store_true")
    parser.add_argument("--build-only",action="store_true")
    parser.add_argument("--skip-build",action="store_true")
    args=parser.parse_args()
    out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    cases=fixtures()
    (out/"equivalence_fixtures.json").write_text(json.dumps(cases,indent=2)+"\n",encoding="utf-8")
    if args.prepare_only:
        print(f"Prepared {len(cases)} nonterminal course positions; sides="+
              str({s:sum(c['side']==s for c in cases) for s in (1,2)}));return 0
    sources={"baseline":args.baseline_source.resolve(),"candidate":args.candidate_source.resolve()}
    executables={name:out/f"equivalence_{name}.exe" for name in sources}
    flags=["-std=c++17","-O2"]
    if os.name=="nt":flags+=["-Wl,--stack,8388608"]
    if not args.skip_build:
        for name,source in sources.items():
            command=[str(args.compiler),*flags,f'-DRAPFI_COURSE_SOURCE="{source.as_posix()}"',
                     str(ROOT/"tests/rapfi_equivalence.cpp"),"-o",str(executables[name])]
            built=subprocess.run(command,capture_output=True,text=True,encoding="utf-8",errors="replace")
            (out/f"equivalence_{name}_build.txt").write_text(built.stdout+built.stderr,encoding="utf-8")
            if built.returncode:
                print(built.stdout+built.stderr);return built.returncode
            print(f"Built {name}",flush=True)
    if args.build_only:return 0
    report={"sources":{k:fingerprint(v) for k,v in sources.items()},
            "probe":fingerprint(ROOT/"tests/rapfi_equivalence.cpp"),
            "executables":{k:fingerprint(v) for k,v in executables.items()},
            "flags":flags,"max_depth":args.depth,"max_nodes":args.nodes,
            "fixtures":fingerprint(out/"equivalence_fixtures.json"),"position_count":len(cases),
            "runs":[],"differences":[]}
    canonical=None
    def save():
        (out/"equivalence.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    for round_index in range(args.rounds):
        order=["baseline","candidate"] if round_index%2==0 else ["candidate","baseline"]
        pair={}
        for name in order:
            result=run(executables[name],cases,args.depth,args.nodes,args.timeout)
            pair[name]=result
            current=semantics(result)
            if canonical is None:canonical=current
            if current!=canonical:
                report["differences"].extend({"round":round_index,"build":name,"index":i,
                    "baseline":a,"actual":b} for i,(a,b) in enumerate(zip(canonical,current)) if a!=b)
            print(f"Round {round_index+1} {name}: {sum(r.get('milliseconds',0) for r in result['rows']):.2f} search ms",flush=True)
        report["runs"].append(pair);save()
    totals={name:[sum(r.get("milliseconds",0) for r in p[name]["rows"]) for p in report["runs"]]
            for name in sources}
    report["summary"]={"exact_results_identical":not report["differences"],
        "positions_per_round":len(cases),"rounds":args.rounds,
        "search_ms":totals,
        "median_candidate_over_baseline":statistics.median(totals["candidate"])/statistics.median(totals["baseline"]),
        "total_nodes_per_pass":sum(r.get("nodes",0) for r in canonical),
        "nontrivial_positions":sum(r.get("nodes",0)>0 for r in canonical),
        "scope":"Identical deterministic depth+node caps; timing varies with host scheduling. Not a win-rate test."}
    save();print(json.dumps(report["summary"],indent=2))
    return int(bool(report["differences"]))


if __name__=="__main__":raise SystemExit(main())
