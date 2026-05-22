#!/usr/bin/env python3
"""
Policy Radar Pipeline Runner
Run all stages: fetch → merge → score → discover
Usage: python run_pipeline.py [--date YYYY-MM-DD]
"""
import subprocess
import sys
import json
import os
from datetime import datetime, timezone, timedelta

def run_step(name, script, args=None):
    cmd = [sys.executable, f"scripts/{script}"] + (args or [])
    print(f"\n{'='*60}")
    print(f"STEP: {name}")
    print(f"CMD:  {' '.join(cmd)}")
    print('='*60)
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"❌ FAILED: {name} (exit {result.returncode})")
        return False
    print(f"✅ DONE: {name}")
    return True

def main():
    # Determine run date
    if len(sys.argv) >= 3 and sys.argv[1] == "--date":
        run_date = sys.argv[2]
    else:
        now = datetime.now(timezone(timedelta(hours=8)))
        run_date = now.strftime("%Y-%m-%d")
    
    run_id = f"{run_date}_{datetime.now().strftime('%H%M%S')}"
    print(f"🚀 Policy Radar Pipeline — Run ID: {run_id}")
    
    steps = [
        ("Fetch Policies (3 channels)", "fetch_policies.py", [run_date, run_id]),
        ("Merge & Deduplicate", "merge.py", [run_date]),
        ("Score with MiniMax", "score_policies.py", [run_date]),
        ("Discover New Sources", "discover_sources.py", [run_date]),
    ]
    
    failed = []
    for name, script, args in steps:
        ok = run_step(name, script, args)
        if not ok:
            failed.append(name)
    
    if failed:
        print(f"\n❌ Pipeline FAILED at: {', '.join(failed)}")
        sys.exit(1)
    
    # Load scored results for summary
    scored_path = f"data/scored/scored_{run_date}.json"
    if os.path.exists(scored_path):
        with open(scored_path) as f:
            data = json.load(f)
        grades = data.get("graded", {})
        items = data.get("items", [])
        top5 = sorted(items, key=lambda x: x.get("score", 0), reverse=True)[:5]
        
        print(f"\n{'='*60}")
        print(f"📊 PIPELINE COMPLETE — {run_date}")
        print(f"{'='*60}")
        print(f"Grades: S={grades.get('S',0)}, A={grades.get('A',0)}, "
              f"B={grades.get('B',0)}, C={grades.get('C',0)}")
        print(f"\n🏆 TOP 5 POLICIES:")
        for i, item in enumerate(top5, 1):
            print(f"  {i}. [{item.get('grade','?')}] {item.get('score',0)}分 — {item.get('title','')[:50]}")
            print(f"     {item.get('apply_recommendation','')} | 截止: {item.get('deadline','未知')}")
        
        # Notify via exit code: 0 if any S/A, 1 if only B/C/C
        has_sa = grades.get('S', 0) + grades.get('A', 0) > 0
        if has_sa:
            print(f"\n🔥 S/A级政策发现！需要人工审核后推送。")
            # Write notification marker for webhook
            with open("data/.has_sa_notification", "w") as f:
                f.write(json.dumps({"date": run_date, "sa_count": grades.get('S',0) + grades.get('A',0), "items": top5[:3]}))
        else:
            print(f"\n📭 今日无S/A级政策，静默。")
    else:
        print(f"\n⚠️  Warning: scored results not found at {scored_path}")
    
    print(f"\n✅ Pipeline completed successfully.")
    sys.exit(0)

if __name__ == "__main__":
    main()
