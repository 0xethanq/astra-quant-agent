#!/usr/bin/env python3
"""
Background loop for legacy console data synchronization and news refresh.
Self-improvement is intentionally excluded; the scheduled evolution job is its sole owner.
"""
import time
import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from sync_web_data import generate_trading_data

def main():
    last_news_time = 0
    last_factor_time = 0

    while True:
        try:
            generate_trading_data()
        except Exception:
            pass

        now_ts = time.time()

        # 1. Harvest OKX News & Macro Sentiment every 10 minutes (600s)
        if now_ts - last_news_time > 600:
            try:
                subprocess.run([sys.executable, os.path.join(BASE_DIR, "news_sentiment_harvester.py")], timeout=30)
                last_news_time = now_ts
            except Exception:
                pass

        # 2. Update 5-Pillar Quantitative Factor Library every 60 seconds
        if now_ts - last_factor_time > 60:
            try:
                subprocess.run([sys.executable, os.path.join(BASE_DIR, "factor_library.py")], timeout=15)
                last_factor_time = now_ts
            except Exception:
                pass

        time.sleep(10)

if __name__ == "__main__":
    main()
