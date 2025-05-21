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

# ── AudioModule: continuous VAD capture, priority playback & FIFO queue ────
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
        self._vad_thread = None
        self.loop = asyncio.get_event_loop()
        self.frame_queue = asyncio.Queue()

        # Priority scheduler
        self._sched_cond = threading.Condition()
        self._schedule_queue = []  # heap of (-priority, count, ScheduledSound)
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
        self._queue_current = None        # track current playing from queue
        self._queue_thread = threading.Thread(target=self._queue_worker, daemon=True)
        self._queue_thread.start()

    # ── Async capture: non-blocking listen & save ───────────────────────────
    async def record(self, silence_duration: float = 1.0, tmp_dir: str = '/tmp') -> str:
        self.start_vad_stream()
        buffer = bytearray()
        in_speech = False
        silence_count = 0
        threshold = int((silence_duration * 1000) / self.FRAME_MS)

        while True:
            frame, is_speech = await self.frame_queue.get()
            if is_speech:
                in_speech = True
                buffer.extend(frame)
                silence_count = 0
            else:
                if in_speech:
                    buffer.extend(frame)
                    silence_count += 1
                    if silence_count >= threshold:
                        break
        self.stop_vad_stream()

        # write to temp WAV
        file_id = str(uuid.uuid4())
        path = os.path.join(tmp_dir, f"{file_id}.wav")
        os.makedirs(tmp_dir, exist_ok=True)
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(self.SAMPLE_WIDTH)
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(bytes(buffer))
        return path

    # ── VAD streaming ────────────────────────────────────────────────────────
    def start_vad_stream(self):
        if self._vad_running: return
        self._vad_running = True
        self._vad_thread = threading.Thread(target=self._vad_reader, daemon=True)
        self._vad_thread.start()

    def stop_vad_stream(self):
        self._vad_running = False
        if self._vad_thread:
            self._vad_thread.join()
        while not self.frame_queue.empty():
            _ = self.frame_queue.get_nowait()

    def _vad_reader(self):
        with pasimple.PaSimple(pasimple.PA_STREAM_RECORD,
                               self.FORMAT,
                               self.CHANNELS,
                               self.SAMPLE_RATE) as pa:
            while self._vad_running:
                frame = pa.read(self.FRAME_BYTES)
                if len(frame) < self.FRAME_BYTES:
                    break
                is_speech = self.vad.is_speech(frame, self.SAMPLE_RATE)
                self.loop.call_soon_threadsafe(
                    self.frame_queue.put_nowait, (frame, is_speech)
                )
        self._vad_running = False

    # ── FIFO Queue ─────────────────────────────────────────────────────────
    def add_audio_to_queue(self, file_path: str):
        """
        Append an audio file to FIFO queue for sequential playback.
        """
        with self._queue_lock:
            self._audio_queue.append(file_path)
            self._queue_event.set()

    def remove_audio_from_queue(self, file_path: str):
        """
        Remove all occurrences of file_path from the FIFO queue.
        """
        with self._queue_lock:
            self._audio_queue = deque([
                p for p in self._audio_queue if p != file_path
            ])

    def clear_queue(self):
        """
        Clear the FIFO playback queue.
        """
        with self._queue_lock:
            self._audio_queue.clear()

    def list_queue(self) -> list:
        """
        Return list of file paths currently in FIFO queue.
        """
        with self._queue_lock:
            return list(self._audio_queue)

    def list_queue_playing(self) -> list:
        """
        Return current file path playing from FIFO queue, if any.
        """
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
                # play sequentially (blocks until done)
                subprocess.call(["paplay", path])
                with self._queue_lock:
                    self._queue_current = None

    def stop_queue(self):
        """
        Stop FIFO queue thread.
        """
        self._queue_running = False
        self._queue_event.set()
        self._queue_thread.join()

    # ── Priority Scheduler ─────────────────────────────────────────────────
    class ScheduledSound:
        def __init__(self, path, priority, loop, play_id):
            self.path = path
            self.priority = priority
            self.loop = loop
            self.play_id = play_id
            self.process = None

    def play(self, file_path: str, priority: int = 0) -> str:
        """
        Play once via priority scheduler. Returns play_id.
        """
        return self.schedule_sound(file_path, priority, loop=False)

    def schedule_sound(self, sound_path: str, priority: int = 0, loop: bool = False) -> str:
        play_id = str(uuid.uuid4())
        task = AudioModule.ScheduledSound(sound_path, priority, loop, play_id)
        with self._sched_cond:
            heapq.heappush(self._schedule_queue, (-priority, self._counter, task))
            self._counter += 1
            self._sched_cond.notify()
        return play_id

    def stop_sound(self, play_id: str):
        with self._sched_cond:
            self._schedule_queue = [item for item in self._schedule_queue if item[2].play_id != play_id]
            heapq.heapify(self._schedule_queue)
            if self._current_task and self._current_task.play_id == play_id:
                if self._current_task.process:
                    self._current_task.process.kill()
                self._current_task = None
            self._paused_tasks.discard(play_id)
            self._sched_cond.notify()

    def pause_sound(self, play_id: str):
        if self._current_task and self._current_task.play_id == play_id and self._current_task.process:
            self._current_task.process.send_signal(signal.SIGSTOP)
            self._paused_tasks.add(play_id)

    def resume_sound(self, play_id: str):
        if play_id in self._paused_tasks and self._current_task and self._current_task.play_id == play_id:
            self._current_task.process.send_signal(signal.SIGCONT)
            self._paused_tasks.remove(play_id)

    def list_playing(self) -> list:
        with self._sched_cond:
            if self._current_task and self._current_task.process and self._current_task.process.poll() is None:
                if self._current_task.play_id not in self._paused_tasks:
                    return [self._current_task.play_id]
            return []

    def list_paused(self) -> list:
        with self._sched_cond:
            return list(self._paused_tasks)

    def pause_all(self):
        with self._sched_cond:
            if self._current_task and self._current_task.process:
                pid = self._current_task.play_id
                self._current_task.process.send_signal(signal.SIGSTOP)
                self._paused_tasks.add(pid)

    def resume_all(self):
        with self._sched_cond:
            for pid in list(self._paused_tasks):
                self.resume_sound(pid)

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

            while self._scheduler_running and self._current_task:
                proc = subprocess.Popen(["paplay", task.path])
                task.process = proc
                self._paused_tasks.discard(task.play_id)
                while proc.poll() is None:
                    time.sleep(0.1)
                    with self._sched_cond:
                        if self._schedule_queue and -self._schedule_queue[0][0] > task.priority:
                            proc.kill()
                            break
                if self._current_task and task.loop and proc.returncode == 0:
                    continue
                with self._sched_cond:
                    self._current_task = None
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



# ── Example usage demonstrating all functions ───────────────────────────
if __name__ == '__main__':
    async def main():
        am = AudioModule()
        am.start_scheduler()

        # 1. Async record speech until pause → save file
        print("Please speak now...")
        recorded_path = await am.record(silence_duration=1.0)
        print(f"Recorded audio at: {recorded_path}")

        # 2. Play recorded audio once
        play_id = am.play(recorded_path, priority=5)
        print(f"Playing recorded clip, play_id={play_id}")

        # Wait a moment then pause specific
        await asyncio.sleep(5)
        am.pause_sound(play_id)
        print(f"Paused play_id={play_id}, currently paused: {am.list_paused()}")

        # Resume that one
        am.resume_sound(play_id)
        print(f"Resumed play_id={play_id}, now playing: {am.list_playing()}")

        # 3. Schedule a looping background track
        loop_id = am.schedule_sound(recorded_path, priority=0, loop=True)
        print(f"Scheduled loop, play_id={loop_id}")

        # Let it loop then pause all
        await asyncio.sleep(3)
        am.pause_all()
        print(f"Paused all, paused list: {am.list_paused()}")

        # Resume all
        am.resume_all()
        print(f"After resume all, playing: {am.list_playing()}")

        # Stop loop after a bit
        await asyncio.sleep(3)
        am.stop_sound(loop_id)
        print(f"Stopped loop play_id={loop_id}, playing now: {am.list_playing()}")
        print(f"After stop, list of playing:", am.list_playing())

        # Play the assistant voice
        am.add_audio_to_queue("sounds/res_part1.wav")
        am.add_audio_to_queue("sounds/res_part2.wav")
        am.add_audio_to_queue("sounds/waterdropletechoed.wav")

        print("Queue", am.list_queue())
        print("Play", am.list_playing())
        # Finish
        while am.list_queue() or am.list_playing():
            pass
        am.stop_scheduler()

    asyncio.run(main())