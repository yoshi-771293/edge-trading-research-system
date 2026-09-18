"""Download every instrument's hourly bid/ask history with retries and a completeness
report. Run detached; progress is printed per instrument."""
import sys, time
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from referee import forex

print("fx_download starting", flush=True)
t0 = time.time()
now = pd.Timestamp.now(tz="UTC")
for i, s in enumerate(forex.INSTRUMENTS, 1):
    t = time.time()
    try:
        df = forex.download(s, first_year=2005, workers=4)
    except Exception as e:
        print(f"[{i}/10] {s}: FAILED {type(e).__name__}: {e}", flush=True)
        continue
    if not len(df):
        print(f"[{i}/10] {s}: NO DATA ({time.time()-t:.0f}s)", flush=True)
        continue
    rep = forex.completeness(df, 2005, now)
    d = forex.to_daily(df)
    print(f"[{i}/10] {s}: {len(df):>7,d} hourly, {len(d):>5,d} days, {df.index[0].date()}..{df.index[-1].date()} | "
          f"coverage {rep['coverage']:.1%} ({len(rep['missing'])} months missing) | "
          f"half-spread median {df['half_spread'].median()*1e4:.3f} bp | {time.time()-t:.0f}s", flush=True)
print(f"FX DOWNLOAD DONE in {(time.time()-t0)/60:.0f} min", flush=True)
