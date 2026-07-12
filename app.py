import os, sys, time, json, ssl, socket, threading, asyncio, random
from datetime import datetime
from threading import Thread
from flask import Flask, request, jsonify
import requests
import urllib3
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from google.protobuf.timestamp_pb2 import Timestamp
# আপনার কাস্টম মডিউল (একই ফোল্ডারে থাকতে হবে)
from byte import *
from byte import xSEndMsg, Auth_Chat
from xHeaders import *
from black9 import openroom, spmroom
import xKEys
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== গ্লোবাল ====================
connected_clients = {}
connected_clients_lock = threading.Lock()
active_spam_targets = {}       # {uid: start_time}
spam_running = False
spam_thread = None
targets = []                   # inv_uid.txt থেকে লোড
app = Flask(__name__)
C = "\033[96m"; G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; RS = "\033[0m"; BOLD = "\033[1m"
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
GROUP_CONFIGS = {3: {"type": 1}, 5: {"type": 2}, 6: {"type": 3}}

# ==================== ফাইল লোডার ====================
def load_targets(filename="inv_uid.txt"):
    global targets
    uids = []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                uid = line.strip()
                if uid and not uid.startswith("#") and uid.isdigit():
                    uids.append(uid)
        targets = uids
        print(f"{G}📦 Loaded {len(targets)} targets from {filename}{RS}")
    except FileNotFoundError:
        print(f"{Y}⚠️ {filename} not found, creating...{RS}")
        with open(filename, "w") as f:
            f.write("# Target UIDs, one per line\n")
        targets = []
    return targets
load_targets("inv_uid.txt")

def save_targets(uids, filename="inv_uid.txt"):
    global targets
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("# Target UIDs, one per line\n")
            for uid in uids:
                f.write(f"{uid}\n")
        targets = uids
        print(f"{G}💾 Saved {len(uids)} targets to {filename}{RS}")
    except Exception as e:
        print(f"{R}❌ Save error: {e}{RS}")

# ==================== প্যাকেট ক্রিয়েটর ====================
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

def create_badge_invite_packet(key, iv, target_uid, badge_value, players=5, region="BD"):
    """ইনভাইট + ব্যাজ (যা কাজ করে)"""
    try:
        proto_fields = {
            1: 2,
            2: {
                1: int(target_uid),
                2: region.upper(),
                4: players,
                31: {1: 1, 2: badge_value},
                32: badge_value
            }
        }
        packet = create_proto_sync(proto_fields).hex()
        if region.lower() == "ind": packet_type = "0514"
        elif region.lower() == "bd": packet_type = "0519"
        else: packet_type = "0515"
        encrypted = EnC_PacKeT(packet, key, iv)
        length = len(encrypted) // 2
        len_hex = DecodE_HeX(length)
        padding_map = {2: "000000", 3: "00000", 4: "0000", 5: "000"}
        padding = padding_map.get(len(len_hex), "000")
        return bytes.fromhex(packet_type + padding + len_hex + encrypted)
    except Exception as e:
        print(f"{R}❌ Badge invite packet error: {e}{RS}")
        return None

def create_group_invite_packet(key, iv, target_uid, players=5, region="BD"):
    """সাধারণ ইনভাইট (৩/৫/৬)"""
    try:
        group_type = GROUP_CONFIGS[players]["type"]
        proto_fields = {
            1: 2,
            2: {
                1: int(target_uid),
                2: region.upper(),
                4: players,
                # ৩১ ও ৩২ না দিলে শুধু ইনভাইট
            }
        }
        packet = create_proto_sync(proto_fields).hex()
        if region.lower() == "ind": packet_type = "0514"
        elif region.lower() == "bd": packet_type = "0519"
        else: packet_type = "0515"
        encrypted = EnC_PacKeT(packet, key, iv)
        length = len(encrypted) // 2
        len_hex = DecodE_HeX(length)
        padding_map = {2: "000000", 3: "00000", 4: "0000", 5: "000"}
        padding = padding_map.get(len(len_hex), "000")
        return bytes.fromhex(packet_type + padding + len_hex + encrypted)
    except Exception as e:
        print(f"{R}❌ Group invite packet error: {e}{RS}")
        return None

# ==================== স্প্যাম ওয়ার্কার ====================
def spam_worker():
    global spam_running, active_spam_targets
    print(f"\n{G}🚀 SPAM WORKER STARTED{RS}")
    total_requests = 0
    round_num = 0
    last_keepalive = time.time()

    def run_async(coro):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        except:
            return None
        finally:
            loop.close()

    while spam_running:
        with connected_clients_lock:
            # মৃত ক্লায়েন্ট বাদ দিন
            active_clients = []
            for cid, client in list(connected_clients.items()):
                try:
                    if client.CliEnts2 and client.CliEnts2.fileno() != -1:
                        active_clients.append(client)
                    else:
                        del connected_clients[cid]
                except:
                    del connected_clients[cid]
            clients = active_clients

        if not clients:
            time.sleep(2)
            continue

        # কিপ-অ্যালাইভ (openroom) – প্রতি ২৫ সেকেন্ডে
        if time.time() - last_keepalive > 25:
            for client in clients:
                try:
                    pkt = openroom(client.key, client.iv)
                    if pkt:
                        client.CliEnts2.send(pkt)
                except:
                    pass
            last_keepalive = time.time()

        # বর্তমান টার্গেট লোড (ফাইল থেকে পড়া, যাতে রানটাইমে পরিবর্তন হয়)
        current_targets = targets[:]  # কপি

        if not current_targets:
            time.sleep(5)
            continue

        round_num += 1
        for target in current_targets:
            for client in clients:
                try:
                    if hasattr(client, 'CliEnts2') and client.key:
                        # 1. ব্যাজ ইনভাইট (৫ প্লেয়ার) – সব ব্যাজ পাঠাবে
                        for badge_name, badge_val in BADGES.items():
                            pkt = create_badge_invite_packet(client.key, client.iv, target, badge_val, players=5)
                            if pkt:
                                client.CliEnts2.send(pkt)
                                total_requests += 1
                                time.sleep(0.08)  # ধীর গতি

                        # 2. সাধারণ ইনভাইট (৩, ৫, ৬) – যদি চান
                        for players in [3, 5, 6]:
                            pkt = create_group_invite_packet(client.key, client.iv, target, players=players)
                            if pkt:
                                client.CliEnts2.send(pkt)
                                total_requests += 1
                                time.sleep(0.08)

                        # 3. রুম স্প্যাম (ঐচ্ছিক)
                        try:
                            open_pkt = openroom(client.key, client.iv)
                            if open_pkt:
                                client.CliEnts2.send(open_pkt)
                            spam_pkt = spmroom(client.key, client.iv, target)
                            if spam_pkt:
                                client.CliEnts2.send(spam_pkt)
                                total_requests += 1
                        except:
                            pass

                except Exception as e:
                    print(f"{R}❌ Send error to {target}: {e}{RS}")
                    # এই ক্লায়েন্ট মৃত – বাদ দিন
                    with connected_clients_lock:
                        if client.id in connected_clients:
                            del connected_clients[client.id]
                time.sleep(0.05)

        if round_num % 5 == 0:
            print(f"{C}📊 Round {round_num} | Total req: {total_requests} | Targets: {len(current_targets)} | Bots: {len(clients)}{RS}")

        time.sleep(0.5)

    print(f"{R}🛑 SPAM WORKER STOPPED{RS}")

# ==================== অ্যাকাউন্ট ম্যানেজার ====================
ACCOUNTS = []
def load_accounts(filename="accs.txt"):
    global ACCOUNTS
    loaded = []
    try:
        if not os.path.exists(filename):
            with open(filename, "w") as f:
                f.write("# UID:PASSWORD\n")
            return []
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if ":" in line:
                        uid, pwd = line.split(":", 1)
                    else:
                        uid, pwd = line, ""
                    if uid.isdigit():
                        loaded.append({'id': uid, 'password': pwd})
        print(f"{G}📦 Loaded {len(loaded)} accounts from {filename}{RS}")
    except Exception as e:
        print(f"{R}❌ Error loading accounts: {e}{RS}")
    ACCOUNTS = loaded
    return ACCOUNTS
load_accounts("accs.txt")

# ==================== FF CLIENT (সংক্ষিপ্ত) ====================
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
        self.dT = bytes.fromhex('1a13323032352d31312d32362030313a35313a3238220966726565206669726528013a07312e3132362e314232416e64726f6964204f532039202f204150492d3238202850492f72656c2e636a772e32303232303531382e313134313333294a0848616e6468656c64520c4d544e2f537061636574656c5a045749464960800a68d00572033234307a2d7838362d3634205353453320535345342e3120535345342e32204156582041565832207c2032343030207c20348001e61e8a010f416472656e6f2028544d292036343092010d4f70656e474c20455320332e329a012b476f6f676c657c36323566373136662d393161372d343935622d396631362d303866653964336336353333a2010e3137362e32382e3133392e313835aa01026172b201203433303632343537393364653836646134323561353263616164663231656564ba010134c2010848616e6468656c64ca010d4f6e65506c7573204135303130ea014063363961653230386661643732373338623637346232383437623530613361316466613235643161313966616537343566633736616334613065343134633934f00101ca020c4d544e2f537061636574656cd2020457494649ca03203161633462383065636630343738613434323033626638666163363132306635e003b5ee02e8039a8002f003af13f80384078004a78f028804b5ee029004a78f029804b5ee02b00404c80401d2043d2f646174612f6170702f636f6d2e6474732e667265656669726574682d66705843537068495636644b43376a4c2d574f7952413d3d2f6c69622f61726de00401ea045f65363261623935333464386662356662303831646233333861636233333439317c2f646174612f6170702f636f6d2e6474732e667265656669726574682d66705843537068495636644b43376a4c2d574f7952413d3d2f626173652e61706bf00406f804018a050233329a050a32303139313139303236a80503b205094f70656e474c455332b805ff01c00504e005be7eea05093372645f7061727479f205704b717348543857393347646347335a6f7a454e6646775648746d377171316552554e6149444e67526f626f7a4942744c4f695943633459367a767670634943787a514632734f453463627974774c7334785a62526e70524d706d5752514b6d654f35766373386e51594268777148374bf805e7e4068806019006019a060134a2060134b2062213521146500e590349510e460900115843395f005b510f685b560a6107576d0f0366')
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

# ==================== স্প্যাম কন্ট্রোল ফাংশন ====================
def start_spam():
    global spam_running, spam_thread
    if spam_running:
        return False, "Spam already running"
    if not targets:
        return False, "No targets found in inv_uid.txt"
    spam_running = True
    spam_thread = Thread(target=spam_worker, daemon=True)
    spam_thread.start()
    return True, "Spam started"

def stop_spam():
    global spam_running
    spam_running = False
    return True, "Spam stopped"

def add_targets(new_uids):
    global targets
    added = []
    for uid in new_uids:
        if uid not in targets and uid.isdigit():
            targets.append(uid)
            added.append(uid)
    if added:
        save_targets(targets)
    return added

def remove_target(uid):
    global targets
    if uid in targets:
        targets.remove(uid)
        save_targets(targets)
        return True
    return False

# ==================== API রাউট ====================
@app.route('/status', methods=['GET'])
def status():
    with connected_clients_lock:
        acc_count = len(connected_clients)
        acc_list = list(connected_clients.keys())
    return jsonify({
        "spam_running": spam_running,
        "targets": targets,
        "active_accounts": acc_count,
        "accounts": acc_list
    })

@app.route('/start', methods=['POST'])
def api_start():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Missing JSON"}), 400
    uids = data.get('uids') or data.get('uid')
    if not uids:
        return jsonify({"success": False, "message": "Provide 'uid' or 'uids'"}), 400
    if isinstance(uids, str):
        uids = [uids]
    added = add_targets(uids)
    if added:
        if not spam_running:
            start_spam()
        return jsonify({"success": True, "added": added, "message": f"Added {len(added)} targets"})
    else:
        return jsonify({"success": False, "message": "No new valid UIDs"})

@app.route('/stop', methods=['POST'])
def api_stop():
    data = request.get_json()
    if data and data.get('uid'):
        uid = data['uid']
        if remove_target(uid):
            return jsonify({"success": True, "message": f"Removed {uid}"})
        else:
            return jsonify({"success": False, "message": f"UID {uid} not found"})
    else:
        stop_spam()
        return jsonify({"success": True, "message": "Spam stopped"})

@app.route('/stop-all', methods=['POST'])
def api_stop_all():
    stop_spam()
    return jsonify({"success": True, "message": "Spam stopped"})

@app.route('/targets', methods=['GET'])
def api_targets():
    return jsonify({"targets": targets})

@app.route('/accounts', methods=['GET'])
def api_accounts():
    with connected_clients_lock:
        return jsonify({"accounts": list(connected_clients.keys()), "count": len(connected_clients)})

@app.route('/reload-targets', methods=['POST'])
def api_reload():
    load_targets("inv_uid.txt")
    return jsonify({"success": True, "targets": targets})

# ==================== WEB INTERFACE (REDESIGNED) ====================
@app.route('/')
def index():
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SALIM ROOM SPAM</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <!-- Google Fonts: Inter + Orbitron for futuristic look -->
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=Orbitron:wght@400;600;700;900&display=swap" rel="stylesheet">
    <style>
        /* ============================================================
                   PREMIUM GLOBAL STYLES
                   ============================================================ */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        :root {
            /* Gold / Amber animated palette */
            --gold-1: #d4af37;
            --gold-2: #f9d976;
            --gold-3: #ffd700;
            --gold-4: #e6b800;
            --gold-5: #c9a32a;
            --gold-6: #f0c040;
            /* Glass */
            --glass-bg: rgba(10, 10, 20, 0.55);
            --glass-border: rgba(212, 175, 55, 0.2);
            --glass-shadow: 0 8px 32px rgba(0, 0, 0, 0.7);
            --text-primary: #f0e8d0;
            --text-secondary: rgba(240, 232, 208, 0.7);
        }

        body {
            min-height: 100vh;
            background: #0a0a0f;
            color: var(--text-primary);
            font-family: 'Inter', sans-serif;
            overflow-x: hidden;
            position: relative;
            margin: 0;
            padding: 0;
        }

        /* ============================================================
                   ANIMATED BACKGROUND LAYERS
                   ============================================================ */
        #bg-canvas {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 0;
            pointer-events: none;
            opacity: 0.6;
        }

        /* Gold Particles Canvas (new) */
        #gold-canvas {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 1;
            pointer-events: none;
            mix-blend-mode: screen;
        }

        /* Aurora Overlay */
        .aurora-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 1;
            pointer-events: none;
            background:
                radial-gradient(ellipse at 20% 50%, rgba(212, 175, 55, 0.08) 0%, transparent 60%),
                radial-gradient(ellipse at 80% 50%, rgba(255, 215, 0, 0.06) 0%, transparent 60%),
                radial-gradient(ellipse at 50% 100%, rgba(200, 150, 50, 0.04) 0%, transparent 50%);
            animation: auroraFloat 20s ease-in-out infinite alternate;
        }
        @keyframes auroraFloat {
            0% { transform: translateX(-5%) scale(1); opacity: 0.5; }
            100% { transform: translateX(5%) scale(1.1); opacity: 1; }
        }

        /* ============================================================
                   LOADING SCREEN
                   ============================================================ */
        #loading-screen {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: #0a0a0f;
            z-index: 9999;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            font-family: 'Orbitron', monospace;
            color: var(--text-primary);
            transition: opacity 1.2s ease, visibility 1.2s ease;
            pointer-events: none;
        }
        #loading-screen.hidden {
            opacity: 0;
            visibility: hidden;
        }
        #loading-screen .loader-text {
            font-size: 1.8rem;
            font-weight: 700;
            letter-spacing: 6px;
            background: linear-gradient(135deg, var(--gold-1), var(--gold-3), var(--gold-1));
            background-size: 300% 300%;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            animation: goldShift 4s ease-in-out infinite alternate;
            margin-bottom: 30px;
            text-shadow: 0 0 40px rgba(212, 175, 55, 0.3);
        }
        #loading-screen .progress-bar {
            width: 300px;
            height: 4px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 4px;
            overflow: hidden;
            box-shadow: 0 0 20px rgba(212, 175, 55, 0.2);
        }
        #loading-screen .progress-bar .fill {
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, var(--gold-1), var(--gold-3));
            border-radius: 4px;
            animation: loadProgress 3s ease-in-out forwards;
            box-shadow: 0 0 20px rgba(212, 175, 55, 0.4);
        }
        @keyframes loadProgress {
            0% { width: 0%; }
            20% { width: 30%; }
            50% { width: 65%; }
            80% { width: 85%; }
            100% { width: 100%; }
        }
        .loading-sub {
            margin-top: 18px;
            font-size: 0.9rem;
            color: rgba(240, 232, 208, 0.5);
            letter-spacing: 2px;
            font-family: 'Inter', sans-serif;
        }

        /* ============================================================
                   MAIN CONTAINER
                   ============================================================ */
        .app-container {
            position: relative;
            z-index: 2;
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px 25px 30px;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }

        /* ============================================================
                   HEADER
                   ============================================================ */
        .header {
            text-align: center;
            padding: 30px 0 20px;
            position: relative;
            margin-bottom: 30px;
            border-bottom: 1px solid rgba(212, 175, 55, 0.15);
        }
        .header::after {
            content: '';
            position: absolute;
            bottom: -1px;
            left: 10%;
            width: 80%;
            height: 2px;
            background: linear-gradient(90deg, transparent, var(--gold-3), var(--gold-1), var(--gold-3), transparent);
            filter: blur(2px);
            animation: borderGoldPulse 4s ease-in-out infinite alternate;
        }
        @keyframes borderGoldPulse {
            0% { opacity: 0.3; width: 40%; left: 30%; }
            100% { opacity: 1; width: 70%; left: 15%; }
        }

        .logo-wrapper {
            position: relative;
            display: inline-block;
        }
        .logo-glow {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 300px;
            height: 300px;
            background: radial-gradient(circle, rgba(212, 175, 55, 0.2), transparent 70%);
            border-radius: 50%;
            filter: blur(50px);
            animation: glowPulse 5s ease-in-out infinite alternate;
            pointer-events: none;
        }
        @keyframes glowPulse {
            0% { transform: translate(-50%, -50%) scale(0.8); opacity: 0.5; }
            100% { transform: translate(-50%, -50%) scale(1.3); opacity: 1; }
        }

        .header h1 {
            font-size: 3.8rem;
            font-weight: 900;
            font-family: 'Orbitron', monospace;
            background: linear-gradient(135deg, var(--gold-1), var(--gold-3), var(--gold-2), var(--gold-5), var(--gold-1));
            background-size: 400% 400%;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            animation: goldShift 12s ease-in-out infinite alternate;
            text-shadow: 0 0 60px rgba(212, 175, 55, 0.2);
            letter-spacing: 4px;
            position: relative;
        }
        @keyframes goldShift {
            0% { background-position: 0% 50%; }
            25% { background-position: 50% 0%; }
            50% { background-position: 100% 50%; }
            75% { background-position: 50% 100%; }
            100% { background-position: 0% 50%; }
        }

        .header .sub {
            font-size: 1.2rem;
            font-weight: 400;
            color: rgba(240, 232, 208, 0.5);
            letter-spacing: 6px;
            text-transform: uppercase;
            margin-top: -6px;
            font-family: 'Inter', sans-serif;
            text-shadow: 0 0 30px rgba(212, 175, 55, 0.1);
        }

        /* Rotating halo */
        .halo {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 400px;
            height: 400px;
            border-radius: 50%;
            border: 1px solid rgba(212, 175, 55, 0.1);
            animation: spin 30s linear infinite;
            pointer-events: none;
        }
        .halo::before {
            content: '';
            position: absolute;
            top: -2px;
            left: 50%;
            width: 30px;
            height: 30px;
            background: radial-gradient(circle, var(--gold-3), transparent);
            border-radius: 50%;
            transform: translateX(-50%);
            filter: blur(4px);
            animation: lensFlare 4s ease-in-out infinite alternate;
        }
        @keyframes spin {
            100% { transform: translate(-50%, -50%) rotate(360deg); }
        }
        @keyframes lensFlare {
            0% { opacity: 0.3; transform: translateX(-50%) scale(0.8); }
            100% { opacity: 1; transform: translateX(-50%) scale(1.5); }
        }

        /* ============================================================
                   STATUS BAR
                   ============================================================ */
        .status-bar {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 30px;
            margin-top: 20px;
            flex-wrap: wrap;
        }
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 28px;
            border-radius: 50px;
            background: var(--glass-bg);
            backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border);
            box-shadow: var(--glass-shadow);
            font-weight: 500;
            font-size: 0.95rem;
            transition: all 0.4s;
            position: relative;
            overflow: hidden;
        }
        .status-indicator::after {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(212, 175, 55, 0.05) 0%, transparent 60%);
            opacity: 0;
            transition: 0.6s;
        }
        .status-indicator:hover::after {
            opacity: 1;
        }
        .status-indicator:hover {
            border-color: rgba(212, 175, 55, 0.5);
            transform: translateY(-2px);
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5), 0 0 30px rgba(212, 175, 55, 0.1);
        }
        .status-dot {
            width: 14px;
            height: 14px;
            border-radius: 50%;
            display: inline-block;
            transition: 0.3s;
            box-shadow: 0 0 20px currentColor;
        }
        .status-dot.running {
            background: #00ff88;
            color: #00ff88;
            animation: pulse 1.2s infinite;
        }
        .status-dot.stopped {
            background: #ff4757;
            color: #ff4757;
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
            0% { opacity: 0.5; transform: scale(0.95); }
            50% { opacity: 1; transform: scale(1.2); }
            100% { opacity: 0.5; transform: scale(0.95); }
        }
        .status-indicator i {
            color: var(--gold-3);
            opacity: 0.7;
        }

        /* ============================================================
                   GRID – MAIN CARDS
                   ============================================================ */
        .grid-main {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 25px;
            margin-top: 10px;
        }

        /* ============================================================
                   WIDGETS ROW
                   ============================================================ */
        .widget-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 18px;
            margin-top: 25px;
        }
        .widget-card {
            background: var(--glass-bg);
            backdrop-filter: blur(12px);
            border-radius: 18px;
            padding: 16px 14px;
            border: 1px solid var(--glass-border);
            box-shadow: var(--glass-shadow);
            transition: all 0.4s;
            text-align: center;
            position: relative;
            overflow: hidden;
        }
        .widget-card::before {
            content: '';
            position: absolute;
            top: -2px;
            left: -2px;
            right: -2px;
            bottom: -2px;
            border-radius: 20px;
            background: linear-gradient(45deg, transparent, rgba(212, 175, 55, 0.05), transparent);
            z-index: -1;
            opacity: 0;
            transition: 0.4s;
        }
        .widget-card:hover {
            transform: translateY(-4px);
            border-color: rgba(212, 175, 55, 0.4);
            box-shadow: 0 15px 40px rgba(0, 0, 0, 0.6), 0 0 40px rgba(212, 175, 55, 0.05);
        }
        .widget-card:hover::before {
            opacity: 1;
        }
        .widget-card .icon {
            font-size: 1.6rem;
            color: var(--gold-3);
            margin-bottom: 6px;
            text-shadow: 0 0 20px rgba(212, 175, 55, 0.3);
        }
        .widget-card .value {
            font-size: 1.8rem;
            font-weight: 700;
            font-family: 'Orbitron', monospace;
            background: linear-gradient(135deg, var(--gold-1), var(--gold-3));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            animation: goldShift 8s ease-in-out infinite alternate;
        }
        .widget-card .label {
            font-size: 0.7rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1.5px;
            margin-top: 4px;
            font-weight: 600;
        }
        /* Animated border beam for widgets */
        .widget-card .border-beam {
            position: absolute;
            top: 0;
            left: -100%;
            width: 300%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(212, 175, 55, 0.1), transparent);
            transform: skewX(-25deg);
            animation: beamSlide 6s infinite linear;
            pointer-events: none;
        }
        @keyframes beamSlide {
            0% { left: -100%; }
            100% { left: 100%; }
        }

        /* ============================================================
                   GLASS CARD (common)
                   ============================================================ */
        .glass-card {
            background: var(--glass-bg);
            backdrop-filter: blur(12px);
            border-radius: 20px;
            padding: 24px 22px;
            border: 1px solid var(--glass-border);
            box-shadow: var(--glass-shadow);
            transition: all 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94);
            position: relative;
            overflow: hidden;
        }
        .glass-card::before {
            content: '';
            position: absolute;
            top: -2px;
            left: -2px;
            right: -2px;
            bottom: -2px;
            border-radius: 22px;
            background: linear-gradient(45deg, transparent, rgba(212, 175, 55, 0.05), transparent);
            z-index: -1;
            opacity: 0;
            transition: 0.4s;
        }
        .glass-card:hover {
            transform: translateY(-5px);
            border-color: rgba(212, 175, 55, 0.4);
            box-shadow: 0 15px 50px rgba(0, 0, 0, 0.7), 0 0 40px rgba(212, 175, 55, 0.05);
        }
        .glass-card:hover::before {
            opacity: 1;
        }
        .glass-card h3 {
            color: var(--text-primary);
            margin-bottom: 18px;
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 1.2rem;
            font-weight: 700;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 12px;
            letter-spacing: 0.5px;
        }
        .glass-card h3 i {
            color: var(--gold-3);
            text-shadow: 0 0 20px rgba(212, 175, 55, 0.3);
        }

        /* ============================================================
                   TARGET LIST
                   ============================================================ */
        .target-list {
            max-height: 200px;
            overflow-y: auto;
            margin-bottom: 12px;
            padding-right: 5px;
            scrollbar-width: thin;
            scrollbar-color: var(--gold-3) transparent;
        }
        .target-list::-webkit-scrollbar {
            width: 4px;
        }
        .target-list::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 10px;
        }
        .target-list::-webkit-scrollbar-thumb {
            background: var(--gold-3);
            border-radius: 10px;
            box-shadow: 0 0 10px var(--gold-3);
        }
        .target-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(0, 0, 0, 0.3);
            padding: 8px 14px;
            border-radius: 10px;
            margin-bottom: 6px;
            border-left: 2px solid rgba(212, 175, 55, 0.3);
            transition: all 0.3s;
            animation: slideIn 0.3s ease;
        }
        .target-item:hover {
            background: rgba(212, 175, 55, 0.05);
            border-left-color: var(--gold-3);
            box-shadow: 0 0 20px rgba(212, 175, 55, 0.05);
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateX(-15px); }
            to { opacity: 1; transform: translateX(0); }
        }
        .target-item .uid {
            color: #d0c8b0;
            font-weight: 500;
        }
        .target-item .remove-btn {
            background: none;
            border: none;
            color: #ff6b6b;
            cursor: pointer;
            font-size: 1.1rem;
            transition: 0.2s;
            padding: 4px 8px;
            border-radius: 6px;
        }
        .target-item .remove-btn:hover {
            color: #ff4757;
            background: rgba(255, 71, 87, 0.15);
            transform: scale(1.2);
        }

        /* ============================================================
                   INPUTS
                   ============================================================ */
        .input-group {
            display: flex;
            gap: 10px;
            margin-top: 12px;
            flex-wrap: wrap;
        }
        .input-group input,
        .input-group textarea {
            flex: 1;
            padding: 12px 16px;
            border: 1px solid rgba(212, 175, 55, 0.2);
            border-radius: 12px;
            background: rgba(0, 0, 0, 0.5);
            color: var(--text-primary);
            font-size: 0.9rem;
            outline: none;
            transition: 0.3s;
            min-width: 140px;
            font-weight: 400;
            backdrop-filter: blur(4px);
            font-family: 'Inter', sans-serif;
        }
        .input-group input:focus,
        .input-group textarea:focus {
            border-color: var(--gold-3);
            box-shadow: 0 0 30px rgba(212, 175, 55, 0.1), inset 0 0 20px rgba(212, 175, 55, 0.05);
            background: rgba(0, 0, 0, 0.7);
        }
        .input-group textarea {
            min-height: 60px;
            resize: vertical;
        }

        /* ============================================================
                   BUTTONS (Premium Glass + Gold)
                   ============================================================ */
        .btn {
            padding: 12px 28px;
            border: none;
            border-radius: 14px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            position: relative;
            overflow: hidden;
            background: transparent;
            color: #fff;
            border: 1px solid transparent;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            font-family: 'Inter', sans-serif;
        }
        .btn .ripple {
            position: absolute;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.3);
            transform: scale(0);
            animation: rippleAnim 0.6s linear;
            pointer-events: none;
        }
        @keyframes rippleAnim {
            to { transform: scale(4); opacity: 0; }
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--gold-1), var(--gold-3), var(--gold-5));
            background-size: 300% 300%;
            animation: goldShift 8s ease-in-out infinite alternate;
            color: #0a0a0f;
            box-shadow: 0 0 25px rgba(212, 175, 55, 0.2);
            border: 1px solid rgba(212, 175, 55, 0.3);
        }
        .btn-primary:hover {
            transform: translateY(-3px) scale(1.02);
            box-shadow: 0 10px 50px rgba(212, 175, 55, 0.4);
            border-color: var(--gold-3);
        }

        .btn-danger {
            background: linear-gradient(135deg, #ff6b6b, #ff0033);
            background-size: 300% 300%;
            animation: dangerShift 5s ease-in-out infinite alternate;
            color: #fff;
            box-shadow: 0 0 25px rgba(255, 0, 51, 0.2);
            border: 1px solid rgba(255, 0, 51, 0.3);
        }
        @keyframes dangerShift {
            0% { background-position: 0% 50%; }
            100% { background-position: 100% 50%; }
        }
        .btn-danger:hover {
            transform: translateY(-3px) scale(1.02);
            box-shadow: 0 10px 50px rgba(255, 0, 51, 0.4);
            border-color: #ff0033;
        }

        .btn-secondary {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(4px);
            color: var(--text-primary);
            border: 1px solid rgba(255, 255, 255, 0.1);
            box-shadow: 0 0 20px rgba(0, 0, 0, 0.2);
        }
        .btn-secondary:hover {
            transform: translateY(-3px) scale(1.02);
            background: rgba(255, 255, 255, 0.1);
            border-color: rgba(212, 175, 55, 0.3);
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.4);
        }

        .btn-sm {
            padding: 8px 20px;
            font-size: 0.8rem;
        }
        .btn-block {
            width: 100%;
            justify-content: center;
        }
        .btn:disabled {
            opacity: 0.4;
            cursor: not-allowed;
            transform: none !important;
            box-shadow: none !important;
        }

        .control-group {
            display: flex;
            gap: 14px;
            flex-wrap: wrap;
            margin-top: 12px;
        }
        .control-group .btn {
            flex: 1;
            min-width: 120px;
        }

        /* ============================================================
                   STATS (inside controls card)
                   ============================================================ */
        .stats {
            display: flex;
            justify-content: space-around;
            margin-top: 20px;
            gap: 10px;
        }
        .stats .stat {
            text-align: center;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 14px;
            padding: 12px 10px;
            flex: 1;
            border: 1px solid rgba(212, 175, 55, 0.05);
            transition: 0.3s;
        }
        .stats .stat:hover {
            border-color: rgba(212, 175, 55, 0.2);
            box-shadow: 0 0 30px rgba(212, 175, 55, 0.05);
        }
        .stats .stat .num {
            font-size: 2.2rem;
            font-weight: 800;
            font-family: 'Orbitron', monospace;
            background: linear-gradient(135deg, var(--gold-1), var(--gold-3));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            display: inline-block;
            transition: 0.3s;
        }
        .stats .stat .label {
            font-size: 0.7rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1.5px;
            margin-top: 4px;
            display: block;
        }

        /* ============================================================
                   ACCOUNT LIST
                   ============================================================ */
        .account-list {
            max-height: 150px;
            overflow-y: auto;
            font-size: 0.9rem;
            color: #d0c8b0;
            scrollbar-width: thin;
            scrollbar-color: var(--gold-3) transparent;
        }
        .account-list::-webkit-scrollbar {
            width: 4px;
        }
        .account-list::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.3);
            border-radius: 10px;
        }
        .account-list::-webkit-scrollbar-thumb {
            background: var(--gold-3);
            border-radius: 10px;
            box-shadow: 0 0 10px var(--gold-3);
        }
        .account-list .acc-item {
            padding: 6px 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
            transition: 0.2s;
            border-radius: 6px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .account-list .acc-item::before {
            content: '●';
            color: #00ff88;
            font-size: 0.6rem;
            text-shadow: 0 0 10px #00ff88;
            animation: pulse 2s infinite;
        }
        .account-list .acc-item:hover {
            background: rgba(212, 175, 55, 0.05);
            box-shadow: 0 0 20px rgba(212, 175, 55, 0.05);
            padding-left: 16px;
        }
        .account-list .acc-item:last-child {
            border-bottom: none;
        }

        /* ============================================================
                   AI ORB (Floating, bottom right)
                   ============================================================ */
        .ai-orb {
            position: fixed;
            bottom: 40px;
            right: 40px;
            width: 90px;
            height: 90px;
            z-index: 100;
            pointer-events: none;
            cursor: default;
        }
        .ai-orb .orb {
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: radial-gradient(circle at 30% 30%, rgba(212, 175, 55, 0.4), rgba(10, 10, 15, 0.8));
            box-shadow:
                0 0 60px rgba(212, 175, 55, 0.3),
                inset 0 0 80px rgba(212, 175, 55, 0.1);
            border: 1px solid rgba(212, 175, 55, 0.2);
            animation: orbFloat 6s ease-in-out infinite alternate, orbPulse 4s ease-in-out infinite alternate;
            transition: all 0.4s;
            backdrop-filter: blur(10px);
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .ai-orb .orb i {
            font-size: 2.4rem;
            color: var(--gold-3);
            text-shadow: 0 0 40px rgba(212, 175, 55, 0.5);
            animation: orbIconPulse 3s ease-in-out infinite alternate;
        }
        @keyframes orbFloat {
            0% { transform: translateY(0px) scale(1); }
            100% { transform: translateY(-20px) scale(1.02); }
        }
        @keyframes orbPulse {
            0% { box-shadow: 0 0 60px rgba(212, 175, 55, 0.2), inset 0 0 80px rgba(212, 175, 55, 0.05); }
            100% { box-shadow: 0 0 100px rgba(212, 175, 55, 0.5), inset 0 0 120px rgba(212, 175, 55, 0.1); }
        }
        @keyframes orbIconPulse {
            0% { transform: scale(0.9); opacity: 0.7; }
            100% { transform: scale(1.1); opacity: 1; }
        }
        .ai-orb:hover .orb {
            transform: scale(1.1);
            box-shadow: 0 0 120px rgba(212, 175, 55, 0.6);
        }

        /* ============================================================
                   SYSTEM TERMINAL (bottom left)
                   ============================================================ */
        .terminal {
            position: fixed;
            bottom: 40px;
            left: 40px;
            width: 320px;
            max-height: 200px;
            background: rgba(10, 10, 20, 0.7);
            backdrop-filter: blur(12px);
            border-radius: 16px;
            border: 1px solid rgba(212, 175, 55, 0.15);
            padding: 14px 18px;
            box-shadow: var(--glass-shadow);
            z-index: 100;
            overflow: hidden;
            font-family: 'Orbitron', monospace;
            font-size: 0.75rem;
            color: var(--text-secondary);
            pointer-events: none;
        }
        .terminal .term-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(212, 175, 55, 0.1);
            padding-bottom: 6px;
            margin-bottom: 8px;
            font-weight: 600;
            color: var(--gold-3);
            letter-spacing: 1px;
        }
        .terminal .term-header i {
            color: var(--gold-3);
        }
        .terminal .term-body {
            max-height: 130px;
            overflow-y: auto;
            scrollbar-width: thin;
            scrollbar-color: var(--gold-3) transparent;
        }
        .terminal .term-body::-webkit-scrollbar {
            width: 3px;
        }
        .terminal .term-body::-webkit-scrollbar-thumb {
            background: var(--gold-3);
            border-radius: 10px;
        }
        .terminal .log-line {
            opacity: 0.8;
            animation: logFade 0.4s ease;
            padding: 2px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.02);
        }
        .terminal .log-line .time {
            color: var(--gold-3);
            margin-right: 8px;
        }
        @keyframes logFade {
            from { opacity: 0; transform: translateX(-10px); }
            to { opacity: 0.8; transform: translateX(0); }
        }

        /* ============================================================
                   TOAST
                   ============================================================ */
        .toast {
            position: fixed;
            bottom: 30px;
            left: 50%;
            transform: translateX(-50%) translateY(100px);
            background: rgba(10, 10, 20, 0.85);
            backdrop-filter: blur(16px);
            padding: 16px 34px;
            border-radius: 16px;
            border-left: 4px solid var(--gold-3);
            box-shadow: 0 15px 50px rgba(0, 0, 0, 0.7), 0 0 60px rgba(212, 175, 55, 0.05);
            color: var(--text-primary);
            font-size: 0.95rem;
            transition: all 0.4s cubic-bezier(0.68, -0.55, 0.27, 1.55);
            z-index: 999;
            max-width: 400px;
            border: 1px solid rgba(212, 175, 55, 0.1);
            text-align: center;
            pointer-events: none;
        }
        .toast.show {
            transform: translateX(-50%) translateY(0);
            opacity: 1;
        }
        .toast.error {
            border-left-color: #ff6b6b;
            border-color: rgba(255, 107, 107, 0.2);
        }

        /* ============================================================
                   RESPONSIVE
                   ============================================================ */
        @media (max-width: 992px) {
            .header h1 { font-size: 2.8rem; }
            .grid-main { grid-template-columns: 1fr; }
            .widget-grid { grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }
            .terminal { width: 260px; left: 20px; bottom: 20px; }
            .ai-orb { width: 70px; height: 70px; right: 20px; bottom: 20px; }
        }
        @media (max-width: 600px) {
            .header h1 { font-size: 2rem; }
            .status-bar { gap: 12px; }
            .status-indicator { padding: 6px 14px; font-size: 0.8rem; }
            .btn { padding: 10px 16px; font-size: 0.8rem; }
            .stats .stat .num { font-size: 1.6rem; }
            .glass-card { padding: 18px; }
            .terminal { width: 200px; font-size: 0.65rem; bottom: 10px; left: 10px; }
            .ai-orb { width: 60px; height: 60px; right: 10px; bottom: 10px; }
            .widget-grid { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>

    <!-- ============================================================
    LOADING SCREEN
    ============================================================ -->
    <div id="loading-screen">
        <div class="loader-text">INITIALIZING</div>
        <div class="progress-bar"><div class="fill"></div></div>
        <div class="loading-sub">Loading ROOM SPAM SYSTEM...</div>
    </div>

    <!-- ============================================================
    BACKGROUND LAYERS
    ============================================================ -->
    <canvas id="bg-canvas"></canvas>
    <canvas id="gold-canvas"></canvas>
    <div class="aurora-overlay"></div>

    <!-- ============================================================
    MAIN CONTAINER
    ============================================================ -->
    <div class="app-container">

        <!-- ============================================================
        HEADER
        ============================================================ -->
        <header class="header">
            <div class="logo-wrapper">
                <div class="logo-glow"></div>
                <div class="halo"></div>
                <h1><i class="fas fa-bolt" style="background: none; -webkit-text-fill-color: initial; color: var(--gold-3); text-shadow: 0 0 40px rgba(212,175,55,0.5); margin-right: 12px;"></i> SALIM ROOM SPAM</h1>
            </div>
            <div class="sub"> Room Invite Dashboard</div>
            <div class="status-bar">
                <span class="status-indicator">
                    <span class="status-dot stopped" id="statusDot"></span>
                    <span id="statusText">Stopped</span>
                </span>
                <span class="status-indicator">
                    <i class="fas fa-users"></i> <span id="accCount">0</span> bots
                </span>
                <span class="status-indicator">
                    <i class="fas fa-bullseye"></i> <span id="targetCount">0</span> targets
                </span>
            </div>
        </header>

        <!-- ============================================================
        MAIN GRID (Existing 3 cards)
        ============================================================ -->
        <div class="grid-main">
            <!-- Targets Card -->
            <div class="glass-card">
                <h3><i class="fas fa-crosshairs"></i> Targets</h3>
                <div class="target-list" id="targetList"></div>
                <div class="input-group">
                    <textarea id="addTargetsInput" placeholder="Enter UID(s) comma separated"></textarea>
                </div>
                <div class="input-group" style="margin-top:5px;">
                    <button class="btn btn-primary btn-sm" id="addTargetsBtn"><i class="fas fa-plus"></i> Add & Start</button>
                    <button class="btn btn-secondary btn-sm" id="reloadTargetsBtn"><i class="fas fa-sync-alt"></i> Reload</button>
                </div>
            </div>

            <!-- Controls Card -->
            <div class="glass-card">
                <h3><i class="fas fa-play-circle"></i> Control</h3>
                <div class="control-group">
                    <button class="btn btn-primary btn-block" id="startBtn"><i class="fas fa-play"></i> Start Spam</button>
                    <button class="btn btn-danger btn-block" id="stopBtn"><i class="fas fa-stop"></i> Stop Spam</button>
                </div>
                <div style="margin-top:15px;">
                    <button class="btn btn-secondary btn-sm" id="stopAllBtn"><i class="fas fa-ban"></i> Stop All</button>
                </div>
                <div class="stats">
                    <div class="stat">
                        <div class="num" id="statTargets">0</div>
                        <span class="label">Targets</span>
                    </div>
                    <div class="stat">
                        <div class="num" id="statAccounts">0</div>
                        <span class="label">Bots</span>
                    </div>
                </div>
            </div>

            <!-- Accounts Card -->
            <div class="glass-card">
                <h3><i class="fas fa-robot"></i> Active Bots</h3>
                <div class="account-list" id="accountList"></div>
                <div style="margin-top:10px; text-align:right; font-size:0.8rem; color:var(--text-secondary);">
                    <span id="accCountSmall">0</span> connected
                </div>
            </div>
        </div>

        <!-- ============================================================
        WIDGETS ROW (Premium visual widgets)
        ============================================================ -->
        <div class="widget-grid">
            <div class="widget-card">
                <div class="border-beam"></div>
                <div class="icon"><i class="fas fa-microchip"></i></div>
                <div class="value" id="cpuWidget">0%</div>
                <div class="label">CPU</div>
            </div>
            <div class="widget-card">
                <div class="border-beam"></div>
                <div class="icon"><i class="fas fa-memory"></i></div>
                <div class="value" id="ramWidget">0%</div>
                <div class="label">RAM</div>
            </div>
            <div class="widget-card">
                <div class="border-beam"></div>
                <div class="icon"><i class="fas fa-tachometer-alt"></i></div>
                <div class="value" id="fpsWidget">60</div>
                <div class="label">FPS</div>
            </div>
            <div class="widget-card">
                <div class="border-beam"></div>
                <div class="icon"><i class="fas fa-wifi"></i></div>
                <div class="value" id="networkWidget">0 ms</div>
                <div class="label">Latency</div>
            </div>
            <div class="widget-card">
                <div class="border-beam"></div>
                <div class="icon"><i class="fas fa-clock"></i></div>
                <div class="value" id="clockWidget">00:00</div>
                <div class="label">Time</div>
            </div>
            <div class="widget-card">
                <div class="border-beam"></div>
                <div class="icon"><i class="fas fa-calendar-alt"></i></div>
                <div class="value" id="dateWidget">--</div>
                <div class="label">Date</div>
            </div>
            <div class="widget-card">
                <div class="border-beam"></div>
                <div class="icon"><i class="fas fa-chart-line"></i></div>
                <div class="value" id="requestsWidget">0</div>
                <div class="label">Requests</div>
            </div>
            <div class="widget-card">
                <div class="border-beam"></div>
                <div class="icon"><i class="fas fa-rocket"></i></div>
                <div class="value" id="reqPerSecWidget">0</div>
                <div class="label">Req/s</div>
            </div>
        </div>

        <!-- ============================================================
        FOOTER
        ============================================================ -->
        <footer class="footer" style="text-align:center; margin-top:40px; padding-top:20px; border-top:1px solid rgba(255,255,255,0.05); color:var(--text-secondary); font-size:0.9rem; letter-spacing:1px;">
            <i class="fas fa-heart" style="color:#ff6b6b; text-shadow:0 0 15px rgba(255,107,107,0.3);"></i>
            <span id="footerText"></span>
        </footer>

    </div> <!-- end app-container -->

    <!-- ============================================================
    FLOATING AI ORB
    ============================================================ -->
    <div class="ai-orb" id="aiOrb">
        <div class="orb">
            <i class="fas fa-robot"></i>
        </div>
    </div>

    <!-- ============================================================
    SYSTEM TERMINAL
    ============================================================ -->
    <div class="terminal" id="terminal">
        <div class="term-header">
            <span><i class="fas fa-terminal"></i> SYSTEM</span>
            <span><i class="fas fa-circle" style="color:#00ff88; font-size:0.5rem; text-shadow:0 0 10px #00ff88;"></i> ONLINE</span>
        </div>
        <div class="term-body" id="termBody"></div>
    </div>

    <!-- ============================================================
    TOAST
    ============================================================ -->
    <div class="toast" id="toast"></div>

    <!-- ============================================================
    NEW JAVASCRIPT – Premium Enhancements
    ============================================================ -->
    <script>
        // ============================================================
        // GOLD PARTICLES CANVAS (separate from existing)
        // ============================================================
        (function() {
            const canvas = document.getElementById('gold-canvas');
            const ctx = canvas.getContext('2d');
            let width, height;
            let particles = [];
            const num = 80;

            function resize() {
                width = canvas.width = window.innerWidth;
                height = canvas.height = window.innerHeight;
            }
            window.addEventListener('resize', resize);
            resize();

            class GoldParticle {
                constructor() {
                    this.reset();
                }
                reset() {
                    this.x = Math.random() * width;
                    this.y = Math.random() * height;
                    this.size = Math.random() * 3 + 1;
                    this.speedX = (Math.random() - 0.5) * 0.4;
                    this.speedY = (Math.random() - 0.5) * 0.4;
                    this.opacity = Math.random() * 0.5 + 0.3;
                    this.hue = 40 + Math.random() * 20; // gold hues
                }
                update() {
                    this.x += this.speedX;
                    this.y += this.speedY;
                    if (this.x < 0 || this.x > width) this.speedX *= -1;
                    if (this.y < 0 || this.y > height) this.speedY *= -1;
                }
                draw() {
                    ctx.beginPath();
                    ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
                    ctx.shadowColor = `hsl(${this.hue}, 100%, 60%)`;
                    ctx.shadowBlur = 20;
                    ctx.fillStyle = `hsla(${this.hue}, 100%, 70%, ${this.opacity})`;
                    ctx.fill();
                    ctx.shadowBlur = 0;
                }
            }

            for (let i = 0; i < num; i++) {
                particles.push(new GoldParticle());
            }

            function animate() {
                ctx.clearRect(0, 0, width, height);
                particles.forEach(p => {
                    p.update();
                    p.draw();
                });
                // Draw connecting lines between nearby particles
                for (let i = 0; i < particles.length; i++) {
                    for (let j = i + 1; j < particles.length; j++) {
                        const dx = particles[i].x - particles[j].x;
                        const dy = particles[i].y - particles[j].y;
                        const dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < 150) {
                            ctx.beginPath();
                            ctx.moveTo(particles[i].x, particles[i].y);
                            ctx.lineTo(particles[j].x, particles[j].y);
                            ctx.strokeStyle = `rgba(212, 175, 55, ${0.08 * (1 - dist/150)})`;
                            ctx.lineWidth = 0.6;
                            ctx.stroke();
                        }
                    }
                }
                requestAnimationFrame(animate);
            }
            animate();
        })();

        // ============================================================
        // SYSTEM TERMINAL – Fake logs
        // ============================================================
        (function() {
            const termBody = document.getElementById('termBody');
            const logs = [
                'SYSTEM ONLINE',
                'Loading Modules...',
                'Connecting to AI Core...',
                'Monitoring active bots...',
                'Bots Connected: {bots}',
                'Target Loaded: {targets}',
                'Requests/sec updated',
                'Memory stable',
                'Network online',
                'Session active'
            ];
            let logIndex = 0;
            let interval;

            function addLog(text) {
                const line = document.createElement('div');
                line.className = 'log-line';
                const time = new Date().toLocaleTimeString();
                line.innerHTML = `<span class="time">[${time}]</span> ${text}`;
                termBody.appendChild(line);
                if (termBody.children.length > 30) {
                    termBody.removeChild(termBody.firstChild);
                }
                termBody.scrollTop = termBody.scrollHeight;
            }

            function updateLogs() {
                const bots = document.getElementById('accCount')?.textContent || '0';
                const targets = document.getElementById('targetCount')?.textContent || '0';
                let msg = logs[logIndex % logs.length];
                msg = msg.replace(/{bots}/g, bots).replace(/{targets}/g, targets);
                addLog(msg);
                logIndex++;
            }

            // Start after loading
            setTimeout(() => {
                interval = setInterval(updateLogs, 3000);
                // initial logs
                addLog('Initializing SALIM System...');
                setTimeout(() => addLog('AI Core loaded'), 500);
                setTimeout(() => addLog('Dashboard ready'), 1000);
            }, 2000);
        })();

        // ============================================================
        // WIDGETS – Simulated values
        // ============================================================
        (function() {
            function updateWidgets() {
                // CPU: random 10-60%
                document.getElementById('cpuWidget').textContent = Math.floor(Math.random() * 50 + 10) + '%';
                // RAM: random 20-70%
                document.getElementById('ramWidget').textContent = Math.floor(Math.random() * 50 + 20) + '%';
                // FPS: 55-62
                document.getElementById('fpsWidget').textContent = Math.floor(Math.random() * 8 + 55);
                // Latency: 10-80ms
                document.getElementById('networkWidget').textContent = Math.floor(Math.random() * 70 + 10) + ' ms';
                // Clock
                const now = new Date();
                document.getElementById('clockWidget').textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                document.getElementById('dateWidget').textContent = now.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
                // Requests (simulated from existing acc count)
                const bots = parseInt(document.getElementById('accCount')?.textContent || '0');
                const targets = parseInt(document.getElementById('targetCount')?.textContent || '0');
                const req = bots * targets * 2;
                document.getElementById('requestsWidget').textContent = req;
                document.getElementById('reqPerSecWidget').textContent = Math.floor(req / 10);
            }
            updateWidgets();
            setInterval(updateWidgets, 2000);
        })();

        // ============================================================
        // LOADING SCREEN – Hide after 4s
        // ============================================================
        setTimeout(() => {
            document.getElementById('loading-screen').classList.add('hidden');
        }, 4000);

        // ============================================================
        // FOOTER TEXT (using String.fromCharCode)
        // ============================================================
        document.getElementById('footerText').textContent =
            String.fromCharCode(77, 97, 100, 101, 32, 66, 121, 32, 74, 65, 72, 73, 68, 32, 88, 32, 69, 77, 80, 73, 82, 69, 32, 91, 74, 88, 69, 93);

        // ============================================================
        // MOUSE SPOTLIGHT (CSS only? we'll add a moving glow using JS)
        // ============================================================
        (function() {
            const spotlight = document.createElement('div');
            spotlight.style.cssText = `
                    position: fixed;
                    top: 0; left: 0;
                    width: 100%; height: 100%;
                    pointer-events: none;
                    z-index: 0;
                    background: radial-gradient(circle at var(--mx, 50%) var(--my, 50%), rgba(212,175,55,0.04) 0%, transparent 70%);
                    transition: background 0.1s;
                `;
            document.body.appendChild(spotlight);
            document.addEventListener('mousemove', (e) => {
                const x = e.clientX / window.innerWidth * 100;
                const y = e.clientY / window.innerHeight * 100;
                spotlight.style.setProperty('--mx', x + '%');
                spotlight.style.setProperty('--my', y + '%');
            });
        })();

        // ============================================================
        // RIPPLE EFFECT (attached to all .btn)
        // ============================================================
        document.querySelectorAll('.btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                const rect = this.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                const ripple = document.createElement('span');
                ripple.className = 'ripple';
                ripple.style.left = x + 'px';
                ripple.style.top = y + 'px';
                ripple.style.width = ripple.style.height = '20px';
                this.appendChild(ripple);
                setTimeout(() => ripple.remove(), 600);
            });
        });
    </script>

    <!-- ============================================================
    EXISTING JAVASCRIPT (Keep exactly as before)
    ============================================================ -->
    <script>
        // ===== PARTICLES (Canvas) – ORIGINAL (kept intact)
        (function() {
            const canvas = document.getElementById('bg-canvas');
            const ctx = canvas.getContext('2d');
            let width, height;
            let particles = [];
            const numParticles = 120;
            let mouseX = -9999,
                mouseY = -9999;

            function resize() {
                width = canvas.width = window.innerWidth;
                height = canvas.height = window.innerHeight;
            }
            window.addEventListener('resize', resize);
            resize();

            class Particle {
                constructor() {
                    this.reset();
                }
                reset() {
                    this.x = Math.random() * width;
                    this.y = Math.random() * height;
                    this.size = Math.random() * 2 + 0.5;
                    this.speedX = (Math.random() - 0.5) * 0.3;
                    this.speedY = (Math.random() - 0.5) * 0.3;
                    this.opacity = Math.random() * 0.5 + 0.2;
                }
                update() {
                    this.x += this.speedX;
                    this.y += this.speedY;
                    const dx = mouseX - this.x;
                    const dy = mouseY - this.y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < 200) {
                        const force = (200 - dist) / 200 * 0.02;
                        this.x += dx * force;
                        this.y += dy * force;
                    }
                    if (this.x < 0 || this.x > width) this.speedX *= -1;
                    if (this.y < 0 || this.y > height) this.speedY *= -1;
                }
                draw() {
                    ctx.beginPath();
                    ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
                    ctx.fillStyle = `rgba(0, 255, 255, ${this.opacity})`;
                    ctx.fill();
                    ctx.shadowColor = '#00ffff';
                    ctx.shadowBlur = 10;
                    ctx.fill();
                    ctx.shadowBlur = 0;
                }
            }

            for (let i = 0; i < numParticles; i++) {
                particles.push(new Particle());
            }

            function drawLines() {
                for (let i = 0; i < particles.length; i++) {
                    for (let j = i + 1; j < particles.length; j++) {
                        const dx = particles[i].x - particles[j].x;
                        const dy = particles[i].y - particles[j].y;
                        const dist = Math.sqrt(dx * dx + dy * dy);
                        if (dist < 120) {
                            ctx.beginPath();
                            ctx.moveTo(particles[i].x, particles[i].y);
                            ctx.lineTo(particles[j].x, particles[j].y);
                            ctx.strokeStyle = `rgba(0, 255, 255, ${0.08 * (1 - dist/120)})`;
                            ctx.lineWidth = 0.5;
                            ctx.stroke();
                        }
                    }
                }
            }

            function animate() {
                ctx.clearRect(0, 0, width, height);
                particles.forEach(p => {
                    p.update();
                    p.draw();
                });
                drawLines();
                requestAnimationFrame(animate);
            }
            animate();

            document.addEventListener('mousemove', (e) => {
                mouseX = e.clientX;
                mouseY = e.clientY;
            });
            document.addEventListener('mouseleave', () => {
                mouseX = -9999;
                mouseY = -9999;
            });
        })();

        // ===== RIPPLE EFFECT ON BUTTONS (original) – we already added above, but keep this one as well (they are identical)
        document.querySelectorAll('.btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                const rect = this.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                const ripple = document.createElement('span');
                ripple.className = 'ripple';
                ripple.style.left = x + 'px';
                ripple.style.top = y + 'px';
                ripple.style.width = ripple.style.height = '20px';
                this.appendChild(ripple);
                setTimeout(() => ripple.remove(), 600);
            });
        });

        // ===== SET FOOTER TEXT USING UNICODE/HEX ENTITIES (original)
        const footerText = String.fromCharCode(77, 97, 100, 101, 32, 66, 121, 32, 74, 65, 72, 73, 68, 32, 88, 32, 69, 77, 80, 73, 82, 69, 32, 91, 74, 88, 69, 93);
        document.getElementById('footerText').textContent = footerText;

        // ============================================================
        // KEEP EXISTING JAVASCRIPT LOGIC (unchanged)
        // ============================================================

        // ======= API helpers =======
        async function apiFetch(endpoint, options = {}) {
            const res = await fetch(endpoint, {
                ...options,
                headers: { 'Content-Type': 'application/json', ...options.headers }
            });
            return res.json();
        }

        function showToast(msg, isError = false) {
            const t = document.getElementById('toast');
            t.textContent = msg;
            t.className = 'toast show' + (isError ? ' error' : '');
            clearTimeout(t._timer);
            t._timer = setTimeout(() => t.classList.remove('show'), 3500);
        }

        // ======= UI Update =======
        async function updateUI() {
            try {
                const status = await apiFetch('/status');
                const accounts = await apiFetch('/accounts');

                // Status dot
                const dot = document.getElementById('statusDot');
                const statusText = document.getElementById('statusText');
                if (status.spam_running) {
                    dot.className = 'status-dot running';
                    statusText.textContent = 'Running';
                } else {
                    dot.className = 'status-dot stopped';
                    statusText.textContent = 'Stopped';
                }

                // Counts
                document.getElementById('accCount').textContent = status.active_accounts || 0;
                document.getElementById('targetCount').textContent = status.targets ? status.targets.length : 0;
                document.getElementById('statTargets').textContent = status.targets ? status.targets.length : 0;
                document.getElementById('statAccounts').textContent = status.active_accounts || 0;
                document.getElementById('accCountSmall').textContent = status.active_accounts || 0;

                // Target list
                const targetList = document.getElementById('targetList');
                targetList.innerHTML = '';
                if (status.targets && status.targets.length) {
                    status.targets.forEach(uid => {
                        const div = document.createElement('div');
                        div.className = 'target-item';
                        div.innerHTML = `
                                <span class="uid">${uid}</span>
                                <button class="remove-btn" data-uid="${uid}"><i class="fas fa-times"></i></button>
                            `;
                        div.querySelector('.remove-btn').addEventListener('click', (e) => {
                            const uid = e.currentTarget.dataset.uid;
                            removeTarget(uid);
                        });
                        targetList.appendChild(div);
                    });
                } else {
                    targetList.innerHTML = '<div style="color:rgba(255,255,255,0.3); text-align:center; padding:10px;">No targets</div>';
                }

                // Account list
                const accList = document.getElementById('accountList');
                accList.innerHTML = '';
                if (accounts.accounts && accounts.accounts.length) {
                    accounts.accounts.forEach(acc => {
                        const div = document.createElement('div');
                        div.className = 'acc-item';
                        div.textContent = acc;
                        accList.appendChild(div);
                    });
                } else {
                    accList.innerHTML = '<div style="color:rgba(255,255,255,0.3); text-align:center; padding:10px;">No bots connected</div>';
                }

            } catch (e) {
                console.error('Update error', e);
            }
        }

        // ======= Actions =======
        async function addTargets() {
            const input = document.getElementById('addTargetsInput');
            const raw = input.value.trim();
            if (!raw) { showToast('Please enter at least one UID', true); return; }
            const uids = raw.split(',').map(s => s.trim()).filter(s => s.length > 0 && /^\d+$/.test(s));
            if (!uids.length) { showToast('No valid UIDs found', true); return; }
            try {
                const result = await apiFetch('/start', { method: 'POST', body: JSON.stringify({ uids }) });
                if (result.success) {
                    showToast(result.message || 'Added targets and started spam!');
                    input.value = '';
                    updateUI();
                } else {
                    showToast(result.message || 'Failed to add targets', true);
                }
            } catch (e) {
                showToast('Error contacting server', true);
            }
        }

        async function removeTarget(uid) {
            try {
                const result = await apiFetch('/stop', { method: 'POST', body: JSON.stringify({ uid }) });
                if (result.success) {
                    showToast(`Removed ${uid}`);
                    updateUI();
                } else {
                    showToast(result.message || 'Failed to remove', true);
                }
            } catch (e) {
                showToast('Error', true);
            }
        }

        async function startSpam() {
            try {
                const status = await apiFetch('/status');
                if (!status.targets || status.targets.length === 0) {
                    showToast('No targets available. Add some first.', true);
                    return;
                }
                const result = await apiFetch('/start', { method: 'POST', body: JSON.stringify({ uids: status.targets }) });
                if (result.success) {
                    showToast('Spam started!');
                    updateUI();
                } else {
                    showToast(result.message || 'Failed to start', true);
                }
            } catch (e) {
                showToast('Error', true);
            }
        }

        async function stopSpam() {
            try {
                const result = await apiFetch('/stop-all', { method: 'POST' });
                if (result.success) {
                    showToast('Spam stopped');
                    updateUI();
                } else {
                    showToast(result.message || 'Failed to stop', true);
                }
            } catch (e) {
                showToast('Error', true);
            }
        }

        async function reloadTargets() {
            try {
                const result = await apiFetch('/reload-targets', { method: 'POST' });
                if (result.success) {
                    showToast('Targets reloaded from file');
                    updateUI();
                } else {
                    showToast('Reload failed', true);
                }
            } catch (e) {
                showToast('Error', true);
            }
        }

        // ======= Events =======
        document.getElementById('addTargetsBtn').addEventListener('click', addTargets);
        document.getElementById('startBtn').addEventListener('click', startSpam);
        document.getElementById('stopBtn').addEventListener('click', stopSpam);
        document.getElementById('stopAllBtn').addEventListener('click', stopSpam);
        document.getElementById('reloadTargetsBtn').addEventListener('click', reloadTargets);

        // ======= Auto Refresh =======
        updateUI();
        setInterval(updateUI, 3000);
    </script>

</body>
</html>'''

# ==================== MAIN ====================
def main():
    print(f"""
{C}{BOLD}
╔═══════════════════════════════════════════════╗
║   🎖️  SALIM ROOM SPAM WEB STARTED  🎖️           ║
║             ONLY ROOM SPAM                    ║
║        👑 Developer: SALIM CODEX           ║
║   Web UI available at http://0.0.0.0:5000     ║
╚═══════════════════════════════════════════════╝
{RS}
""")
    load_targets("inv_uid.txt")
    Thread(target=run_accounts, daemon=True).start()
    time.sleep(3)  # কিছু অ্যাকাউন্ট সংযুক্ত হোক
    if targets:
        start_spam()  # স্বয়ংক্রিয় শুরু

    # Flask চালান
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

if __name__ == "__main__":
    try:
        import aiohttp
        import jwt
    except ImportError:
        os.system("pip install aiohttp pyjwt")
    main()
