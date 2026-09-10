import requests
import os
import time
import sys

API_KEY = "AIzaSyC-pCOghTQ3JAwE7SAI_Gq3cCEIvtuu2z4"
A1_SOURCE_ID = "1GuXRTz8idMNHV99IhTtUDaxEMlGGInTJ"
A2_DEST_ID = "1KOWhnJUlOYR12yD0OQYWgJ3cxXzg1bDo"
LOCAL_SAVE_DIR = r"D:\8th semester\Files-backup"
BLOCK_WORDS = ["paradox", "toolkit"]

CACHE_FILE = os.path.join(LOCAL_SAVE_DIR, "matched_files_cache.txt")

def format_size(bytes_size):
    if bytes_size >= 1024**3:
        return f"{bytes_size / (1024**3):.2f} GB"
    elif bytes_size >= 1024**2:
        return f"{bytes_size / (1024**2):.2f} MB"
    elif bytes_size >= 1024:
        return f"{bytes_size / 1024:.2f} KB"
    else:
        return f"{bytes_size} Bytes"

def save_to_cache(filename):
    with open(CACHE_FILE, 'a', encoding='utf-8') as f:
        f.write(filename.lower().strip() + '\n')

def cleanup_cache(cache_set):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        for name in cache_set:
            f.write(name + '\n')

def get_a2_files(folder_id, scan_stats=None):
    if scan_stats is None:
        scan_stats = {'count': 0}
        
    existing_names = set()
    url = "https://www.googleapis.com/drive/v3/files"
    page_token = None
    while True:
        params = {'q': f"'{folder_id}' in parents and trashed = false", 'fields': 'nextPageToken, files(id, name, mimeType)', 'key': API_KEY, 'pageSize': 1000}
        if page_token:
            params['pageToken'] = page_token
        res = requests.get(url, params=params).json()
        if 'error' in res:
            break
        for item in res.get('files', []):
            scan_stats['count'] += 1
            
            if scan_stats['count'] % 50 == 0:
                sys.stdout.write(f"\r🔄 Scanning A2 Drive: Found {scan_stats['count']} items so far...")
                sys.stdout.flush()
                
            if item['mimeType'] == 'application/vnd.google-apps.folder':
                existing_names.update(get_a2_files(item['id'], scan_stats))
            else:
                existing_names.add(item['name'].lower().strip())
        page_token = res.get('nextPageToken')
        if not page_token:
            break
    return existing_names

def build_download_queue(source_id, a2_set, current_path, queue, stats, matched_cache):
    url = "https://www.googleapis.com/drive/v3/files"
    page_token = None
    while True:
        params = {'q': f"'{source_id}' in parents and trashed = false", 'fields': 'nextPageToken, files(id, name, mimeType, size)', 'key': API_KEY, 'pageSize': 1000}
        if page_token:
            params['pageToken'] = page_token
        res = requests.get(url, params=params).json()
        if 'error' in res:
            break
        for item in res.get('files', []):
            name = item['name']
            lower_name = name.lower().strip()
            
            if item['mimeType'] == 'application/vnd.google-apps.folder':
                new_path = os.path.join(current_path, name)
                os.makedirs(new_path, exist_ok=True)
                build_download_queue(item['id'], a2_set, new_path, queue, stats, matched_cache)
            else:
                stats['total_a1_files'] += 1
                
                if stats['total_a1_files'] % 100 == 0:
                    # Added spaces at the end to prevent visual glitch
                    sys.stdout.write(f"\r🔄 Scanning A1 & Local Disk: Checked {stats['total_a1_files']} files...          ")
                    sys.stdout.flush()
                
                if any(word in lower_name for word in BLOCK_WORDS):
                    stats['blocked_files'] += 1
                    continue
                
                file_size = int(item.get('size', 0))
                
                # 1. DIRECT SKIP: If file is in Cache
                if lower_name in matched_cache:
                    stats['already_downloaded'] += 1
                    stats['already_downloaded_size'] += file_size
                    continue
                
                final_path = os.path.join(current_path, name)
                
                # 2. CHECK: If in A2 (if scanned) OR Local Path
                if lower_name in a2_set or (os.path.exists(final_path) and os.path.getsize(final_path) > 0):
                    stats['already_downloaded'] += 1
                    stats['already_downloaded_size'] += file_size
                    
                    matched_cache.add(lower_name)
                    save_to_cache(lower_name)
                else:
                    # 3. Add to Download Queue
                    queue.append({'id': item['id'], 'name': name, 'size': file_size, 'path': final_path})
                    stats['pending_downloads'] += 1
                    stats['pending_size'] += file_size
                        
        page_token = res.get('nextPageToken')
        if not page_token:
            break

def process_downloads(queue, stats, matched_cache):
    total_queue = len(queue)
    for index, file_data in enumerate(queue, 1):
        temp_path = file_data['path'] + ".temp"
        final_path = file_data['path']
        
        print(f"\n[{index}/{total_queue}] 📥 Downloading: {file_data['name']}")
        print(f"    💾 Size: {format_size(file_data['size'])} | ⏳ Remaining in Queue: {total_queue - index}")
        
        download_url = f"https://www.googleapis.com/drive/v3/files/{file_data['id']}?alt=media&key={API_KEY}"
        success = False
        
        for attempt in range(1, 4):
            try:
                with requests.get(download_url, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    downloaded_size = 0
                    with open(temp_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            if chunk:
                                f.write(chunk)
                                downloaded_size += len(chunk)
                                if file_data['size'] > 0:
                                    percent = int((downloaded_size / file_data['size']) * 100)
                                    # Added spaces here to prevent "MBB" glitch
                                    sys.stdout.write(f"\r    🔄 Progress: [{percent}%] {format_size(downloaded_size)} / {format_size(file_data['size'])}          ")
                                    sys.stdout.flush()
                
                os.rename(temp_path, final_path)
                print(f"\n    ✅ Success!")
                stats['success_count'] += 1
                
                lower_name = file_data['name'].lower().strip()
                matched_cache.add(lower_name)
                save_to_cache(lower_name)
                
                success = True
                break
                
            except requests.exceptions.HTTPError as e:
                # Yeh naya block humein Google ki taraf se aane wala EXACT error batayega (403 ki asli wajah)
                print(f"\n    ⚠️ Attempt {attempt}/3 Failed: {e}")
                print(f"    🔍 Google Says: {e.response.text}")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                time.sleep(2)
                
            except Exception as e:
                print(f"\n    ⚠️ Attempt {attempt}/3 Failed: {e}")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                time.sleep(2)
                
        if not success:
            print(f"    ❌ Final Failure. Skipped: {file_data['name']}")
            stats['fail_count'] += 1

# ==========================================
# MAIN EXECUTION
# ==========================================
os.makedirs(LOCAL_SAVE_DIR, exist_ok=True)

# LOAD CACHE
matched_cache_set = set()
if os.path.exists(CACHE_FILE):
    print("==================================================")
    print("📂 LOADING MATCHED FILES CACHE (RESUME MODE)")
    print("==================================================")
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        matched_cache_set = set(line.strip().lower() for line in f if line.strip())
    print(f"✅ Loaded {len(matched_cache_set)} previously matched files from cache.\n")

a2_files_set = set()

# 🔥 NEW LOGIC: Skip Phase 1 if Cache has items
if len(matched_cache_set) > 0:
    print("==================================================")
    print("⏩ SKIPPING PHASE 1: CACHE FOUND!")
    print("==================================================")
    print("✅ Using cache instead of scanning A2 Drive again.\n")
else:
    print("==================================================")
    print("🔍 PHASE 1: SCANNING GOOGLE DRIVE (A2)")
    print("==================================================")
    a2_files_set = get_a2_files(A2_DEST_ID)
    print(f"\n✅ Scan Complete! Found {len(a2_files_set)} files in A2.\n")

queue_stats = {
    'total_a1_files': 0, 'blocked_files': 0, 
    'already_downloaded': 0, 'already_downloaded_size': 0,
    'pending_downloads': 0, 'pending_size': 0
}
download_queue = []

print("==================================================")
print("🚀 PHASE 2: SCANNING A1 & CHECKING LOCAL STORAGE")
print("==================================================")
build_download_queue(A1_SOURCE_ID, a2_files_set, LOCAL_SAVE_DIR, download_queue, queue_stats, matched_cache_set)
print("\n\n✅ Scan & Comparison Complete!\n")

print("==================================================")
print("📊 PRE-DOWNLOAD STATISTICS")
print("==================================================")
print(f"📁 Total Files Checked in A1 : {queue_stats['total_a1_files']}")
print(f"🚫 Blocked Files Skipped     : {queue_stats['blocked_files']}")
print(f"✅ Already Downloaded/Matched: {queue_stats['already_downloaded']} ({format_size(queue_stats['already_downloaded_size'])})")
print(f"⚠️ Remaining to Download     : {queue_stats['pending_downloads']} ({format_size(queue_stats['pending_size'])})")
print("==================================================")

if queue_stats['pending_downloads'] > 0:
    print("\n==================================================")
    print("📥 PHASE 3: DOWNLOADING FILES")
    print("==================================================")
    dl_stats = {'success_count': 0, 'fail_count': 0}
    process_downloads(download_queue, dl_stats, matched_cache_set)
    
    print("\n==================================================")
    print("🎉 ALL TASKS COMPLETED!")
    print(f"✅ Successfully Downloaded: {dl_stats['success_count']}")
    print(f"❌ Failed Downloads       : {dl_stats['fail_count']}")
    print("==================================================")
else:
    print("\n🎉 ALL FILES ARE ALREADY DOWNLOADED! NOTHING TO DO.")

cleanup_cache(matched_cache_set)
