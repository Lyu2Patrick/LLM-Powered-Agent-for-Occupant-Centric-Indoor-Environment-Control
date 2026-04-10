import tkinter as tk
import threading
import sounddevice as sd
import numpy as np
import whisper
import time
from tkinter.simpledialog import askstring
from graph_utils import record_entry_event, record_exit_event
import control_free as control_llm

model = whisper.load_model("small")


def show_sentinel_message(result):
    if isinstance(result, dict) and result.get("should_notify", False):
        issues = result.get("issues", [])
        if isinstance(issues, list) and issues:
            msg = "\n".join(
                f"[{i.get('issue', 'Issue')}]\n  {i.get('suggestion', '')}" for i in issues
            )
        else:
            issue = result.get("issue", "Potential issue detected")
            suggestion = result.get("suggestion", "Consider checking the environment.")
            msg = f"{issue} -- {suggestion}"
        app.display_message("Sentinel", msg)
    else:
        reason = result.get("debug_reason", "No alert triggered.")
        app.display_message("Sentinel", f"No issues. {reason}")


class EnvControlGUI:
    def __init__(self, root):
        self.root = root
        self.control = control_llm
        self.root.title("Joi")
        self.setup_ui()
        self.recording = False
        self.audio_buffer = []
        self.samplerate = 16000

    def on_resize(self, event=None):
        canvas_width = self.chat_canvas.winfo_width()
        new_wrap = int(canvas_width * 0.75)
        for msg_frame in self.chat_frame.winfo_children():
            if isinstance(msg_frame, tk.Frame):
                for content_line in msg_frame.winfo_children():
                    if isinstance(content_line, tk.Frame):
                        for widget in content_line.winfo_children():
                            if isinstance(widget, tk.Label) and widget.cget("wraplength"):
                                widget.config(wraplength=new_wrap)

    def setup_ui(self):
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.chat_canvas = tk.Canvas(self.main_frame, bg="#F0F0F0", highlightthickness=0)
        self.chat_scrollbar = tk.Scrollbar(self.main_frame, command=self.chat_canvas.yview)
        self.chat_frame = tk.Frame(self.chat_canvas, bg="#F0F0F0")

        self.chat_frame.bind(
            "<Configure>",
            lambda e: self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        )
        self.chat_canvas.configure(yscrollcommand=self.chat_scrollbar.set)
        self.chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.chat_scrollbar.pack(side=tk.LEFT, fill=tk.Y)

        def _on_mousewheel(event):
            self.chat_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self.chat_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.chat_canvas.bind_all("<Button-4>", lambda e: self.chat_canvas.yview_scroll(-1, "units"))
        self.chat_canvas.bind_all("<Button-5>", lambda e: self.chat_canvas.yview_scroll(1, "units"))

        input_frame = tk.Frame(self.root)
        input_frame.pack(padx=10, pady=5, fill=tk.X)

        self.entry = tk.Entry(input_frame, width=50)
        self.entry.pack(side=tk.LEFT, padx=(0, 5), expand=True, fill=tk.X)
        self.entry.bind("<Return>", self.send_text)

        self.send_button = tk.Button(input_frame, text="Send", command=self.send_text)
        self.send_button.pack(side=tk.LEFT)

        self.voice_button = tk.Button(self.root, text="Hold to Speak", width=20)
        self.voice_button.pack(pady=(0, 10))
        self.voice_button.bind("<ButtonPress-1>", self.start_recording)
        self.voice_button.bind("<ButtonRelease-1>", self.stop_recording)

        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=(0, 10))
        self.enter_button = tk.Button(button_frame, text="Enter", command=self.user_entry_dialog)
        self.enter_button.pack(side=tk.LEFT, padx=5)
        self.exit_button = tk.Button(button_frame, text="Exit", command=self.user_exit_dialog)
        self.exit_button.pack(side=tk.LEFT, padx=5)

        def _resize_chat_frame(event):
            self.chat_canvas.itemconfig(self.chat_window_id, width=event.width)

        self.chat_window_id = self.chat_canvas.create_window((0, 0), window=self.chat_frame, anchor="nw")
        self.chat_canvas.bind("<Configure>", _resize_chat_frame)
        self.root.bind("<Configure>", self.on_resize)

    def send_text(self, event=None):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        self.display_message("Me", text)
        self.handle_input(text)

    def display_message(self, sender, message):
        is_user   = sender in ("Me", "Me (voice)")
        is_status = sender in ("sent", "timing")

        if is_status:
            label = tk.Label(
                self.chat_frame, text=message, font=("Arial", 10),
                fg="gray", bg="#F0F0F0",
                anchor="e" if sender == "sent" else "w",
                justify="right" if sender == "sent" else "left"
            )
            label.pack(
                anchor="e" if sender == "sent" else "w",
                fill=tk.X,
                padx=(50, 10) if sender == "sent" else (10, 50),
                pady=(0, 2) if sender == "sent" else (2, 8)
            )
            self.chat_canvas.update_idletasks()
            self.chat_canvas.yview_moveto(1.0)
            return

        bubble_color = "#DCF8C6" if is_user else "#FFFFFF"
        app_bg = "#F0F0F0"

        msg_frame = tk.Frame(self.chat_frame, bg=app_bg, pady=4)
        initial = sender[0].upper()
        canvas_width = self.chat_canvas.winfo_width()
        wraplength = int(canvas_width * 0.75) if canvas_width > 0 else 400

        content_line = tk.Frame(msg_frame, bg=app_bg)
        avatar = tk.Label(content_line, text=initial, font=("Arial", 14, "bold"),
                          bg=app_bg, width=2)
        bubble = tk.Label(
            content_line,
            text=message,
            wraplength=wraplength,
            justify="left",
            font=("Arial", 11),
            padx=12, pady=8,
            bg=bubble_color, fg="#000000",
            relief=tk.SOLID, bd=1
        )

        if is_user:
            avatar.pack(side=tk.RIGHT, padx=(5, 2))
            bubble.pack(side=tk.RIGHT)
            content_line.pack(anchor="e", fill=tk.X, padx=10)
            msg_frame.pack(anchor="e", fill=tk.X)
        else:
            avatar.pack(side=tk.LEFT, padx=(2, 5))
            bubble.pack(side=tk.LEFT)
            content_line.pack(anchor="w", fill=tk.X, padx=10)
            msg_frame.pack(anchor="w", fill=tk.X)

        content_line.pack()
        self.chat_canvas.update_idletasks()
        self.chat_canvas.yview_moveto(1.0)

    def handle_input(self, text):
        try:
            t_send = time.time()
            self.display_message("sent", f"Sent at {time.strftime('%H:%M:%S', time.localtime(t_send))}")
            result = self.control.handle_user_input(text)
            t_done = time.time()
            t_generate = result.get("response_ts") if result else None

            explanation = result.get("explanation", "Control executed") if result else "No response"
            self.display_message("LLM", explanation)

            if t_generate:
                self.display_message("timing",
                    f"Generation: {t_generate - t_send:.2f}s  "
                    f"Execution: {t_done - t_generate:.2f}s  "
                    f"Total: {t_done - t_send:.2f}s")
            else:
                self.display_message("timing", f"Total: {t_done - t_send:.2f}s")

        except Exception as e:
            self.display_message("LLM", f"Control error: {e}")

    def start_recording(self, event=None):
        self.recording = True
        self.audio_buffer = []
        self.stream = sd.InputStream(samplerate=self.samplerate, channels=1,
                                     callback=self.audio_callback)
        self.stream.start()
        self.start_time = time.time()
        self.display_message("LLM", "Recording...")

    def stop_recording(self, event=None):
        if not self.recording:
            return
        self.recording = False
        self.stream.stop()
        duration = time.time() - self.start_time
        if duration < 1.0:
            self.display_message("LLM", f"Recording too short ({duration:.2f}s), ignored.")
            return
        threading.Thread(target=self.process_audio, daemon=True).start()

    def audio_callback(self, indata, frames, time_info, status):
        if self.recording:
            self.audio_buffer.append(indata.copy())

    def process_audio(self):
        try:
            audio = np.concatenate(self.audio_buffer, axis=0).flatten().astype(np.float32)
            result = model.transcribe(
                audio,
                language="en",
                fp16=False,
                temperature=0.5,
                beam_size=5,
                best_of=3,
                condition_on_previous_text=False,
                initial_prompt="You are a smart home assistant."
            )
            text = result["text"].strip()
            if not text:
                self.root.after(0, lambda: self.display_message("LLM", "No speech detected."))
                return
            self.root.after(0, lambda: self.display_message("Me (voice)", text))
            self.root.after(0, lambda: self.handle_input(text))
        except Exception as e:
            self.root.after(0, lambda: self.display_message("LLM", f"Speech recognition failed: {e}"))

    def user_exit_dialog(self):
        self.simple_input_dialog("Name of the person leaving:", self.handle_user_exit)

    def user_entry_dialog(self):
        self.simple_input_dialog("Name of the person entering:", self.handle_user_entry)

    def simple_input_dialog(self, prompt, callback):
        input_win = tk.Toplevel(self.root)
        input_win.title("Input")
        tk.Label(input_win, text=prompt).pack(padx=10, pady=5)
        entry = tk.Entry(input_win)
        entry.pack(padx=10, pady=5)

        def submit():
            name = entry.get().strip()
            input_win.destroy()
            if name:
                callback(name)

        tk.Button(input_win, text="Confirm", command=submit).pack(pady=5)

    def handle_user_exit(self, name):
        record_exit_event(name, "Office")
        self.display_message("sent", f"{name} left the room.")

    def handle_user_entry(self, name):
        record_entry_event(name, "Office")
        self.display_message("LLM", f"{name} entered the room.")


if __name__ == "__main__":
    root_login = tk.Tk()
    root_login.withdraw()
    names_input = askstring(
        "Occupants",
        "Names of occupants currently in the room (comma-separated):"
    )
    root_login.destroy()

    if names_input:
        names = [n.strip() for n in names_input.split(",") if n.strip()]
        for name in names:
            record_entry_event(name, room_name="Office")
        print(f"Recorded {len(names)} occupant(s).")
    else:
        print("No names provided.")

    root = tk.Tk()
    app = EnvControlGUI(root)

    app.control.start_control_loop()
    app.control.wait_for_env_ready()
    app.control.sentinel_gui_callback = show_sentinel_message

    root.mainloop()
