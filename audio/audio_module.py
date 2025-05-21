import pasimple
import webrtcvad
import wave
import asyncio
import subprocess
import threading
import signal
import heapq
import uuid
import time
import os
from collections import deque

# ── AudioModule: continuous VAD capture, priority scheduler, FIFO queue & concurrent ───
class AudioModule:
    def __init__(
        self,
        format=pasimple.PA_SAMPLE_S16LE,
        channels=1,
        sample_rate=16000,
        frame_ms=30,
        vad_aggressiveness=1,
    ):
        # Recording/VAD config
        self.FORMAT = format
        self.CHANNELS = channels
        self.SAMPLE_RATE = sample_rate
        self.SAMPLE_WIDTH = pasimple.format2width(format)
        self.FRAME_MS = frame_ms
        self.FRAME_BYTES = int(sample_rate * frame_ms / 1000) * self.SAMPLE_WIDTH * channels

        # VAD
        self.vad = webrtcvad.Vad(vad_aggressiveness)
        self._vad_running = False
        self.loop = asyncio.get_event_loop()
        self.frame_queue = asyncio.Queue()

        # Priority scheduler
        self._sched_cond = threading.Condition()
        self._schedule_queue = []
        self._counter = 0
        self._current_task = None
        self._paused_tasks = set()
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_running = False

        # FIFO queue playback
        self._audio_queue = deque()
        self._queue_lock = threading.Lock()
        self._queue_event = threading.Event()
        self._queue_running = True
        self._queue_current = None
        self._queue_process = None
        self._queue_thread = threading.Thread(target=self._queue_worker, daemon=True)
        self._queue_thread.start()

        # Concurrent playback
        self._concurrent = {}
        self._concurrent_lock = threading.Lock()

    ##### VAD-based record #####
    async def record(self, silence_duration: float = 1.0, tmp_dir: str = 'tmp', min_speech_duration=0.3) -> str:
        self.start_vad_stream()
        buffer = bytearray()
        in_speech = 0
        silence_count = 0
        threshold = int((silence_duration * 1000) / self.FRAME_MS)
        speech_threshold = int((min_speech_duration * 1000) / self.FRAME_MS)
        while True:
            frame, is_speech = await self.frame_queue.get()
            if is_speech:
                in_speech += 1 # +True
                buffer.extend(frame)
                silence_count = 0
            elif in_speech > speech_threshold:
                buffer.extend(frame)
                silence_count += 1
                if silence_count >= threshold:
                    break
        self.stop_vad_stream()
        file_id = str(uuid.uuid4())
        path = os.path.join(tmp_dir, f"{file_id}.wav")
        os.makedirs(tmp_dir, exist_ok=True)
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(self.SAMPLE_WIDTH)
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(bytes(buffer))
        return path

    def start_vad_stream(self):
        if self._vad_running:
            return
        self._vad_running = True
        threading.Thread(target=self._vad_reader, daemon=True).start()

    def stop_vad_stream(self):
        self._vad_running = False
        while not self.frame_queue.empty():
            self.frame_queue.get_nowait()

    def _vad_reader(self):
        with pasimple.PaSimple(pasimple.PA_STREAM_RECORD, self.FORMAT, self.CHANNELS, self.SAMPLE_RATE) as pa:
            while self._vad_running:
                frame = pa.read(self.FRAME_BYTES)
                if len(frame) < self.FRAME_BYTES:
                    break
                is_speech = self.vad.is_speech(frame, self.SAMPLE_RATE)
                self.loop.call_soon_threadsafe(self.frame_queue.put_nowait, (frame, is_speech))
        self._vad_running = False

    ##### FIFO queue #####
    def add_audio_to_queue(self, path: str):
        with self._queue_lock:
            self._audio_queue.append(path)
            self._queue_event.set()

    def force_queue_play(self, path: str):
        with self._queue_lock:
            if self._queue_process:
                self._queue_process.kill()
            self._audio_queue.clear()
            self._audio_queue.appendleft(path)
            self._queue_event.set()

    def list_queue(self) -> list:
        with self._queue_lock:
            return list(self._audio_queue)

    def list_queue_playing(self) -> list:
        with self._queue_lock:
            return [self._queue_current] if self._queue_current else []

    def _queue_worker(self):
        while self._queue_running:
            self._queue_event.wait()
            while True:
                with self._queue_lock:
                    if not self._audio_queue:
                        self._queue_event.clear()
                        break
                    path = self._audio_queue.popleft()
                    self._queue_current = path
                proc = subprocess.Popen(["paplay", path])
                with self._queue_lock:
                    self._queue_process = proc
                proc.wait()
                with self._queue_lock:
                    self._queue_current = None
                    self._queue_process = None

    def stop_queue(self):
        self._queue_running = False
        self._queue_event.set()
        self._queue_thread.join()

    ##### Priority scheduler #####
    class ScheduledSound:
        def __init__(self, path, priority, loop, play_id):
            self.path = path
            self.priority = priority
            self.loop = loop
            self.play_id = play_id
            self.process = None

    def play(self, path: str, priority: int = 0) -> str:
        return self.schedule(path, priority, loop=False)

    def play_now(self, path: str) -> str:
        return self.schedule(path, 9999, loop=False)

    def schedule(self, path: str, priority: int = 0, loop: bool = False) -> str:
        pid = str(uuid.uuid4())
        task = AudioModule.ScheduledSound(path, priority, loop, pid)
        with self._sched_cond:
            heapq.heappush(self._schedule_queue, (-priority, self._counter, task))
            self._counter += 1
            self._sched_cond.notify()
        return pid

    def pause_sound(self, pid: str):
        if self._current_task and self._current_task.play_id == pid:
            self._current_task.process.send_signal(signal.SIGSTOP)
            self._paused_tasks.add(pid)

    def resume_sound(self, pid: str):
        if pid in self._paused_tasks:
            self._current_task.process.send_signal(signal.SIGCONT)
            self._paused_tasks.remove(pid)

    def stop_sound(self, pid: str):
        with self._sched_cond:
            # remove pending
            self._schedule_queue = [t for t in self._schedule_queue if t[2].play_id != pid]
            heapq.heapify(self._schedule_queue)
            # if currently playing, kill and disable loop
            if self._current_task and self._current_task.play_id == pid:
                if self._current_task.process:
                    self._current_task.process.kill()
                # prevent restart
                self._current_task.loop = False
                self._current_task = None
            self._sched_cond.notify()

    def list_playing(self) -> list:
        with self._sched_cond:
            if self._current_task and self._current_task.process.poll() is None:
                return [self._current_task.play_id]
            return []

    def list_paused(self) -> list:
        return list(self._paused_tasks)

    def clear_schedule(self):
        with self._sched_cond:
            self._schedule_queue.clear()
            self._sched_cond.notify()

    def _scheduler_loop(self):
        self._scheduler_running = True
        while self._scheduler_running:
            with self._sched_cond:
                while not self._schedule_queue and self._scheduler_running:
                    self._sched_cond.wait()
                if not self._scheduler_running:
                    break
                _, _, task = heapq.heappop(self._schedule_queue)
                self._current_task = task

            # play at least once, then loop if requested
            while self._scheduler_running:
                proc = subprocess.Popen(["paplay", task.path])
                task.process = proc
                self._paused_tasks.discard(task.play_id)
                proc.wait()
                # break if not looping or shutdown requested
                if not task.loop or not self._scheduler_running:
                    break
            self._current_task = None
        # cleanup on exit
        if self._current_task and self._current_task.process:
            self._current_task.process.kill()

    def start_scheduler(self):
        if not self._scheduler_thread.is_alive():
            self._scheduler_thread.start()

    def stop_scheduler(self):
        with self._sched_cond:
            self._scheduler_running = False
            self._sched_cond.notify_all()
        self._scheduler_thread.join()

    ##### Concurrent playback #####
    def play_concurrent(self, path: str) -> str:
        pid = str(uuid.uuid4())
        proc = subprocess.Popen(["paplay", path])
        with self._concurrent_lock:
            self._concurrent[pid] = proc
        return pid

    def stop_concurrent(self, pid: str):
        with self._concurrent_lock:
            proc = self._concurrent.pop(pid, None)
        if proc:
            proc.kill()

    def list_concurrent(self) -> list:
        with self._concurrent_lock:
            live = [pid for pid, proc in self._concurrent.items() if proc.poll() is None]
            # cleanup
            for pid in list(self._concurrent):
                if self._concurrent[pid].poll() is not None:
                    del self._concurrent[pid]
            return live


# ── Example: Power & Simplicity ───────────────────────────────────────────
if __name__ == '__main__':
    async def main():
        try:
            am = AudioModule()
            am.start_scheduler()

            # 1️⃣ Record speech to file
            print("Speak now:")
            speech_file = await am.record()
            print(f"Captured → {speech_file}")

            # 2️⃣ One-shot priority play
            pid1 = am.play(speech_file, priority=10)
            print("Playing speech with priority 10, pid=", pid1)

            # 3️⃣ After 2s, pause and resume
            await asyncio.sleep(2)
            am.pause_sound(pid1)
            print("Paused pid=", pid1)
            await asyncio.sleep(1)
            am.resume_sound(pid1)
            print("Resumed pid=", pid1)

            # 4️⃣ Schedule a background loop at low priority
            pid_loop = am.schedule("sounds/waterdropletechoed.wav", priority=0, loop=True)
            print("Looping background.wav, pid=", pid_loop)

            # 5️⃣ Queue up sequential responses
            am.add_audio_to_queue("sounds/res_part1.wav")
            am.add_audio_to_queue("sounds/res_part2.wav")
            print("Queue:", am.list_queue())

            await asyncio.sleep(5)
            # 6️⃣ Force-play an alert immediately
            print("Forcing alert now…")
            am.force_queue_play("sounds/waterdropletechoed.wav")

            # 7️⃣ Play a concurrent chime
            pid_c = am.play_concurrent("response.wav")
            print("Concurrent pid=", pid_c)

            # Monitor for 5s
            for _ in range(20):
                print(_, "Playing:", am.list_playing(),
                    "Paused:", am.list_paused(),
                    "QueuePlaying:", am.list_queue_playing(),
                    "Concurrent:", am.list_concurrent())
                await asyncio.sleep(1)
        except Exception as e:
            pass
        finally:
            # Cleanup
            print("Stopping everything...")
            am.stop_sound(pid_loop)
            print("1")
            am.stop_concurrent(pid_c)
            print("2")
            await asyncio.sleep(1)
            am.stop_queue()
            print("3")
            am.stop_scheduler()

    asyncio.run(main())
