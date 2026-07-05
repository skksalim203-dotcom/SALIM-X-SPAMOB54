import os, sys, time, json, ssl, socket, threading, asyncio, base64, binascii, re, jwt, pickle, random
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from flask import Flask, request, jsonify, render_template_string

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

# ==================== গ্লোবাল ভেরিয়েবল ====================
connected_clients = {}
connected_clients_lock = threading.Lock()
active_power_targets = {}
active_power_lock = threading.Lock()
spam_threads = {}
spam_threads_lock = threading.Lock()
auto_uids = []      # auto_uid.txt - SMART MONITORED (স্ট্যাটাস দেখে অটো স্প্যাম)
invite_uids = []    # inv_uid.txt - ACTIVE TARGETS (সরাসরি স্প্যাম)
auto_spam_active = False
auto_spam_thread = None
refresh_timer = None
target_status_cache = {}
smart_target_statuses = {}
smart_monitor_threads = {}
smart_monitor_lock = threading.Lock()
target_group_leaders = {}
active_invite_targets = {}  # inv_uid.txt এর জন্য সক্রিয় টার্গেট
invite_spam_thread = None

C = "\033[96m"
G = "\033[92m"
Y = "\033[93m"
R = "\033[91m"
RS = "\033[0m"
BOLD = "\033[1m"

_ID = '4575104506'
_PW = 'TORIKUL_TORIKUL_E6H3H'

# ==================== ব্যাজ ভ্যালু ====================
BADGES = {
    "V_BADGE": 32768,
    "PRO_BADGE": 262144,
    "CRAFTLAND": 1048576,
    "MODERATOR": 2048,
    "SMALL_V": 64,
}

# ==================== GROUP INVITE CONFIG ====================
GROUP_CONFIGS = {
    3: {"type": 1, "players": 3},
    5: {"type": 2, "players": 5},
    6: {"type": 3, "players": 6}
}

# ==================== FILE LOADERS ====================
def load_invite_uids(filename="inv_uid.txt"):
    """Load UIDs from inv_uid.txt - এগুলো সরাসরি ACTIVE TARGETS হিসেবে স্প্যাম পাবে"""
    global invite_uids
    uids = []
    try:
        with open(filename, "r", encoding="utf-8") as file:
            for line in file:
                uid = line.strip()
                if uid and not uid.startswith("#") and uid.isdigit():
                    uids.append(uid)
        invite_uids = uids
        print(f"{G}📦 Loaded {len(invite_uids)} ACTIVE TARGETS from inv_uid.txt{RS}")
    except FileNotFoundError:
        print(f"{Y}⚠️ inv_uid.txt not found! Creating...{RS}")
        with open(filename, "w") as f:
            f.write("# ACTIVE TARGETS - These UIDs will be spammed directly\n")
            f.write("# Example:\n")
            f.write("# 1234567890\n")
            f.write("# 0987654321\n")
        invite_uids = []
    return invite_uids

def save_invite_uids(uids):
    """Save UIDs to inv_uid.txt"""
    try:
        with open("inv_uid.txt", "w", encoding="utf-8") as file:
            file.write("# ACTIVE TARGETS - These UIDs will be spammed directly\n")
            file.write("# Example:\n")
            for uid in uids:
                file.write(f"{uid}\n")
        global invite_uids
        invite_uids = uids
        # নতুন UIDs যোগ করলে স্প্যাম শুরু করুন
        if uids and not auto_spam_active:
            start_invite_targets_spam()
    except Exception as e:
        print(f"{R}❌ Failed to save inv_uid.txt: {e}{RS}")

def load_auto_uids(filename="auto_uid.txt"):
    """Load UIDs from auto_uid.txt - এগুলো SMART MONITORED (স্ট্যাটাস দেখে স্প্যাম)"""
    global auto_uids
    uids = []
    try:
        with open(filename, "r", encoding="utf-8") as file:
            for line in file:
                uid = line.strip()
                if uid and not uid.startswith("#") and uid.isdigit():
                    uids.append(uid)
        auto_uids = uids
        print(f"{G}📦 Loaded {len(auto_uids)} SMART MONITORED UIDs from auto_uid.txt{RS}")
    except FileNotFoundError:
        print(f"{Y}⚠️ auto_uid.txt not found! Creating...{RS}")
        with open(filename, "w") as f:
            f.write("# SMART MONITORED UIDs - Status based auto spam\n")
            f.write("# Example:\n")
            f.write("# 1234567890\n")
            f.write("# 0987654321\n")
        auto_uids = []
    return auto_uids

def save_auto_uids(uids):
    """Save UIDs to auto_uid.txt"""
    try:
        with open("auto_uid.txt", "w", encoding="utf-8") as file:
            file.write("# SMART MONITORED UIDs - Status based auto spam\n")
            file.write("# Example:\n")
            for uid in uids:
                file.write(f"{uid}\n")
    except Exception as e:
        print(f"{R}❌ Failed to save auto_uid.txt: {e}{RS}")

# ==================== INVITE TARGETS SPAM WORKER ====================
def invite_targets_spam_worker():
    """inv_uid.txt এর UID গুলোতে সরাসরি স্প্যাম পাঠানোর জন্য ওয়ার্কার"""
    global auto_spam_active
    
    print(f"\n{G}{'='*60}{RS}")
    print(f"{G}🎯 ACTIVE TARGETS SPAM STARTED ON {len(invite_uids)} TARGETS:{RS}")
    for tid in invite_uids:
        print(f"{G}   ➤ {tid} (ACTIVE TARGET){RS}")
    print(f"{C}{'='*60}{RS}\n")

    total_requests = 0
    round_number = 0

    def run_async(coro):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        except:
            return None
        finally:
            loop.close()

    while auto_spam_active:
        with connected_clients_lock:
            clients_list = list(connected_clients.values())

        if not clients_list:
            time.sleep(2)
            continue

        round_number += 1

        for target_id in invite_uids:
            for client in clients_list:
                try:
                    if hasattr(client, 'CliEnts2') and client.key:
                        # === 1. রুম স্প্যাম ===
                        try:
                            open_pkt = openroom(client.key, client.iv)
                            if open_pkt:
                                client.CliEnts2.send(open_pkt)
                            
                            spam_pkt = spmroom(client.key, client.iv, target_id)
                            if spam_pkt:
                                client.CliEnts2.send(spam_pkt)
                                total_requests += 1
                        except:
                            pass

                        # === 2. গ্রুপ ইনভাইট (3/5/6 প্লেয়ার) ===
                        for players in [3, 5, 6]:
                            try:
                                async def send_invite():
                                    p1 = await OpEnSq(client.key, client.iv)
                                    client.CliEnts2.send(p1)
                                    await asyncio.sleep(0.05)
                                    p2 = await cHSq(players, target_id, client.key, client.iv)
                                    client.CliEnts2.send(p2)
                                    await asyncio.sleep(0.05)
                                    p3 = await SEnd_InV(players, target_id, client.key, client.iv)
                                    client.CliEnts2.send(p3)
                                    total_requests += 1
                                    await asyncio.sleep(0.05)
                                    p4 = await ExiT(client.key, client.iv)
                                    client.CliEnts2.send(p4)
                                run_async(send_invite())
                            except:
                                pass

                        # === 3. ব্যাজ জয়িন ===
                        for badge_name, badge_value in BADGES.items():
                            try:
                                badge_pkt = create_badge_join_packet(client.key, client.iv, target_id, badge_value)
                                if badge_pkt:
                                    client.CliEnts2.send(badge_pkt)
                                    total_requests += 1
                                    time.sleep(0.03)
                            except:
                                pass

                except Exception as e:
                    print(f"{R}❌ Error: {e}{RS}")

                time.sleep(0.05)

        if round_number % 5 == 0:
            print(f"{C}{'='*50}{RS}")
            print(f"{G}📊 ACTIVE TARGETS Round {round_number} Complete{RS}")
            print(f"{G}📊 Total Requests: {total_requests}{RS}")
            print(f"{G}🎯 Active Targets: {len(invite_uids)}{RS}")
            print(f"{G}🤖 Bots Online: {len(clients_list)}{RS}")
            print(f"{C}{'='*50}{RS}\n")
        
        time.sleep(0.5)

    print(f"\n{R}🛑 ACTIVE TARGETS SPAM STOPPED{RS}\n")

def start_invite_targets_spam():
    """inv_uid.txt এর UID গুলোতে স্প্যাম শুরু করুন"""
    global auto_spam_active, invite_spam_thread
    
    if not invite_uids:
        print(f"{Y}⚠️ No active targets in inv_uid.txt{RS}")
        return False, "No active targets in inv_uid.txt"
    
    if invite_spam_thread and invite_spam_thread.is_alive():
        return False, "Active targets spam already running"
    
    auto_spam_active = True
    invite_spam_thread = Thread(target=invite_targets_spam_worker, daemon=True)
    invite_spam_thread.start()
    
    return True, f"Started spam on {len(invite_uids)} active targets"

def stop_invite_targets_spam():
    """inv_uid.txt এর স্প্যাম বন্ধ করুন"""
    global auto_spam_active
    auto_spam_active = False
    return True, "Active targets spam stopped"

# ==================== STATUS CHECKER FUNCTIONS ====================
def create_group_invite_packet(key, iv, target_uid, players=5, region="BD"):
    """Create group invite packet"""
    try:
        group_config = GROUP_CONFIGS.get(players, GROUP_CONFIGS[5])
        group_type = group_config["type"]
        
        proto_fields = {
            1: 33,
            2: {
                1: int(target_uid),
                2: region.upper(),
                3: 1,
                4: 1,
                5: bytes([1, 7, 9, 10, 11, 18, 25, 26, 32]),
                6: "[C][B][FF0000] INVITE",
                7: 330,
                8: 1000,
                10: region.upper(),
                11: bytes.fromhex("61" * 32),
                12: 1,
                13: int(target_uid),
                14: {
                    1: random.randint(1000000000, 9999999999),
                    2: group_type,
                    3: "\u0010\u0015\b\n\u000b\u0013\f\u000f\u0011\u0004\u0007\u0002\u0003\r\u000e\u0012\u0001\u0005\u0006"
                },
                16: 1,
                17: 1,
                18: 312,
                19: 46,
                23: bytes([16, 1, 24, 1]),
                24: random.randint(902000000, 902050099),
                26: "",
                28: ""
            },
            10: "en",
            13: {2: 1, 3: 1}
        }
        
        packet = create_proto_sync(proto_fields).hex()
        
        if region.lower() == "ind":
            packet_type = "0514"
        elif region.lower() == "bd":
            packet_type = "0519"
        else:
            packet_type = "0515"
        
        encrypted = EnC_PacKeT(packet, key, iv)
        length = len(encrypted) // 2
        len_hex = DecodE_HeX(length)
        padding_map = {2: "000000", 3: "00000", 4: "0000", 5: "000"}
        padding = padding_map.get(len(len_hex), "000")
        
        return bytes.fromhex(packet_type + padding + len_hex + encrypted)
    except Exception as e:
        print(f"{R}❌ Group invite packet error: {e}{RS}")
        return None

def create_badge_join_packet(key, iv, target_uid, badge_value, region="BD"):
    """Create join request with badge using custom working avatars"""
    try:
        # xBunnEr list of working avatar IDs
        avatar_ids = [
            902000028, 902000011, 902000015, 902000013, 902000086,
            902000154, 902000127, 902000207, 902000246, 902000305,
            902000338, 902047016, 902049015, 902052006, 902000100,
            902000204, 902052006, 902037031, 902042011, 902053016, 902051013
        ]
        selected_avatar = random.choice(avatar_ids)

        proto_fields = {
            1: 33,
            2: {
                1: int(target_uid),
                2: region.upper(),
                3: 1,
                4: 1,
                5: bytes([1, 7, 9, 10, 11, 18, 25, 26, 32]),
                6: "[C][B][FF0000] KAWSAR BADGE",
                7: 330,
                8: 1000,
                10: region.upper(),
                11: bytes.fromhex("61" * 32),
                12: 1,
                13: int(target_uid),
                14: {
                    1: random.randint(1000000000, 9999999999),
                    2: 8,
                    3: "\u0010\u0015\b\n\u000b\u0013\f\u000f\u0011\u0004\u0007\u0002\u0003\r\u000e\u0012\u0001\u0005\u0006"
                },
                16: 1,
                17: 1,
                18: 312,
                19: 46,
                23: bytes([16, 1, 24, 1]),
                24: selected_avatar, # এখানে xBunnEr এর অবতার আইডি ব্যবহার করা হয়েছে
                26: "",
                28: "",
                31: {1: 1, 2: badge_value},
                32: badge_value,
                34: {
                    1: int(target_uid),
                    2: 8,
                    3: bytes([15, 6, 21, 8, 10, 11, 19, 12, 17, 4, 14, 20, 7, 2, 1, 5, 16, 3, 13, 18])
                }
            },
            10: "en",
            13: {2: 1, 3: 1}
        }
        
        packet = create_proto_sync(proto_fields).hex()
        
        if region.lower() == "ind":
            packet_type = "0514"
        elif region.lower() == "bd":
            packet_type = "0519"
        else:
            packet_type = "0515"
        
        encrypted = EnC_PacKeT(packet, key, iv)
        length = len(encrypted) // 2
        len_hex = DecodE_HeX(length)
        padding_map = {2: "000000", 3: "00000", 4: "0000", 5: "000"}
        padding = padding_map.get(len(len_hex), "000")
        
        return bytes.fromhex(packet_type + padding + len_hex + encrypted)
    except Exception as e:
        print(f"{R}❌ Badge join packet error: {e}{RS}")
        return None

def encode_varint_sync(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        result.append(byte)
        if not value:
            break
    return bytes(result)

def create_proto_sync(fields):
    packet = bytearray()
    
    for field, value in fields.items():
        field_num = int(field)
        
        if isinstance(value, dict):
            nested = create_proto_sync(value)
            packet.extend(encode_varint_sync((field_num << 3) | 2))
            packet.extend(encode_varint_sync(len(nested)))
            packet.extend(nested)
        elif isinstance(value, int):
            packet.extend(encode_varint_sync((field_num << 3) | 0))
            packet.extend(encode_varint_sync(value))
        elif isinstance(value, str):
            data = value.encode('utf-8')
            packet.extend(encode_varint_sync((field_num << 3) | 2))
            packet.extend(encode_varint_sync(len(data)))
            packet.extend(data)
        elif isinstance(value, bytes):
            packet.extend(encode_varint_sync((field_num << 3) | 2))
            packet.extend(encode_varint_sync(len(value)))
            packet.extend(value)
            
    return bytes(packet)

async def OpEnSq(K, V, region="BD"):
    fields = {1: 1, 2: {2: "\u0001", 3: 1, 4: 1, 5: "en", 9: 1, 11: 1, 13: 1, 14: {2: 5756, 6: 11, 8: "1.122.1", 9: 2, 10: 4}}}
    packet_type = '0514' if region.lower() == "ind" else "0515"
    return await _pk((await _pb(fields)).hex(), packet_type, K, V)

async def cHSq(Nu, Uid, K, V, region="BD"):
    fields = {1: 17, 2: {1: int(Uid), 2: 1, 3: int(Nu - 1), 4: 62, 5: "\u001a", 8: 5, 13: 329}}
    packet_type = '0514' if region.lower() == "ind" else "0515"
    return await _pk((await _pb(fields)).hex(), packet_type, K, V)

async def SEnd_InV(Nu, Uid, K, V, region="BD"):
    fields = {1: 2, 2: {1: int(Uid), 2: region, 4: int(Nu)}}
    packet_type = '0514' if region.lower() == "ind" else "0515"
    return await _pk((await _pb(fields)).hex(), packet_type, K, V)

async def ExiT(K, V):
    fields = {1: 7, 2: {1: 0}}
    return await _pk((await _pb(fields)).hex(), '0515', K, V)

# ==================== SMART MONITOR FOR AUTO_UID ====================
def monitor_target_smart(target_uid):
    """Smart monitor that automatically starts/stops spam based on target status"""
    print(f"{C}🧠 SMART MONITOR started for target: {target_uid}{RS}")
    
    last_status = None
    is_currently_spamming = False
    leader_spam_started = set()
    
    while True:
        with smart_monitor_lock:
            if target_uid not in smart_monitor_threads:
                print(f"{Y}📌 Smart monitor stopped for: {target_uid}{RS}")
                break
        
        try:
            status_info = get_detailed_status(target_uid)
            current_status = status_info.get('status', 'OFFLINE')
            is_online = status_info.get('is_online', False)
            mode = status_info.get('mode', '')
            squad_owner = status_info.get('squad_owner')
            
            should_spam = False
            spam_reason = ""
            
            if not is_online or current_status == 'OFFLINE':
                spam_reason = "Target is OFFLINE"
                should_spam = False
            elif current_status == 'INGAME':
                spam_reason = f"Target is IN-GAME ({mode})"
                should_spam = False
            elif current_status == 'MATCHMAKING':
                spam_reason = "Target is MATCHMAKING"
                should_spam = False
            elif current_status in ['SOLO', 'SOCIAL_ISLAND', 'IN_ROOM']:
                spam_reason = f"Target is {current_status} - READY TO SPAM"
                should_spam = True
            elif current_status == 'INSQUAD':
                if squad_owner and str(squad_owner) != str(target_uid):
                    spam_reason = f"Target in squad, leader: {squad_owner}"
                    should_spam = True
                    if squad_owner not in leader_spam_started:
                        print(f"{G}🎯 Starting spam on group leader: {squad_owner}{RS}")
                        start_multi_spam([squad_owner])
                        leader_spam_started.add(squad_owner)
                        target_group_leaders[target_uid] = squad_owner
                else:
                    spam_reason = "Target is squad owner - READY TO SPAM"
                    should_spam = True
            else:
                spam_reason = f"Status: {current_status}"
                should_spam = is_online
            
            if should_spam and not is_currently_spamming:
                print(f"{G}▶️ SMART: Starting spam on {target_uid} - {spam_reason}{RS}")
                start_multi_spam([target_uid])
                is_currently_spamming = True
                
            elif not should_spam and is_currently_spamming:
                print(f"{R}⏸️ SMART: Stopping spam on {target_uid} - {spam_reason}{RS}")
                stop_spam(target_uid)
                is_currently_spamming = False
            
            if current_status != 'INSQUAD' and target_uid in target_group_leaders:
                old_leader = target_group_leaders[target_uid]
                print(f"{Y}👋 Target left squad, stopping leader spam: {old_leader}{RS}")
                stop_spam(old_leader)
                del target_group_leaders[target_uid]
                if old_leader in leader_spam_started:
                    leader_spam_started.discard(old_leader)
            
            if last_status != current_status:
                status_icon = "🟢 ONLINE" if is_online else "⚫ OFFLINE"
                print(f"\n{BOLD}🧠 SMART MONITOR - UID: {target_uid}")
                print(f"  Status:     {status_icon}")
                print(f"  Game Mode:  {current_status}")
                print(f"  Time:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RS}")
                print(f"{C}Status changed: {last_status} → {current_status}{RS}\n")
                last_status = current_status
                
                with smart_monitor_lock:
                    smart_target_statuses[target_uid] = current_status
            
            if target_uid in target_group_leaders:
                leader_uid = target_group_leaders[target_uid]
                leader_status = get_detailed_status(leader_uid)
                if not leader_status.get('is_online', False):
                    print(f"{Y}⚠️ Leader {leader_uid} went offline, stopping{RS}")
                    stop_spam(leader_uid)
                    
        except Exception as e:
            print(f"{R}❌ Smart monitor error for {target_uid}: {e}{RS}")
        
        time.sleep(3)

def start_smart_monitor(target_uid):
    """Start smart monitoring for a target"""
    with smart_monitor_lock:
        if target_uid in smart_monitor_threads:
            return False, f"Already monitoring {target_uid}"
        
        thread = Thread(target=monitor_target_smart, args=(target_uid,), daemon=True)
        smart_monitor_threads[target_uid] = thread
        thread.start()
        return True, f"Smart monitoring started for {target_uid}"

def stop_smart_monitor(target_uid):
    """Stop smart monitoring for a target"""
    with smart_monitor_lock:
        if target_uid in smart_monitor_threads:
            del smart_monitor_threads[target_uid]
            stop_spam(target_uid)
            return True, f"Smart monitoring stopped for {target_uid}"
    return False, f"No monitor found for {target_uid}"

# ==================== STATUS CHECKER SESSION ====================
_TTL = 6 * 60 * 60

_Hr = {
    'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 9; G011A Build/PI)',
    'Connection': 'Keep-Alive',
    'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Expect': '100-continue',
    'X-Unity-Version': '2018.4.11f1',
    'X-GA': 'v1 1',
    'ReleaseVersion': 'OB54',
}

_cx = {}

def _rdVr(data, pos):
    n = 0
    sh = 0
    while True:
        b = data[pos]
        pos += 1
        n |= (b & 0x7F) << sh
        sh += 7
        if not b & 0x80:
            break
    return n, pos

def _pbF(data):
    out = {}
    pos = 0
    while pos < len(data):
        try:
            tag, pos = _rdVr(data, pos)
            fn = tag >> 3
            wt = tag & 0x7
            if wt == 0:
                v, pos = _rdVr(data, pos)
                out[fn] = v
            elif wt == 2:
                ln, pos = _rdVr(data, pos)
                out[fn] = data[pos:pos+ln]
                pos += ln
            elif wt == 1:
                out[fn] = data[pos:pos+8]
                pos += 8
            elif wt == 5:
                out[fn] = data[pos:pos+4]
                pos += 4
            else:
                break
        except:
            break
    return out

async def _vr(n):
    h = []
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        h.append(b)
        if not n:
            break
    return bytes(h)

async def _enc(hx, k, v):
    return AES.new(k, AES.MODE_CBC, v).encrypt(pad(bytes.fromhex(hx), 16)).hex()

async def _hx(n):
    f = hex(n)[2:]
    return ('0' + f) if len(f) == 1 else f

async def _var(fn, val):
    return await _vr((fn << 3) | 0) + await _vr(val)

async def _len(fn, val):
    e = val.encode() if isinstance(val, str) else val
    return await _vr((fn << 3) | 2) + await _vr(len(e)) + e

async def _pb(flds):
    p = bytearray()
    for f, v in flds.items():
        if isinstance(v, dict):
            p.extend(await _len(f, await _pb(v)))
        elif isinstance(v, int):
            p.extend(await _var(f, v))
        elif isinstance(v, (str, bytes)):
            p.extend(await _len(f, v))
    return p

async def _pk(px, n, k, v):
    e = await _enc(px, k, v)
    _ = await _hx(len(e) // 2)
    m = {2: '000000', 3: '00000', 4: '0000', 5: '000'}
    return bytes.fromhex(n + m.get(len(_), '000000') + _ + e)

async def _fix(rs):
    d = {}
    for r in rs:
        fd = {'wire_type': r.wire_type}
        if r.wire_type in ('varint', 'string', 'bytes'):
            fd['data'] = r.data
        elif r.wire_type == 'length_delimited':
            fd['data'] = await _fix(r.data.results)
        d[r.field] = fd
    return d

async def _parse(hx):
    try:
        from protobuf_decoder.protobuf_decoder import Parser
        return json.dumps(await _fix(Parser().parse(hx)))
    except:
        return None

async def _uidEnc(uid):
    return (await _pb({1: int(uid)})).hex()[2:]

async def _stPkt(uid, k, v):
    ue = await _uidEnc(int(uid))
    return await _pk(f"080112090A05{ue}1005", '0F15', k, v)

async def _rmPkt(ruid, k, v):
    return await _pk((await _pb({1: 1, 2: {1: ruid, 3: {}, 4: 1, 6: 'en'}})).hex(), '0E15', k, v)

def _tdiff(ts):
    d = int((datetime.now() - datetime.fromtimestamp(ts)).total_seconds())
    return f"{(abs(d) % 3600) // 60:02}:{abs(d) % 60:02}"

def _pStatus(pkt):
    data = json.loads(pkt)
    if '5' not in data or 'data' not in data['5']:
        return {'status': 'OFFLINE'}
    jd = data['5']['data']
    if '1' not in jd or 'data' not in jd['1']:
        return {'status': 'OFFLINE'}
    d = jd['1']['data']
    if '3' not in d or 'data' not in d['3']:
        return {'status': 'OFFLINE'}
    st = d['3']['data']
    gc = d.get('9', {}).get('data', 0)
    cm = d.get('10', {}).get('data', 0) + 1 if '10' in d else 0
    go = d.get('8', {}).get('data', 0)
    tg = d.get('4', {}).get('data', 0)
    m5 = d.get('5', {}).get('data')
    m6 = d.get('6', {}).get('data')
    mn = sc = 0
    if tg:
        a, b = _tdiff(tg).split(':')
        mn = int(a)
        sc = int(b)
    
    if st == 4:
        return {
            'status': 'IN_ROOM',
            'room_uid': d.get('15', {}).get('data'),
            'players': f"{d.get('17',{}).get('data',0)}/{d.get('18',{}).get('data',0)}",
            'room_owner': d.get('1', {}).get('data')
        }
    
    base = {
        1: 'SOLO',
        2: 'INSQUAD',
        3: 'INGAME',
        5: 'INGAME',
        7: 'MATCHMAKING',
        6: 'SOCIAL_ISLAND'
    }.get(st, 'OFFLINE')
    
    mode = None
    f14 = d.get('14', {}).get('data')
    if f14 == 1:
        mode = 'TRAINING'
    elif f14 == 2:
        mode = 'SOCIAL_ISLAND'
    
    mm = {
        (2, 1): 'BR_RANK', (5, 23): 'TRAINING', (6, 15): 'CS_RANK',
        (1, 43): 'LONE_WOLF', (1, 1): 'BERMUDA', (1, 15): 'CLASH_SQUAD',
        (1, 29): 'CONVOY_CRUNCH', (1, 61): 'FREE_FOR_ALL'
    }
    if (m5, m6) in mm:
        mode = mm[(m5, m6)]
    
    res = {'status': base, 'mode': mode}
    if base == 'INSQUAD':
        res['squad_owner'] = go
        res['squad_size'] = f"{gc}/{cm}" if gc else None
    if base in ('INGAME', 'INSQUAD') and tg:
        res['time_playing'] = f"{mn}m {sc}s"
    return res

def _pRoom(pkt):
    data = json.loads(pkt)
    rd = data['5']['data']['1']['data']
    mm = {
        1: 'BERMUDA', 201: 'BATTLE_CAGE', 15: 'CLASH_SQUAD', 43: 'LONE_WOLF',
        3: 'RUSH_HOUR', 27: 'BOMB_SQUAD_5V5', 24: 'DEATH_MATCH'
    }
    return {
        'room_id': int(rd['1']['data']),
        'room_name': rd['2']['data'],
        'owner_uid': int(rd['37']['data']['1']['data']),
        'mode': mm.get(rd.get('4', {}).get('data'), 'UNKNOWN'),
        'players': f"{rd.get('6',{}).get('data',0)}/{rd.get('7',{}).get('data',0)}",
        'spectators': rd.get('9', {}).get('data', 0),
        'emulator': bool(rd.get('17', {}).get('data', 1)),
    }

async def _rAll(reader, timeout=5):
    buf = b''
    while True:
        try:
            chunk = await asyncio.wait_for(reader.read(65536), timeout=timeout)
        except asyncio.TimeoutError:
            break
        if not chunk:
            break
        buf += chunk
    return buf

async def _scan(buf, k, v):
    h = buf.hex()
    for mk, pt in [('0f00', '0f'), ('0e00', '0e')]:
        i = h.find(mk)
        if i != -1 and i % 2 == 0:
            return pt, h[i + 10:]
    if len(buf) > 5:
        pl = buf[5:]
        pl = pl[:len(pl) - (len(pl) % 16)]
        if len(pl) >= 16:
            try:
                dc = unpad(AES.new(k, AES.MODE_CBC, v).decrypt(pl), 16).hex()
                for mk, pt in [('0f00', '0f'), ('0e00', '0e')]:
                    i = dc.find(mk)
                    if i != -1 and i % 2 == 0:
                        return pt, dc[i + 10:]
            except:
                pass
    return None, None

async def _mkLogin(oid, atk):
    return await _pb({
        3: str(datetime.now())[:-7], 4: 'free fire', 5: 1, 7: '1.123.1',
        8: 'Android OS 9 / API-28 (PQ3B.190801.10101846/G9650ZHU2ARC6)',
        9: 'Handheld', 10: 'Verizon', 11: 'WIFI', 12: 1920, 13: 1080,
        14: '280', 15: 'ARM64 FP ASIMD AES VMH | 2865 | 4', 16: 3003,
        17: 'Adreno (TM) 640', 18: 'OpenGL ES 3.1 v1.46',
        19: 'Google|34a7dcdf-a7d5-4cb6-8d7e-3b0e448a0c57',
        20: '223.191.51.89', 21: 'en', 22: oid, 23: '4', 24: 'Handheld',
        25: {6: 55, 8: 81},
        29: atk, 30: 1, 73: 3, 78: 3, 79: 2, 81: '64',
        93: 'android', 97: 1, 98: 1, 99: '4', 100: '4',
    })


async def _auth(uid, tok, ts, k, v):
    uh = hex(uid)[2:]
    hd = {9: '0000000', 8: '00000000', 10: '000000', 7: '000000000'}.get(len(uh), '0000000')
    e = await _enc(tok.encode().hex(), k, v)
    el = await _hx(len(e) // 2)
    return f"0115{hd}{uh}{await _hx(ts)}00000{el}{e}"

async def _login():
    sx = ssl.create_default_context()
    sx.check_hostname = False
    sx.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession() as s:
        async with s.post('https://100067.connect.garena.com/oauth/guest/token/grant',
                         headers=_Hr,
                         data={
                             'uid': _ID,
                             'password': _PW,
                             'response_type': 'token',
                             'client_type': '2',
                             'client_secret': '2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3',
                             'client_id': '100067'
                         }, ssl=sx) as r:
            if r.status != 200:
                raise Exception(f"OAuth {r.status}")
            d = await r.json()
            oid = d['open_id']
            atk = d['access_token']

    raw = await _mkLogin(oid, atk)
    ep = AES.new(b'Yg&tc%DEuh6%Zc^8', AES.MODE_CBC, b'6oyZDr22E3ychjM%').encrypt(pad(raw, 16))

    async with aiohttp.ClientSession() as s:
        async with s.post('https://loginbp.ggpolarbear.com/MajorLogin', data=ep, headers=_Hr, ssl=sx) as r:
            if r.status != 200:
                raise Exception(f"MajorLogin {r.status}")
            mr = await r.read()

    mlr = _pbF(mr)
    tok = mlr[8].decode()
    tgt = mlr[1]
    k = mlr[22]
    v = mlr[23]
    ts = mlr[21]
    url = mlr[10].decode()

    h2 = {**_Hr, 'Authorization': f'Bearer {tok}'}
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{url}/GetLoginData", data=ep, headers=h2, ssl=sx) as r:
            if r.status != 200:
                raise Exception(f"GetLoginData {r.status}")
            lr = await r.read()

    ld = _pbF(lr)
    ip, port = ld[14].decode().split(':')
    at = await _auth(int(tgt), tok, int(ts), k, v)
    return {
        'account_id': tgt,
        'token': tok,
        'key': k,
        'iv': v,
        'ip': ip,
        'port': int(port),
        'auth': at,
        'exp': time.time() + _TTL
    }

def _sess():
    global _cx
    if 's' in _cx and _cx['s'] and time.time() < _cx['s']['exp']:
        return _cx['s']
    _cx['s'] = asyncio.run(_login())
    return _cx['s']

async def _query(uid, sx):
    rd, wr = await asyncio.open_connection(sx['ip'], sx['port'])
    try:
        wr.write(bytes.fromhex(sx['auth']))
        await wr.drain()
        await _rAll(rd, timeout=3)
        pkt = await _stPkt(uid, sx['key'], sx['iv'])
        wr.write(pkt)
        await wr.drain()
        buf = await _rAll(rd, timeout=5)
        if not buf:
            return {'status': 'NO_RESPONSE'}
        pt, pl = await _scan(buf, sx['key'], sx['iv'])
        if pt == '0f':
            raw = await _parse(pl)
            if not raw:
                return {'status': 'PARSE_ERROR'}
            info = _pStatus(raw)
            if info.get('status') == 'IN_ROOM':
                wr.write(await _rmPkt(int(info['room_uid']), sx['key'], sx['iv']))
                await wr.drain()
                rb = await _rAll(rd, timeout=5)
                if rb:
                    rt, rp = await _scan(rb, sx['key'], sx['iv'])
                    if rt == '0e':
                        rr = await _parse(rp)
                        if rr:
                            info['room_info'] = _pRoom(rr)
            return info
        elif pt == '0e':
            raw = await _parse(pl)
            return _pRoom(raw) if raw else {'status': 'PARSE_ERROR'}
        return {'status': 'UNKNOWN', 'buf': buf.hex()[:120]}
    finally:
        wr.close()
        try:
            await wr.wait_closed()
        except:
            pass

def get_detailed_status(uid):
    """Get detailed status information"""
    try:
        session = _sess()
        result = asyncio.run(_query(int(uid), session))
        
        detailed = {
            'uid': str(uid),
            'timestamp': datetime.now().isoformat(),
            'is_online': result.get('status', 'OFFLINE') not in ['OFFLINE', 'ERROR', 'NO_RESPONSE'],
            'status': result.get('status', 'UNKNOWN'),
            'mode': result.get('mode', 'N/A'),
        }
        
        if result.get('status') == 'INSQUAD':
            detailed['squad_owner'] = result.get('squad_owner')
            detailed['squad_size'] = result.get('squad_size')
        elif result.get('status') == 'IN_ROOM':
            detailed['room_owner'] = result.get('room_owner')
            detailed['players'] = result.get('players')
            if result.get('room_info'):
                detailed['room_details'] = result['room_info']
        
        if result.get('time_playing'):
            detailed['time_playing'] = result['time_playing']
        
        return detailed
    except Exception as e:
        return {'status': 'ERROR', 'error': str(e), 'uid': str(uid)}

# ==================== ENHANCED SPAM WORKER (MULTI-TARGET) ====================
def spam_worker_multi(targets_list):
    """একাধিক টার্গেটে একসাথে স্প্যাম করার জন্য ওয়ার্কার"""
    print(f"\n{G}{'='*60}{RS}")
    print(f"{G}🎯 MULTI-TARGET SPAM STARTED ON {len(targets_list)} TARGETS:{RS}")
    for tid in targets_list:
        print(f"{G}   ➤ {tid}{RS}")
    print(f"{C}{'='*60}{RS}\n")

    total_requests = 0
    round_number = 0

    def run_async(coro):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        except:
            return None
        finally:
            loop.close()

    while True:
        global auto_spam_active
        if not auto_spam_active:
            break

        with active_power_lock:
            current_targets = list(active_power_targets.keys())
            if not current_targets:
                break

        with connected_clients_lock:
            clients_list = list(connected_clients.values())

        if not clients_list:
            time.sleep(2)
            continue

        round_number += 1

        for target_id in current_targets:
            for client in clients_list:
                with active_power_lock:
                    if target_id not in active_power_targets:
                        break

                try:
                    if hasattr(client, 'CliEnts2') and client.key:
                        # === 1. রুম স্প্যাম ===
                        try:
                            open_pkt = openroom(client.key, client.iv)
                            if open_pkt:
                                client.CliEnts2.send(open_pkt)
                            
                            spam_pkt = spmroom(client.key, client.iv, target_id)
                            if spam_pkt:
                                client.CliEnts2.send(spam_pkt)
                                total_requests += 1
                        except:
                            pass

                        # === 2. গ্রুপ ইনভাইট (5 প্লেয়ার) ===
                        try:
                            async def send_invite_5():
                                p1 = await OpEnSq(client.key, client.iv)
                                client.CliEnts2.send(p1)
                                await asyncio.sleep(0.05)
                                p2 = await cHSq(5, target_id, client.key, client.iv)
                                client.CliEnts2.send(p2)
                                await asyncio.sleep(0.05)
                                p3 = await SEnd_InV(5, target_id, client.key, client.iv)
                                client.CliEnts2.send(p3)
                                total_requests += 1
                                await asyncio.sleep(0.05)
                                p4 = await ExiT(client.key, client.iv)
                                client.CliEnts2.send(p4)
                            run_async(send_invite_5())
                        except:
                            pass

                        # === 3. ব্যাজ জয়িন ===
                        for badge_name, badge_value in BADGES.items():
                            try:
                                badge_pkt = create_badge_join_packet(client.key, client.iv, target_id, badge_value)
                                if badge_pkt:
                                    client.CliEnts2.send(badge_pkt)
                                    total_requests += 1
                                    time.sleep(0.03)
                            except:
                                pass

                        # === 4. 3 প্লেয়ার গ্রুপ ইনভাইট ===
                        try:
                            group_pkt_3 = create_group_invite_packet(client.key, client.iv, target_id, 3)
                            if group_pkt_3:
                                client.CliEnts2.send(group_pkt_3)
                                total_requests += 1
                                time.sleep(0.03)
                        except:
                            pass

                        # === 5. 6 প্লেয়ার গ্রুপ ইনভাইট ===
                        try:
                            group_pkt_6 = create_group_invite_packet(client.key, client.iv, target_id, 6)
                            if group_pkt_6:
                                client.CliEnts2.send(group_pkt_6)
                                total_requests += 1
                                time.sleep(0.03)
                        except:
                            pass

                except Exception as e:
                    print(f"{R}❌ Error: {e}{RS}")

                time.sleep(0.05)

        if round_number % 5 == 0:
            print(f"{C}{'='*50}{RS}")
            print(f"{G}📊 Round {round_number} Complete{RS}")
            print(f"{G}📊 Total Requests: {total_requests}{RS}")
            print(f"{G}🎯 Active Targets: {len(current_targets)}{RS}")
            print(f"{G}🤖 Bots Online: {len(clients_list)}{RS}")
            print(f"{C}{'='*50}{RS}\n")
        
        time.sleep(0.5)

    with spam_threads_lock:
        for tid in targets_list:
            if tid in spam_threads:
                del spam_threads[tid]

    print(f"\n{R}🛑 MULTI-SPAM STOPPED ON {len(targets_list)} TARGETS{RS}\n")

def start_multi_spam(targets_list):
    """একাধিক টার্গেটে স্প্যাম শুরু করুন"""
    global auto_spam_active
    
    if isinstance(targets_list, str):
        targets_list = [targets_list]
    
    new_targets = []
    with active_power_lock:
        for target in targets_list:
            if target not in active_power_targets:
                active_power_targets[target] = {
                    'active': True,
                    'start_time': datetime.now()
                }
                new_targets.append(target)
    
    if new_targets:
        auto_spam_active = True
        thread = Thread(target=spam_worker_multi, args=(new_targets,), daemon=True)
        with spam_threads_lock:
            for tid in new_targets:
                spam_threads[tid] = thread
        thread.start()
        return True, f"Started spam on {len(new_targets)} targets: {', '.join(new_targets)}"
    return False, "No new targets to start"

def stop_spam(target_id):
    """একটি নির্দিষ্ট টার্গেটের স্প্যাম বন্ধ করুন"""
    with active_power_lock:
        if target_id in active_power_targets:
            del active_power_targets[target_id]
            return True, f"Spam stopped on: {target_id}"
        return False, f"No active spam on: {target_id}"

def stop_all_spam():
    """সব স্প্যাম বন্ধ করুন"""
    global auto_spam_active
    auto_spam_active = False
    with active_power_lock:
        targets = list(active_power_targets.keys())
        for target in targets:
            del active_power_targets[target]
    return True, f"Stopped all spam ({len(targets)} targets)"

def get_status():
    """বর্তমান স্প্যাম স্ট্যাটাস পাওয়া"""
    with active_power_lock:
        active_targets = list(active_power_targets.keys())
        targets_info = []
        for target in active_targets:
            info = active_power_targets[target]
            start_time = info.get('start_time')
            elapsed = (datetime.now() - start_time).total_seconds() if start_time else 0
            targets_info.append({
                'uid': target,
                'elapsed_minutes': int(elapsed / 60)
            })
    
    with connected_clients_lock:
        accounts_count = len(connected_clients)
        accounts_list = list(connected_clients.keys())
    
    with smart_monitor_lock:
        monitored_targets = [
            {'uid': uid, 'status': smart_target_statuses.get(uid, 'CHECKING...')} 
            for uid in smart_monitor_threads.keys()
        ]
    
    return {
        'active_targets': targets_info,
        'active_count': len(active_targets),
        'accounts_count': accounts_count,
        'accounts_list': accounts_list[:50],
        'auto_uids': auto_uids,
        'invite_uids': invite_uids,
        'auto_active': auto_spam_active,
        'smart_monitored': monitored_targets
    }

# ==================== AUTO REFRESH ====================
def auto_refresh_and_restart():
    """প্রতি ৭ মিনিটে রিফ্রেশ - কিন্তু ACTIVE TARGETS অফ হবে না"""
    global auto_spam_active, refresh_timer
    
    print(f"\n{Y}{'='*50}{RS}")
    print(f"{Y}🔄 AUTO REFRESH INITIATED (KEEPING ACTIVE TARGETS){RS}")
    print(f"{Y}{'='*50}{RS}\n")
    
    # আগে এখানে stop_all_spam() ছিল, যা এখন সরিয়ে দেওয়া হয়েছে।
    # এর ফলে বর্তমানে যা চলছে তা বন্ধ হবে না।

    # ফাইল থেকে নতুন UID গুলো লোড করা (যদি আপনি ফাইলে নতুন কিছু লিখে থাকেন)
    load_auto_uids()
    load_invite_uids()
    
    # SMART MONITORED (auto_uid.txt) - শুধুমাত্র নতুন UID গুলো যোগ করা হবে
    if auto_uids:
        print(f"{G}🧠 Checking for new SMART monitor targets...{RS}")
        for uid in auto_uids:
            with smart_monitor_lock:
                if uid not in smart_monitor_threads:
                    start_smart_monitor(uid)
    
    # ACTIVE TARGETS (inv_uid.txt) - যদি স্প্যাম থ্রেড বন্ধ থাকে তবেই চালু করবে
    if invite_uids:
        if not invite_spam_thread or not invite_spam_thread.is_alive():
            print(f"{G}🎯 Starting ACTIVE TARGETS worker...{RS}")
            start_invite_targets_spam()
        else:
            print(f"{G}✅ ACTIVE TARGETS worker is already running.{RS}")
    
    # টাইমার রিসেট করা
    if refresh_timer:
        refresh_timer.cancel()
    refresh_timer = threading.Timer(7 * 60, auto_refresh_and_restart)
    refresh_timer.daemon = True
    refresh_timer.start()
    
    print(f"{G}✅ Refresh Complete. Next check in 7 minutes.{RS}\n")

def start_auto_refresh():
    global refresh_timer
    if refresh_timer:
        refresh_timer.cancel()
    refresh_timer = threading.Timer(7 * 60, auto_refresh_and_restart)
    refresh_timer.daemon = True
    refresh_timer.start()
    print(f"{G}⏰ Auto-refresh timer started (every 7 minutes){RS}")

def start_auto_spam():
    """অটো স্প্যাম শুরু করুন (auto_uid.txt স্মার্ট মনিটর + inv_uid.txt সরাসরি স্প্যাম)"""
    global auto_spam_active
    
    if auto_spam_active:
        return False, "Auto spam already active"
    
    auto_spam_active = True
    
    # SMART MONITORED (auto_uid.txt)
    if auto_uids:
        for uid in auto_uids:
            start_smart_monitor(uid)
        print(f"{G}🧠 Started SMART monitors on {len(auto_uids)} UIDs{RS}")
    
    # ACTIVE TARGETS (inv_uid.txt)
    if invite_uids:
        start_invite_targets_spam()
        print(f"{G}🎯 Started ACTIVE TARGETS spam on {len(invite_uids)} UIDs{RS}")
    
    return True, f"Auto spam started (Smart: {len(auto_uids)}, Active: {len(invite_uids)})"

def stop_auto_spam():
    """অটো স্প্যাম বন্ধ করুন"""
    global auto_spam_active
    auto_spam_active = False
    
    # স্মার্ট মনিটর বন্ধ
    with smart_monitor_lock:
        monitors = list(smart_monitor_threads.keys())
        for uid in monitors:
            del smart_monitor_threads[uid]
    
    # একটিভ টার্গেট স্প্যাম বন্ধ
    stop_invite_targets_spam()
    stop_all_spam()
    
    return True, "Auto spam stopped"

# ==================== ACCOUNTS ====================
ACCOUNTS = []

def load_accounts_from_file(filename="accs.txt"):
    loaded_accounts = []
    try:
        if not os.path.exists(filename):
            with open(filename, "w") as f:
                f.write(f"# Format: UID:PASSWORD\n")
            return []

        with open(filename, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith("#"):
                    if ":" in line:
                        parts = line.split(":")
                        uid = parts[0].strip()
                        pwd = parts[1].strip()
                    else:
                        uid = line.strip()
                        pwd = ""
                    
                    if uid.isdigit():
                        loaded_accounts.append({'id': uid, 'password': pwd})
        
        print(f"{G}📦 Loaded {len(loaded_accounts)} accounts from {filename}{RS}")
    except Exception as e:
        print(f"{R}❌ Error loading {filename}: {e}{RS}")
    
    return loaded_accounts

ACCOUNTS = load_accounts_from_file("accs.txt")

# ==================== FF CLIENT ====================
class FF_CLient():
    def __init__(self, id, password):
        self.id = id
        self.password = password
        self.key = None
        self.iv = None
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
        except Exception as e:
            print(f"{R}❌ Online error {self.id}: {e}{RS}")
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
            time.sleep(5)
            return self.Get_FiNal_ToKen_0115()

def start_account(account):
    try:
        print(f"{G}🚀 Logging in: {account['id']}{RS}")
        FF_CLient(account['id'], account['password'])
    except Exception as e:
        time.sleep(1)
        start_account(account)

def run_accounts():
    for acc in ACCOUNTS:
        Thread(target=start_account, args=(acc,), daemon=True).start()
        time.sleep(0.2)

# ==================== FLASK ROUTES ====================
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# ==================== NORMAL SPAM GET API ====================
@app.route('/api/normal', methods=['GET'])
def api_normal_get_control():
    """
    Get API for Normal Spam Control
    Usage:
    - ON:  /api/normal?action=on&uid=12345678,98765432
    - OFF: /api/normal?action=off&uid=12345678
    - OFF ALL: /api/normal?action=off
    """
    action = request.args.get('action', '').lower()
    target_input = request.args.get('uid', '').strip()

    if action == 'on':
        if not target_input:
            return jsonify({'success': False, 'message': 'Target UID(s) required!'}), 400
        
        # কমা বা স্পেস দিয়ে আলাদা করা UIDs হ্যান্ডেল করা
        targets = []
        if ',' in target_input:
            targets = [tid.strip() for tid in target_input.split(',') if tid.strip().isdigit()]
        else:
            targets = [tid.strip() for tid in target_input.split() if tid.strip().isdigit()]
            
        if not targets:
            # যদি সরাসরি একটি UID হয়
            if target_input.isdigit():
                targets = [target_input]
            else:
                return jsonify({'success': False, 'message': 'Invalid UID format!'}), 400

        success, message = start_multi_spam(targets)
        return jsonify({'success': success, 'message': message})

    elif action == 'off':
        if target_input:
            # নির্দিষ্ট একটি UID অফ করা
            success, message = stop_spam(target_input)
            stop_smart_monitor(target_input) # যদি স্মার্ট মনিটরে থাকে সেটাও অফ হবে
            return jsonify({'success': success, 'message': message})
        else:
            # সব স্প্যাম অফ করা
            stop_all_spam()
            stop_invite_targets_spam()
            return jsonify({'success': True, 'message': 'All normal spam stopped successfully!'})

    return jsonify({'success': False, 'message': 'Invalid action! Use action=on or action=off'}), 400

@app.route('/api/start', methods=['POST'])
def api_start():
    data = request.get_json()
    target_input = data.get('uid', '').strip()
    smart_mode = data.get('smart', False)
    
    if ',' in target_input:
        targets = [tid.strip() for tid in target_input.split(',') if tid.strip().isdigit()]
    elif ' ' in target_input:
        targets = [tid.strip() for tid in target_input.split() if tid.strip().isdigit()]
    else:
        targets = [target_input] if target_input.isdigit() else []
    
    if not targets:
        return jsonify({'success': False, 'message': 'Valid UID(s) required'})
    
    if smart_mode:
        success_count = 0
        for uid in targets:
            success, msg = start_smart_monitor(uid)
            if success:
                success_count += 1
        return jsonify({'success': success_count > 0, 'message': f'Smart monitoring started on {success_count}/{len(targets)} targets'})
    else:
        success, message = start_multi_spam(targets)
        return jsonify({'success': success, 'message': message})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    data = request.get_json()
    target_id = data.get('uid', '').strip()
    
    if not target_id:
        return jsonify({'success': False, 'message': 'UID is required'})
    
    success, message = stop_spam(target_id)
    stop_smart_monitor(target_id)
    return jsonify({'success': success, 'message': message})

@app.route('/api/stop-all', methods=['POST'])
def api_stop_all():
    stop_auto_spam()
    return jsonify({'success': True, 'message': 'All spam stopped'})

@app.route('/api/status', methods=['GET'])
def api_status():
    status = get_status()
    return jsonify({'success': True, 'data': status})

@app.route('/api/accounts', methods=['GET'])
def api_accounts():
    with connected_clients_lock:
        return jsonify({
            'success': True,
            'count': len(connected_clients),
            'accounts': list(connected_clients.keys())
        })

@app.route('/api/auto-uids', methods=['GET'])
def api_get_auto_uids():
    return jsonify({'success': True, 'uids': auto_uids})

@app.route('/api/auto-uids', methods=['POST'])
def api_update_auto_uids():
    data = request.get_json()
    uids = data.get('uids', [])
    global auto_uids
    auto_uids = [uid.strip() for uid in uids if uid.strip().isdigit()]
    save_auto_uids(auto_uids)
    return jsonify({'success': True, 'message': f'Saved {len(auto_uids)} UIDs'})

@app.route('/api/invite-uids', methods=['GET'])
def api_get_invite_uids():
    return jsonify({'success': True, 'uids': invite_uids})

@app.route('/api/invite-uids', methods=['POST'])
def api_update_invite_uids():
    data = request.get_json()
    uids = data.get('uids', [])
    global invite_uids
    invite_uids = [uid.strip() for uid in uids if uid.strip().isdigit()]
    save_invite_uids(invite_uids)
    # নতুন UIDs যোগ করলে স্প্যাম শুরু করুন
    if invite_uids:
        start_invite_targets_spam()
    return jsonify({'success': True, 'message': f'Saved {len(invite_uids)} invite UIDs'})

@app.route('/api/start-auto', methods=['POST'])
def api_start_auto():
    success, message = start_auto_spam()
    return jsonify({'success': success, 'message': message})

@app.route('/api/stop-auto', methods=['POST'])
def api_stop_auto():
    success, message = stop_auto_spam()
    return jsonify({'success': success, 'message': message})

@app.route('/api/check-status', methods=['POST'])
def api_check_status():
    data = request.get_json()
    target_id = data.get('uid', '').strip()
    
    if not target_id:
        return jsonify({'success': False, 'message': 'UID is required'})
    
    status = get_detailed_status(target_id)
    return jsonify({'success': True, 'data': status})

@app.route('/api/smart-monitors', methods=['GET'])
def api_smart_monitors():
    with smart_monitor_lock:
        return jsonify({
            'success': True,
            'monitored': list(smart_monitor_threads.keys())
        })

# ==================== HTML TEMPLATE ====================
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes" />
    <title>KAWSAR SPAM · B&W</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,600;14..32,800&display=swap" rel="stylesheet" />
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
    <style>
        /* ── reset & base ── */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background: #0b0b0b;
            color: #e0e0e0;
            font-family: 'Inter', system-ui, -apple-system, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 16px;
        }

        /* ── main card ── */
        .app {
            max-width: 720px;
            width: 100%;
            background: #131313;
            border: 1px solid #2a2a2a;
            border-radius: 24px;
            padding: 28px 22px 22px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.8);
        }

        /* ── header ── */
        .header {
            text-align: center;
            margin-bottom: 28px;
        }
        .header .badge {
            font-size: 0.7rem;
            font-weight: 600;
            letter-spacing: 0.08em;
            color: #888;
            display: flex;
            justify-content: center;
            gap: 12px;
            flex-wrap: wrap;
            margin-bottom: 8px;
        }
        .header .badge i {
            margin-right: 4px;
        }
        .header h1 {
            font-size: 2.6rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            color: #f0f0f0;
            line-height: 1.1;
        }
        .header h1 span {
            display: block;
            font-weight: 400;
            font-size: 1rem;
            letter-spacing: 0.2em;
            color: #888;
            margin-top: 4px;
        }

        /* ── cards ── */
        .card {
            background: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 18px;
            padding: 20px 18px;
            margin-bottom: 18px;
            transition: border-color 0.2s;
        }
        .card:hover {
            border-color: #3a3a3a;
        }

        .card-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }
        .card-header .icon {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            background: #222;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #ccc;
            font-size: 1rem;
            border: 1px solid #333;
        }
        .card-header .title h3 {
            font-size: 1.1rem;
            font-weight: 600;
            color: #eee;
        }
        .card-header .title p {
            font-size: 0.7rem;
            color: #777;
            margin-top: 2px;
        }

        /* ── inputs / textareas ── */
        textarea,
        input[type="text"] {
            width: 100%;
            background: #0f0f0f;
            border: 1px solid #2a2a2a;
            border-radius: 12px;
            padding: 14px 16px;
            color: #e0e0e0;
            font-size: 0.95rem;
            font-family: 'Inter', monospace;
            outline: none;
            transition: border-color 0.2s;
            resize: vertical;
        }
        textarea:focus,
        input[type="text"]:focus {
            border-color: #666;
        }
        textarea::placeholder,
        input::placeholder {
            color: #555;
        }

        .input-label {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.8rem;
            color: #999;
            margin-bottom: 6px;
        }
        .input-label i {
            width: 18px;
        }

        /* ── buttons ── */
        .btn {
            padding: 12px 18px;
            border: 1px solid #333;
            border-radius: 12px;
            font-weight: 600;
            font-size: 0.9rem;
            cursor: pointer;
            background: #222;
            color: #ddd;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: 0.15s;
            flex: 1;
            font-family: 'Inter', sans-serif;
        }
        .btn:hover {
            background: #2c2c2c;
            border-color: #555;
        }
        .btn:active {
            transform: scale(0.97);
        }

        .btn-primary {
            background: #2a2a2a;
            border-color: #444;
            color: #f0f0f0;
        }
        .btn-primary:hover {
            background: #333;
        }

        .btn-outline {
            background: transparent;
            border-color: #333;
            color: #aaa;
        }
        .btn-outline:hover {
            background: #1a1a1a;
            border-color: #555;
            color: #eee;
        }

        .btn-danger {
            border-color: #441111;
            color: #cc6666;
        }
        .btn-danger:hover {
            background: #1f0f0f;
            border-color: #772222;
        }

        .btn-warning {
            border-color: #444411;
            color: #cccc66;
        }
        .btn-warning:hover {
            background: #1f1f0f;
            border-color: #777722;
        }

        .btn-success {
            border-color: #114411;
            color: #66cc66;
        }
        .btn-success:hover {
            background: #0f1f0f;
            border-color: #227722;
        }

        .btn-smart {
            border-color: #2a2a44;
            color: #9999dd;
        }
        .btn-smart:hover {
            background: #14142a;
            border-color: #444477;
        }

        .flex-buttons {
            display: flex;
            gap: 10px;
            margin-top: 12px;
            flex-wrap: wrap;
        }
        .flex-buttons .btn {
            flex: 1 1 auto;
            min-width: 80px;
        }

        /* ── mode toggle ── */
        .mode-toggle {
            display: flex;
            gap: 8px;
            margin-bottom: 14px;
        }
        .mode-btn {
            flex: 1;
            padding: 10px 8px;
            background: #141414;
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            text-align: center;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.85rem;
            color: #777;
            transition: 0.15s;
        }
        .mode-btn i {
            margin-right: 6px;
        }
        .mode-btn.active {
            background: #2a2a2a;
            border-color: #555;
            color: #eee;
        }
        .mode-btn.smart-mode.active {
            background: #1a1a2e;
            border-color: #444477;
            color: #bbbbee;
        }

        /* ── console ── */
        .console-box {
            background: #0a0a0a;
            border: 1px solid #222;
            border-radius: 12px;
            height: 160px;
            padding: 14px;
            font-family: 'Inter', monospace;
            font-size: 0.75rem;
            color: #aaa;
            overflow-y: auto;
            text-align: left;
            line-height: 1.6;
        }
        .console-box .time {
            color: #555;
            margin-right: 8px;
        }
        .console-box .success {
            color: #66cc66;
        }
        .console-box .error {
            color: #cc6666;
        }
        .console-box .info {
            color: #88aacc;
        }
        .console-box .smart {
            color: #9999dd;
        }
        .console-box .warning {
            color: #cccc66;
        }

        /* ── badges / status ── */
        .badge-info {
            background: #181818;
            border: 1px solid #2a2a2a;
            border-radius: 12px;
            padding: 10px 14px;
            text-align: center;
            font-size: 0.75rem;
            font-weight: 500;
            color: #999;
            margin-top: 14px;
        }
        .badge-info i {
            margin-right: 6px;
            color: #666;
        }

        .status-badge {
            background: #111;
            border: 1px solid #2a2a2a;
            border-radius: 12px;
            padding: 10px 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            font-weight: 600;
            font-size: 0.8rem;
            color: #ccc;
            margin-top: 10px;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            background: #666;
            border-radius: 50%;
            animation: pulse 1.8s infinite;
        }
        @keyframes pulse {
            0%,
            100% {
                opacity: 0.3;
                transform: scale(0.9);
            }
            50% {
                opacity: 1;
                transform: scale(1.2);
            }
        }

        .smart-badge {
            border-color: #2a2a44;
            color: #9999dd;
            background: #111120;
        }
        .refresh-badge {
            background: #111;
            border: 1px solid #2a2a2a;
            border-radius: 12px;
            padding: 8px 12px;
            text-align: center;
            font-size: 0.65rem;
            color: #666;
            margin-top: 10px;
        }

        .feature-badge {
            display: inline-block;
            background: #181818;
            border: 1px solid #2a2a2a;
            color: #aaa;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.7rem;
            font-weight: 500;
            margin: 2px 4px 2px 0;
        }
        .feature-badge i {
            margin-right: 4px;
            color: #555;
        }

        .multi-hint {
            background: #111;
            border: 1px solid #2a2a2a;
            border-radius: 8px;
            padding: 8px 12px;
            font-size: 0.7rem;
            color: #777;
            text-align: center;
            margin-top: 8px;
        }

        /* ── lists ── */
        .active-list,
        .accounts-list {
            max-height: 180px;
            overflow-y: auto;
            margin-top: 10px;
        }
        .active-item {
            background: #121212;
            padding: 10px 14px;
            margin: 6px 0;
            border-radius: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-left: 3px solid #444;
        }
        .active-item .uid {
            font-family: 'Inter', monospace;
            font-weight: 600;
            font-size: 0.9rem;
            color: #ddd;
        }
        .active-item .meta {
            font-size: 0.65rem;
            color: #666;
            margin-top: 2px;
        }
        .active-item.smart-item {
            border-left-color: #444477;
        }

        .stop-small {
            background: #1f1f1f;
            border: 1px solid #333;
            color: #cc6666;
            padding: 4px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.7rem;
            font-weight: 600;
            transition: 0.15s;
            font-family: 'Inter', sans-serif;
        }
        .stop-small:hover {
            background: #2a1a1a;
            border-color: #662222;
        }

        .account-item {
            background: #111;
            padding: 5px 12px;
            margin: 3px 0;
            border-radius: 6px;
            font-family: 'Inter', monospace;
            font-size: 0.7rem;
            color: #999;
            border: 1px solid #1e1e1e;
        }
        .account-item i {
            margin-right: 6px;
            color: #555;
        }

        /* ── misc ── */
        .copyright {
            text-align: center;
            color: #444;
            font-size: 0.6rem;
            margin-top: 20px;
            letter-spacing: 0.05em;
        }
        .copyright i {
            color: #555;
        }

        ::-webkit-scrollbar {
            width: 4px;
        }
        ::-webkit-scrollbar-track {
            background: #111;
        }
        ::-webkit-scrollbar-thumb {
            background: #333;
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #444;
        }
    </style>
</head>
<body>

    <div class="app">

        <!-- HEADER -->
        <div class="header">
            <div class="badge">
                <span><i class="fa-regular fa-circle"></i> ULTIMATE</span>
                <span><i class="fa-regular fa-circle"></i> MULTI-TARGET</span>
                <span><i class="fa-regular fa-circle"></i> v7.0</span>
            </div>
            <h1>
                KAWSAR
                <span>SPAM</span>
            </h1>
            <div class="badge" style="margin-top:8px;">
                <span><i class="fa-regular fa-user"></i> 3/5/6 INVITE</span>
                <span><i class="fa-regular fa-star"></i> V-BADGE</span>
                <span><i class="fa-regular fa-brain"></i> SMART</span>
                <span><i class="fa-regular fa-layer-group"></i> MULTI</span>
            </div>
        </div>

        <!-- AUTO UIDs -->
        <div class="card">
            <div class="card-header">
                <div class="icon"><i class="fa-regular fa-file-lines"></i></div>
                <div class="title">
                    <h3>AUTO UIDs (auto_uid.txt)</h3>
                    <p>সব UID তে একসাথে স্প্যাম</p>
                </div>
            </div>
            <textarea id="autoUidsText" rows="3" placeholder="এক লাইনে একটি UID&#10;1234567890&#10;0987654321"></textarea>
            <div class="flex-buttons">
                <button class="btn btn-success" onclick="saveAutoUids()"><i class="fa-regular fa-floppy-disk"></i> SAVE</button>
                <button class="btn btn-smart" onclick="startAutoSpam()"><i class="fa-regular fa-brain"></i> START SMART</button>
                <button class="btn btn-danger" onclick="stopAutoSpam()"><i class="fa-regular fa-stop"></i> STOP ALL</button>
            </div>
        </div>

        <!-- INVITE UIDs -->
        <div class="card">
            <div class="card-header">
                <div class="icon"><i class="fa-regular fa-user-plus"></i></div>
                <div class="title">
                    <h3>INVITE UIDs (inv_uid.txt)</h3>
                    <p>এই UID গুলো ইনভাইট পাবে</p>
                </div>
            </div>
            <textarea id="inviteUidsText" rows="2" placeholder="এক লাইনে একটি UID"></textarea>
            <div class="flex-buttons">
                <button class="btn btn-primary" onclick="saveInviteUids()"><i class="fa-regular fa-floppy-disk"></i> SAVE INVITE</button>
            </div>
        </div>

        <!-- TARGET -->
        <div class="card">
            <div class="card-header">
                <div class="icon"><i class="fa-regular fa-bullseye"></i></div>
                <div class="title">
                    <h3>TARGET UIDs</h3>
                    <p>কমা (,) বা স্পেস দিয়ে আলাদা করুন</p>
                </div>
            </div>

            <div class="mode-toggle">
                <div id="normalModeBtn" class="mode-btn active" onclick="setMode('normal')"><i class="fa-regular fa-fire"></i> NORMAL</div>
                <div id="smartModeBtn" class="mode-btn smart-mode" onclick="setMode('smart')"><i class="fa-regular fa-brain"></i> SMART</div>
            </div>

            <input type="text" id="startUid" class="plain-input" placeholder="1234567890, 0987654321, 1122334455" style="padding:14px 16px;" />

            <div class="multi-hint">
                <i class="fa-regular fa-circle-info"></i> একাধিক UID: কমা বা স্পেস দিয়ে আলাদা করুন
            </div>

            <div class="flex-buttons">
                <button class="btn btn-primary" onclick="startSpam()"><i class="fa-regular fa-play"></i> START</button>
                <button class="btn btn-smart" onclick="checkAndStartSmart()"><i class="fa-regular fa-search"></i> CHECK &amp; START</button>
            </div>
        </div>

        <!-- STOP -->
        <div class="card">
            <div class="card-header">
                <div class="icon"><i class="fa-regular fa-stop"></i></div>
                <div class="title">
                    <h3>STOP SPAM</h3>
                    <p>একটি বা সব টার্গেট বন্ধ করুন</p>
                </div>
            </div>
            <input type="text" id="stopUid" class="plain-input" placeholder="UID to stop" style="padding:14px 16px;" />
            <div class="flex-buttons">
                <button class="btn btn-danger" onclick="stopSpam()"><i class="fa-regular fa-power-off"></i> STOP</button>
                <button class="btn btn-warning" onclick="stopAllSpam()"><i class="fa-regular fa-stop-circle"></i> STOP ALL</button>
            </div>
        </div>

        <!-- CONSOLE & STATUS -->
        <div class="card">
            <div class="card-header">
                <div class="icon"><i class="fa-regular fa-terminal"></i></div>
                <div class="title">
                    <h3>Console &amp; Status</h3>
                    <p>Live logs</p>
                </div>
            </div>

            <div class="console-box" id="consoleBox">
                <div><span class="time">[System]</span> <span class="info">KAWSAR SPAM · B&amp;W ready</span></div>
                <div><span class="time">[System]</span> <span class="info">Multi‑target support enabled</span></div>
                <div><span class="time">[System]</span> <span class="info">Auto‑refresh every 7 min</span></div>
            </div>

            <div class="badge-info">
                <i class="fa-regular fa-star"></i> V‑BADGE + PRO_BADGE + CRAFTLAND + MODERATOR
            </div>

            <div class="status-badge">
                <span class="status-dot"></span>
                <span>STATUS: <span id="statusText">IDLE</span></span>
            </div>

            <div class="badge-info smart-badge">
                <i class="fa-regular fa-brain"></i> SMART MONITORING: <span id="smartCount">0</span> targets
            </div>

            <div class="refresh-badge">
                <i class="fa-regular fa-clock"></i> Auto‑refresh every 7 minutes
            </div>
        </div>

        <!-- FEATURES -->
        <div class="card">
            <div class="card-header">
                <div class="icon"><i class="fa-regular fa-star"></i></div>
                <div class="title">
                    <h3>SPAM FEATURES</h3>
                    <p>What's included</p>
                </div>
            </div>
            <div style="display:flex; flex-wrap:wrap; gap:6px;">
                <span class="feature-badge"><i class="fa-regular fa-door-open"></i> Room Join</span>
                <span class="feature-badge"><i class="fa-regular fa-users"></i> 3‑Player</span>
                <span class="feature-badge"><i class="fa-regular fa-users"></i> 5‑Player</span>
                <span class="feature-badge"><i class="fa-regular fa-users"></i> 6‑Player</span>
                <span class="feature-badge"><i class="fa-regular fa-medal"></i> V‑Badge</span>
                <span class="feature-badge"><i class="fa-regular fa-trophy"></i> PRO Badge</span>
                <span class="feature-badge"><i class="fa-regular fa-hammer"></i> CRAFTLAND</span>
                <span class="feature-badge"><i class="fa-regular fa-shield"></i> MODERATOR</span>
                <span class="feature-badge"><i class="fa-regular fa-brain"></i> Smart Monitor</span>
                <span class="feature-badge"><i class="fa-regular fa-chart-line"></i> Status Check</span>
                <span class="feature-badge"><i class="fa-regular fa-layer-group"></i> Multi‑Target</span>
            </div>
        </div>

        <!-- ACTIVE TARGETS -->
        <div class="card">
            <div class="card-header">
                <div class="icon"><i class="fa-regular fa-list"></i></div>
                <div class="title">
                    <h3>ACTIVE TARGETS</h3>
                    <p>সক্রিয় টার্গেট</p>
                </div>
            </div>
            <div id="activeSpamList" class="active-list">
                <div style="color:#555; font-size:0.75rem;">📭 No active targets</div>
            </div>
        </div>

        <!-- SMART MONITORED -->
        <div class="card">
            <div class="card-header">
                <div class="icon"><i class="fa-regular fa-brain"></i></div>
                <div class="title">
                    <h3>SMART MONITORED</h3>
                    <p>স্মার্ট মনিটরে থাকা টার্গেট</p>
                </div>
            </div>
            <div id="smartMonitoredList" class="active-list">
                <div style="color:#555; font-size:0.75rem;">📭 No smart monitored targets</div>
            </div>
        </div>

        <!-- CONNECTED ACCOUNTS -->
        <div class="card">
            <div class="card-header">
                <div class="icon"><i class="fa-regular fa-user"></i></div>
                <div class="title">
                    <h3>CONNECTED ACCOUNTS</h3>
                    <p>অনলাইন অ্যাকাউন্ট</p>
                </div>
            </div>
            <div id="accountsList" class="accounts-list">
                <div style="color:#555; font-size:0.75rem;">Loading…</div>
            </div>
        </div>

        <div class="copyright">
            KAWSAR SPAM · B&amp;W <i class="fa-regular fa-heart"></i> v7.0 &bull; Multi‑target
        </div>
    </div>

    <script>
        // ─────────────────────────────────────────────
        //  STATE
        // ─────────────────────────────────────────────
        let currentMode = 'normal';

        // ─────────────────────────────────────────────
        //  LOG
        // ─────────────────────────────────────────────
        function logToConsole(message, type = 'info') {
            const box = document.getElementById('consoleBox');
            const now = new Date();
            const time = now.toLocaleTimeString();
            const line = document.createElement('div');
            line.innerHTML = `<span class="time">[${time}]</span> <span class="${type}">${message}</span>`;
            box.appendChild(line);
            box.scrollTop = box.scrollHeight;
            if (box.children.length > 80) box.removeChild(box.children[0]);
        }

        // ─────────────────────────────────────────────
        //  MODE
        // ─────────────────────────────────────────────
        function setMode(mode) {
            currentMode = mode;
            document.getElementById('normalModeBtn').classList.toggle('active', mode === 'normal');
            document.getElementById('smartModeBtn').classList.toggle('active', mode === 'smart');
            logToConsole(`🔄 ${mode.toUpperCase()} mode active`, 'info');
        }

        // ─────────────────────────────────────────────
        //  API HELPERS
        // ─────────────────────────────────────────────
        async function fetchJSON(url, options = {}) {
            const res = await fetch(url, {
                ...options,
                headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
            });
            return res.json();
        }

        // ─────────────────────────────────────────────
        //  AUTO UIDs
        // ─────────────────────────────────────────────
        async function loadAutoUids() {
            try {
                const data = await fetchJSON('/api/auto-uids');
                if (data.success && data.uids) {
                    document.getElementById('autoUidsText').value = data.uids.join('\n');
                }
            } catch (_) { /* ignore */ }
        }

        async function saveAutoUids() {
            const text = document.getElementById('autoUidsText').value;
            const uids = text.split('\n').filter(l => l.trim() && /^\d+$/.test(l.trim())).map(l => l.trim());
            try {
                const data = await fetchJSON('/api/auto-uids', {
                    method: 'POST',
                    body: JSON.stringify({ uids })
                });
                if (data.success) logToConsole(`✅ ${uids.length} UID saved to auto_uid.txt`, 'success');
            } catch (e) {
                logToConsole(`❌ ${e.message}`, 'error');
            }
        }

        // ─────────────────────────────────────────────
        //  INVITE UIDs
        // ─────────────────────────────────────────────
        async function loadInviteUids() {
            try {
                const data = await fetchJSON('/api/invite-uids');
                if (data.success && data.uids) {
                    document.getElementById('inviteUidsText').value = data.uids.join('\n');
                }
            } catch (_) { /* ignore */ }
        }

        async function saveInviteUids() {
            const text = document.getElementById('inviteUidsText').value;
            const uids = text.split('\n').filter(l => l.trim() && /^\d+$/.test(l.trim())).map(l => l.trim());
            try {
                const data = await fetchJSON('/api/invite-uids', {
                    method: 'POST',
                    body: JSON.stringify({ uids })
                });
                if (data.success) logToConsole(`✅ ${uids.length} UID saved to inv_uid.txt`, 'success');
            } catch (e) {
                logToConsole(`❌ ${e.message}`, 'error');
            }
        }

        // ─────────────────────────────────────────────
        //  AUTO SPAM
        // ─────────────────────────────────────────────
        async function startAutoSpam() {
            try {
                const data = await fetchJSON('/api/start-auto', { method: 'POST' });
                if (data.success) {
                    logToConsole(`🧠 ${data.message}`, 'smart');
                    refreshStatus();
                } else {
                    logToConsole(`❌ ${data.message}`, 'error');
                }
            } catch (e) {
                logToConsole(`❌ ${e.message}`, 'error');
            }
        }

        async function stopAutoSpam() {
            try {
                const data = await fetchJSON('/api/stop-auto', { method: 'POST' });
                if (data.success) {
                    logToConsole(`✅ ${data.message}`, 'success');
                    refreshStatus();
                }
            } catch (e) {
                logToConsole(`❌ ${e.message}`, 'error');
            }
        }

        // ─────────────────────────────────────────────
        //  SMART CHECK & START
        // ─────────────────────────────────────────────
        async function checkAndStartSmart() {
            const raw = document.getElementById('startUid').value.trim();
            if (!raw) { logToConsole('❌ Enter target UID(s)', 'error'); return; }

            let uids = [];
            if (raw.includes(',')) uids = raw.split(',').map(u => u.trim()).filter(u => /^\d+$/.test(u));
            else if (raw.includes(' ')) uids = raw.split(' ').map(u => u.trim()).filter(u => /^\d+$/.test(u));
            else uids = [raw];

            if (!uids.length) { logToConsole('❌ Invalid UID(s)', 'error'); return; }

            for (const uid of uids) {
                logToConsole(`🔍 Checking ${uid} ...`, 'info');
                try {
                    const data = await fetchJSON('/api/check-status', {
                        method: 'POST',
                        body: JSON.stringify({ uid })
                    });
                    if (data.success) {
                        const s = data.data;
                        logToConsole(`📊 ${uid}: ${s.status} · online: ${s.is_online}`, 'smart');
                        if (s.is_online && s.status !== 'INGAME' && s.status !== 'MATCHMAKING') {
                            await startSmartSpam(uid);
                        } else {
                            logToConsole(`⏸️ ${uid} status ${s.status} → smart monitor start`, 'warning');
                            await startSmartSpam(uid);
                        }
                    }
                } catch (e) {
                    logToConsole(`❌ ${e.message}`, 'error');
                }
            }
        }

        async function startSmartSpam(uid) {
            try {
                const data = await fetchJSON('/api/start', {
                    method: 'POST',
                    body: JSON.stringify({ uid, smart: true })
                });
                if (data.success) {
                    logToConsole(`🧠 ${data.message}`, 'smart');
                    refreshStatus();
                } else {
                    logToConsole(`❌ ${data.message}`, 'error');
                }
            } catch (e) {
                logToConsole(`❌ ${e.message}`, 'error');
            }
        }

        // ─────────────────────────────────────────────
        //  START SPAM (normal / smart)
        // ─────────────────────────────────────────────
        async function startSpam() {
            const raw = document.getElementById('startUid').value.trim();
            if (!raw) { logToConsole('❌ Enter target UID(s)', 'error'); return; }

            let uids = [];
            if (raw.includes(',')) uids = raw.split(',').map(u => u.trim()).filter(u => /^\d+$/.test(u));
            else if (raw.includes(' ')) uids = raw.split(' ').map(u => u.trim()).filter(u => /^\d+$/.test(u));
            else uids = [raw];

            if (!uids.length) { logToConsole('❌ Invalid UID(s)', 'error'); return; }

            if (currentMode === 'smart') {
                for (const uid of uids) await startSmartSpam(uid);
                return;
            }

            logToConsole(`🚀 Starting spam on ${uids.length} target(s): ${uids.join(', ')}`, 'info');
            try {
                const data = await fetchJSON('/api/start', {
                    method: 'POST',
                    body: JSON.stringify({ uid: raw, smart: false })
                });
                if (data.success) {
                    logToConsole(`✅ ${data.message}`, 'success');
                    document.getElementById('startUid').value = '';
                    refreshStatus();
                } else {
                    logToConsole(`❌ ${data.message}`, 'error');
                }
            } catch (e) {
                logToConsole(`❌ ${e.message}`, 'error');
            }
        }

        // ─────────────────────────────────────────────
        //  STOP
        // ─────────────────────────────────────────────
        async function stopSpam() {
            const uid = document.getElementById('stopUid').value.trim();
            if (!uid) { logToConsole('❌ Enter UID to stop', 'error'); return; }
            logToConsole(`🛑 Stopping ${uid} ...`, 'info');
            try {
                const data = await fetchJSON('/api/stop', {
                    method: 'POST',
                    body: JSON.stringify({ uid, smart: true })
                });
                if (data.success) {
                    logToConsole(`✅ ${data.message}`, 'success');
                    document.getElementById('stopUid').value = '';
                    refreshStatus();
                } else {
                    logToConsole(`❌ ${data.message}`, 'error');
                }
            } catch (e) {
                logToConsole(`❌ ${e.message}`, 'error');
            }
        }

        async function stopAllSpam() {
            if (!confirm('⚠️ Stop ALL spam & monitors?')) return;
            logToConsole(`🛑 Stopping all ...`, 'info');
            try {
                const data = await fetchJSON('/api/stop-all', { method: 'POST', body: '{}' });
                if (data.success) {
                    logToConsole(`✅ ${data.message}`, 'success');
                    refreshStatus();
                } else {
                    logToConsole(`❌ ${data.message}`, 'error');
                }
            } catch (e) {
                logToConsole(`❌ ${e.message}`, 'error');
            }
        }

        // ─────────────────────────────────────────────
        //  REFRESH STATUS
        // ─────────────────────────────────────────────
        async function refreshStatus() {
            try {
                const data = await fetchJSON('/api/status');
                if (!data.success || !data.data) return;
                const s = data.data;

                // active targets
                const activeEl = document.getElementById('activeSpamList');
                if (s.active_targets && s.active_targets.length) {
                    document.getElementById('statusText').innerHTML =
                        `<i class="fa-regular fa-bolt"></i> SPAMMING: ${s.active_targets.length} targets`;
                    activeEl.innerHTML = s.active_targets.map(t => `
                        <div class="active-item">
                            <div>
                                <div class="uid">🎯 ${t.uid}</div>
                                <div class="meta">♾️ UNLIMITED · ${t.elapsed_minutes} min</div>
                            </div>
                            <button class="stop-small" onclick="stopFromList('${t.uid}')">STOP</button>
                        </div>
                    `).join('');
                } else {
                    document.getElementById('statusText').innerHTML = `<i class="fa-regular fa-check"></i> IDLE`;
                    activeEl.innerHTML = `<div style="color:#555;font-size:0.75rem;">📭 No active targets</div>`;
                }

                // smart monitored
                const smartEl = document.getElementById('smartMonitoredList');
                if (s.smart_monitored && s.smart_monitored.length) {
                    document.getElementById('smartCount').textContent = s.smart_monitored.length;
                    smartEl.innerHTML = s.smart_monitored.map(item => `
                        <div class="active-item smart-item">
                            <div>
                                <div class="uid">🧠 ${item.uid}</div>
                                <div class="meta" style="color:#8888bb;">status: ${item.status || 'checking...'}</div>
                            </div>
                            <button class="stop-small" onclick="stopFromList('${item.uid}')">STOP</button>
                        </div>
                    `).join('');
                } else {
                    document.getElementById('smartCount').textContent = '0';
                    smartEl.innerHTML = `<div style="color:#555;font-size:0.75rem;">📭 No smart monitored targets</div>`;
                }

                // accounts
                const accEl = document.getElementById('accountsList');
                if (s.accounts_list && s.accounts_list.length) {
                    let html = s.accounts_list.slice(0, 50).map(acc =>
                        `<div class="account-item"><i class="fa-regular fa-user"></i> ${acc}</div>`
                    ).join('');
                    if (s.accounts_count > 50) {
                        html += `<div class="account-item" style="color:#555;">… and ${s.accounts_count - 50} more</div>`;
                    }
                    accEl.innerHTML = html;
                } else {
                    accEl.innerHTML = `<div style="color:#555;font-size:0.75rem;">⚠️ No accounts connected</div>`;
                }

                if (s.auto_active) {
                    logToConsole(`🧠 Auto-spam active: ${s.auto_uids?.length || 0} targets`, 'smart');
                }
            } catch (_) { /* ignore */ }
        }

        // ─────────────────────────────────────────────
        //  STOP FROM LIST
        // ─────────────────────────────────────────────
        async function stopFromList(uid) {
            document.getElementById('stopUid').value = uid;
            await stopSpam();
        }

        // ─────────────────────────────────────────────
        //  INIT
        // ─────────────────────────────────────────────
        loadAutoUids();
        loadInviteUids();
        refreshStatus();
        setInterval(refreshStatus, 3000);

        // Enter key shortcuts
        document.getElementById('startUid').addEventListener('keydown', e => { if (e.key === 'Enter') startSpam(); });
        document.getElementById('stopUid').addEventListener('keydown', e => { if (e.key === 'Enter') stopSpam(); });
    </script>

</body>
</html>
'''

# ==================== MAIN ====================
def main():
    print(f"""
    {C}{BOLD}
    ╔══════════════════════════════════════════════════════════════════════╗
    ║              🎯 KAWSAR SPAM ULTIMATE MULTI-TARGET 🎯                  ║
    ║                                                                      ║
    ║     📁 auto_uid.txt  → SMART MONITORED (স্ট্যাটাস দেখে স্প্যাম)      ║
    ║     📁 inv_uid.txt   → ACTIVE TARGETS (সরাসরি স্প্যাম)               ║
    ║                                                                      ║
    ║     ✅ 3/5/6 প্লেয়ার গ্রুপ ইনভাইট                                  ║
    ║     ✅ V-BADGE + PRO_BADGE + CRAFTLAND + MODERATOR জয়িন             ║
    ║     ✅ স্মার্ট মনিটরিং - স্ট্যাটাস দেখে অটো স্প্যাম                  ║
    ║     ✅ প্রতি ৭ মিনিটে অটো রিফ্রেশ                                    ║
    ║                                                                      ║
    ║     🌐 ওয়েব প্যানেল: http://127.0.0.1:5000                         ║
    ║     👑 ডেভেলপার: KAWSAR                                             ║
    ╚══════════════════════════════════════════════════════════════════════╝
    {RS}
    """)
    
    # Load files
    load_auto_uids()
    load_invite_uids()
    
    # Start accounts
    Thread(target=run_accounts, daemon=True).start()
    
    # Start auto refresh timer
    start_auto_refresh()
    
    # Start auto spam
    start_auto_spam()
    
    port = int(os.environ.get("PORT", 4543))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

if __name__ == "__main__":
    try:
        import aiohttp
    except ImportError:
        os.system("pip install aiohttp")
    
    main()