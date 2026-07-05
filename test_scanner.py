#!/usr/bin/env python3
"""
Test script for Portal Scanner

Run this to verify the scanner is working correctly.
"""

import asyncio
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

import scan_portals


async def main():
    print("🔍 Job Orchestrator — Portal Scanner Test\n")
    
    # Load config
    config = scan_portals.load_portals_config()
    
    if not config.get("tracked_companies"):
        print("❌ No companies configured in portals.yml")
        print("\nExample configuration:")
        print("""
tracked_companies:
  - name: "Anthropic"
    careers_url: "https://www.anthropic.com/careers"
    api: "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs"
    api_provider: "greenhouse"
    enabled: true
        """)
        return
    
    # Run full scan
    print("Starting full scan...\n")
    result = await scan_portals.run_full_scan(config)
    
    print("\n" + "="*70)
    print("✅ SCAN COMPLETE")
    print("="*70)
    print(f"\nNew jobs found: {len(result['new_jobs'])}")
    
    if result['new_jobs']:
        print("\nSample jobs:")
        for job in result['new_jobs'][:5]:
            print(f"  • {job.get('title', 'N/A')} @ {job.get('company', 'N/A')}")
            print(f"    Location: {job.get('location', 'N/A')}")
            print(f"    URL: {job.get('url', 'N/A')}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
