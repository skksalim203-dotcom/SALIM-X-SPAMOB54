import requests, os, psutil, sys, jwt, pickle, json, binascii, time, urllib3, xKEys, base64, datetime, re, socket, threading
import asyncio
from protobuf_decoder.protobuf_decoder import Parser
from byte import *
from byte import xSEndMsg
from byte import Auth_Chat
from xHeaders import *
from datetime import datetime
from google.protobuf.timestamp_pb2 import Timestamp
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from flask import Flask, request, jsonify
from black9 import openroom, spmroom

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  

# Global variables
connected_clients = {}
connected_clients_lock = threading.Lock()
active_spam_targets = {}
active_spam_lock = threading.Lock()
auto_spam_watchers = {}
auto_spam_lock = threading.Lock()

app = Flask(__name__)

# ==================== AUTO SPAM CHECKER (UID STATUS MONITOR) ====================

_ID = '4781242366'
_PW = 'EB29A9E13607F90EFA783D5A92EDC553F7A87C8540FFD3F12B8AB50AF2C499A1'
_TTL = 6 * 60 * 60
_cx = {}

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

def _rdVr(data, pos):
    n = 0; sh = 0
    while True:
        b = data[pos]; pos += 1
        n |= (b & 0x7F) << sh; sh += 7
        if not b & 0x80: break
    return n, pos

def _pbF(data):
    out = {}; pos = 0
    while pos < len(data):
        try:
            tag, pos = _rdVr(data, pos)
            fn = tag >> 3; wt = tag & 0x7
            if wt == 0:
                v, pos = _rdVr(data, pos); out[fn] = v
            elif wt == 2:
                ln, pos = _rdVr(data, pos); out[fn] = data[pos:pos+ln]; pos += ln
            elif wt == 1:
                out[fn] = data[pos:pos+8]; pos += 8
            elif wt == 5:
                out[fn] = data[pos:pos+4]; pos += 4
            else: break
        except: break
    return out

async def _vr(n):
    h = []
    while True:
        b = n & 0x7F; n >>= 7
        if n: b |= 0x80
        h.append(b)
        if not n: break
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
        if isinstance(v, dict): p.extend(await _len(f, await _pb(v)))
        elif isinstance(v, int): p.extend(await _var(f, v))
        elif isinstance(v, (str, bytes)): p.extend(await _len(f, v))
    return p

async def _pk(px, n, k, v):
    e = await _enc(px, k, v)
    _ = await _hx(len(e) // 2)
    m = {2:'000000', 3:'00000', 4:'0000', 5:'000'}
    return bytes.fromhex(n + m.get(len(_), '000000') + _ + e)

async def _fix(rs):
    d = {}
    for r in rs:
        fd = {'wire_type': r.wire_type}
        if r.wire_type in ('varint', 'string', 'bytes'): fd['data'] = r.data
        elif r.wire_type == 'length_delimited': fd['data'] = await _fix(r.data.results)
        d[r.field] = fd
    return d

async def _parse(hx):
    try: return json.dumps(await _fix(Parser().parse(hx)))
    except: return None

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
    if '5' not in data or 'data' not in data['5']: return {'status': 'OFFLINE'}
    jd = data['5']['data']
    if '1' not in jd or 'data' not in jd['1']: return {'status': 'OFFLINE'}
    d = jd['1']['data']
    if '3' not in d or 'data' not in d['3']: return {'status': 'OFFLINE'}
    st = d['3']['data']
    gc = d.get('9', {}).get('data', 0)
    cm = d.get('10', {}).get('data', 0) + 1 if '10' in d else 0
    go = d.get('8', {}).get('data', 0)
    tg = d.get('4', {}).get('data', 0)
    m5 = d.get('5', {}).get('data')
    m6 = d.get('6', {}).get('data')
    mn = sc = 0
    if tg:
        a, b = _tdiff(tg).split(':'); mn = int(a); sc = int(b)
    if st == 4:
        return {'status': 'IN_ROOM', 'room_uid': d.get('15', {}).get('data'),
                'players': f"{d.get('17',{}).get('data',0)}/{d.get('18',{}).get('data',0)}",
                'room_owner': d.get('1', {}).get('data')}
    base = {1:'SOLO', 2:'INSQUAD', 3:'INGAME', 5:'INGAME', 7:'MATCHMAKING', 6:'SOCIAL_ISLAND'}.get(st, 'OFFLINE')
    mode = None
    f14 = d.get('14', {}).get('data')
    if f14 == 1: mode = 'TRAINING'
    elif f14 == 2: mode = 'SOCIAL_ISLAND'
    mm = {(2,1):'BR_RANK',(5,23):'TRAINING',(6,15):'CS_RANK',(1,43):'LONE_WOLF',
          (1,1):'BERMUDA',(1,15):'CLASH_SQUAD',(1,29):'CONVOY_CRUNCH',(1,61):'FREE_FOR_ALL'}
    if (m5, m6) in mm: mode = mm[(m5, m6)]
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
    mm = {1:'BERMUDA',201:'BATTLE_CAGE',15:'CLASH_SQUAD',43:'LONE_WOLF',3:'RUSH_HOUR',27:'BOMB_SQUAD_5V5',24:'DEATH_MATCH'}
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
        try: chunk = await asyncio.wait_for(reader.read(65536), timeout=timeout)
        except asyncio.TimeoutError: break
        if not chunk: break
        buf += chunk
    return buf

async def _scan(buf, k, v):
    h = buf.hex()
    for mk, pt in [('0f00','0f'),('0e00','0e')]:
        i = h.find(mk)
        if i != -1 and i % 2 == 0: return pt, h[i + 10:]
    if len(buf) > 5:
        pl = buf[5:]; pl = pl[:len(pl) - (len(pl) % 16)]
        if len(pl) >= 16:
            try:
                dc = unpad(AES.new(k, AES.MODE_CBC, v).decrypt(pl), 16).hex()
                for mk, pt in [('0f00','0f'),('0e00','0e')]:
                    i = dc.find(mk)
                    if i != -1 and i % 2 == 0: return pt, dc[i + 10:]
            except: pass
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
    hd = {9:'0000000',8:'00000000',10:'000000',7:'000000000'}.get(len(uh),'0000000')
    e = await _enc(tok.encode().hex(), k, v)
    el = await _hx(len(e) // 2)
    return f"0115{hd}{uh}{await _hx(ts)}00000{el}{e}"

async def _login():
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    
    sx = ssl.create_default_context()
    sx.check_hostname = False; sx.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession() as s:
        async with s.post('https://100067.connect.garena.com/oauth/guest/token/grant', headers=_Hr,
            data={'uid':_ID, 'password':_PW, 'response_type':'token', 'client_type':'2',
                  'client_secret':'2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3',
                  'client_id':'100067'}, ssl=sx) as r:
            if r.status != 200: raise Exception(f"OAuth {r.status}")
            d = await r.json()
            oid = d['open_id']; atk = d['access_token']

    raw = await _mkLogin(oid, atk)
    ep  = AES.new(b'Yg&tc%DEuh6%Zc^8', AES.MODE_CBC, b'6oyZDr22E3ychjM%').encrypt(pad(raw, 16))

    async with aiohttp.ClientSession() as s:
        async with s.post('https://loginbp.ggpolarbear.com/MajorLogin', data=ep, headers=_Hr, ssl=sx) as r:
            if r.status != 200: raise Exception(f"MajorLogin {r.status}")
            mr = await r.read()

    mlr = _pbF(mr)
    tok = mlr[8].decode()
    tgt = mlr[1]
    k   = mlr[22]
    v   = mlr[23]
    ts  = mlr[21]
    url = mlr[10].decode()

    h2 = {**_Hr, 'Authorization': f'Bearer {tok}'}
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{url}/GetLoginData", data=ep, headers=h2, ssl=sx) as r:
            if r.status != 200: raise Exception(f"GetLoginData {r.status}")
            lr = await r.read()

    ld = _pbF(lr)
    ip, port = ld[14].decode().split(':')
    at = await _auth(int(tgt), tok, int(ts), k, v)
    return {'account_id':tgt,'token':tok,'key':k,'iv':v,'ip':ip,'port':int(port),'auth':at,'exp':time.time()+_TTL}

def _sess():
    global _cx
    if 's' in _cx and _cx['s'] and time.time() < _cx['s']['exp']:
        return _cx['s']
    _cx['s'] = asyncio.run(_login())
    return _cx['s']

async def _query(uid, sx):
    rd, wr = await asyncio.open_connection(sx['ip'], sx['port'])
    try:
        wr.write(bytes.fromhex(sx['auth'])); await wr.drain()
        await _rAll(rd, timeout=3)
        pkt = await _stPkt(uid, sx['key'], sx['iv'])
        wr.write(pkt); await wr.drain()
        buf = await _rAll(rd, timeout=5)
        if not buf: return {'status': 'NO_RESPONSE'}
        pt, pl = await _scan(buf, sx['key'], sx['iv'])
        if pt == '0f':
            raw = await _parse(pl)
            if not raw: return {'status': 'PARSE_ERROR'}
            info = _pStatus(raw)
            if info.get('status') == 'IN_ROOM':
                wr.write(await _rmPkt(int(info['room_uid']), sx['key'], sx['iv'])); await wr.drain()
                rb = await _rAll(rd, timeout=5)
                if rb:
                    rt, rp = await _scan(rb, sx['key'], sx['iv'])
                    if rt == '0e':
                        rr = await _parse(rp)
                        if rr: info['room_info'] = _pRoom(rr)
            return info
        elif pt == '0e':
            raw = await _parse(pl)
            return _pRoom(raw) if raw else {'status': 'PARSE_ERROR'}
        return {'status': 'UNKNOWN', 'buf': buf.hex()[:120]}
    finally:
        wr.close()
        try: await wr.wait_closed()
        except: pass

def check_user_status(uid):
    """Check user status (SOLO, INSQUAD, IN_ROOM, INGAME, OFFLINE)"""
    try:
        session = _sess()
        result = asyncio.run(_query(int(uid), session))
        return result
    except Exception as e:
        print(f"Status check error for {uid}: {e}")
        return {'status': 'ERROR', 'error': str(e)}

def should_spam_target(status):
    """Check if target should be spammed based on status"""
    spam_statuses = ['SOLO', 'INSQUAD', 'IN_ROOM']
    current_status = status.get('status', 'OFFLINE')
    return current_status in spam_statuses

# ==================== AUTO SPAM WATCHER ====================

class AutoSpamWatcher:
    def __init__(self, target_id, check_interval=5):
        self.target_id = target_id
        self.check_interval = check_interval
        self.running = False
        self.thread = None
        self.currently_spamming = False
        self.last_status = None
        
    def start(self):
        if self.running:
            return False
        self.running = True
        self.thread = threading.Thread(target=self._watch_loop, daemon=True)
        self.thread.start()
        print(f"🤖 Auto spam watcher started for: {self.target_id}")
        return True
        
    def stop(self):
        self.running = False
        if self.currently_spamming:
            self._stop_spam()
        print(f"🛑 Auto spam watcher stopped for: {self.target_id}")
        return True
        
    def _start_spam(self):
        with active_spam_lock:
            if self.target_id not in active_spam_targets:
                active_spam_targets[self.target_id] = {
                    'active': True,
                    'start_time': datetime.now(),
                    'duration': None,
                    'auto_mode': True
                }
                threading.Thread(target=spam_worker, args=(self.target_id, None), daemon=True).start()
                self.currently_spamming = True
                print(f"🚀 Auto spam STARTED for: {self.target_id}")
                
    def _stop_spam(self):
        with active_spam_lock:
            if self.target_id in active_spam_targets:
                del active_spam_targets[self.target_id]
                self.currently_spamming = False
                print(f"⏸️ Auto spam STOPPED for: {self.target_id}")
                
    def _watch_loop(self):
        while self.running:
            try:
                status = check_user_status(self.target_id)
                self.last_status = status
                
                current_status = status.get('status', 'OFFLINE')
                
                print(f"📊 [{self.target_id}] Status: {current_status}")
                
                if should_spam_target(status):
                    if not self.currently_spamming:
                        self._start_spam()
                else:
                    if self.currently_spamming:
                        self._stop_spam()
                        
            except Exception as e:
                print(f"⚠️ Watcher error for {self.target_id}: {e}")
                
            time.sleep(self.check_interval)

# ==================== API CLASS ====================

class SimpleAPI:
    def __init__(self):
        self.running = True
        
    def process_spam_command(self, target_id, duration_minutes=None):
        try:
            if not ChEck_Commande(target_id):
                return {"status": "error", "message": "user_id Invalid"}
                
            with active_spam_lock:
                if target_id not in active_spam_targets:
                    active_spam_targets[target_id] = {
                        'active': True,
                        'start_time': datetime.now(),
                        'duration': duration_minutes,
                        'auto_mode': False
                    }
                    threading.Thread(target=spam_worker, args=(target_id, duration_minutes), daemon=True).start()
                    message = f"The spam was started on the user: {target_id}"
                    if duration_minutes:
                        message += f" for {duration_minutes} minutes"
                    return {"status": "success", "message": message}
                else:
                    return {"status": "error", "message": f"Spam is already working on the user: {target_id}"}
                    
        except Exception as e:
            return {"status": "error", "message": f"Error in handling the matter: {str(e)}"}
            
    def process_stop_command(self, target_id):
        try:
            # First stop auto watcher if exists
            with auto_spam_lock:
                if target_id in auto_spam_watchers:
                    auto_spam_watchers[target_id].stop()
                    del auto_spam_watchers[target_id]
                    
            with active_spam_lock:
                if target_id in active_spam_targets:
                    del active_spam_targets[target_id]
                    message = f"Spam has been disabled for the user: {target_id}"
                    return {"status": "success", "message": message}
                else:
                    return {"status": "error", "message": f"There is no active spam on user: {target_id}"}
                    
        except Exception as e:
            return {"status": "error", "message": f"Error in handling the matter: {str(e)}"}
    
    def process_auto_spam_command(self, target_id, check_interval=5):
        """Start auto spam mode - automatically checks status and spams when target is available"""
        try:
            if not ChEck_Commande(target_id):
                return {"status": "error", "message": "user_id Invalid"}
                
            with auto_spam_lock:
                if target_id in auto_spam_watchers:
                    return {"status": "error", "message": f"Auto spam already running on: {target_id}"}
                    
                watcher = AutoSpamWatcher(target_id, check_interval)
                auto_spam_watchers[target_id] = watcher
                watcher.start()
                
            return {"status": "success", "message": f"Auto spam started on: {target_id} (checks every {check_interval}s)"}
            
        except Exception as e:
            return {"status": "error", "message": f"Error: {str(e)}"}
    
    def process_stop_auto_spam_command(self, target_id):
        """Stop auto spam mode for a target"""
        try:
            with auto_spam_lock:
                if target_id in auto_spam_watchers:
                    auto_spam_watchers[target_id].stop()
                    del auto_spam_watchers[target_id]
                    return {"status": "success", "message": f"Auto spam stopped for: {target_id}"}
                else:
                    return {"status": "error", "message": f"No auto spam running on: {target_id}"}
                    
        except Exception as e:
            return {"status": "error", "message": f"Error: {str(e)}"}
    
    def check_status(self, target_id):
        """Check a user's current status"""
        try:
            status = check_user_status(target_id)
            return {"status": "success", "data": status}
        except Exception as e:
            return {"status": "error", "message": str(e)}
            
    def get_system_status(self):
        try:
            with active_spam_lock:
                active_targets = list(active_spam_targets.keys())
                active_targets_info = []
                for target_id in active_targets:
                    info = active_spam_targets[target_id]
                    auto_mode = "🔁 AUTO" if info.get('auto_mode', False) else "🎮 MANUAL"
                    duration_info = ""
                    if info.get('duration'):
                        elapsed = datetime.now() - info['start_time']
                        remaining = info['duration'] * 60 - elapsed.total_seconds()
                        if remaining > 0:
                            duration_info = f" ({int(remaining/60)} min left)"
                    active_targets_info.append(f"{target_id}{duration_info} [{auto_mode}]")
                    
            with auto_spam_lock:
                auto_targets = list(auto_spam_watchers.keys())
                
            with connected_clients_lock:
                accounts_count = len(connected_clients)
                accounts_list = list(connected_clients.keys())
                
            status_data = {
                "active_spam_count": len(active_targets),
                "active_spam_targets": active_targets_info,
                "auto_spam_count": len(auto_targets),
                "auto_spam_targets": auto_targets,
                "connected_accounts_count": accounts_count,
                "connected_accounts": accounts_list
            }
            
            return {"status": "success", "data": status_data}
            
        except Exception as e:
            return {"status": "error", "message": f"Error: {str(e)}"}

def spam_worker(target_id, duration_minutes=None):
    print(f"🎯 Start spam on target: {target_id}" + (f" for {duration_minutes} minutes" if duration_minutes else ""))
    
    start_time = datetime.now()
    
    while True:
        with active_spam_lock:
            if target_id not in active_spam_targets:
                print(f"🛑 Spam stopped on target: {target_id}")
                break
                
            if duration_minutes:
                elapsed = datetime.now() - start_time
                if elapsed.total_seconds() >= duration_minutes * 60:
                    print(f"⏰ Spam duration ended on: {target_id}")
                    del active_spam_targets[target_id]
                    break
                
        try:
            send_spam_from_all_accounts(target_id)
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ Spam error on {target_id}: {e}")
            time.sleep(1)

def send_spam_from_all_accounts(target_id):
    with connected_clients_lock:
        for account_id, client in connected_clients.items():
            try:
                if (hasattr(client, 'CliEnts2') and client.CliEnts2 and 
                    hasattr(client, 'key') and client.key and 
                    hasattr(client, 'iv') and client.iv):
                    
                    try:
                        client.CliEnts2.send(openroom(client.key, client.iv))
                    except Exception as e:
                        pass
                    
                    for i in range(10):
                        try:
                            client.CliEnts2.send(spmroom(client.key, client.iv, target_id))
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            break
                        except Exception:
                            break
            except Exception:
                pass

# ==================== FLASK API ENDPOINTS ====================

api = SimpleAPI()

@app.route('/spam', methods=['GET'])
def start_spam():
    target_id = request.args.get('user_id')
    duration = request.args.get('duration', type=int)
    
    if not target_id:
        return jsonify({"status": "error", "message": "Please enter user_id"})
    
    result = api.process_spam_command(target_id, duration)
    return jsonify(result)

@app.route('/stop', methods=['GET'])
def stop_spam():
    target_id = request.args.get('user_id')
    
    if not target_id:
        return jsonify({"status": "error", "message": "Please enter user_id"})
    
    result = api.process_stop_command(target_id)
    return jsonify(result)

@app.route('/auto', methods=['GET'])
def start_auto_spam():
    """Start auto spam mode - automatically checks status and spams when target is available"""
    target_id = request.args.get('user_id')
    interval = request.args.get('interval', 5, type=int)
    
    if not target_id:
        return jsonify({"status": "error", "message": "Please enter user_id"})
    
    if interval < 3:
        interval = 3
    if interval > 30:
        interval = 30
        
    result = api.process_auto_spam_command(target_id, interval)
    return jsonify(result)

@app.route('/auto/stop', methods=['GET'])
def stop_auto_spam():
    target_id = request.args.get('user_id')
    
    if not target_id:
        return jsonify({"status": "error", "message": "Please enter user_id"})
    
    result = api.process_stop_auto_spam_command(target_id)
    return jsonify(result)

@app.route('/check', methods=['GET'])
def check_user():
    """Check a user's current status"""
    target_id = request.args.get('user_id')
    
    if not target_id:
        return jsonify({"status": "error", "message": "Please enter user_id"})
    
    result = api.check_status(target_id)
    return jsonify(result)

@app.route('/status', methods=['GET'])
def get_status():
    result = api.get_system_status()
    return jsonify(result)

@app.route('/accounts', methods=['GET'])
def get_accounts():
    try:
        with connected_clients_lock:
            accounts_count = len(connected_clients)
            accounts_list = list(connected_clients.keys())
            
        accounts_data = {
            "connected_accounts_count": accounts_count,
            "connected_accounts": accounts_list
        }
        
        return jsonify({"status": "success", "data": accounts_data})
        
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error: {str(e)}"})

@app.route('/')
def home():
    return """
    <h1>🤖 Free Fire Auto Spam System</h1>
    <h2>🎮 Endpoints:</h2>
    <ul>
        <li><strong>Manual Spam:</strong> GET /spam?user_id=123&amp;duration=5</li>
        <li><strong>Stop Manual:</strong> GET /stop?user_id=123</li>
        <li><strong>🤖 AUTO SPAM:</strong> GET /auto?user_id=123&amp;interval=5</li>
        <li><strong>🛑 Stop Auto:</strong> GET /auto/stop?user_id=123</li>
        <li><strong>🔍 Check Status:</strong> GET /check?user_id=123</li>
        <li><strong>📊 System Status:</strong> GET /status</li>
        <li><strong>👥 Connected Accounts:</strong> GET /accounts</li>
    </ul>
    <h3>📌 Auto Spam Features:</h3>
    <ul>
        <li>✅ Automatically checks user status every X seconds</li>
        <li>✅ Spams when user is: SOLO, INSQUAD, or IN_ROOM</li>
        <li>✅ Stops automatically when user is: OFFLINE or INGAME</li>
        <li>✅ Restarts automatically when user comes back online</li>
    </ul>
    """

# ==================== MAIN ====================

def run_api():
    print("🌐 Starting API on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False)

def AuTo_ResTartinG():
    time.sleep(6 * 60 * 60)
    print('\n🔄 Auto Restarting Bot...')
    p = psutil.Process(os.getpid())
    for handler in p.open_files():
        try:
            os.close(handler.fd)
        except Exception:
            pass
    for conn in p.net_connections():
        try:
            if hasattr(conn, 'fd'):
                os.close(conn.fd)
        except Exception:
            pass
    sys.path.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    python = sys.executable
    os.execl(python, python, *sys.argv)

def ResTarT_BoT():
    print('\n🔄 Restarting Bot...')
    p = psutil.Process(os.getpid())
    open_files = p.open_files()
    connections = p.net_connections()
    for handler in open_files:
        try:
            os.close(handler.fd)
        except Exception:
            pass           
    for conn in connections:
        try:
            conn.close()
        except Exception:
            pass
    sys.path.append(os.path.dirname(os.path.abspath(sys.argv[0])))
    python = sys.executable
    os.execl(python, python, *sys.argv)

def GeT_Time(timestamp):
    last_login = datetime.fromtimestamp(timestamp)
    now = datetime.now()
    diff = now - last_login   
    d = diff.days
    h , rem = divmod(diff.seconds, 3600)
    m , s = divmod(rem, 60)    
    return d, h, m, s

def Time_En_Ar(t): 
    return ' '.join(t.replace("Day","يوم").replace("Hour","ساعة").replace("Min","دقيقة").replace("Sec","ثانية").split(" - "))
    
Thread(target=AuTo_ResTartinG, daemon=True).start()

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
                        if len(parts) >= 2:
                            account_id = parts[0].strip()
                            password = parts[1].strip()
                            accounts.append({'id': account_id, 'password': password})
                    else:
                        accounts.append({'id': line.strip(), 'password': ''})
        print(f"📦 Loaded {len(accounts)} accounts from {filename}")
    except FileNotFoundError:
        print(f"⚠️ File {filename} not found!")
    except Exception as e:
        print(f"❌ Error reading file: {e}")
    return accounts

ACCOUNTS = load_accounts_from_file()

# Import missing modules
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    import aiohttp
    import ssl
except ImportError:
    print("⚠️ Installing required modules...")
    os.system("pip install pycryptodome aiohttp")
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    import aiohttp
    import ssl

class FF_CLient():

    def __init__(self, id, password):
        self.id = id
        self.password = password
        self.key = None
        self.iv = None
        self.Get_FiNal_ToKen_0115()     
            
    def Connect_SerVer_OnLine(self , Token , tok , host , port , key , iv , host2 , port2):
            try:
                self.AutH_ToKen_0115 = tok    
                self.CliEnts2 = socket.create_connection((host2 , int(port2)))
                self.CliEnts2.send(bytes.fromhex(self.AutH_ToKen_0115))                  
            except:pass        
            while True:
                try:
                    self.DaTa2 = self.CliEnts2.recv(99999)
                    if '0500' in self.DaTa2.hex()[0:4] and len(self.DaTa2.hex()) > 30:	         	    	    
                            self.packet = json.loads(DeCode_PackEt(f'08{self.DaTa2.hex().split("08", 1)[1]}'))
                            self.AutH = self.packet['5']['data']['7']['data']
                    
                except:pass    	
                                                            
    def Connect_SerVer(self , Token , tok , host , port , key , iv , host2 , port2):
            self.AutH_ToKen_0115 = tok    
            self.CliEnts = socket.create_connection((host , int(port)))
            self.CliEnts.send(bytes.fromhex(self.AutH_ToKen_0115))  
            self.DaTa = self.CliEnts.recv(1024)          	        
            threading.Thread(target=self.Connect_SerVer_OnLine, args=(Token , tok , host , port , key , iv , host2 , port2)).start()
            self.Exemple = xMsGFixinG('12345678')
            
            
            self.key = key
            self.iv = iv
            
            
            with connected_clients_lock:
                connected_clients[self.id] = self
                print(f" Account registered {self.id} In the global list, the number of accounts now: {len(connected_clients)}")
            
            while True:      
                try:
                    self.DaTa = self.CliEnts.recv(1024)   
                    if len(self.DaTa) == 0 or (hasattr(self, 'DaTa2') and len(self.DaTa2) == 0):	            		
                        try:            		    
                            self.CliEnts.close()
                            if hasattr(self, 'CliEnts2'):
                                self.CliEnts2.close()
                            self.Connect_SerVer(Token , tok , host , port , key , iv , host2 , port2)                    		                    
                        except:
                            try:
                                self.CliEnts.close()
                                if hasattr(self, 'CliEnts2'):
                                    self.CliEnts2.close()
                                self.Connect_SerVer(Token , tok , host , port , key , iv , host2 , port2)
                            except:
                                self.CliEnts.close()
                                if hasattr(self, 'CliEnts2'):
                                    self.CliEnts2.close()
                                ResTarT_BoT()	            
                                      
        	 	 
                                                               
                    if '/pp/' in self.input_msg[:4]:
                        self.target_id = self.input_msg[4:]	 
                        self.Zx = ChEck_Commande(self.target_id)
                        if True == self.Zx:	            		     
                            
                            threading.Thread(target=send_spam_from_all_accounts, args=(self.target_id,)).start()
                            time.sleep(2.5)    			         
                            self.CliEnts.send(xSEndMsg(f'\n[b][c][{ArA_CoLor()}] SuccEss Spam To {xMsGFixinG(self.target_id)} From All Accounts\n', 2 , self.DeCode_CliEnt_Uid , self.DeCode_CliEnt_Uid , key , iv))
                            time.sleep(1.3)
                            self.CliEnts.close()
                            if hasattr(self, 'CliEnts2'):
                                self.CliEnts2.close()
                            self.Connect_SerVer(Token , tok , host , port , key , iv , host2 , port2)	            		      	
                        elif False == self.Zx: 
                            self.CliEnts.send(xSEndMsg(f'\n[b][c][{ArA_CoLor()}] - PLease Use /pp/<id>\n - Ex : /pp/{self.Exemple}\n', 2 , self.DeCode_CliEnt_Uid , self.DeCode_CliEnt_Uid , key , iv))	
                            time.sleep(1.1)
                            self.CliEnts.close()
                            if hasattr(self, 'CliEnts2'):
                                self.CliEnts2.close()
                            self.Connect_SerVer(Token , tok , host , port , key , iv , host2 , port2)	            		

                except Exception as e:
                    print(f"Error in Connect_SerVer: {e}")
                    try:
                        self.CliEnts.close()
                        if hasattr(self, 'CliEnts2'):
                            self.CliEnts2.close()
                    except:
                        pass
                    self.Connect_SerVer(Token , tok , host , port , key , iv , host2 , port2)
                                    
    def GeT_Key_Iv(self , serialized_data):
        my_message = xKEys.MyMessage()
        my_message.ParseFromString(serialized_data)
        timestamp , key , iv = my_message.field21 , my_message.field22 , my_message.field23
        timestamp_obj = Timestamp()
        timestamp_obj.FromNanoseconds(timestamp)
        timestamp_seconds = timestamp_obj.seconds
        timestamp_nanos = timestamp_obj.nanos
        combined_timestamp = timestamp_seconds * 1_000_000_000 + timestamp_nanos
        return combined_timestamp , key , iv    

    def Guest_GeneRaTe(self , uid , password):
        self.url = "https://100067.connect.garena.com/oauth/guest/token/grant"
        self.headers = {"Host": "100067.connect.garena.com","User-Agent": "GarenaMSDK/4.0.19P4(G011A ;Android 9;en;US;)","Content-Type": "application/x-www-form-urlencoded","Accept-Encoding": "gzip, deflate, br","Connection": "close",}
        self.dataa = {"uid": f"{uid}","password": f"{password}","response_type": "token","client_type": "2","client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3","client_id": "100067",}
        try:
            self.response = requests.post(self.url, headers=self.headers, data=self.dataa).json()
            self.Access_ToKen , self.Access_Uid = self.response['access_token'] , self.response['open_id']
            time.sleep(0.2)
            print(' - Starting RIZER Freind BoT !')
            print(f' - Uid : {uid}\n - Password : {password}')
            print(f' - Access Token : {self.Access_ToKen}\n - Access Id : {self.Access_Uid}')
            return self.ToKen_GeneRaTe(self.Access_ToKen , self.Access_Uid)
        except Exception as e: 
            print(f"Error in Guest_GeneRaTe: {e}")
            time.sleep(10)
            return self.Guest_GeneRaTe(uid, password)
                                        
    def GeT_LoGin_PorTs(self , JwT_ToKen , PayLoad):
        self.UrL = 'https://clientbp.ggblueshark.com/GetLoginData'
        self.HeadErs = {
            'Expect': '100-continue',
            'Authorization': f'Bearer {JwT_ToKen}',
            'X-Unity-Version': '2022.3.47f1',
            'X-GA': 'v1 1',
            'ReleaseVersion': 'OB54',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'UnityPlayer/2022.3.47f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
        
            'Connection': 'close',
            'Accept-Encoding': 'deflate, gzip',}        
        try:
                self.Res = requests.post(self.UrL , headers=self.HeadErs , data=PayLoad , verify=False)
                self.BesTo_data = json.loads(DeCode_PackEt(self.Res.content.hex()))  
          
                address , address2 = self.BesTo_data['32']['data'] , self.BesTo_data['14']['data'] 
                ip , ip2 = address[:len(address) - 6] , address2[:len(address) - 6]
                port , port2 = address[len(address) - 5:] , address2[len(address2) - 5:]             
                return ip , port , ip2 , port2          
        except requests.RequestException as e:
                print(f" - Bad Requests !")
        print(" - Failed To GeT PorTs !")
        return None, None, None, None
        
    def ToKen_GeneRaTe(self , Access_ToKen , Access_Uid):
        self.UrL = "https://loginbp.ggblueshark.com/MajorLogin"
        self.HeadErs = {
            'X-Unity-Version': '2022.3.47f1',
            'ReleaseVersion': 'OB54',
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-GA': 'v1 1',
            'Content-Length': '928',
            'User-Agent': 'UnityPlayer/2022.3.47f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
            'Host': 'loginbp.ggblueshark.com',
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'deflate, gzip'}   
        
        
        self.dT = bytes.fromhex('1a13323032352d31312d32362030313a35313a3238220966726565206669726528013a07312e3132332e314232416e64726f6964204f532039202f204150492d3238202850492f72656c2e636a772e32303232303531382e313134313333294a0848616e6468656c64520c4d544e2f537061636574656c5a045749464960800a68d00572033234307a2d7838362d3634205353453320535345342e3120535345342e32204156582041565832207c2032343030207c20348001e61e8a010f416472656e6f2028544d292036343092010d4f70656e474c20455320332e329a012b476f6f676c657c36323566373136662d393161372d343935622d396631362d303866653964336336353333a2010e3137362e32382e3133392e313835aa01026172b201203433303632343537393364653836646134323561353263616164663231656564ba010134c2010848616e6468656c64ca010d4f6e65506c7573204135303130ea014063363961653230386661643732373338623637346232383437623530613361316466613235643161313966616537343566633736616334613065343134633934f00101ca020c4d544e2f537061636574656cd2020457494649ca03203161633462383065636630343738613434323033626638666163363132306635e003b5ee02e8039a8002f003af13f80384078004a78f028804b5ee029004a78f029804b5ee02b00404c80401d2043d2f646174612f6170702f636f6d2e6474732e667265656669726574682d66705843537068495636644b43376a4c2d574f7952413d3d2f6c69622f61726de00401ea045f65363261623933353464386662356662303831646233333861636233333439317c2f646174612f6170702f636f6d2e6474732e667265656669726574682d66705843537068495636644b43376a4c2d574f7952413d3d2f626173652e61706bf00406f804018a050233329a050a32303139313139303236a80503b205094f70656e474c455332b805ff01c00504e005be7eea05093372645f7061727479f205704b717348543857393347646347335a6f7a454e6646775648746d377171316552554e6149444e67526f626f7a4942744c4f695943633459367a767670634943787a514632734f453463627974774c7334785a62526e70524d706d5752514b6d654f35766373386e51594268777148374bf805e7e4068806019006019a060134a2060134b2062213521146500e590349510e460900115843395f005b510f685b560a6107576d0f0366')
        
       
        self.dT = self.dT.replace(b'2026-07-30 14:11:20' , str(datetime.now())[:-7].encode())        
        self.dT = self.dT.replace(b'c69ae208fad72738b674b2847b50a3a1dfa25d1a19fae745fc76ac4a0e414c94' , Access_ToKen.encode())
        self.dT = self.dT.replace(b'4306245793de86da425a52caadf21eed' , Access_Uid.encode())
        
        try:
            
            hex_data = self.dT.hex()
            encoded_data = EnC_AEs(hex_data)
            
            
            if not all(c in '0123456789abcdefABCDEF' for c in encoded_data):
                print(" Invalid hex output from EnC_AEs, using alternative encoding")
                
                encoded_data = hex_data  
            
            self.PaYload = bytes.fromhex(encoded_data)
        except Exception as e:
            print(f" Error in encoding: {e}")
            
            self.PaYload = self.dT
        
        self.ResPonse = requests.post(self.UrL, headers = self.HeadErs ,  data = self.PaYload , verify=False)        
        if self.ResPonse.status_code == 200 and len(self.ResPonse.text) > 10:
            try:
                self.BesTo_data = json.loads(DeCode_PackEt(self.ResPonse.content.hex()))
                self.JwT_ToKen = self.BesTo_data['8']['data']           
                self.combined_timestamp , self.key , self.iv = self.GeT_Key_Iv(self.ResPonse.content)
                ip , port , ip2 , port2 = self.GeT_LoGin_PorTs(self.JwT_ToKen , self.PaYload)            
                return self.JwT_ToKen , self.key , self.iv, self.combined_timestamp , ip , port , ip2 , port2
            except Exception as e:
                print(f" Error parsing response: {e}")
                time.sleep(5)
                return self.ToKen_GeneRaTe(Access_ToKen, Access_Uid)
        else:
            print(f" Error in ToKen_GeneRaTe, status: {self.ResPonse.status_code}")
            time.sleep(5)
            return self.ToKen_GeneRaTe(Access_ToKen, Access_Uid)
      
    def Get_FiNal_ToKen_0115(self):
        try:
            result = self.Guest_GeneRaTe(self.id , self.password)
            if not result:
                print(" Failed to get tokens, retrying...")
                time.sleep(5)
                return self.Get_FiNal_ToKen_0115()
                
            token , key , iv , Timestamp , ip , port , ip2 , port2 = result
            
            if not all([ip, port, ip2, port2]):
                print(" Failed to get ports, retrying...")
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
                print(f' ProxCed Uid : {self.AccounT_Uid}')
            except Exception as e:
                print(f" Error In ToKen : {e}")
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
                else:
                    print('Unexpected length encountered')                
                self.Header = f'0115{self.__}{self.EncoDed_AccounT}{self.TimE_HEx}00000{self.Header}'
                self.FiNal_ToKen_0115 = self.Header + EnC_PacKeT(self.JwT_ToKen_ , key , iv)
            except Exception as e:
                print(f" Error In Final Token : {e}")
                time.sleep(5)
                return self.Get_FiNal_ToKen_0115()
                
            self.AutH_ToKen = self.FiNal_ToKen_0115
            self.Connect_SerVer(self.JwT_ToKen , self.AutH_ToKen , ip , port , key , iv , ip2 , port2)        
            return self.AutH_ToKen , key , iv
            
        except Exception as e:
            print(f" Error in Get_FiNal_ToKen_0115: {e}")
            time.sleep(10)
            return self.Get_FiNal_ToKen_0115()

def start_account(account):
    try:
        print(f"🚀 Starting account: {account['id']}")
        FF_CLient(account['id'], account['password'])
    except Exception as e:
        print(f"❌ Error starting {account['id']}: {e}")
        time.sleep(5)
        start_account(account)

def StarT_SerVer():
    print("=" * 50)
    print("   🤖 FREE FIRE AUTO SPAM BOT")
    print("=" * 50)
    print(f"📦 Loaded {len(ACCOUNTS)} accounts")
    print("🌐 Starting API on http://0.0.0.0:5000")
    print("=" * 50)
    
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    
    threads = []
    for account in ACCOUNTS:
        thread = threading.Thread(target=start_account, args=(account,))
        thread.daemon = True
        threads.append(thread)
        thread.start()
        time.sleep(3)
    
    for thread in threads:
        thread.join()
  
StarT_SerVer()