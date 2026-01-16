import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import subprocess
import threading
import sys
from pathlib import Path
import os
import platform
import re
import locale

# --- [중요] 앱 내부의 FFmpeg를 인식하도록 경로 설정 ---
# PyInstaller로 포장된 앱(frozen 상태)에서 실행될 때,
# 임시 압축 해제 폴더(sys._MEIPASS)를 시스템 PATH에 추가하여
# subprocess가 ffmpeg 명령어를 바로 찾을 수 있게 함.
if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
    os.environ["PATH"] += os.pathsep + bundle_dir

# --- 설정 ---
BASE_PATH = Path(__file__).parent
DOWNLOADS_DIR = "downloads"
SEPARATED_DIR = "separated"
# 윈도우 로컬 테스트용 Rubberband 경로 (그대로 유지)
RUBBERBAND_PATH = "C:/ffmpeg/rubberband-4.0.0-gpl-executable-windows"
SYSTEM_ENCODING = locale.getpreferredencoding()

class OutputRedirector:
    """터미널 출력을 텍스트 창에 보여주는 역할"""
    def __init__(self, text_widget, progress_var):
        self.text_widget = text_widget
        self.progress_var = progress_var

    def write(self, string):
        try:
            self.text_widget.insert(tk.END, string)
            self.text_widget.see(tk.END)
            
            # 진행률 파싱
            match = re.search(r"(\d+\.?\d*)%", string)
            if match:
                try:
                    percent = float(match.group(1))
                    self.progress_var.set(percent)
                except ValueError:
                    pass
        except:
            pass
    
    def flush(self):
        pass

def read_pipe(process, text_widget, progress_var):
    """프로세스의 출력을 실시간으로 읽어서 GUI에 뿌려주는 함수"""
    while True:
        # 한 글자씩 읽어서 GUI 반응성을 높임
        char = process.stdout.read(1)
        if not char and process.poll() is not None:
            break
        if char:
            text_widget.insert(tk.END, char)
            text_widget.see(tk.END)
            
            if char in ('\r', '\n', '%'):
                last_line = text_widget.get("end-2c linestart", "end-1c")
                match = re.search(r"(\d+\.?\d*)%", last_line)
                if match:
                    try:
                        val = float(match.group(1))
                        progress_var.set(val)
                    except:
                        pass

def run_process_thread(input_str, mode, pitch_val=0):
    """실제 작업을 수행하는 백그라운드 스레드"""
    
    btn_run.config(state=tk.DISABLED)
    progress_var.set(0)
    
    try:
        python_exec = sys.executable
        downloads_path = BASE_PATH / DOWNLOADS_DIR
        separated_path = BASE_PATH / SEPARATED_DIR
        downloads_path.mkdir(exist_ok=True)
        separated_path.mkdir(exist_ok=True)
        
        target_file = None

        # --- 1. 다운로드 ---
        if input_str.startswith(('http://', 'https://')):
            print(f"\n[1단계] 유튜브 다운로드 시작: {input_str}")
            
            cmd = [
                "yt-dlp", "-f", "bestaudio",
                "-o", f"{downloads_path}/%(title)s.%(ext)s",
                "--extract-audio", "--audio-format", "wav",
                input_str
            ]
            
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT,
                universal_newlines=True, 
                encoding=SYSTEM_ENCODING,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system()=='Windows' else 0
            )
            
            read_pipe(process, log_text, progress_var)
            
            if process.returncode != 0:
                raise Exception("다운로드 중 오류가 발생했습니다.")

            wav_files = list(downloads_path.glob("*.wav"))
            if not wav_files:
                raise Exception("다운로드된 파일을 찾을 수 없습니다.")
            target_file = max(wav_files, key=lambda f: f.stat().st_mtime)
            print(f"\n다운로드 완료: {target_file.name}")
            
        else:
            print(f"\n[1단계] 로컬 파일 선택됨")
            target_file = Path(input_str)
            if not target_file.exists():
                raise Exception("파일이 존재하지 않습니다.")

        progress_var.set(0)

        # --- 2. 작업 수행 ---
        if mode == "separate":
            print(f"\n[2단계] 음원 분리 시작 (Demucs)...")
            cmd = [python_exec, "-m", "demucs", "-o", str(separated_path), "--two-stems=vocals"]
            
            if platform.system() == "Darwin":
                print("INFO: Mac 환경 감지 (MPS 가속 사용)")
                cmd.extend(["-n", "mdx_extra_q", "-d", "mps"])
            
            cmd.append(str(target_file))
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding=SYSTEM_ENCODING,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system()=='Windows' else 0
            )
            read_pipe(process, log_text, progress_var)

            if process.returncode != 0:
                raise Exception("Demucs 분리 실패")
                
            print(f"\n🎉 분리 완료! 저장 폴더: {separated_path}")
            progress_var.set(100)
            messagebox.showinfo("성공", "음원 분리가 완료되었습니다!")

        elif mode == "pitch":
            print(f"\n[2단계] 피치 조절 시작 ({pitch_val}키)...")
            
            if Path(RUBBERBAND_PATH).exists():
                os.environ['PATH'] = f"{RUBBERBAND_PATH}{os.pathsep}{os.environ['PATH']}"
            
            output_name = f"{target_file.stem}_pitch_{pitch_val:+}{target_file.suffix}"
            output_path = BASE_PATH / "pitch_shifted" / output_name
            (BASE_PATH / "pitch_shifted").mkdir(exist_ok=True)
            
            cmd = [
                "rubberband", "--pitch", str(pitch_val),
                "--formant", "--crispness", "4",
                str(target_file), str(output_path)
            ]
            
            subprocess.run(cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW if platform.system()=='Windows' else 0)
            
            print(f"\n🎉 변환 완료! 파일: {output_path}")
            progress_var.set(100)
            messagebox.showinfo("성공", "피치 조절이 완료되었습니다!")

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        messagebox.showerror("오류", f"작업 중 문제가 발생했습니다: {e}")
    finally:
        btn_run.config(state=tk.NORMAL)

def start_job():
    input_val = entry_input.get().strip()
    if not input_val:
        messagebox.showwarning("경고", "유튜브 주소나 파일 경로를 입력하세요!")
        return
    
    try:
        pitch = int(entry_pitch.get())
    except:
        pitch = 0

    mode = "separate"
    if pitch != 0:
        mode = "pitch"

    t = threading.Thread(target=run_process_thread, args=(input_val, mode, pitch))
    t.start()

def select_file():
    filename = filedialog.askopenfilename(filetypes=[("Audio Files", "*.wav;*.mp3;*.flac")])
    if filename:
        entry_input.delete(0, tk.END)
        entry_input.insert(0, filename)

# --- GUI 구성 ---
root = tk.Tk()
root.title("AI 음원 분리 & 키 조절기 v2.1 (FFmpeg 내장)")
root.geometry("600x600")

# 1. 입력창
frame_input = tk.LabelFrame(root, text="입력 (유튜브 URL 또는 파일)", padx=10, pady=10)
frame_input.pack(fill="x", padx=10, pady=5)
entry_input = tk.Entry(frame_input, width=50)
entry_input.pack(side=tk.LEFT, fill="x", expand=True)
btn_file = tk.Button(frame_input, text="파일찾기", command=select_file)
btn_file.pack(side=tk.RIGHT, padx=5)

# 2. 옵션
frame_opt = tk.LabelFrame(root, text="옵션", padx=10, pady=10)
frame_opt.pack(fill="x", padx=10, pady=5)
tk.Label(frame_opt, text="키(Pitch) 조절 (0이면 분리 모드):").pack(side=tk.LEFT)
entry_pitch = tk.Entry(frame_opt, width=5)
entry_pitch.insert(0, "0")
entry_pitch.pack(side=tk.LEFT, padx=5)
tk.Label(frame_opt, text="(예: +2, -1)").pack(side=tk.LEFT)

# 3. 실행 버튼 및 진행률 바
frame_run = tk.Frame(root, padx=10, pady=5)
frame_run.pack(fill="x")

btn_run = tk.Button(frame_run, text="작업 시작 🚀", command=start_job, bg="lightblue", height=2, font=("Arial", 12, "bold"))
btn_run.pack(fill="x", padx=10, pady=5)

tk.Label(frame_run, text="작업 진행률:").pack(anchor="w", padx=10)
progress_var = tk.DoubleVar()
progress_bar = ttk.Progressbar(frame_run, maximum=100, variable=progress_var)
progress_bar.pack(fill="x", padx=10, pady=5)

# 4. 로그 창
frame_log = tk.LabelFrame(root, text="상세 로그", padx=5, pady=5)
frame_log.pack(fill="both", expand=True, padx=10, pady=5)
log_text = scrolledtext.ScrolledText(frame_log, height=10)
log_text.pack(fill="both", expand=True)

sys.stdout = OutputRedirector(log_text, progress_var)

root.mainloop()
