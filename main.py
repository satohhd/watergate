#######################################################
# 水門開閉管理 2024.4.8
#######################################################

#必要なライブラリのインポート
from machine import SoftI2C, Pin, RTC
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
#AUTOSELF_AUTO = 0
#AUTOSELF_SELF = 1
OPENCLOSE_OPEN = 0
OPENCLOSE_CLOSE = 1
FORCE_OPEN_ON = 0
FORCE_OPEN_OFF = 1
FORCE_CLOSE_ON = 0
FORCE_CLOSE_OFF = 1


#######################################################
# 変数
#######################################################
g_ble_ope_mode = "show"
g_ble_commands = []
g_config_dic = {
                "water_level_correction_mm": 50, \
                "waiting_for_interval_sec": 5, \
                "open_closing_standards_mm": 7, \
                "distance_correction": 3, \
                "open_time_sec": 25, \
                "close_time_sec": 40, \
                "ope_time_1": False, \
                "ope_time_2": True, \
                "ope_time_3": False, \
                "ope_time_4": False, \
                "ope_time_5": False, \
                "ope_time_6": False \
            }

g_ope_time_dic = [ \
                    {"id": 1,"start_time": "00:00", "end_time": "04:00" }, \
                    {"id": 2,"start_time": "04:00", "end_time": "08:00" }, \
                    {"id": 3,"start_time": "08:00", "end_time": "12:00" }, \
                    {"id": 4,"start_time": "12:00", "end_time": "16:00" }, \
                    {"id": 5,"start_time": "16:00", "end_time": "20:00" }, \
                    {"id": 6,"start_time": "20:00", "end_time": "24:00" } \
                ]

g_count_down_since_opening = 0
#######################################################
#関数ログ出力関数定義
#######################################################
def logger(msg):
    global g_ble_ope_mode
    try:
        _dateTime = fromatDateTimeStr(utime.localtime())

        formated_msg = _dateTime + ' ' + msg + '\n'
        if BLE_SP.is_connected():
            if g_ble_ope_mode == 'log':
                BLE_SP.send(formated_msg)

        with open(LOG_FILE, 'a') as f:  # ファイルを追記モードで開く
            f.write(formated_msg)    # 追記実行（文字列で）※改行付
            #print("Append:", data)  # 追記データ表示

        print(formated_msg.strip())
    except Exception as e:
        print('logger error:' + str(e))
        with open(LOG_FILE, 'w') as f:  # ファイルを追記モードで開く
            f.write(formated_msg)    # 追記実行（文字列で）※改行付
            #print("Append:", data)  # 追記データ表示

#######################################################
# データから最も値がかたまっている値群の平均値を求める関数
#######################################################
def get_clustered_values_average(data):
    logger("get_clustered_values_average start")
    
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
    
    logger("get_clustered_values_average end")

    return avg

#######################################################
# 水門開ける
#######################################################
def wopen(sec=10):

    try:
        logger('watergate open')
        M1.low()
        M2.high()
        
        logger('open sec=' + str(sec))
        utime.sleep(sec)
        M1.low()
        M2.low()
        

        logger('watergate stop')
        utime.sleep(5)

    except Exception as e:
        logger(e)

    return "Open OK"

#######################################################
# 水門閉じる
#######################################################
def wclose(sec=20):


    try:
        logger('watergate close')
        M1.high()
        M2.low()
        logger('close sec=' + str(sec))
        utime.sleep(sec)

        logger('watergate stop')

        M1.low()
        M2.low()

        utime.sleep(5)


    except Exception as e:
        logger(str(e))

    return "Close OK"

#######################################################
# 距離測定関数定義
#######################################################
def ultra():
    global TRIG
    global ECHO
    

    logger('ultra start')
    _values = []

    #データから最も値がかたまっている値群の平均値を求める
    for i in range(3):
        logger('loop start')

        TRIG.low()
        utime.sleep_us(2) #2 10
        TRIG.high()
        utime.sleep_us(10) #5 2
        TRIG.low()
        k = 0
        signaloff = 0.0
        while ECHO.value() == 0:
            signaloff = utime.ticks_us()
            k += 1
            if k > 10000:
                logger('計測エラー1')
                #ECHO.init(Pin.IN, Pin.PULL_DOWN)
                #TRIG.init(Pin.OUT)
                signaloff = 0.0

                break
        k = 0
        signalon = 0.0
        while ECHO.value() == 1:
            signalon = utime.ticks_us()
            k += 1
            if k > 10000:
                logger('計測エラー2')
                #ECHO.init(Pin.IN, Pin.PULL_DOWN)
                #TRIG.init(Pin.OUT)
                signalon = 0.0
                break
            
        logger('距離算出')
        logger('signalon:' + str(signalon))
        logger('signaloff:' + str(signaloff))
        #timepassed = signalon - signaloff
        timepassed = utime.ticks_diff(signalon, signaloff)
        #logger('signalon:' + str(signalon))
        #logger('signaloff:' + str(signaloff))

        distance = round((timepassed * 0.0343) / 2,1)
        distance_correction = g_config_dic['distance_correction']
        water_level_correction_mm = g_config_dic['water_level_correction_mm']
        
        logger(str(i+1) + '回目測定 ' + str(distance + distance_correction) + "cm")
        if distance > 0 and distance < 100:
            _values.append(distance + distance_correction)
        else:
            _values.append(water_level_correction_mm)
            
    
        utime.sleep(5)
        
        
    ret = get_clustered_values_average(_values)
    logger("average is " + str(ret) + "cm")
    logger('ultra end')

    logger(str(ret))
    return ret

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

# Define a callback function to handle received data
#######################################################
# Callback関数の定義
#######################################################
def on_rx(data):
    global g_ble_ope_mode
    #log,menu,show,config
    global g_ble_commands
    #config → xxxx=9999,save,destory,
    print(data.strip())
    #logger(data.strip())
    #print("Data received: ", data)  # Print the received data
    #global led_state  # Access the global variable led_state
    if data.strip() == b'log':  # Check if the received data is "toggle"
        logger('log mode')
        g_ble_ope_mode = 'log'
        #g_ble_ope_mode = {mode: 'log', time: utime.localtime()}
    elif data.strip() == b'test':  # Check if the received data is "toggle"
        logger('test mode')
        g_ble_ope_mode = 'test'
        #g_ble_ope_mode = {mode: 'menu', time: utime.localtime()}
    elif data.strip() == b'self':  # Check if the received data is "toggle"
        logger('self mode')
        g_ble_ope_mode = 'self'
        #g_ble_ope_mode = {mode: 'menu', time: utime.localtime()}
    elif data.strip() == b'menu':  # Check if the received data is "toggle"
        logger('menu mode')
        g_ble_ope_mode = 'menu'
        #g_ble_ope_mode = {mode: 'menu', time: utime.localtime()}
    elif data.strip() == b'show':  # Check if the received data is "toggle"
        logger('show mode')
        g_ble_ope_mode = 'show'
        #g_ble_ope_mode = {mode: 'show', time: utime.localtime()}
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
# 状態表示定義
#######################################################
def show_status(level,openClose,is_drive):
    global g_config_dic
    
    if BLE_SP.is_connected():
        formated_msg = '現在水位' + str(round(g_config_dic['water_level_correction_mm'] - level,1)) + 'cm ' \
               + '閾値' + str(g_config_dic['open_closing_standards_mm']) + 'cm' \
               + ' ' + ('自動' if g_ble_ope_mode != 'self' else '手動') \
               + ' ' + ('開門' if openClose == OPENCLOSE_OPEN else '閉門') \
               + ' ' + ('運転時間帯' if is_drive==True else '停止時間帯') 
        BLE_SP.send(formated_msg)

#######################################################
# メイン処理定義
#######################################################
def main():

    #初期処理
    logger('start')
    
    #初期設定
    global g_ble_ope_mode
    global g_ble_commands
    global g_config_dic
    global g_ope_time_dic
    global g_count_down_since_opening


    #RTCから時刻取得
    logger('rtc connect')
    _i2c_rtc = SoftI2C(scl = Pin(1),sda = Pin(0),freq = 100000)
    _result = SoftI2C.scan(_i2c_rtc)
    _rtc = DS1307(_i2c_rtc)

    #時間設定
    #utime.localtime()
    logger('datetime setting')
    RTC().datetime(_rtc.datetime())

    logger('watergate close')

    #門を一度完全に閉じる
    wclose(g_config_dic['close_time_sec'])
    _openClose = OPENCLOSE_CLOSE #1
    
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

    #ループ待ち時間
    _wfis = g_config_dic["waiting_for_interval_sec"]
    #水位
    _level = 0.0
    #手動自動運転
    _is_drive = False
    
    #自動手動スイッチ情報退避
    #_back_auto_self = AUTOSELF.value()

    


    #無限ループ
    while True:
        #①時間の取得
        (_today,_current_time) = getDateTime(utime.localtime())

        #②水位の測定
        try:
            _level = ultra()
        except Exception as e:
            logger(str(e))
            #_level = 0

        #③運用時間帯チェック
        _is_drive = False
        for item in g_ope_time_dic:
            #print(item)
            if item['start_time'] <= _current_time and _current_time < item['end_time']:
                #print(item['is_drive'])
                _is_drive = g_config_dic['ope_time_' + str(item['id'])]
                print("現在の時間＝" + str(_current_time))
                print("運用時間帯か？＝" + str(_is_drive))
                #break

        #print("test=" + FORCE_OPEN)

         #強制オープンの場合
        if FORCE_OPEN.value() == FORCE_OPEN_ON:
            g_count_down_since_opening = 0
            logger('FORCE_OPEN_ON')
            g_ble_ope_mode = "self"
            #show_status(_level,OPENCLOSE_OPEN,_is_drive)
            show_status(_level,_openClose,_is_drive)
            if _openClose != OPENCLOSE_OPEN:
                _openClose = OPENCLOSE_OPEN #1
                show_status(_level,_openClose,_is_drive)
                wopen(g_config_dic['open_time_sec'])

            g_ble_ope_mode = "show"
            continue
        
        #強制クローズの場合
        if FORCE_CLOSE.value() == FORCE_CLOSE_ON:
            g_count_down_since_opening = 0
            logger('FORCE_CLOSE_ON')
            g_ble_ope_mode = "self"
            #show_status(_level,OPENCLOSE_CLOSE,_is_drive)
            show_status(_level,_openClose,_is_drive)
            if _openClose != OPENCLOSE_CLOSE:
                _openClose = OPENCLOSE_CLOSE #1
                show_status(_level,_openClose,_is_drive)
                wclose(g_config_dic['close_time_sec'])

            g_ble_ope_mode = "show"
            continue
        
        #運転モード
        #if _is_drive != True:
        #    continue
        #if g_ble_ope_mode == "self"
        #    g_ble_ope_mode = "show"
        

         #①BLE通信
        if BLE_SP.is_connected():  # Check if a BLE connection is established
            logger('ble setting')
            BLE_SP.on_write(on_rx)  # Set the callback function for data reception

        ## Bleコマンド処理
        logger('モード=' + str(g_ble_ope_mode))
        logger('コマンド=' + str(g_ble_commands))

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
                        show_status(_level,_openClose,_is_drive)
                        if _openClose != OPENCLOSE_OPEN:
                            _openClose = OPENCLOSE_OPEN #1
                            show_status(_level,_openClose,_is_drive)
                            wopen(g_config_dic['open_time_sec'])
                    elif command['command'] == b'close':
                        logger("close command  run")
                        show_status(_level,_openClose,_is_drive)
                        if _openClose != OPENCLOSE_CLOSE:
                            _openClose = OPENCLOSE_CLOSE #1
                            show_status(_level,_openClose,_is_drive)
                            wclose(g_config_dic['close_time_sec'])

                elif str(command['mode']) == 'menu':
                    None

                #処理したら、行削除
                g_ble_commands.remove(command)

        elif g_ble_ope_mode == "test":
            g_count_down_since_opening = 0
            show_status(_level,_openClose,_is_drive)
            if _openClose != OPENCLOSE_OPEN:
                _openClose = OPENCLOSE_OPEN #1
                show_status(_level,_openClose,_is_drive)
                wopen(g_config_dic['open_time_sec'])
            if _openClose != OPENCLOSE_CLOSE:
                _openClose = OPENCLOSE_CLOSE #1
                show_status(_level,_openClose,_is_drive)
                wclose(g_config_dic['close_time_sec'])

            g_ble_ope_mode = "show"
        elif g_ble_ope_mode == "show":
            g_count_down_since_opening = 0
            show_status(_level,_openClose,_is_drive)
#             if BLE_SP.is_connected():
#                 formated_msg = '現在水位' + str(round(g_config_dic['water_level_correction_mm'] - _level,1)) + 'cm ' \
#                        + '閾値' + str(g_config_dic['open_closing_standards_mm']) + 'cm' \
#                        + ' ' + ('自動' if AUTOSELF.value() == AUTOSELF_AUTO else '手動') \
#                        + ' ' + ('開門' if _openClose == OPENCLOSE_OPEN else '閉門') \
#                        + ' ' + ('運転時間帯' if _is_drive==True else '停止時間帯') 
#                 BLE_SP.send(formated_msg)


        #自動手動スイッチの切替判断 (物理スイッチを変更した場合は、ソフトセルフは解除される)
#         if AUTOSELF.value() != _back_auto_self:
#             if AUTOSELF.value() == AUTOSELF_AUTO:
#                 g_ble_ope_mode = 'show'
#             else:
#                 g_ble_ope_mode = 'self'
# 
#             #直近の情報保持
#             _back_auto_self = AUTOSELF.value()



        #自動時の繰り返し処理
        if g_ble_ope_mode != 'self' :
            
            #①時間の取得
            (_today,_current_time) = getDateTime(utime.localtime())

            logger("自動モード")


#             logger('現在水位:' + str(round(g_config_dic['water_level_correction_mm'] - _level,1)))
#             logger('開門基準:' + str(g_config_dic['open_closing_standards_mm']))
#             logger(' 運用時間' if _is_drive==True else ' 停止時間')
#             
            #④判定 運用時間帯かつ　水位が基準を下回る
            if g_count_down_since_opening <= 0 and _is_drive and ((g_config_dic['water_level_correction_mm'] - _level) < g_config_dic['open_closing_standards_mm']):
                logger('watergate open')
                g_count_down_since_opening = 30
                show_status(_level,_openClose,_is_drive)
                if _openClose != OPENCLOSE_OPEN:
                    _openClose = OPENCLOSE_OPEN #0
                    show_status(_level,_openClose,_is_drive)
                    wopen(g_config_dic['open_time_sec'])
            else:
                logger('watergate close')
                g_count_down_since_opening -= 1
                show_status(_level,_openClose,_is_drive)
                if _openClose != OPENCLOSE_CLOSE:
                    _openClose = OPENCLOSE_CLOSE #1
                    show_status(_level,_openClose,_is_drive)
                    wclose(g_config_dic['close_time_sec'])


#         #手動時の繰り返し処理
#         if g_ble_ope_mode == 'self':
#             #①時間の取得
#             (_today,_current_time) = getDateTime(utime.localtime())
# 
#             logger("手動モード")
# 
#             if SELFOPENCLOSE.value() == OPENCLOSE_OPEN:
#                 logger('watergate open')
#                 if _openClose != OPENCLOSE_OPEN:
#                     _openClose = OPENCLOSE_OPEN #0
#                     show_status(_level,_openClose,_is_drive)
#                     wopen(g_config_dic['open_time_sec'])
#             else:
#                 logger('watergate close')
#                 if _openClose != OPENCLOSE_CLOSE:
#                     _openClose = OPENCLOSE_CLOSE #1
#                     show_status(_level,_openClose,_is_drive)
#                     wclose(g_config_dic['close_time_sec'])
            logger('g_count_down_since_opening =' + str(g_count_down_since_opening))

        #ループ待ち
        utime.sleep(_wfis)




#######################################################
# 水門開閉管理 処理実行
#######################################################
try:
    #無限ループ
    while True:
        main()

except Exception as e:
    logger(str(e))




