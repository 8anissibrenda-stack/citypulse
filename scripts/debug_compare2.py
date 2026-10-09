import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.routers.ambulance import compare_both
from fastapi import Request
import asyncio

async def test():
    class DummyRequest:
        app = None
    res = await compare_both(DummyRequest())
    print('\n--- BASELINE TIMELINE ---')
    for p in res['baseline']:
        if p['t'] % 10.0 == 0.0 or p == res['baseline'][-1]:
            print(f"t={p['t']:5.1f} frac={p['route_fraction']:.2f} S1={p['signals'].get('S1')} S2={p['signals'].get('S2')} S3={p['signals'].get('S3')} stops={p['stops']} wait={p['wait_s']}")
            
    print('\n--- PRIORITY TIMELINE ---')
    for p in res['priority']:
        if p['t'] % 10.0 == 0.0 or p == res['priority'][-1]:
            print(f"t={p['t']:5.1f} frac={p['route_fraction']:.2f} S1={p['signals'].get('S1')} S2={p['signals'].get('S2')} S3={p['signals'].get('S3')} PriS2={p['priority_active'].get('S2')} PriS3={p['priority_active'].get('S3')} stops={p['stops']} wait={p['wait_s']}")

if __name__ == "__main__":
    asyncio.run(test())
