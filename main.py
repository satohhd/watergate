# 水門開閉管理 2024.4.8 リファクタ版（閉門までの待機に変更）

import uasyncio as asyncio
from machine import SoftI2C, Pin, RTC, reset
from ds1307 import DS1307
import utime
import json
import bluetooth
from ble_simple_peripheral import BLESimplePeripheral
import uos

# BLE モード定数
BLE_MODE_LOG = 'log'
BLE_MODE_MENU = 'menu'
BLE_MODE_SELF = 'self'
BLE_MODE_CONFIGURE = 'configure'
BLE_MODE_AUTO = 'auto'
BLE_MODE_FORCE = 'force'
BLE_MODE_TEST = 'test'

# 強制制御ピン
FORCE_OPEN = Pin(2, Pin.IN, Pin.PULL_UP)
FORCE_CLOSE = Pin(3, Pin.IN, Pin.PULL_UP)

# モーター制御ピン
M1 = Pin(12, Pin.OUT)
M2 = Pin(13, Pin.OUT)

# 距離測定ピン
ECHO = Pin(14, Pin.IN, Pin.PULL_DOWN)
TRIG = Pin(15, Pin.OUT)

# BLE 初期化
BLE = bluetooth.BLE()
BLE_SP = BLESimplePeripheral(BLE)

# ファイル定数
CONFIG_JSON_FILE = '/config.json'
OPE_TIME_JSON_FILE = '/operation_time.json'
LOG_FILE = '/operation.log'
LOG_DIR = '/log'
LOG_RETAIN_DAYS = 7  # 保存日数

# 状態定数
OPENCLOSE_OPEN = 0
OPENCLOSE_CLOSE = 1
FORCE_OPEN_ON = 0
FORCE_OPEN_OFF = 1
FORCE_CLOSE_ON = 0
FORCE_CLOSE_OFF = 1

# グローバル変数
g_water_level = 0
g_is_drive_times = False
g_open_close = OPENCLOSE_OPEN
g_count_down_until_closing = 0  # 閉門までの待機用
g_ble_ope_mode = None
g_ble_commands = []

# デフォルト設定 　# 80
g_config_dic = {
    "water_level_correction_mm": 50,
    "waiting_for_interval_sec": 5,
    "open_closing_standards_mm": 7,
    "open_time_sec": 20,
    "close_time_sec": 40,
    "wait_before_closing_sec": 120,
    "ope_time_1": False,
    "ope_time_2": True,
    "ope_time_3": False,
    "ope_time_4": False,
    "ope_time_5": True,
    "ope_time_6": False,
    "ope_time_7": True,
    "ope_time_8": False
}

# 設定ファイル読み込み
def load_config():
    global g_config_dic, g_ope_time_dic
    try:
        with open(CONFIG_JSON_FILE, 'r') as f:
            g_config_dic = json.load(f)
    except OSError:
        with open(CONFIG_JSON_FILE, 'w') as f:
            json.dump(g_config_dic, f, separators=(',', ': '))

    try:
        with open(OPE_TIME_JSON_FILE, 'r') as f:
            g_ope_time_dic = json.load(f)
    except OSError:
        with open(OPE_TIME_JSON_FILE, 'w') as f:
            json.dump(g_ope_time_dic, f, separators=(',', ': '))

def zfill(s, width):
    if len(s) < width:
        return ("0" * (width - len(s))) + s
    else:
        return s

g_ope_time_dic = [
    {"id": i + 1, "start_time": f"{zfill(str(i*3),2)}:00", "end_time": f"{zfill(str((i+1)*3),2)}:00"}
    for i in range(8)
]

def ensure_log_dir():
    if LOG_DIR not in uos.listdir('/'):
        try:
            uos.mkdir(LOG_DIR)
        except:
            pass

def get_log_filename():
    t = utime.localtime()
    return f"{LOG_DIR}/log_{t[0]:04d}{t[1]:02d}{t[2]:02d}.txt"

def delete_old_logs():
    try:
        files = uos.listdir(LOG_DIR)
        now = utime.time()

        for fname in files:
            if fname.startswith("log_") and fname.endswith(".txt"):
                try:
                    y = int(fname[4:8])
                    m = int(fname[8:10])
                    d = int(fname[10:12])
                    log_time = utime.mktime((y, m, d, 0, 0, 0, 0, 0))
                    if now - log_time > LOG_RETAIN_DAYS * 86400:
                        uos.remove(f"{LOG_DIR}/{fname}")
                        print(f"削除: {fname}")
                except Exception as e:
                    print("ログファイル日付解析エラー:", fname, e)
    except Exception as e:
        print("ログ削除処理エラー:", e)


# ログ出力
# def logger(msg):
#     try:
#         _dateTime = fromatDateTimeStr(utime.localtime())
#         formated_msg = f"{_dateTime} {msg}\n"
#         if g_ble_ope_mode == BLE_MODE_LOG:
#             BLE_SP.send(formated_msg.strip())
#             
#         with open(LOG_FILE, 'a') as f:  # ファイルを追記モードで開く
#             f.write(formated_msg.strip())    # 追記実行（文字列で）※改行付
#             #print("Append:", data)  # 追記データ表示
#             
#         print(formated_msg.strip())
#     except Exception as e:
#         print('logger error:' + str(e))
# 新しい logger
def logger(msg):
    try:
        _dateTime = fromatDateTimeStr(utime.localtime())
        formated_msg = f"{_dateTime} {msg}\n"

        # BLEに送信
        if g_ble_ope_mode == BLE_MODE_LOG:
            BLE_SP.send(formated_msg.strip())

        ensure_log_dir()
        delete_old_logs()

        # 日付ごとのファイルに書き出す
        with open(get_log_filename(), 'a') as f:
            f.write(formated_msg)

        print(formated_msg.strip())
    except Exception as e:
        print('logger error:' + str(e))

# RTC設定
def set_rtc():
    try:
        logger('rtc connect')
        _i2c_rtc = SoftI2C(scl=Pin(1), sda=Pin(0), freq=100000)
        _rtc = DS1307(_i2c_rtc)
        logger('datetime setting')
        #RTC().datetime(_rtc.datetime())
        # JST = UTC + 9 時間
        ds_time = list(_rtc.datetime())
        ds_time[4] += 9  # index 4 = hour
        if ds_time[4] >= 24:
            ds_time[4] -= 24
            ds_time[2] += 1  # 日を1日進める（簡易的、月超えには非対応）

        RTC().datetime(tuple(ds_time))
    except Exception as e:
        logger(f"RTC初期化エラー: {str(e)}")
        logger("RTC未接続または無効。内蔵タイマーを使用します。時刻の正確性が保証されません。")




# 運用時間チェック
async def check_drive_times():
    global g_is_drive_times
    while True:
        _, current_time = getDateTime(utime.localtime())
        logger('運用時間帯チェック')
        g_is_drive_times = False
        for item in g_ope_time_dic:
            if item['start_time'] <= current_time < item['end_time']:
                g_is_drive_times = g_config_dic.get('ope_time_' + str(item['id']), False)
        logger(f"現在の時間＝{current_time}")
        logger(f"運用時間帯か？＝{g_is_drive_times}")
        await asyncio.sleep(3)

# 水位測定
async def ultra():
    global g_water_level
    logger(f"測定開始")
    while True:
        
        _values = []
        for _ in range(3):
            TRIG.low()
            utime.sleep_us(10)
            TRIG.high()
            utime.sleep_us(2)
            TRIG.low()
            k = 0
            while ECHO.value() == 0:
                signaloff = utime.ticks_us()
                k += 1
                if k > 10000:
                    break
            k = 0
            while ECHO.value() == 1:
                signalon = utime.ticks_us()
                k += 1
                if k > 10000:
                    break
            timepassed = signalon - signaloff
            distance = round((timepassed * 0.0343) / 2, 1)
            logger(f"測定 {distance}cm")
            _values.append(distance)
            await asyncio.sleep(3)
        g_water_level = get_clustered_values_average(_values)
        logger(f"測定(g_water_level): {g_water_level}")
        await asyncio.sleep(3)

# クラスタ化平均
def get_clustered_values_average(data):
    try:
        if not data:
            return 0
        sorted_data = sorted(data)
        threshold = 5
        clusters = []
        current = [sorted_data[0]]
        for i in range(1, len(sorted_data)):
            if sorted_data[i] - sorted_data[i-1] <= threshold:
                current.append(sorted_data[i])
            else:
                clusters.append(current)
                current = [sorted_data[i]]
        clusters.append(current)
        max_cluster = max(clusters, key=len)
        return round(sum(max_cluster) / len(max_cluster), 1)
    except Exception as e:
        logger(str(e))
        return 0


# 水門開ける
async def wopen(sec=10):
    global g_open_close, g_count_down_until_closing
    if g_open_close == OPENCLOSE_OPEN:
        return
    g_open_close = OPENCLOSE_OPEN
    g_count_down_until_closing = g_config_dic.get("wait_before_closing_sec", 120)
    logger(f'watergate open: {sec} sec')
    M1.low()
    M2.high()
    await asyncio.sleep(sec)
    M1.low()
    M2.low()
    await asyncio.sleep(5)

# 水門閉じる
async def wclose(sec=20):
    global g_open_close
    if g_open_close == OPENCLOSE_CLOSE:
        return
    g_open_close = OPENCLOSE_CLOSE
    logger(f'watergate close: {sec} sec')
    M1.high()
    M2.low()
    await asyncio.sleep(sec)
    M1.low()
    M2.low()
    await asyncio.sleep(5)
# ステータス送信
async def show_status_service():
    while True:
        await asyncio.sleep(g_config_dic["waiting_for_interval_sec"])
        show_status()

def show_status():
    _, current_time = getDateTime(utime.localtime())
    mode = {
        BLE_MODE_FORCE: '強制',
        BLE_MODE_AUTO: '自動',
    }.get(g_ble_ope_mode, '手動')
    msg = f"現在水位{round(g_config_dic['water_level_correction_mm'] - g_water_level, 1)}cm 閾値{g_config_dic['open_closing_standards_mm']}cm {mode} {'開門' if g_open_close == OPENCLOSE_OPEN else '閉門'} {'運中帯' if g_is_drive_times else '運止帯'} {current_time}"
    BLE_SP.send(msg.strip())
    logger(msg.strip())

# 時刻フォーマット
def fromatDateTimeStr(localTIme):
    Y, M, D, hr, m, s, _, _ = localTIme
    return f"{Y:04}/{M:02}/{D:02} {hr:02}:{m:02}:{s:02}"

def getDateTime(localTIme):
    Y, M, D, hr, m, _, _, _ = localTIme
    return f"{Y:04}/{M:02}/{D:02}", f"{hr:02}:{m:02}"
# auto_drive 修正
def get_current_water_level():
    return g_config_dic['water_level_correction_mm'] - g_water_level

# 自動運転
async def auto_drive():
    global g_is_drive_times, g_open_close, g_count_down_until_closing
    while True:
        await asyncio.sleep(g_config_dic["waiting_for_interval_sec"])
        if g_ble_ope_mode == BLE_MODE_AUTO:
            _, _current_time = getDateTime(utime.localtime())
            logger("自動モード")
            wl = get_current_water_level()
            if g_open_close == OPENCLOSE_CLOSE:
                if (g_is_drive_times and wl < g_config_dic['open_closing_standards_mm']) or \
                   (not g_is_drive_times and wl < 4):
                    logger('open条件成立')
                    await wopen(g_config_dic['open_time_sec'])
                else:
                    logger('close条件成立')
                    pass

            elif g_open_close == OPENCLOSE_OPEN:
                if (g_is_drive_times and wl < g_config_dic['open_closing_standards_mm']) or \
                   (not g_is_drive_times and wl < 4):
                    logger('open条件成立')
                    pass
                else:
                    logger('close条件成立')
                    if g_count_down_until_closing > 0:
                        g_count_down_until_closing -= g_config_dic["waiting_for_interval_sec"]
                        logger(f"閉門可能まであと {g_count_down_until_closing} 秒")
                    else:
                        logger('close実行')
                        await wclose(g_config_dic['close_time_sec'])


# BLE受信

def on_rx(data):
    global g_ble_ope_mode, g_ble_commands
    cmd = data.strip()
    logger(f"BLE RX: {cmd}")
    if cmd == b'log':
        g_ble_ope_mode = BLE_MODE_LOG
    elif cmd == b'reset':
        reset()
    elif cmd == b'self':
        g_ble_ope_mode = BLE_MODE_SELF
    elif cmd == b'menu':
        g_ble_ope_mode = BLE_MODE_MENU
    elif cmd == b'configure':
        g_ble_ope_mode = BLE_MODE_CONFIGURE
    else:
        if g_ble_ope_mode in [BLE_MODE_CONFIGURE, BLE_MODE_MENU, BLE_MODE_TEST, BLE_MODE_SELF]:
            g_ble_commands.append({
                'mode': g_ble_ope_mode,
                'command': cmd,
                'timestamp': fromatDateTimeStr(utime.localtime())
            })

# メイン関数
async def main():
    logger('start')
    set_rtc()
    load_config()
    await wclose(g_config_dic['close_time_sec'])
    BLE_SP.on_write(on_rx)
    asyncio.create_task(ultra())
    asyncio.create_task(check_drive_times())
    asyncio.create_task(auto_drive())
    asyncio.create_task(show_status_service())
    global g_count_down_since_opening, g_ble_ope_mode

    while True:
        await asyncio.sleep(g_config_dic["waiting_for_interval_sec"])
        if g_water_level is None:
            continue
        if FORCE_OPEN.value() == FORCE_OPEN_ON:
            g_ble_ope_mode = BLE_MODE_FORCE
            g_ble_commands.clear()
            await wopen(g_config_dic['open_time_sec'])
            continue
        if FORCE_CLOSE.value() == FORCE_CLOSE_ON:
            g_ble_ope_mode = BLE_MODE_FORCE
            g_ble_commands.clear()
            await wclose(g_config_dic['close_time_sec'])
            continue
        if g_ble_commands:
            g_ble_commands.sort(key=lambda x: x['timestamp'])
            command = g_ble_commands.pop(0)
            logger(f"処理: {command}")
            if command['mode'] == BLE_MODE_CONFIGURE:
                g_count_down_since_opening = 0
                if command['command'] == b'save':
                    with open(CONFIG_JSON_FILE, 'w') as f:
                        json.dump(g_config_dic, f, separators=(',', ': '))
                elif b'=' in command['command']:
                    kv = command['command'].decode().split('=')
                    if kv[0] in g_config_dic:
                        try:
                            g_config_dic[kv[0]] = type(g_config_dic[kv[0]])(eval(kv[1]))
                        except:
                            logger(f"設定エラー: {kv}")
                else:
                    logger(f"参照: {command['command']} = {g_config_dic.get(command['command'], '??')}")
            elif command['mode'] == BLE_MODE_SELF:
                if command['command'] == b'open':
                    await wopen(g_config_dic['open_time_sec'])
                elif command['command'] == b'close':
                    await wclose(g_config_dic['close_time_sec'])
            g_count_down_since_opening = 0
        elif g_ble_ope_mode == BLE_MODE_TEST:
            await wopen(g_config_dic['open_time_sec'])
            await wclose(g_config_dic['close_time_sec'])
            g_count_down_since_opening = 0
            g_ble_ope_mode = BLE_MODE_AUTO
        elif g_ble_ope_mode not in [BLE_MODE_LOG, BLE_MODE_AUTO]:
            g_ble_ope_mode = BLE_MODE_AUTO

# 実行
try:
    asyncio.run(main())
except Exception as e:
    logger(str(e))
finally:
    utime.sleep(5)
    reset()
