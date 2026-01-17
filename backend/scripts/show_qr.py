import socket
import os
import sys

# Windows環境での文字コードエラー対策
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 実際に接続はしないが、ルートを確認してIPを特定する
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def show_qr():
    ip = get_local_ip()
    port = "8000"
    url = f"http://{ip}:{port}"
    
    # コンソールクリア
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("\n" + "="*50)
    print(f" 📱 Scan to open Nia on Mobile")
    print(f" 🔗 {url}")
    print("="*50 + "\n")
    
    # QRコード表示試行
    try:
        import qrcode
        qr = qrcode.QRCode()
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except ImportError:
        print("⚠️ 'qrcode' library not found.")
        print("   Run: pip install qrcode")
        print("   (You can still access via the URL above)")

if __name__ == "__main__":
    show_qr()
