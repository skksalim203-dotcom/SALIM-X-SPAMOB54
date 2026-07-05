import os, sys, time, json, ssl, socket, threading, asyncio, base64, binascii, re, jwt, pickle
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

import requests
import urllib3
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from google.protobuf.timestamp_pb2 import Timestamp

# custom project modules
from byte import *
from byte import xSEndMsg, Auth_Chat
from xHeaders import *
from black9 import openroom, spmroom
import xKEys

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== ফ্লাস্ক অ্যাপ ====================
app = Flask(__name__)
CORS(app)

# ==================== গ্লোবাল ভেরিয়েবল ====================
connected_clients = {}
connected_clients_lock = threading.Lock()
active_spam_targets = {}
active_spam_lock = threading.Lock()
spam_threads = {}
spam_threads_lock = threading.Lock()

C = "\033[96m"
G = "\033[92m"
Y = "\033[93m"
R = "\033[91m"
RS = "\033[0m"
BOLD = "\033[1m"

AUTO_UID_FILE = "auto_uid.txt"

# ==================== Auto UID ফাইল ফাংশন ====================
def load_uids_from_file():
    try:
        with open(AUTO_UID_FILE, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip().isdigit()]
    except FileNotFoundError:
        return []

def save_uids_to_file(uids):
    with open(AUTO_UID_FILE, "w", encoding="utf-8") as f:
        for uid in uids:
            f.write(f"{uid}\n")

def add_uid_to_file(uid):
    uids = load_uids_from_file()
    if uid not in uids and len(uids) < 20:
        uids.append(uid)
        save_uids_to_file(uids)
        return True
    return False

def remove_uid_from_file(uid):
    uids = load_uids_from_file()
    if uid in uids:
        uids.remove(uid)
        save_uids_to_file(uids)
        return True
    return False

def clear_all_uids_from_file():
    save_uids_to_file([])

# ==================== স্প্যাম ফাংশন (Super Fast - 1 Second Gap) ====================
def spam_worker(target_id):
    print(f"\n{C}{'='*60}{RS}")
    print(f"{G}🎯 SPAM STARTED ON: {BOLD}{target_id}{RS}")
    print(f"{C}{'='*60}{RS}\n")
    
    add_console_log(f"🚀 SPAM STARTED ON: {target_id} (UNLIMITED MODE)", "success")

    total_requests = 0
    round_number = 0

    while True:
        with active_spam_lock:
            if target_id not in active_spam_targets:
                break

        with connected_clients_lock:
            clients_list = list(connected_clients.values())

        if not clients_list:
            time.sleep(0.5)
            continue

        round_number += 1
        round_requests = 0

        for client in clients_list:
            with active_spam_lock:
                if target_id not in active_spam_targets:
                    break

            account_id = getattr(client, 'id', 'Unknown')

            try:
                if (hasattr(client, 'CliEnts2') and client.CliEnts2 and
                    hasattr(client, 'key') and client.key and
                    hasattr(client, 'iv') and client.iv):

                    try:
                        open_pkt = openroom(client.key, client.iv)
                        if open_pkt:
                            client.CliEnts2.send(open_pkt)
                    except:
                        pass

                    for i in range(1, 101):
                        with active_spam_lock:
                            if target_id not in active_spam_targets:
                                break
                        try:
                            spam_pkt = spmroom(client.key, client.iv, target_id)
                            if spam_pkt:
                                client.CliEnts2.send(spam_pkt)
                                total_requests += 1
                                round_requests += 1
                                
                                if total_requests % 100 == 0:
                                    add_console_log(f"📊 {target_id}: {total_requests} total requests sent", "info")
                                    
                                time.sleep(1)
                                
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            with connected_clients_lock:
                                if account_id in connected_clients:
                                    del connected_clients[account_id]
                            add_console_log(f"❌ Client {account_id} disconnected", "error")
                            break
                        except:
                            break
            except:
                pass

        if round_requests > 0 and round_number % 10 == 0:
            add_console_log(f"📈 {target_id} - Round {round_number}: {round_requests} requests", "info")

    with spam_threads_lock:
        if target_id in spam_threads:
            del spam_threads[target_id]

    print(f"\n{R}{'='*50}{RS}")
    print(f"{R}🛑 SPAM STOPPED ON: {target_id}{RS}")
    print(f"{R}{'='*50}{RS}\n")
    add_console_log(f"🛑 SPAM STOPPED ON: {target_id} (Total: {total_requests} requests)", "error")

# Console log storage for web UI
console_logs = []
console_logs_lock = threading.Lock()

def add_console_log(message, log_type="info"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    with console_logs_lock:
        console_logs.append({
            'timestamp': timestamp,
            'message': message,
            'type': log_type
        })
        while len(console_logs) > 100:
            console_logs.pop(0)

def get_console_logs():
    with console_logs_lock:
        return console_logs.copy()

def clear_console_logs():
    with console_logs_lock:
        console_logs.clear()

def start_spam(target_id):
    with active_spam_lock:
        if target_id in active_spam_targets:
            return False, f"Already spamming on: {target_id}"
        active_spam_targets[target_id] = {
            'active': True,
            'start_time': datetime.now(),
        }

    thread = Thread(target=spam_worker, args=(target_id,), daemon=True)
    with spam_threads_lock:
        spam_threads[target_id] = thread
    thread.start()
    return True, f"Spam started on: {target_id}"

def stop_spam(target_id):
    with active_spam_lock:
        if target_id in active_spam_targets:
            del active_spam_targets[target_id]
            add_console_log(f"🛑 Stop command received for {target_id}", "error")
            return True, f"Spam stopped on: {target_id}"
        return False, f"No active spam on: {target_id}"

def stop_all_spam():
    with active_spam_lock:
        targets = list(active_spam_targets.keys())
        for target in targets:
            del active_spam_targets[target]
    add_console_log(f"🛑 Stopped all spam ({len(targets)} targets)", "error")
    return True, f"Stopped all spam ({len(targets)} targets)"

def get_status():
    with active_spam_lock:
        active_targets = list(active_spam_targets.keys())
        targets_info = []
        for target in active_targets:
            info = active_spam_targets[target]
            start_time = info.get('start_time')
            elapsed = (datetime.now() - start_time).total_seconds() if start_time else 0
            targets_info.append({
                'uid': target,
                'elapsed_minutes': int(elapsed / 60),
                'is_unlimited': True
            })
    
    with connected_clients_lock:
        accounts_count = len(connected_clients)
        accounts_list = list(connected_clients.keys())
    
    return {
        'active_targets': targets_info,
        'active_count': len(active_targets),
        'accounts_count': accounts_count,
        'accounts_list': accounts_list[:50]
    }

# ==================== অটো-রিফ্রেশ সিস্টেম (৭ মিনিট) ====================
auto_refresh_running = True
last_refresh_time = datetime.now()

def auto_refresh_spam():
    global auto_refresh_running, last_refresh_time
    while auto_refresh_running:
        time.sleep(7 * 60)
        last_refresh_time = datetime.now()
        
        add_console_log("🔄 Auto-refresh triggered (7 minutes) - Restarting all spam from file", "warning")
        
        uids = load_uids_from_file()
        
        with active_spam_lock:
            current_targets = list(active_spam_targets.keys())
            for target in current_targets:
                del active_spam_targets[target]
            add_console_log(f"🛑 Stopped {len(current_targets)} existing spam threads", "error")
        
        time.sleep(2)
        
        if uids:
            add_console_log(f"📋 Found {len(uids)} UIDs in file, restarting spam...", "info")
            for uid in uids:
                if uid not in active_spam_targets:
                    start_spam(uid)
                    add_console_log(f"🔄 Restarted spam on {uid} (from auto-refresh)", "success")
                    time.sleep(0.3)
        else:
            add_console_log("📭 No UIDs found in auto_uid.txt, skipping refresh", "warning")

refresh_thread = Thread(target=auto_refresh_spam, daemon=True)
refresh_thread.start()

# ==================== ফ্লাস্ক রাউট ====================
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/start', methods=['POST'])
def api_start():
    data = request.get_json()
    target_id = data.get('uid', '').strip()
    
    if not target_id:
        return jsonify({'success': False, 'message': 'UID is required'})
    
    if not target_id.isdigit():
        return jsonify({'success': False, 'message': 'UID must contain only numbers'})
    
    uids = load_uids_from_file()
    if len(uids) >= 20 and target_id not in uids:
        return jsonify({'success': False, 'message': f'Maximum 20 UIDs allowed. Current: {len(uids)}/20'})
    
    add_uid_to_file(target_id)
    success, message = start_spam(target_id)
    return jsonify({'success': success, 'message': message})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    data = request.get_json()
    target_id = data.get('uid', '').strip()
    
    if not target_id:
        return jsonify({'success': False, 'message': 'UID is required'})
    
    remove_uid_from_file(target_id)
    success, message = stop_spam(target_id)
    return jsonify({'success': success, 'message': message})

@app.route('/api/stop-all', methods=['POST'])
def api_stop_all():
    clear_all_uids_from_file()
    success, message = stop_all_spam()
    return jsonify({'success': success, 'message': message})

@app.route('/api/status', methods=['GET'])
def api_status():
    status = get_status()
    status['file_uids'] = load_uids_from_file()
    status['max_uids'] = 20
    status['next_refresh_seconds'] = max(0, 420 - (datetime.now() - last_refresh_time).total_seconds())
    return jsonify({'success': True, 'data': status})

@app.route('/api/accounts', methods=['GET'])
def api_accounts():
    with connected_clients_lock:
        return jsonify({
            'success': True,
            'count': len(connected_clients),
            'accounts': list(connected_clients.keys())
        })

@app.route('/api/logs', methods=['GET'])
def api_logs():
    return jsonify({
        'success': True,
        'logs': get_console_logs()
    })

@app.route('/api/clear-logs', methods=['POST'])
def api_clear_logs():
    clear_console_logs()
    return jsonify({'success': True, 'message': 'Logs cleared'})

# ==================== HTML টেমপ্লেট ====================
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NIROB SPAM - Ultimate Edition</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;600;800;900&family=Poppins:wght@300;400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;600;800;900&family=Poppins:wght@300;400;600;700;800&display=swap');
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Poppins', sans-serif;
            background: #0a0a0a;
            min-height: 100vh;
            overflow: hidden;
            position: relative;
        }

        /* === PREMIUM ANIMATED BACKGROUND === */
        .bg-canvas {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: -2;
        }

        .bg-canvas::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: 
                radial-gradient(circle at 20% 50%, rgba(0, 212, 255, 0.08) 0%, transparent 50%),
                radial-gradient(circle at 80% 50%, rgba(255, 51, 102, 0.06) 0%, transparent 50%),
                radial-gradient(circle at 50% 100%, rgba(255, 215, 0, 0.04) 0%, transparent 40%),
                linear-gradient(180deg, #0a0a0a 0%, #0a0a1a 30%, #0d0d2b 60%, #0a0a0a 100%);
        }

        .particle-container {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: -1;
            pointer-events: none;
            overflow: hidden;
        }

        .particle {
            position: absolute;
            width: 4px;
            height: 4px;
            background: radial-gradient(circle, rgba(0, 212, 255, 0.8), transparent);
            border-radius: 50%;
            animation: floatParticle linear infinite;
        }

        @keyframes floatParticle {
            0% {
                transform: translateY(100vh) translateX(0px) scale(0);
                opacity: 0;
            }
            10% {
                opacity: 1;
                transform: translateY(90vh) translateX(20px) scale(1);
            }
            90% {
                opacity: 1;
            }
            100% {
                transform: translateY(-10vh) translateX(-20px) scale(0.5);
                opacity: 0;
            }
        }

        .glow-orb {
            position: fixed;
            border-radius: 50%;
            filter: blur(100px);
            z-index: -1;
            animation: orbFloat 20s ease-in-out infinite;
        }

        .glow-orb-1 {
            width: 400px;
            height: 400px;
            background: rgba(0, 212, 255, 0.10);
            top: -100px;
            left: -100px;
            animation-delay: 0s;
        }

        .glow-orb-2 {
            width: 500px;
            height: 500px;
            background: rgba(255, 51, 102, 0.08);
            bottom: -150px;
            right: -150px;
            animation-delay: -10s;
        }

        .glow-orb-3 {
            width: 300px;
            height: 300px;
            background: rgba(255, 215, 0, 0.06);
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            animation-delay: -5s;
        }

        @keyframes orbFloat {
            0%, 100% { transform: translate(0, 0) scale(1); }
            33% { transform: translate(50px, -30px) scale(1.1); }
            66% { transform: translate(-30px, 40px) scale(0.9); }
        }

        /* === MATRIX RAIN === */
        #matrixCanvas {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: -1;
            opacity: 0.12;
        }

        /* === ENTER PAGE (SPLASH) === */
        .splash-screen {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.97);
            backdrop-filter: blur(20px);
            z-index: 9999;
            display: flex;
            justify-content: center;
            align-items: center;
            transition: all 0.8s cubic-bezier(0.34, 1.56, 0.64, 1);
        }

        .splash-screen.hidden {
            opacity: 0;
            pointer-events: none;
            transform: scale(1.05);
        }

        .splash-content {
            text-align: center;
            padding: 40px;
            max-width: 500px;
            width: 90%;
        }

        .splash-icon {
            font-size: 80px;
            margin-bottom: 20px;
            animation: iconPulse 2s ease-in-out infinite;
            display: inline-block;
        }

        @keyframes iconPulse {
            0%, 100% { transform: scale(1); text-shadow: 0 0 20px rgba(0, 212, 255, 0.3); }
            50% { transform: scale(1.05); text-shadow: 0 0 40px rgba(0, 212, 255, 0.6); }
        }

        .splash-title {
            font-family: 'Orbitron', monospace;
            font-size: 3.5rem;
            font-weight: 900;
            background: linear-gradient(135deg, #00d4ff, #ff3366, #ffd700, #00d4ff);
            background-size: 300% 300%;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: gradientMove 4s ease-in-out infinite;
            letter-spacing: 4px;
            margin-bottom: 15px;
        }

        @keyframes gradientMove {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        .splash-sub {
            color: rgba(255, 255, 255, 0.4);
            font-size: 0.9rem;
            letter-spacing: 6px;
            text-transform: uppercase;
            margin-bottom: 30px;
        }

        .splash-btn {
            background: linear-gradient(135deg, #00d4ff, #0088ff);
            border: none;
            padding: 16px 50px;
            font-size: 1.1rem;
            font-weight: 700;
            color: white;
            border-radius: 50px;
            cursor: pointer;
            transition: all 0.3s;
            position: relative;
            overflow: hidden;
            letter-spacing: 2px;
            box-shadow: 0 0 30px rgba(0, 212, 255, 0.3);
        }

        .splash-btn:hover {
            transform: scale(1.05);
            box-shadow: 0 0 50px rgba(0, 212, 255, 0.5);
        }

        .splash-btn::after {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: linear-gradient(45deg, transparent, rgba(255, 255, 255, 0.1), transparent);
            transform: rotate(45deg);
            animation: btnShine 3s ease-in-out infinite;
        }

        @keyframes btnShine {
            0% { transform: translateX(-100%) rotate(45deg); }
            100% { transform: translateX(100%) rotate(45deg); }
        }

        .splash-version {
            color: rgba(255, 255, 255, 0.2);
            font-size: 0.6rem;
            margin-top: 25px;
            letter-spacing: 3px;
        }

        /* === MAIN APP === */
        .app-container {
            max-width: 480px;
            margin: 0 auto;
            padding: 15px;
            height: 100vh;
            overflow-y: auto;
            padding-top: 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            position: relative;
            z-index: 1;
        }

        .app-container::-webkit-scrollbar {
            width: 3px;
        }
        .app-container::-webkit-scrollbar-track {
            background: transparent;
        }
        .app-container::-webkit-scrollbar-thumb {
            background: rgba(0, 212, 255, 0.3);
            border-radius: 10px;
        }

        /* === PREMIUM HEADER === */
        .premium-header {
            text-align: center;
            padding: 15px 0 5px 0;
            position: relative;
        }

        .header-title {
            font-family: 'Orbitron', monospace;
            font-size: 2.4rem;
            font-weight: 900;
            background: linear-gradient(135deg, #00d4ff, #ff3366, #ffd700, #00d4ff);
            background-size: 300% 300%;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: gradientMove 4s ease-in-out infinite;
            letter-spacing: 3px;
            line-height: 1.1;
        }

        .header-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(0, 212, 255, 0.15);
            border: 1px solid rgba(0, 212, 255, 0.3);
            padding: 4px 16px;
            border-radius: 30px;
            font-size: 0.6rem;
            color: #00d4ff;
            letter-spacing: 2px;
            text-transform: uppercase;
            margin-top: 5px;
        }

        .header-badge i {
            font-size: 0.5rem;
        }

        /* === GLASS CARDS === */
        .glass-card {
            background: rgba(15, 20, 40, 0.6);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-radius: 20px;
            padding: 18px 16px;
            border: 1px solid rgba(255, 255, 255, 0.06);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
            transition: all 0.3s;
        }

        .glass-card:hover {
            border-color: rgba(0, 212, 255, 0.15);
        }

        .card-flex {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
        }

        .card-icon {
            width: 40px;
            height: 40px;
            border-radius: 12px;
            background: linear-gradient(135deg, rgba(0, 212, 255, 0.2), rgba(0, 212, 255, 0.05));
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.1rem;
            color: #00d4ff;
            flex-shrink: 0;
        }

        .card-label {
            font-size: 0.65rem;
            color: rgba(255, 255, 255, 0.4);
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .card-title-text {
            font-size: 1rem;
            font-weight: 600;
            color: white;
        }

        /* === INPUTS === */
        .input-field {
            width: 100%;
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            padding: 14px 16px;
            color: white;
            font-size: 0.9rem;
            font-family: 'Poppins', sans-serif;
            outline: none;
            transition: all 0.3s;
        }

        .input-field:focus {
            border-color: rgba(0, 212, 255, 0.4);
            box-shadow: 0 0 20px rgba(0, 212, 255, 0.05);
        }

        .input-field::placeholder {
            color: rgba(255, 255, 255, 0.2);
        }

        /* === BUTTONS === */
        .btn {
            padding: 12px 20px;
            border: none;
            border-radius: 14px;
            font-weight: 700;
            font-size: 0.85rem;
            cursor: pointer;
            transition: all 0.3s;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            width: 100%;
            font-family: 'Poppins', sans-serif;
            letter-spacing: 0.5px;
        }

        .btn-primary {
            background: linear-gradient(135deg, #00d4ff, #0088ff);
            color: white;
            box-shadow: 0 4px 20px rgba(0, 212, 255, 0.25);
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 30px rgba(0, 212, 255, 0.35);
        }

        .btn-danger {
            background: linear-gradient(135deg, #ff3366, #cc0044);
            color: white;
            box-shadow: 0 4px 20px rgba(255, 51, 102, 0.2);
        }

        .btn-danger:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 30px rgba(255, 51, 102, 0.3);
        }

        .btn-gold {
            background: linear-gradient(135deg, #ffd700, #ff8c00);
            color: #000;
            box-shadow: 0 4px 20px rgba(255, 215, 0, 0.2);
        }

        .btn-gold:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 30px rgba(255, 215, 0, 0.3);
        }

        .btn-outline {
            background: transparent;
            border: 1px solid rgba(255, 255, 255, 0.15);
            color: rgba(255, 255, 255, 0.7);
        }

        .btn-outline:hover {
            background: rgba(255, 255, 255, 0.05);
            border-color: rgba(255, 255, 255, 0.3);
        }

        .btn-sm {
            padding: 8px 14px;
            font-size: 0.7rem;
            width: auto;
        }

        .btn-group {
            display: flex;
            gap: 10px;
            margin-top: 10px;
        }

        .btn-group .btn {
            flex: 1;
        }

        /* === UID LIST === */
        .uid-list {
            max-height: 160px;
            overflow-y: auto;
            margin-top: 8px;
        }

        .uid-list::-webkit-scrollbar {
            width: 3px;
        }
        .uid-list::-webkit-scrollbar-thumb {
            background: rgba(0, 212, 255, 0.3);
            border-radius: 10px;
        }

        .uid-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 12px;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 10px;
            margin-bottom: 4px;
            border-left: 2px solid rgba(0, 212, 255, 0.2);
            transition: all 0.2s;
        }

        .uid-item:hover {
            background: rgba(0, 0, 0, 0.5);
        }

        .uid-info {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .uid-num {
            font-family: 'Courier New', monospace;
            font-size: 0.75rem;
            color: white;
            font-weight: 600;
        }

        .uid-status {
            font-size: 0.5rem;
            padding: 2px 8px;
            border-radius: 20px;
            background: rgba(0, 204, 102, 0.2);
            color: #00cc66;
        }

        .uid-status.inactive {
            background: rgba(255, 51, 102, 0.2);
            color: #ff3366;
        }

        .uid-stop-btn {
            background: rgba(255, 51, 102, 0.15);
            border: none;
            color: #ff3366;
            padding: 4px 12px;
            border-radius: 8px;
            font-size: 0.6rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .uid-stop-btn:hover {
            background: #ff3366;
            color: white;
        }

        /* === CONSOLE === */
        .console-box {
            background: rgba(0, 0, 0, 0.7);
            border-radius: 14px;
            padding: 12px;
            height: 140px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
            font-size: 0.65rem;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .console-box::-webkit-scrollbar {
            width: 3px;
        }
        .console-box::-webkit-scrollbar-thumb {
            background: rgba(0, 212, 255, 0.3);
            border-radius: 10px;
        }

        .console-line {
            padding: 2px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
            color: rgba(255, 255, 255, 0.7);
        }

        .console-line .time {
            color: rgba(0, 212, 255, 0.5);
            margin-right: 10px;
        }

        .console-line .success { color: #00cc66; }
        .console-line .error { color: #ff3366; }
        .console-line .warning { color: #ffd700; }
        .console-line .info { color: #00d4ff; }

        /* === STATS === */
        .stats-row {
            display: flex;
            gap: 10px;
        }

        .stat-item {
            flex: 1;
            text-align: center;
            padding: 10px;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .stat-number {
            font-size: 1.5rem;
            font-weight: 800;
            color: #00d4ff;
            font-family: 'Orbitron', monospace;
        }

        .stat-label {
            font-size: 0.55rem;
            color: rgba(255, 255, 255, 0.4);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-top: 2px;
        }

        /* === STATUS BAR === */
        .status-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 12px;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 12px;
            border: 1px solid rgba(0, 204, 102, 0.15);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #00cc66;
            animation: statusPulse 1.5s ease-in-out infinite;
            display: inline-block;
        }

        @keyframes statusPulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.4; transform: scale(0.8); }
        }

        .status-text {
            font-size: 0.7rem;
            color: rgba(255, 255, 255, 0.6);
            font-weight: 500;
        }

        .status-text strong {
            color: #00cc66;
        }

        .refresh-timer {
            font-size: 0.6rem;
            color: rgba(255, 255, 255, 0.3);
            display: flex;
            align-items: center;
            gap: 5px;
        }

        .refresh-timer span {
            color: #ffd700;
            font-weight: 600;
        }

        /* === FOOTER === */
        .footer-text {
            text-align: center;
            font-size: 0.5rem;
            color: rgba(255, 255, 255, 0.15);
            letter-spacing: 3px;
            padding: 5px 0;
            text-transform: uppercase;
        }

        /* === RESPONSIVE === */
        @media (max-width: 480px) {
            .splash-title {
                font-size: 2.5rem;
            }
            .header-title {
                font-size: 1.8rem;
            }
            .app-container {
                padding: 10px;
                gap: 10px;
            }
            .glass-card {
                padding: 14px 12px;
            }
            .stats-row {
                flex-wrap: wrap;
            }
            .stat-item {
                min-width: 60px;
            }
            .btn-group {
                flex-wrap: wrap;
            }
            .btn-group .btn {
                flex: 1 1 45%;
            }
        }
    </style>
</head>
<body>

    <!-- ====== ANIMATED BACKGROUND ====== -->
    <div class="bg-canvas"></div>
    <div class="glow-orb glow-orb-1"></div>
    <div class="glow-orb glow-orb-2"></div>
    <div class="glow-orb glow-orb-3"></div>
    <canvas id="matrixCanvas"></canvas>
    <div class="particle-container" id="particleContainer"></div>

    <!-- ====== SPLASH / ENTER SCREEN ====== -->
    <div class="splash-screen" id="splashScreen">
        <div class="splash-content">
            <div class="splash-icon">
                <i class="fas fa-skull"></i>
            </div>
            <div class="splash-title">NIROB SPAM</div>
            <div class="splash-sub">Ultimate Power Tool</div>
            <button class="splash-btn" onclick="enterApp()">
                <i class="fas fa-arrow-right"></i> ENTER
            </button>
            <div class="splash-version">v3.0 • UNLIMITED EDITION</div>
        </div>
    </div>

    <!-- ====== MAIN APP ====== -->
    <div class="app-container" id="mainApp" style="display:none;">

        <!-- ====== HEADER ====== -->
        <div class="premium-header">
            <div class="header-title">NIROB SPAM</div>
            <div class="header-badge">
                <i class="fas fa-circle" style="color:#00cc66; font-size:0.4rem;"></i>
                SYSTEM ACTIVE
                <i class="fas fa-bolt" style="color:#ffd700;"></i>
            </div>
        </div>

        <!-- ====== SINGLE TARGET ====== -->
        <div class="glass-card">
            <div class="card-flex">
                <div class="card-icon"><i class="fas fa-bullseye"></i></div>
                <div>
                    <div class="card-label">Single Target</div>
                    <div class="card-title-text">Enter UID</div>
                </div>
            </div>
            <input type="text" id="targetUidInput" class="input-field" placeholder="Enter Game UID" inputmode="numeric">
            <div class="btn-group">
                <button class="btn btn-primary" onclick="startSpam()"><i class="fas fa-play"></i> START</button>
                <button class="btn btn-danger" onclick="stopSpam()"><i class="fas fa-stop"></i> STOP</button>
            </div>
        </div>

        <!-- ====== SAVED UIDs ====== -->
        <div class="glass-card">
            <div class="card-flex">
                <div class="card-icon"><i class="fas fa-list"></i></div>
                <div>
                    <div class="card-label">Saved UIDs</div>
                    <div class="card-title-text">Active Targets</div>
                </div>
                <div style="margin-left:auto; font-size:0.7rem; color:rgba(255,255,255,0.3);">
                    <span id="uidCount">0</span>/20
                </div>
            </div>
            <div class="uid-list" id="uidList"></div>
            <div class="btn-group" style="margin-top:10px;">
                <button class="btn btn-gold btn-sm" onclick="stopAllSpam()" style="width:100%;"><i class="fas fa-ban"></i> STOP ALL</button>
            </div>
        </div>

        <!-- ====== CONSOLE ====== -->
        <div class="glass-card">
            <div class="card-flex">
                <div class="card-icon"><i class="fas fa-terminal"></i></div>
                <div>
                    <div class="card-label">Live Console</div>
                    <div class="card-title-text">Attack Logs</div>
                </div>
            </div>
            <div class="console-box" id="consoleBox">
                <div class="console-line"><span class="time">[System]</span> <span class="info">NIROB SPAM LOADED</span></div>
                <div class="console-line"><span class="time">[System]</span> <span class="success">READY TO ATTACK</span></div>
            </div>
        </div>

        <!-- ====== STATS ====== -->
        <div class="glass-card">
            <div class="card-flex">
                <div class="card-icon"><i class="fas fa-chart-simple"></i></div>
                <div>
                    <div class="card-label">Statistics</div>
                    <div class="card-title-text">Live Status</div>
                </div>
            </div>
            <div class="stats-row">
                <div class="stat-item">
                    <div class="stat-number" id="activeTargetsCount">0</div>
                    <div class="stat-label">Attacks</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number" id="accountsCount">0</div>
                    <div class="stat-label">Bots</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number" id="totalRequests">0</div>
                    <div class="stat-label">Requests</div>
                </div>
            </div>
        </div>

        <!-- ====== STATUS BAR ====== -->
        <div class="status-bar">
            <div style="display:flex; align-items:center; gap:10px;">
                <span class="status-dot"></span>
                <span class="status-text"><strong>LIVE</strong> · READY</span>
            </div>
            <div class="refresh-timer">
                <i class="fas fa-rotate"></i> <span id="refreshTimer">07:00</span>
            </div>
        </div>

        <!-- ====== FOOTER ====== -->
        <div class="footer-text">NIROB SPAM · ULTIMATE EDITION</div>

    </div>

    <script>
        // =============================================
        //  SPLASH / ENTER
        // =============================================
        function enterApp() {
            const splash = document.getElementById('splashScreen');
            const app = document.getElementById('mainApp');
            splash.classList.add('hidden');
            setTimeout(() => {
                splash.style.display = 'none';
                app.style.display = 'flex';
                app.style.flexDirection = 'column';
                app.style.gap = '12px';
            }, 800);
        }

        // =============================================
        //  PARTICLES
        // =============================================
        (function createParticles() {
            const container = document.getElementById('particleContainer');
            const colors = ['rgba(0,212,255,0.6)', 'rgba(255,51,102,0.4)', 'rgba(255,215,0,0.4)'];
            for (let i = 0; i < 30; i++) {
                const p = document.createElement('div');
                p.className = 'particle';
                p.style.left = Math.random() * 100 + '%';
                p.style.width = (Math.random() * 4 + 2) + 'px';
                p.style.height = p.style.width;
                p.style.animationDuration = (10 + Math.random() * 20) + 's';
                p.style.animationDelay = (Math.random() * 20) + 's';
                p.style.background = colors[Math.floor(Math.random() * colors.length)];
                container.appendChild(p);
            }
        })();

        // =============================================
        //  MATRIX CANVAS
        // =============================================
        const canvas = document.getElementById('matrixCanvas');
        const ctx = canvas.getContext('2d');
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        const chars = 'NIROBSPAM0123456789@#$%&*'.split('');
        const fontSize = 12;
        const columns = canvas.width / fontSize;
        const drops = Array(Math.floor(columns)).fill(1);

        function drawMatrix() {
            ctx.fillStyle = 'rgba(0, 0, 0, 0.04)';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = '#00d4ff';
            ctx.font = fontSize + 'px monospace';
            ctx.shadowBlur = 0;
            for (let i = 0; i < drops.length; i++) {
                const text = chars[Math.floor(Math.random() * chars.length)];
                ctx.fillText(text, i * fontSize, drops[i] * fontSize);
                if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) {
                    drops[i] = 0;
                }
                drops[i]++;
            }
        }
        setInterval(drawMatrix, 50);

        window.addEventListener('resize', () => {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
        });

        // =============================================
        //  CONSOLE LOG
        // =============================================
        function logToConsole(message, type = 'info') {
            const consoleBox = document.getElementById('consoleBox');
            const now = new Date();
            const h = String(now.getHours()).padStart(2, '0');
            const m = String(now.getMinutes()).padStart(2, '0');
            const s = String(now.getSeconds()).padStart(2, '0');
            const timeStr = h + ':' + m + ':' + s;
            const line = document.createElement('div');
            line.className = 'console-line';
            line.innerHTML = `<span class="time">[${timeStr}]</span> <span class="${type}">${message}</span>`;
            consoleBox.appendChild(line);
            consoleBox.scrollTop = consoleBox.scrollHeight;
            if (consoleBox.children.length > 60) {
                consoleBox.removeChild(consoleBox.firstChild);
            }
        }

        // =============================================
        //  TOAST (simple)
        // =============================================
        function showToast(msg, isError = false) {
            // brief console indication
            logToConsole(msg, isError ? 'error' : 'success');
        }

        // =============================================
        //  API FUNCTIONS
        // =============================================
        async function startSpam() {
            const uid = document.getElementById('targetUidInput').value.trim();
            if (!uid) {
                logToConsole('❌ Please enter a target UID!', 'error');
                return;
            }
            if (!/^\d+$/.test(uid)) {
                logToConsole('❌ UID must contain only numbers!', 'error');
                return;
            }
            try {
                const res = await fetch('/api/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ uid: uid })
                });
                const data = await res.json();
                if (data.success) {
                    logToConsole(`✅ ${data.message}`, 'success');
                    document.getElementById('targetUidInput').value = '';
                    loadUIDList();
                    updateStatus();
                } else {
                    logToConsole(`❌ ${data.message}`, 'error');
                }
            } catch (e) {
                logToConsole(`❌ Network error: ${e.message}`, 'error');
            }
        }

        async function stopSpam() {
            const uid = document.getElementById('targetUidInput').value.trim();
            if (!uid) {
                logToConsole('❌ Enter UID to stop!', 'error');
                return;
            }
            try {
                const res = await fetch('/api/stop', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ uid: uid })
                });
                const data = await res.json();
                if (data.success) {
                    logToConsole(`🛑 ${data.message}`, 'error');
                    document.getElementById('targetUidInput').value = '';
                    loadUIDList();
                    updateStatus();
                } else {
                    logToConsole(`⚠️ ${data.message}`, 'warning');
                }
            } catch (e) {
                logToConsole(`❌ Network error: ${e.message}`, 'error');
            }
        }

        async function stopAllSpam() {
            try {
                const res = await fetch('/api/stop-all', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    logToConsole(`🛑 ${data.message}`, 'error');
                    loadUIDList();
                    updateStatus();
                }
            } catch (e) {
                logToConsole(`❌ Network error: ${e.message}`, 'error');
            }
        }

        async function stopUid(uid) {
            try {
                const res = await fetch('/api/stop', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ uid: uid })
                });
                const data = await res.json();
                if (data.success) {
                    logToConsole(`🛑 Stopped: ${uid}`, 'error');
                    loadUIDList();
                    updateStatus();
                }
            } catch (e) {
                logToConsole(`❌ Error: ${e.message}`, 'error');
            }
        }

        // =============================================
        //  LOAD UID LIST
        // =============================================
        async function loadUIDList() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                if (data.success && data.data.file_uids) {
                    const uids = data.data.file_uids;
                    document.getElementById('uidCount').innerText = uids.length;
                    const container = document.getElementById('uidList');
                    if (uids.length === 0) {
                        container.innerHTML = '<div style="text-align:center; color:rgba(255,255,255,0.2); font-size:0.7rem; padding:10px;">No UIDs saved</div>';
                    } else {
                        container.innerHTML = uids.map(uid => `
                            <div class="uid-item">
                                <div class="uid-info">
                                    <span class="uid-num">${uid}</span>
                                    <span class="uid-status">● ACTIVE</span>
                                </div>
                                <button class="uid-stop-btn" onclick="stopUid('${uid}')">STOP</button>
                            </div>
                        `).join('');
                    }
                }
            } catch (e) {
                console.error('Load UIDs error:', e);
            }
        }

        // =============================================
        //  UPDATE STATUS
        // =============================================
        async function updateStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                if (data.success) {
                    const s = data.data;
                    document.getElementById('activeTargetsCount').innerText = s.active_count || 0;
                    document.getElementById('accountsCount').innerText = s.accounts_count || 0;
                    document.getElementById('totalRequests').innerText = s.active_count * 100 || 0;
                    if (s.next_refresh_seconds !== undefined) {
                        const mins = Math.floor(s.next_refresh_seconds / 60);
                        const secs = Math.floor(s.next_refresh_seconds % 60);
                        document.getElementById('refreshTimer').innerText =
                            String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
                    }
                }
            } catch (e) {
                console.error('Status update error:', e);
            }
        }

        // =============================================
        //  FETCH LOGS
        // =============================================
        async function fetchLogs() {
            try {
                const res = await fetch('/api/logs');
                const data = await res.json();
                if (data.success && data.logs.length > 0) {
                    const box = document.getElementById('consoleBox');
                    // only update if new logs
                    const lastLog = data.logs[data.logs.length - 1];
                    const existing = box.querySelectorAll('.console-line');
                    if (existing.length > 0) {
                        const lastExisting = existing[existing.length - 1];
                        const lastTime = lastExisting.querySelector('.time');
                        if (lastTime && lastTime.textContent.includes(lastLog.timestamp)) {
                            return;
                        }
                    }
                    box.innerHTML = data.logs.map(log => `
                        <div class="console-line">
                            <span class="time">[${log.timestamp}]</span>
                            <span class="${log.type}">${log.message}</span>
                        </div>
                    `).join('');
                    box.scrollTop = box.scrollHeight;
                }
            } catch (e) {
                console.error('Log fetch error:', e);
            }
        }

        // =============================================
        //  AUTO REFRESH
        // =============================================
        setInterval(updateStatus, 2000);
        setInterval(fetchLogs, 1000);
        setInterval(loadUIDList, 3000);

        // Initial load
        setTimeout(() => {
            updateStatus();
            loadUIDList();
            logToConsole('💀 SYSTEM READY', 'success');
            logToConsole('🎯 Enter UID to start attack', 'info');
        }, 500);

        // Enter key support
        document.getElementById('targetUidInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') startSpam();
        });
    </script>

</body>
</html>
'''

# ==================== অ্যাকাউন্ট লোড ====================
ACCOUNTS = []

def load_accounts_from_file(filename="accs.txt"):
    accounts = []
    try:
        with open(filename, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith("#"):
                    if ":" in line:
                        parts = line.split(":")
                        accounts.append({'id': parts[0].strip(), 'password': parts[1].strip()})
                    else:
                        accounts.append({'id': line.strip(), 'password': ''})
        print(f"{G}📦 Loaded {len(accounts)} accounts{RS}")
        add_console_log(f"📦 Loaded {len(accounts)} accounts from accs.txt", "success")
    except FileNotFoundError:
        print(f"{Y}⚠️ accs.txt not found! Creating sample file...{RS}")
        with open(filename, "w") as f:
            f.write("# accs.txt - Format: UID:PASSWORD\n")
            f.write("# Example: 4575104506:password123\n")
            f.write("4575104506:examplepass\n")
        add_console_log("⚠️ accs.txt created, please add your accounts", "warning")
    return accounts

ACCOUNTS = load_accounts_from_file()

def start_spam_from_file():
    uids = load_uids_from_file()
    if uids:
        add_console_log(f"📋 Loading {len(uids)} UIDs from auto_uid.txt", "info")
        for uid in uids:
            start_spam(uid)
            add_console_log(f"🚀 Started spam on {uid} (from file)", "success")
            time.sleep(0.5)

# ==================== FF Client ====================
class FF_CLient():
    def __init__(self, id, password):
        self.id = id
        self.password = password
        self.key = None
        self.iv = None
        add_console_log(f"🔐 Initializing account: {id}", "info")
        self.Get_FiNal_ToKen_0115()

    def Connect_SerVer_OnLine(self, Token, tok, host, port, key, iv, host2, port2):
        try:
            self.AutH_ToKen_0115 = tok    
            self.CliEnts2 = socket.create_connection((host2, int(port2)))
            self.CliEnts2.send(bytes.fromhex(self.AutH_ToKen_0115))
            with connected_clients_lock:
                if self.id not in connected_clients:
                    connected_clients[self.id] = self
                    print(f"{G}✅ Online: {self.id} (Total: {len(connected_clients)}){RS}")
                    add_console_log(f"✅ Account {self.id} is now ONLINE", "success")
        except Exception as e:
            print(f"{R}❌ Online error {self.id}: {e}{RS}")
            add_console_log(f"❌ Online error {self.id}: {e}", "error")
            return
        while True:
            try:
                self.DaTa2 = self.CliEnts2.recv(99999)
                if '0500' in self.DaTa2.hex()[0:4] and len(self.DaTa2.hex()) > 30:
                    self.packet = json.loads(DeCode_PackEt(f'08{self.DaTa2.hex().split("08", 1)[1]}'))
                    self.AutH = self.packet['5']['data']['7']['data']
            except: pass
                                                            
    def Connect_SerVer(self, Token, tok, host, port, key, iv, host2, port2):
        self.AutH_ToKen_0115 = tok    
        self.CliEnts = socket.create_connection((host, int(port)))
        self.CliEnts.send(bytes.fromhex(self.AutH_ToKen_0115))  
        self.DaTa = self.CliEnts.recv(1024)          	        
        threading.Thread(target=self.Connect_SerVer_OnLine, args=(Token, tok, host, port, key, iv, host2, port2)).start()
        try: self.Exemple = xMsGFixinG('12345678')
        except: pass
        self.key = key
        self.iv = iv
        with connected_clients_lock:
            if self.id not in connected_clients:
                connected_clients[self.id] = self
                print(f"{G}✅ Registered: {self.id}{RS}")
                add_console_log(f"✅ Account {self.id} registered successfully", "success")
        while True:      
            try:
                self.DaTa = self.CliEnts.recv(1024)   
                if len(self.DaTa) == 0 or (hasattr(self, 'DaTa2') and len(self.DaTa2) == 0):
                    try:
                        self.CliEnts.close()
                        if hasattr(self, 'CliEnts2'): self.CliEnts2.close()
                        self.Connect_SerVer(Token, tok, host, port, key, iv, host2, port2)                    		                    
                    except:
                        try:
                            self.CliEnts.close()
                            if hasattr(self, 'CliEnts2'): self.CliEnts2.close()
                            self.Connect_SerVer(Token, tok, host, port, key, iv, host2, port2)
                        except:
                            self.CliEnts.close()
                            if hasattr(self, 'CliEnts2'): self.CliEnts2.close()
                            ResTarT_BoT()	            
            except Exception as e:
                print(f"{R}❌ Connection error {self.id}: {e}{RS}")
                add_console_log(f"❌ Connection error {self.id}: {e}", "error")
                with connected_clients_lock:
                    if self.id in connected_clients: del connected_clients[self.id]
                self.Connect_SerVer(Token, tok, host, port, key, iv, host2, port2)
                                    
    def GeT_Key_Iv(self, serialized_data):
        my_message = xKEys.MyMessage()
        my_message.ParseFromString(serialized_data)
        timestamp, key, iv = my_message.field21, my_message.field22, my_message.field23
        timestamp_obj = Timestamp()
        timestamp_obj.FromNanoseconds(timestamp)
        timestamp_seconds = timestamp_obj.seconds
        timestamp_nanos = timestamp_obj.nanos
        combined_timestamp = timestamp_seconds * 1_000_000_000 + timestamp_nanos
        return combined_timestamp, key, iv    

    def Guest_GeneRaTe(self, uid, password):
        self.url = "https://100067.connect.garena.com/oauth/guest/token/grant"
        self.headers = {
            "Host": "100067.connect.garena.com",
            "User-Agent": "GarenaMSDK/4.0.19P4(G011A ;Android 9;en;US;)",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "close",
        }
        self.dataa = {
            "uid": f"{uid}",
            "password": f"{password}",
            "response_type": "token",
            "client_type": "2",
            "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
            "client_id": "100067",
        }
        try:
            self.response = requests.post(self.url, headers=self.headers, data=self.dataa).json()
            self.Access_ToKen, self.Access_Uid = self.response['access_token'], self.response['open_id']
            time.sleep(0.2)
            print(f'{C}🔐 Login: {self.id}{RS}')
            return self.ToKen_GeneRaTe(self.Access_ToKen, self.Access_Uid)
        except Exception as e: 
            print(f"{R}❌ Login error {self.id}: {e}{RS}")
            add_console_log(f"❌ Login error {self.id}: {e}", "error")
            time.sleep(10)
            return self.Guest_GeneRaTe(uid, password)
                                        
    def GeT_LoGin_PorTs(self, JwT_ToKen, PayLoad, dynamic_url="https://clientbp.ggpolarbear.com"):
        self.UrL = f'{dynamic_url}/GetLoginData'
        self.HeadErs = {
            'Expect': '100-continue',
            'Authorization': f'Bearer {JwT_ToKen}',
            'X-Unity-Version': '2022.3.47f1',
            'X-GA': 'v1 1',
            'ReleaseVersion': 'OB54',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'UnityPlayer/2022.3.47f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
            'Connection': 'close',
            'Accept-Encoding': 'deflate, gzip',
        }        
        try:
            self.Res = requests.post(self.UrL, headers=self.HeadErs, data=PayLoad, verify=False)
            self.BesTo_data = json.loads(DeCode_PackEt(self.Res.content.hex()))  
            address, address2 = self.BesTo_data['32']['data'], self.BesTo_data['14']['data'] 
            ip, ip2 = address[:len(address) - 6], address2[:len(address2) - 6]
            port, port2 = address[len(address) - 5:], address2[len(address2) - 5:]             
            return ip, port, ip2, port2          
        except Exception as e:
            print(f"{R}❌ Failed to get ports: {e}{RS}")
            add_console_log(f"❌ Failed to get ports: {e}", "error")
        return None, None, None, None
        
    def ToKen_GeneRaTe(self, Access_ToKen, Access_Uid):
        self.UrL = "https://loginbp.ggwhitehawk.com/MajorLogin"
        self.HeadErs = {
            'X-Unity-Version': '2022.3.47f1',
            'ReleaseVersion': 'OB54',
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-GA': 'v1 1',
            'Content-Length': '928',
            'User-Agent': 'UnityPlayer/2022.3.47f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
            'Host': 'loginbp.ggwhitehawk.com',
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'deflate, gzip'
        }   
        
        self.dT = bytes.fromhex('1a13323032352d31312d32362030313a35313a3238220966726565206669726528013a07312e3132362e314232416e64726f6964204f532039202f204150492d3238202850492f72656c2e636a772e32303232303531382e313134313333294a0848616e6468656c64520c4d544e2f537061636574656c5a045749464960800a68d00572033234307a2d7838362d3634205353453320535345342e3120535345342e32204156582041565832207c2032343030207c20348001e61e8a010f416472656e6f2028544d292036343092010d4f70656e474c20455320332e329a012b476f6f676c657c36323566373136662d393161372d343935622d396631362d303866653964336336353333a2010e3137362e32382e3133392e313835aa01026172b201203433303632343537393364653836646134323561353263616164663231656564ba010134c2010848616e6468656c64ca010d4f6e65506c7573204135303130ea014063363961653230386661643732373338623637346232383437623530613361316466613235643161313966616537343566633736616334613065343134633934f00101ca020c4d544e2f537061636574656cd2020457494649ca03203161633462383065636630343738613434323033626638666163363132306635e003b5ee02e8039a8002f003af13f80384078004a78f028804b5ee029004a78f029804b5ee02b00404c80401d2043d2f646174612f6170702f636f6d2e6474732e667265656669726574682d66705843537068495636644b43376a4c2d574f7952413d3d2f6c69622f61726de00401ea045f65363261623933353464386662356662303831646233333861636233333439317c2f646174612f6170702f636f6d2e6474732e667265656669726574682d66705843537068495636644b43376a4c2d574f7952413d3d2f626173652e61706bf00406f804018a050233329a050a32303139313139303236a80503b205094f70656e474c455332b805ff01c00504e005be7eea05093372645f7061727479f205704b717348543857393347646347335a6f7a454e6646775648746d377171316552554e6149444e67526f626f7a4942744c4f695943633459367a767670634943787a514632734f453463627974774c7334785a62526e70524d706d5752514b6d654f35766373386e51594268777148374bf805e7e4068806019006019a060134a2060134b2062213521146500e590349510e460900115843395f005b510f685b560a6107576d0f0366')
        
        self.dT = self.dT.replace(b'2025-07-30 14:11:20', str(datetime.now())[:-7].encode())
        self.dT = self.dT.replace(b'c69ae208fad72738b674b2847b50a3a1dfa25d1a19fae745fc76ac4a0e414c94', Access_ToKen.encode())
        self.dT = self.dT.replace(b'4306245793de86da425a52caadf21eed', Access_Uid.encode())
        
        try:
            hex_data = self.dT.hex()
            encoded_data = EnC_AEs(hex_data)
            if not all(c in '0123456789abcdefABCDEF' for c in encoded_data):
                encoded_data = hex_data
            self.PaYload = bytes.fromhex(encoded_data)
        except Exception as e:
            print(f"{R}❌ Encoding error: {e}{RS}")
            self.PaYload = self.dT
        
        self.ResPonse = requests.post(self.UrL, headers=self.HeadErs, data=self.PaYload, verify=False)        
        if self.ResPonse.status_code == 200 and len(self.ResPonse.text) > 10:
            try:
                self.BesTo_data = json.loads(DeCode_PackEt(self.ResPonse.content.hex()))
                self.JwT_ToKen = self.BesTo_data['8']['data']           
                self.combined_timestamp, self.key, self.iv = self.GeT_Key_Iv(self.ResPonse.content)
                ip, port, ip2, port2 = self.GeT_LoGin_PorTs(self.JwT_ToKen, self.PaYload)            
                return self.JwT_ToKen, self.key, self.iv, self.combined_timestamp, ip, port, ip2, port2
            except Exception as e:
                print(f"{R}❌ Response parsing error: {e}{RS}")
                time.sleep(5)
                return self.ToKen_GeneRaTe(Access_ToKen, Access_Uid)
        else:
            print(f"{R}❌ Token generation error, status: {self.ResPonse.status_code}{RS}")
            time.sleep(5)
            return self.ToKen_GeneRaTe(Access_ToKen, Access_Uid)
      
    def Get_FiNal_ToKen_0115(self):
        try:
            result = self.Guest_GeneRaTe(self.id, self.password)
            if not result:
                print(f"{Y}⚠️ Failed to get token {self.id}, retrying...{RS}")
                time.sleep(5)
                return self.Get_FiNal_ToKen_0115()
                
            token, key, iv, Timestamp, ip, port, ip2, port2 = result
            
            if not all([ip, port, ip2, port2]):
                print(f"{Y}⚠️ Failed to get ports {self.id}, retrying...{RS}")
                time.sleep(5)
                return self.Get_FiNal_ToKen_0115()
                
            self.JwT_ToKen = token        
            try:
                self.AfTer_DeC_JwT = jwt.decode(token, options={"verify_signature": False})
                self.AccounT_Uid = self.AfTer_DeC_JwT.get('account_id')
                self.EncoDed_AccounT = hex(self.AccounT_Uid)[2:]
                self.HeX_VaLue = DecodE_HeX(Timestamp)
                self.TimE_HEx = self.HeX_VaLue
                self.JwT_ToKen_ = token.encode().hex()
                print(f'{C}🆔 Account UID: {self.AccounT_Uid}{RS}')
            except Exception as e:
                print(f"{R}❌ Token decode error {self.id}: {e}{RS}")
                time.sleep(5)
                return self.Get_FiNal_ToKen_0115()
                
            try:
                self.Header = hex(len(EnC_PacKeT(self.JwT_ToKen_, key, iv)) // 2)[2:]
                length = len(self.EncoDed_AccounT)
                self.__ = '00000000'
                if length == 9: self.__ = '0000000'
                elif length == 8: self.__ = '00000000'
                elif length == 10: self.__ = '000000'
                elif length == 7: self.__ = '000000000'
                self.Header = f'0115{self.__}{self.EncoDed_AccounT}{self.TimE_HEx}00000{self.Header}'
                self.FiNal_ToKen_0115 = self.Header + EnC_PacKeT(self.JwT_ToKen_, key, iv)
            except Exception as e:
                print(f"{R}❌ Final token error {self.id}: {e}{RS}")
                time.sleep(5)
                return self.Get_FiNal_ToKen_0115()
                
            self.AutH_ToKen = self.FiNal_ToKen_0115
            self.Connect_SerVer(self.JwT_ToKen, self.AutH_ToKen, ip, port, key, iv, ip2, port2)        
            return self.AutH_ToKen, key, iv
            
        except Exception as e:
            print(f"{R}❌ {self.id} connection failed: {e}{RS}")
            add_console_log(f"❌ {self.id} connection failed: {e}", "error")
            time.sleep(10)
            return self.Get_FiNal_ToKen_0115()

def start_account(account):
    try:
        print(f"{G}🚀 Starting: {account['id']}{RS}")
        add_console_log(f"🚀 Starting account: {account['id']}", "info")
        FF_CLient(account['id'], account['password'])
    except Exception as e:
        print(f"{R}❌ {account['id']} failed: {e}{RS}")
        add_console_log(f"❌ {account['id']} failed: {e}", "error")
        time.sleep(5)
        start_account(account)

def run_accounts():
    add_console_log("📡 Starting all accounts...", "info")
    for account in ACCOUNTS:
        Thread(target=start_account, args=(account,), daemon=True).start()
        time.sleep(2)
    add_console_log(f"✅ All {len(ACCOUNTS)} accounts started", "success")

# ==================== মেইন ====================
def main():
    Thread(target=run_accounts, daemon=True).start()
    
    time.sleep(5)
    start_spam_from_file()
    
    port = int(os.environ.get("PORT", 5000))
    
    print(f"""
    {C}{BOLD}
    ╔══════════════════════════════════════════════════════════════════╗
    ║                    🎯 NIROB POWER SPAM SYSTEM 🎯                 ║
    ║                                                                  ║
    ║     ✅ UNLIMITED SPAM MODE - FULLY AUTOMATED                     ║
    ║     ✅ VIP DARK THEME WITH ANIMATED BACKGROUND                   ║
    ║     ✅ MULTI-TARGET (MAX 20 UIDs)                                ║
    ║     ✅ AUTO-SAVE TO FILE & AUTO-REFRESH (7 MIN)                  ║
    ║     ✅ SUPER FAST SPAM (1 SECOND GAP)                           ║
    ║     ✅ ENTER SPLASH SCREEN WITH ANIMATION                        ║
    ║                                                                  ║
    ║     🌐 Web Panel: http://127.0.0.1:{port}                        ║
    ║     👑 Developer: NIROB                                          ║
    ║     💀 STATUS: SYSTEM ACTIVE                                     ║
    ╚══════════════════════════════════════════════════════════════════╝
    {RS}
    """)
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

if __name__ == "__main__":
    main()