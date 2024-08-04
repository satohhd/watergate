#######################################################
# 水門開閉管理 2024.4.8
#######################################################

#必要なライブラリのインポート
import uasyncio as asyncio
from machine import SoftI2C, Pin, RTC, reset
from ds1307 import DS1307
import utime
import json
import bluetooth
from ble_simple_peripheral import BLESimplePeripheral

#######################################################
# 初期設定
#######################################################

#強制開閉切替
FORCE_OPEN = Pin(2,Pin.IN, Pin.PULL_UP)
FORCE_CLOSE = Pin(3,Pin.IN, Pin.PULL_UP)

#SELFOPENCLOSE = Pin(2,Pin.IN, Pin.PULL_UP)
#自動手動切替
#AUTOSELF = Pin(3,Pin.IN, Pin.PULL_UP)
#モーター関連
M1 = Pin(12,Pin.OUT)
M2 = Pin(13,Pin.OUT)
#距離測定用
ECHO = Pin(14,Pin.IN, Pin.PULL_DOWN)
TRIG = Pin(15,Pin.OUT)

# Create a Bluetooth Low Energy (BLE) object
BLE = bluetooth.BLE()
# Create an instance of the BLESimplePeripheral class with the BLE object
BLE_SP = BLESimplePeripheral(BLE)


#######################################################
# 定数
#######################################################
CONFIG_JSON_FILE = '/config.json'
OPE_TIME_JSON_FILE = '/operation_time.json' 
LOG_FILE = '/operation.log'

OPENCLOSE_OPEN = 0
OPENCLOSE_CLOSE = 1
FORCE_OPEN_ON = 0
FORCE_OPEN_OFF = 1
FORCE_CLOSE_ON = 0
FORCE_CLOSE_OFF = 1


#######################################################
# 変数
#######################################################
g_water_level = 0
g_is_drive_times = False
g_open_close = OPENCLOSE_OPEN #電源いれたときに一度閉じるため
g_count_down_since_opening = 0
#g_ble_ope_mode = "show"
g_ble_ope_mode = None
g_ble_commands = []
g_config_dic = {
                "water_level_correction_mm": 50, \
                "waiting_for_interval_sec": 5, \
                "open_closing_standards_mm": 7, \
                "open_time_sec": 50, \
                "close_time_sec": 80, \
                "ope_time_1": False, \
                "ope_time_2": True, \
                "ope_time_3": False, \
                "ope_time_4": False, \
                "ope_time_5": True, \
                "ope_time_6": False, \
                "ope_time_7": True, \
                "ope_time_8": False \
            }

g_ope_time_dic = [ \
                    {"id": 1,"start_time": "00:00", "end_time": "03:00" }, \
                    {"id": 2,"start_time": "03:00", "end_time": "06:00" }, \
                    {"id": 3,"start_time": "06:00", "end_time": "09:00" }, \
                    {"id": 4,"start_time": "09:00", "end_time": "12:00" }, \
                    {"id": 5,"start_time": "12:00", "end_time": "15:00" }, \
                    {"id": 6,"start_time": "15:00", "end_time": "18:00" }, \
                    {"id": 7,"start_time": "18:00", "end_time": "21:00" }, \
                    {"id": 8,"start_time": "21:00", "end_time": "24:00" } \
                ]

#######################################################
#関数ログ出力関数定義
#######################################################
def logger(msg):
    global g_ble_ope_mode
    try:
        _dateTime = fromatDateTimeStr(utime.localtime())

        formated_msg = _dateTime + ' ' + msg + '\n'
        #if BLE_SP.is_connected():
            #if g_ble_ope_mode == 'log':
        #    BLE_SP.send(formated_msg.strip())

        #with open(LOG_FILE, 'a') as f:  # ファイルを追記モードで開く
            #f.write(formated_msg)    # 追記実行（文字列で）※改行付
            #print("Append:", data)  # 追記データ表示

        print(formated_msg.strip())
    except Exception as e:
        print('logger error:' + str(e))
        #with open(LOG_FILE, 'w') as f:  # ファイルを追記モードで開く
        #    f.write(formated_msg)    # 追記実行（文字列で）※改行付
            #print("Append:", data)  # 追記データ表示

#######################################################
# 状態表示定義
#######################################################
def show_status():
    #global g_config_dic
    #logger('11111')
    (_today,_current_time) = getDateTime(utime.localtime())
    #logger('211111')
    #if BLE_SP.is_connected():
    #logger('311111')
    formated_msg = '現在水位' + str(round(g_config_dic['water_level_correction_mm'] - g_water_level,1)) + 'cm ' \
           + '閾値' + str(g_config_dic['open_closing_standards_mm']) + 'cm' \
           + ' ' + ('強制' if g_ble_ope_mode == 'force' else '自動' if g_ble_ope_mode == 'auto' else '手動') \
           + ' ' + ('開門' if g_open_close == OPENCLOSE_OPEN else '閉門') \
           + ' ' + ('運中帯' if g_is_drive_times ==True else '運止帯') \
           + ' ' + str(_current_time)
    #logger('411111')
    BLE_SP.send(formated_msg.strip())
    #logger('511111')
    logger(formated_msg.strip())
    #logger('611111')

#######################################################
# rtc
#######################################################
def set_rtc():

    #RTCから時刻取得
    logger('rtc connect')
    _i2c_rtc = SoftI2C(scl = Pin(1),sda = Pin(0),freq = 100000)
    _result = SoftI2C.scan(_i2c_rtc)
    _rtc = DS1307(_i2c_rtc)
    #時間設定
    #utime.localtime()
    logger('datetime setting')
    RTC().datetime(_rtc.datetime())


#######################################################
# load_config
#######################################################
def load_config():
    global g_config_dic
    global g_ope_time_dic

    #初期設定情報の読み込み
    logger('config load')
    try:

        # 設定ファイルの読み込み
        with open(CONFIG_JSON_FILE, 'r') as f:
            g_config_dic = json.load(f)

    except OSError:  # ファイルが存在しない場合のエラーハンドリング
        # 設定ファイルの書き込み
        with open(CONFIG_JSON_FILE, 'w') as f:
            json.dump(g_config_dic,f, separators=(',', ': '))

    try:

        # 運用時間ファイルの読み込み
        with open(OPE_TIME_JSON_FILE, 'r') as f:
            g_ope_time_dic = json.load(f)

    except OSError:  # ファイルが存在しない場合のエラーハンドリング

        # 運用時間ファイルの書き込み
        with open(OPE_TIME_JSON_FILE, 'w') as f:
            json.dump(g_ope_time_dic,f, separators=(',', ': '))


#######################################################
# 運用時間チェック
#######################################################
async def check_drive_times():
    global g_is_drive_times
    #無限ループ
    while True:
        (_today,_current_time) = getDateTime(utime.localtime())
        #③運用時間帯チェック
        logger('運用時間帯チェック')
        g_is_drive_times = False
        for item in g_ope_time_dic:
            #print(item)
            if item['start_time'] <= _current_time and _current_time < item['end_time']:
                #print(item['is_drive'])
                g_is_drive_times = g_config_dic['ope_time_' + str(item['id'])]

        logger("現在の時間＝" + str(_current_time))
        logger("運用時間帯か？＝" + str(g_is_drive_times))
        #break
        #実行時間
        await asyncio.sleep(3)

#######################################################
# データから最も値がかたまっている値群の平均値を求める関数
#######################################################
def get_clustered_values_average(data):
    #logger("get_clustered_values_average start")
    
    try:
        if len(data) == 0:
            return 0
        
        # データをソートする
        sorted_data = sorted(data)

        # 隣接する値の差を計算し、閾値より小さい差が続く値群を見つける
        threshold = 5  # 閾値を設定（この値を調整してください）
        clusters = []
        current_cluster = [sorted_data[0]]
        for i in range(1, len(sorted_data)):
            diff = sorted_data[i] - sorted_data[i - 1]
            if diff <= threshold:
                current_cluster.append(sorted_data[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [sorted_data[i]]
        clusters.append(current_cluster)

        # 値群ごとの平均値を計算し、最も値がかたまっている値群の平均値を取得する
        max_cluster = max(clusters, key=len)
        avg = round(sum(max_cluster) / len(max_cluster),1)
    
    except Exception as e:
        logger(str(e))
        avg = 0
    
    #logger("get_clustered_values_average end")

    return avg

#######################################################
# 水門開ける
#######################################################
async def wopen(sec=10):
    global g_open_close
    global g_count_down_since_opening
    try:
        if g_open_close == OPENCLOSE_OPEN:
            return
        g_open_close = OPENCLOSE_OPEN
        
        #(_today,_current_time) = getDateTime(utime.localtime())
        #show_status_opening(_current_time)

        logger('watergate open')
        M1.low()
        M2.high()
        
        logger('open sec=' + str(sec))
        #utime.sleep(sec)
        await asyncio.sleep(sec)

        M1.low()
        M2.low()
        

        logger('watergate stop')
        #utime.sleep(5)
        await asyncio.sleep(5)

    except Exception as e:
        logger(e)

    return

#######################################################
# 水門閉じる
#######################################################
async def wclose(sec=20):
    global g_open_close
    global g_count_down_since_opening

    try:
        if g_open_close == OPENCLOSE_CLOSE:
            return
        g_open_close = OPENCLOSE_CLOSE
        g_count_down_since_opening = 120

        #(_today,_current_time) = getDateTime(utime.localtime())
        #show_status_closing(_current_time)

        logger('watergate close')
        M1.high()
        M2.low()
        logger('close sec=' + str(sec))
        #utime.sleep(sec)
        await asyncio.sleep(sec)


        logger('watergate stop')

        M1.low()
        M2.low()
        #utime.sleep(5)
        await asyncio.sleep(5)


    except Exception as e:
        logger(str(e))

    return

#######################################################
# 距離測定関数定義
#######################################################
async def ultra():
    global g_water_level
    #logger('ultra start')
    #無限ループ
    while True:
        _values = []

        #データから最も値がかたまっている値群の平均値を求める
        for i in range(3):
            #logger('loop start')

            TRIG.low()
            utime.sleep_us(10) #2 10
            TRIG.high()
            utime.sleep_us(2) #5 2
            TRIG.low()
            k = 0
            while ECHO.value() == 0:
                signaloff = utime.ticks_us()
                k += 1
                if k > 10000:
                    logger('計測エラー1')
                    #ECHO.init(Pin.IN, Pin.PULL_DOWN)
                    #TRIG.init(Pin.OUT)

                    break
            k = 0
            while ECHO.value() == 1:
                signalon = utime.ticks_us()
                k += 1
                if k > 10000:
                    logger('計測エラー2')
                    #ECHO.init(Pin.IN, Pin.PULL_DOWN)
                    #TRIG.init(Pin.OUT)
                    break
                
            #logger('signalon:' + str(signalon))
            #logger('signaloff:' + str(signaloff))
            
            timepassed = signalon - signaloff

            distance = round((timepassed * 0.0343) / 2,1)
            logger(str(i+1) + '回目測定 ' + str(distance) + "cm")
        
            _values.append(distance)
        
            #utime.sleep(3)
            #ループ待ち
            await asyncio.sleep(3)
            
        g_water_level = get_clustered_values_average(_values)
        #ループ待ち
        await asyncio.sleep(3)

#     logger("average is " + str(ret) + "cm")
#     logger('ultra end')
# 
#     logger(str(ret))
    #return ret
#######################################################
# Callback関数の定義
#######################################################
def on_rx(data):
    global g_ble_ope_mode #log,menu,show,config
    global g_ble_commands #config → xxxx=9999,save,destory,
    print(data.strip())
    #logger(data.strip())
    #print("Data received: ", data)  # Print the received data
    #global led_state  # Access the global variable led_state
    if data.strip() == b'log':  # Check if the received data is "toggle"
        logger('log mode')
        g_ble_ope_mode = 'log'
        #g_ble_ope_mode = {mode: 'log', time: utime.localtime()}
    elif data.strip() == b'reset':  # Check if the received data is "toggle"
        reset()
        #g_ble_ope_mode = 'test'
        #g_ble_ope_mode = {mode: 'menu', time: utime.localtime()}
    elif data.strip() == b'self':  # Check if the received data is "toggle"
        logger('self mode')
        g_ble_ope_mode = 'self'
        #g_ble_ope_mode = {mode: 'menu', time: utime.localtime()}
    elif data.strip() == b'menu':  # Check if the received data is "toggle"
        logger('menu mode')
        g_ble_ope_mode = 'menu'
        #g_ble_ope_mode = {mode: 'menu', time: utime.localtime()}
    elif data.strip() == b'configure':  # Check if the received data is "toggle"
        logger('configure mode')
        g_ble_ope_mode = 'configure'
        #print('summary show')
        #g_ble_ope_mode = {mode: 'config', time: utime.localtime()}
    #else if data.strip() == b'save':  # Check if the received data is "toggle"
        #print('summary show')
        #g_ble_ope_mode = 'save'
    else:
        if g_ble_ope_mode == 'configure' or g_ble_ope_mode == 'menu' or g_ble_ope_mode == 'test' or g_ble_ope_mode == 'self':
            g_ble_commands.append({'mode': g_ble_ope_mode, 'command': data.strip(), 'timestamp': fromatDateTimeStr(utime.localtime())})




#######################################################
# ステータス表示
#######################################################
async def show_status_service():
    while True:
        await asyncio.sleep(g_config_dic["waiting_for_interval_sec"])
        show_status()



#######################################################
# 自動運転モード
#######################################################
async def auto_drive():
    global g_count_down_since_opening
    while True:
        await asyncio.sleep(g_config_dic["waiting_for_interval_sec"])
        if g_ble_ope_mode == "auto":
            g_count_down_since_opening -= 1
            
            #①時間の取得
            (_today,_current_time) = getDateTime(utime.localtime())

            logger("自動モード")

            #④判定 運用時間帯かつ　水位が基準を下回る
            if (g_count_down_since_opening <= 0) and g_is_drive_times and ((g_config_dic['water_level_correction_mm'] - g_water_level) < g_config_dic['open_closing_standards_mm']):
                logger('watergate open')
                await wopen(g_config_dic['open_time_sec'])

            #⑤判定 運用時間帯以外かつ　水位が4を下回る
            elif (g_count_down_since_opening <= 0) and (g_is_drive_times == False) and ((g_config_dic['water_level_correction_mm'] - g_water_level) < 4):
                logger('watergate open2')
                await wopen(g_config_dic['open_time_sec'])
            else:
                logger('watergate close')
                await wclose(g_config_dic['close_time_sec'])


#######################################################
# 時間取得処理定義
#######################################################
def fromatDateTime(localTIme):
    (Y,M,D,hr,m,s,w,y) = localTIme
    if s < 10:
        s = "0" + str(s)
    if m < 10:
        m = "0" + str(m)
    if hr < 10:
        hr = "0" + str(hr)
    if D < 10:
        D = "0" + str(D)
    if M < 10:
        M = "0" + str(M)

    _date = str(Y) + "/" + str(M) + "/" + str(D)
    _current_time = str(hr) + ":" + str(m) + ":" + str(s)

    return (_date,_current_time)
#######################################################
# 時間取得処理定義
#######################################################
def fromatDateTimeStr(localTIme):
    (Y,M,D,hr,m,s,w,y) = localTIme
    if s < 10:
        s = "0" + str(s)
    if m < 10:
        m = "0" + str(m)
    if hr < 10:
        hr = "0" + str(hr)
    if D < 10:
        D = "0" + str(D)
    if M < 10:
        M = "0" + str(M)

    _date = str(Y) + "/" + str(M) + "/" + str(D)
    _current_time = str(hr) + ":" + str(m) + ":" + str(s)

    return _date +  ' ' + _current_time
#######################################################
# 時間取得処理定義
#######################################################
def getDateTime(localTIme):
#    (Y,M,D,hr,m,s,w,y) = rtc.datetime()
    (Y,M,D,hr,m,s,w,y) = localTIme
    
    if s < 10:
        s = "0" + str(s)
    if m < 10:
        m = "0" + str(m)
    if hr < 10:
        hr = "0" + str(hr)
    if D < 10:
        D = "0" + str(D)
    if M < 10:
        M = "0" + str(M)

    _date = str(Y) + "/" + str(M) + "/" + str(D)
    _current_time = str(hr) + ":" + str(m)

    return (_date,_current_time)


#######################################################
# メイン処理定義
#######################################################
async def main():

    #初期処理
    logger('start')
    
    #初期設定
    global g_water_level
    global g_is_drive_times


    global g_ble_ope_mode
    global g_ble_commands
    global g_config_dic
    global g_ope_time_dic
    global g_count_down_since_opening

    #RTCの設定
    set_rtc()

    #門を一度完全に閉じる
    await wclose(g_config_dic['close_time_sec'])
    g_count_down_since_opening = 0

    #BLE通信
    BLE_SP.on_write(on_rx)    
    
    #初期設定情報の読み込み
    load_config()

    #水位測定
    asyncio.create_task(ultra())

    #運用時間チェック
    asyncio.create_task(check_drive_times())

    #自動運転処理
    asyncio.create_task(auto_drive())
    #ステータスをブルートースで送信
    asyncio.create_task(show_status_service())


    #無限ループ
    while True:
            
        #ループ待ち
        await asyncio.sleep(g_config_dic["waiting_for_interval_sec"])
        logger("g_ble_ope_mode=" + str(g_ble_ope_mode))
        logger("g_water_level=" + str(g_water_level))
        logger("g_count_down_since_opening=" + str(g_count_down_since_opening)) 
        if g_water_level == None:
            continue
        

          #強制オープンの場合
        if FORCE_OPEN.value() == FORCE_OPEN_ON:
            g_ble_ope_mode = "force"
            g_ble_commands = []
            await wopen(g_config_dic['open_time_sec'])
            continue
        
        #強制クローズの場合
        if FORCE_CLOSE.value() == FORCE_CLOSE_ON:
            g_ble_ope_mode = "force"
            g_ble_commands = []
            await wclose(g_config_dic['close_time_sec'])
            continue
        

        ## Bleコマンド処理
        #logger('モード=' + str(g_ble_ope_mode))
        #logger('コマンド=' + str(g_ble_commands))

        #コマンドがある場合
        if len(g_ble_commands) > 0:
            g_ble_commands.sort(key=lambda x: x['timestamp'])
            while len(g_ble_commands) > 0:
                command = g_ble_commands[0]
                logger(str(command))
                logger("------")
                logger(str(command['mode']))
                logger(str(command['command']))
                logger("------")
                #処理する
                if str(command['mode']) == 'configure':
                    g_count_down_since_opening = 0
                    #処理をする
                    if command['command'] == b'save':
                        # 設定ファイルの書き込み
                        with open(CONFIG_JSON_FILE, 'w') as f:
                            json.dump(g_config_dic,f, separators=(',', ': '))

                    elif '=' in command['command']:
                        kv = command['command'].split('=')

                        if kv[0] in g_config_dic:
                            g_config_dic[kv[0]] = kv[1]

                    else:
                        if str(command['command']) in g_config_dic:
                            logger(command['command'] + '=' + g_config_dic[command['command']])
                            
                elif str(command['mode']) == 'self':
                    logger("self mode")

                    #処理をする
                    if command['command'] == b'open':
                        logger("open command  run")
                        await wopen(g_config_dic['open_time_sec'])
                    elif command['command'] == b'close':
                        logger("close command  run")
                        await wclose(g_config_dic['close_time_sec'])

                elif str(command['mode']) == 'menu':
                    None

                #処理したら、行削除
                g_ble_commands.remove(command)
                g_count_down_since_opening = 0

        elif g_ble_ope_mode == "auto":
            pass
        elif g_ble_ope_mode == "test":
            await wopen(g_config_dic['open_time_sec'])
            await wclose(g_config_dic['close_time_sec'])
            g_count_down_since_opening = 0
            g_ble_ope_mode = "auto"
        else:
            g_ble_ope_mode = "auto"


#######################################################
# 水門開閉管理 処理実行
#######################################################
try:
    #メイン処理
    asyncio.run(main())
except Exception as e:
    logger(str(e))
finally:
    #終了してきた場合は、リセットする
    utime.sleep(5)
    reset()





