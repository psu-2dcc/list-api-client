"""Demo: fetch MBE2-grown samples since 2026-07-01 and print their recipes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from listapi import sign_in  # noqa: E402

client = sign_in()  # URL / auth from LIST_URL, LIST_API_KEY or config/list.py
samples = client.find_samples(syn_instrument="MBE2", grown_after="2026-07-01")
rows = client.query_activities(samples[:100], processing_types=["SYN"])

for row in rows:
    print(row["sampleLabel"], row["activities"])
