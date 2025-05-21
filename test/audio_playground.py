import wave
import pasimple
import webrtcvad

# ── Configure for 16-bit @ 16 kHz ─────────────────────────────────────────
FORMAT       = pasimple.PA_SAMPLE_S16LE
SAMPLE_WIDTH = pasimple.format2width(FORMAT)  # will be 2 bytes
CHANNELS     = 1
SAMPLE_RATE  = 16000
DURATION_S   = 10

# ── VAD frame settings ────────────────────────────────────────────────────
FRAME_MS     = 30                      # 10, 20 or 30
FRAME_BYTES  = int(SAMPLE_RATE * FRAME_MS / 1000) * SAMPLE_WIDTH * CHANNELS

vad = webrtcvad.Vad(1)                 # aggressiveness 0–3

# ── Record your whole buffer ──────────────────────────────────────────────
print("Start recording...")
with pasimple.PaSimple(pasimple.PA_STREAM_RECORD, FORMAT, CHANNELS, SAMPLE_RATE) as pa:
    total_bytes = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH * DURATION_S
    audio_data  = pa.read(total_bytes)
print("Recording stopped")
# ── Split into 30 ms frames and detect speech ─────────────────────────────
i = 0
speech_frames = []
for offset in range(0, len(audio_data), FRAME_BYTES):
    print(i, ":", end="\t")
    frame = audio_data[offset:offset + FRAME_BYTES]
    if len(frame) < FRAME_BYTES:
        break
    if vad.is_speech(frame, SAMPLE_RATE):
        print("true")
        speech_frames.append(frame)
    else:
        print("false")

# ── Combine only the speech segments ──────────────────────────────────────
combined = b''.join(speech_frames)

# ── Save to WAV ───────────────────────────────────────────────────────────
with wave.open('recording_speech.wav', 'wb') as wf:
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(SAMPLE_WIDTH)
    wf.setframerate(SAMPLE_RATE)
    wf.writeframes(combined)

print(f"Saved {len(speech_frames)} frames of speech → recording_speech.wav")
