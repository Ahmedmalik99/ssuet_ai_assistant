import schedule
import time
import subprocess
import sys
from datetime import datetime

def run_scraper():
    """Run the scraper and update RAG index"""
    print(f"\n⏰ [{datetime.now()}] Starting scheduled SSUET scrape...")
    try:
        # Run scraper
        result = subprocess.run([sys.executable, "rag_scraper.py"], 
                              capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"❌ Scraper failed: {result.stderr}")
            return
        
        print("✅ Scraper completed")
        
        # Update RAG index
        result = subprocess.run([sys.executable, "rag_engine.py"], 
                              capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            print(f"❌ RAG update failed: {result.stderr}")
            return
            
        print("✅ RAG index updated successfully")
        print(f"⏰ [{datetime.now()}] Scheduled task completed\n")
        
    except subprocess.TimeoutExpired:
        print("❌ Task timed out (took too long)")
    except Exception as e:
        print(f"❌ Error in scheduled task: {e}")

def start_scheduler():
    """Start the weekly scraping scheduler"""
    # Run every Sunday at 2 AM
    schedule.every().sunday.at("02:00").do(run_scraper)
    
    # Also run immediately on startup for initial index
    print("🚀 Running initial scrape and RAG setup...")
    run_scraper()
    
    print("📅 Scheduler started. Scraping will run every Sunday at 2:00 AM")
    print("Press CTRL+C to exit")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n👋 Scheduler stopped")

if __name__ == "__main__":
    start_scheduler()
