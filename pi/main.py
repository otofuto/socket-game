import network
import socket
import time
import json
import machine
from machine import Pin, PWM

# 設定ファイル読み込み
def load_config():
    """設定ファイルを読み込み"""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        print("設定ファイルを読み込みました")
        return config
    except OSError:
        print("config.jsonが見つかりません。デフォルト設定を使用します")
        # デフォルト設定
        return {
            "wifi": {
                "ssid": "Buffalo-2G-16F0",
                "password": "i3n7wuvewa5br"
            },
            "websocket": {
                "host": "mb2022.local",
                "port": 3033,
                "path": "/ws/ws"
            },
            "gpio": {
                "led_r_pin": 9,
                "led_l_pin": 3,
                "button_r_pin": 28,
                "button_l_pin": 27
            },
            "settings": {
                "timeout_ms": 10000,
                "check_interval_ms": 5
            }
        }
    except Exception as e:
        print(f"設定ファイル読み込みエラー: {e}")
        raise

# 設定読み込み
config = load_config()

# 設定値を変数に展開
WIFI_SSID = config["wifi"]["ssid"]
WIFI_PASSWORD = config["wifi"]["password"]
WS_HOST = config["websocket"]["host"]
WS_PORT = config["websocket"]["port"]
WS_PATH = config["websocket"]["path"]

# GPIO設定
led_r_pin = Pin(config["gpio"]["led_r_pin"], Pin.OUT)
led_l_pin = Pin(config["gpio"]["led_l_pin"], Pin.OUT)
button_r_pin = Pin(config["gpio"]["button_r_pin"], Pin.IN, Pin.PULL_UP)
button_l_pin = Pin(config["gpio"]["button_l_pin"], Pin.IN, Pin.PULL_UP)

# PWM設定（右LEDのみ）
led_r_pwm = None
wifi_connecting = False
fade_start_time = 0
fade_direction = 1  # 1: フェードイン, -1: フェードアウト

# その他設定
TIMEOUT_MS = config["settings"]["timeout_ms"]
CHECK_INTERVAL_MS = config["settings"]["check_interval_ms"]

# 計測状態管理
measuring = False
start_time = 0
button_r_pressed = False
button_l_pressed = False
last_button_r_state = 1  # 前回のボタン状態（1=押されていない）
last_button_l_state = 1
expected_button = None  # 押すべきボタン（"right", "left", None）

def setup_fade_led():
    """右LEDのPWM制御を初期化"""
    global led_r_pwm, wifi_connecting, fade_start_time, fade_direction
    led_r_pwm = PWM(led_r_pin)
    led_r_pwm.freq(1000)  # 1kHz
    led_r_pwm.duty_u16(0)  # 初期値は消灯
    wifi_connecting = True
    fade_start_time = time.ticks_ms()
    fade_direction = 1
    print("右LED PWM制御開始")

def stop_fade_led():
    """右LEDのPWM制御を停止し、通常制御に戻す"""
    global led_r_pwm, wifi_connecting
    if led_r_pwm:
        led_r_pwm.duty_u16(0)
        time.sleep(0.01)
        led_r_pwm.deinit()
        led_r_pwm = None
    wifi_connecting = False
    global led_r_pin
    led_r_pin = Pin(config["gpio"]["led_r_pin"], Pin.OUT)
    led_r_pin.off()  # 通常制御に戻す
    print("右LED PWM制御停止")

def update_fade_led():
    """右LEDのフェード処理（1秒でフェードイン、1秒でフェードアウト）"""
    global fade_start_time, fade_direction
    
    if not wifi_connecting or not led_r_pwm:
        return
    
    current_time = time.ticks_ms()
    elapsed = time.ticks_diff(current_time, fade_start_time)
    
    # 1秒（1000ms）でフェードイン/アウト
    fade_duration = 1000
    
    if elapsed >= fade_duration:
        # 方向を反転して次のフェードを開始
        fade_direction = -fade_direction
        fade_start_time = current_time
        elapsed = 0
    
    # 進行度を計算（0.0 - 1.0）
    progress = elapsed / fade_duration
    
    if fade_direction == 1:  # フェードイン
        duty_value = int(progress * 65535)
    else:  # フェードアウト
        duty_value = int((1.0 - progress) * 65535)
    
    led_r_pwm.duty_u16(duty_value)

def wifi_failure_blink():
    """WiFi接続失敗時に右LEDを0.1秒間隔で4回点滅"""
    print("WiFi接続失敗 - エラー表示点滅開始")
    for i in range(4):
        led_r_pin.on()
        time.sleep(0.1)
        led_r_pin.off()
        time.sleep(0.1)
        print(f"エラー点滅 {i+1}/4")
    print("エラー表示点滅完了")

def connect_wifi():
    """WiFiに接続"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        print(f"WiFi接続中... ({WIFI_SSID})")
        
        # PWM制御開始
        setup_fade_led()
        
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        
        # 接続を待機
        timeout = 10
        while not wlan.isconnected() and timeout > 0:
            update_fade_led()  # フェード処理を更新
            time.sleep(0.1)
            timeout -= 0.1
            print("接続を待機中...")
        
        # PWM制御停止
        stop_fade_led()
        
        if wlan.isconnected():
            print(f"WiFi接続成功: {wlan.ifconfig()}")
            return True
        else:
            print("WiFi接続に失敗しました")
            # 失敗時のエラー点滅
            wifi_failure_blink()
            return False
    else:
        print("WiFiは既に接続されています")
        return True

def create_websocket_key():
    """WebSocketハンドシェイク用のキーを生成"""
    try:
        import ubinascii
        import urandom
        key = ubinascii.b2a_base64(bytes([urandom.getrandbits(8) for _ in range(16)])).decode().strip()
        return key
    except ImportError:
        # urandomが使用できない場合の代替
        import time
        import ubinascii
        # 簡易的なランダムキー生成（時間ベース）
        seed = int(time.time() * 1000000) % 65536
        key_bytes = [(seed + i) % 256 for i in range(16)]
        key = ubinascii.b2a_base64(bytes(key_bytes)).decode().strip()
        return key

def websocket_handshake(sock, host, path):
    """WebSocketハンドシェイクを実行"""
    key = create_websocket_key()
    
    handshake = f"""GET {path} HTTP/1.1\r
Host: {host}\r
Upgrade: websocket\r
Connection: Upgrade\r
Sec-WebSocket-Key: {key}\r
Sec-WebSocket-Version: 13\r
\r
"""
    
    sock.send(handshake.encode())
    response = sock.recv(1024).decode()
    
    if "101 Switching Protocols" in response:
        print("WebSocketハンドシェイク成功")
        return True
    else:
        print(f"WebSocketハンドシェイク失敗: {response}")
        return False

def websocket_send(sock, message):
    """WebSocketメッセージを送信"""
    try:
        import urandom
        mask_key = bytes([urandom.getrandbits(8) for _ in range(4)])
    except ImportError:
        # urandomが使用できない場合の代替
        import time
        seed = int(time.time() * 1000000) % 65536
        mask_key = bytes([(seed + i) % 256 for i in range(4)])
    
    # JSON文字列をバイトに変換
    payload = message.encode('utf-8')
    payload_len = len(payload)
    
    # ペイロードをマスク
    masked_payload = bytes([payload[i] ^ mask_key[i % 4] for i in range(payload_len)])
    
    # WebSocketフレームを構築
    frame = bytearray()
    frame.append(0x81)  # FIN=1, TEXT frame
    
    if payload_len < 126:
        frame.append(payload_len | 0x80)  # MASK=1
    elif payload_len < 65536:
        frame.append(126 | 0x80)
        frame.extend(payload_len.to_bytes(2, 'big'))
    else:
        frame.append(127 | 0x80)
        frame.extend(payload_len.to_bytes(8, 'big'))
    
    frame.extend(mask_key)
    frame.extend(masked_payload)
    
    sock.send(frame)

def websocket_recv_nonblocking(sock):
    """WebSocketメッセージを非ブロッキングで受信"""
    try:
        # ソケットを非ブロッキングモードに設定
        sock.settimeout(0.001)  # 1msタイムアウト
        
        # 最初の2バイトを読む
        header = sock.recv(2)
        if len(header) < 2:
            return None
        
        # ペイロード長を取得
        payload_len = header[1] & 0x7F
        
        if payload_len == 126:
            length_bytes = sock.recv(2)
            payload_len = int.from_bytes(length_bytes, 'big')
        elif payload_len == 127:
            length_bytes = sock.recv(8)
            payload_len = int.from_bytes(length_bytes, 'big')
        
        # ペイロードを読む
        payload = sock.recv(payload_len)
        
        if len(payload) == payload_len:
            try:
                return payload.decode('utf-8')
            except:
                return None
        
    except OSError:
        # タイムアウトまたはデータなし
        return None
    except Exception as e:
        print(f"メッセージ受信エラー: {e}")
        return None
    
    return None

def control_led(command):
    """LED制御と計測開始"""
    global measuring, start_time, button_r_pressed, last_button_r_state, button_l_pressed, last_button_l_state, expected_button
    
    if command == "led_r":
        led_r_pin.on()
        measuring = True
        button_r_pressed = False  # 常にFalseにリセット
        start_time = time.ticks_ms()
        expected_button = "right"  # 右ボタンを押すべき
        
        # 現在のボタン状態を確認
        current_state = button_r_pin.value()
        if current_state == 0:  # 既にボタンが押されている
            last_button_r_state = 0  # 現在の状態を記録
            print("右LED点灯時に既にボタンが押されています")
        else:
            last_button_r_state = 1  # 押されていない状態
        
        print(f"右LED点灯 - 計測開始: {start_time}ms, 初期ボタン状態: {last_button_r_state}, 期待ボタン: {expected_button}")

    elif command == "led_l":
        led_l_pin.on()
        measuring = True
        button_l_pressed = False  # 常にFalseにリセット
        start_time = time.ticks_ms()
        expected_button = "left"  # 左ボタンを押すべき
        
        # 現在のボタン状態を確認
        current_state = button_l_pin.value()
        if current_state == 0:  # 既にボタンが押されている
            last_button_l_state = 0  # 現在の状態を記録
            print("左LED点灯時に既にボタンが押されています")
        else:
            last_button_l_state = 1  # 押されていない状態
        
        print(f"左LED点灯 - 計測開始: {start_time}ms, 初期ボタン状態: {last_button_l_state}, 期待ボタン: {expected_button}")

def check_button_and_timeout():
    """ボタン押下チェックとタイムアウト処理"""
    global measuring, start_time, button_r_pressed, last_button_r_state, button_l_pressed, last_button_l_state, expected_button
    
    current_time = time.ticks_ms()
    current_button_r_state = button_r_pin.value()
    current_button_l_state = button_l_pin.value()
    
    # 計測中の場合
    if measuring:
        elapsed_time = time.ticks_diff(current_time, start_time)
        
        # 右ボタンの状態変化を検出（1から0への変化 = 押下）
        if last_button_r_state == 1 and current_button_r_state == 0 and not button_r_pressed:
            button_r_pressed = True
            
            if expected_button == "right":
                # 正解 - LEDを消して計測終了
                led_r_pin.off()
                measuring = False
                expected_button = None
                print(f"右ボタン押下検出！ - 反応時間: {elapsed_time}ms")
                return elapsed_time
            else:
                # 間違い（左ボタンを押すべきだった） - LEDはそのままでmissのみ送信
                print(f"右ボタン押下検出（間違い）！ - 経過時間: {elapsed_time}ms")
                return "miss"
        
        # 右ボタンが離された場合のフラグリセット
        if last_button_r_state == 0 and current_button_r_state == 1:
            button_r_pressed = False
        
        # 左ボタンの状態変化を検出（1から0への変化 = 押下）
        if last_button_l_state == 1 and current_button_l_state == 0 and not button_l_pressed:
            button_l_pressed = True
            
            if expected_button == "left":
                # 正解 - LEDを消して計測終了
                led_l_pin.off()
                measuring = False
                expected_button = None
                print(f"左ボタン押下検出！ - 反応時間: {elapsed_time}ms")
                return elapsed_time
            else:
                # 間違い（右ボタンを押すべきだった） - LEDはそのままでmissのみ送信
                print(f"左ボタン押下検出（間違い）！ - 経過時間: {elapsed_time}ms")
                return "miss"
        
        # 左ボタンが離された場合のフラグリセット
        if last_button_l_state == 0 and current_button_l_state == 1:
            button_l_pressed = False
        
        # タイムアウトチェック（10秒）
        if elapsed_time >= TIMEOUT_MS:
            led_r_pin.off()
            led_l_pin.off()
            measuring = False
            expected_button = None  # 期待ボタンをリセット
            print(f"タイムアウト！ - LED消灯 (経過時間: {elapsed_time}ms)")
            return "timeout"
    
    # 計測中でない場合でも、ボタン状態の変化を検出（何もしない）
    else:
        # 右ボタンの状態変化を検出
        if last_button_r_state == 1 and current_button_r_state == 0:
            print("右ボタン押下検出（計測中ではない）- 何もしません")
        
        # 左ボタンの状態変化を検出
        if last_button_l_state == 1 and current_button_l_state == 0:
            print("左ボタン押下検出（計測中ではない）- 何もしません")
    
    # ボタン状態を常に更新
    last_button_r_state = current_button_r_state
    last_button_l_state = current_button_l_state
    
    return None

def resolve_hostname(hostname):
    """ホスト名をIPアドレスに解決"""
    try:
        import socket
        addr_info = socket.getaddrinfo(hostname, 80)
        ip = addr_info[0][-1][0]
        print(f"ホスト名解決: {hostname} -> {ip}")
        return ip
    except Exception as e:
        print(f"ホスト名解決エラー ({hostname}): {e}")
        return None

def main():
    """メイン処理"""
    print("プログラム開始")
    
    # 起動時LED点滅（右→左）
    led_r_pin.off()
    led_l_pin.off()
    time.sleep(0.1)
    led_r_pin.on()
    time.sleep(0.1)
    led_r_pin.off()
    time.sleep(0.3)
    led_l_pin.on()
    time.sleep(0.1)
    led_l_pin.off()
    
    # WiFi接続
    print("WiFi接続を開始します...")
    if not connect_wifi():
        print("WiFi接続に失敗しました")
        return
    
    # WiFi接続完了後、右LEDを確実にオフにする
    led_r_pin.off()
    print("WiFi接続完了 - 右LEDをオフにしました")
    
    # ホスト名解決
    print(f"ホスト名を解決中: {WS_HOST}")
    ip_address = resolve_hostname(WS_HOST)
    if not ip_address:
        print("ホスト名の解決に失敗しました")
        return
    
    try:
        # ソケット作成
        print("ソケットを作成中...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        print(f"WebSocket接続中... ({ip_address}:{WS_PORT})")
        
        # WebSocketサーバーに接続
        sock.connect((ip_address, WS_PORT))
        
        # WebSocketハンドシェイク
        print("WebSocketハンドシェイクを実行中...")
        if not websocket_handshake(sock, WS_HOST, WS_PATH):
            print("WebSocketハンドシェイクに失敗しました")
            sock.close()
            return
        
        # 接続完了メッセージを送信
        print("接続完了メッセージを送信中...")
        connect_msg = json.dumps({"message": "connected"})
        websocket_send(sock, connect_msg)
        print("接続完了メッセージを送信しました")
        
        # メッセージ受信ループ
        print("メッセージ受信ループを開始...")
        while True:
            try:
                # WebSocketメッセージ受信（非ブロッキング）
                message = websocket_recv_nonblocking(sock)
                if message:
                    print(f"受信: {message}")
                    
                    try:
                        data = json.loads(message)
                        if data.get("message") == "led_r":
                            control_led("led_r")
                        elif data.get("message") == "led_l":
                            control_led("led_l")
                        elif data.get("message") == "pico":
                            # Pico動作確認用の応答
                            response_msg = json.dumps({"message": "running"})
                            websocket_send(sock, response_msg)
                            print("Pico動作確認応答を送信: running")
                    except Exception as json_e:
                        print(f"JSONパースエラー: {json_e}")
                
                # ボタン押下とタイムアウトをチェック
                result = check_button_and_timeout()
                if result is not None:
                    if result == "timeout":
                        # タイムアウトの場合は何も送信しない
                        print("タイムアウト処理完了")
                    elif result == "miss":
                        # ミスの場合は"miss"を送信
                        response_msg = json.dumps({"message": "miss"})
                        websocket_send(sock, response_msg)
                        print("ミス送信: miss")
                    else:
                        # 反応時間を送信
                        response_msg = json.dumps({"message": str(result)})
                        websocket_send(sock, response_msg)
                        print(f"反応時間送信: {result}ms")
                
                time.sleep(CHECK_INTERVAL_MS / 1000.0)  # 設定ファイルの間隔でチェック
                
            except Exception as loop_e:
                print(f"メッセージ処理エラー: {loop_e}")
                import sys
                sys.print_exception(loop_e)
                break
                
    except Exception as e:
        print(f"接続エラー: {e}")
        import sys
        sys.print_exception(e)  # 詳細なエラー情報を表示
    
    finally:
        # PWM制御が残っていれば停止
        stop_fade_led()
        try:
            sock.close()
            print("ソケットを閉じました")
        except Exception as close_e:
            print(f"ソケット終了エラー: {close_e}")
        print("接続を終了しました")

# プログラム実行
if __name__ == "__main__":
    main()