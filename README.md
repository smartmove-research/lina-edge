# LINA: Cloud-Accelerated AI Assistant for the Visually Impaired

**LINA** (Live Intelligent Navigation Assistant) is a wearable AI system that helps blind and low-vision individuals navigate and understand their surroundings using a hybrid edge–cloud architecture. It combines lightweight local processing (on a Raspberry Pi 4) with state-of-the-art AI models (deployed in the cloud) to deliver real-time object detection, scene description, text reading, and conversational assistance.

## Features

- **Camera + Audio Input** via ESP32-CAM and Bluetooth headset
- **Object Detection** with YOLOx-M (MindSpore)
- **Scene Captioning** using BLIP (PyTorch)
- **Optical Character Recognition** using PaddleOCR
- **Automatic Speech Recognition** with Whisper.cpp (offline) and Faster-Whisper (cloud)
- **Dialogue Engine** powered by quantized LLaMA 3B
- **Speech Synthesis** using Glow-TTS + HiFi-GAN
- **Bluetooth Audio Output** via custom `pasimple` module
- **Variational Frame Acquisition** (histogram and pixel differencing) for bandwidth optimization
- **Fallback Mode** for offline usage

## Architecture

- 🧠 Cloud: Huawei Cloud instance (NVIDIA T4 GPU) running Docker containers for each model
- 🧱 Edge: Raspberry Pi 4 orchestrates sensors, voice I/O, and inference requests
- 🎥 ESP32-CAM streams video to Pi via Wi-Fi
- 🔊 Audio feedback streamed via PulseAudio to Bluetooth device
- 📡 Communication via gRPC and HTTPS

## Quick Start

> _Note: This project is under active development. Instructions may evolve._

### 1. Clone the Repository
```bash
git clone https://github.com/smartmove-research/lina.git
cd lina
```

### 2. Set Up Raspberry Pi (Edge Node)
- Flash `openEuler` or Raspbian
- Install dependencies: Python 3.9+, `ffmpeg`, `pulseaudio`, `libasound2-dev`
- Enable Bluetooth and Wi-Fi
- Pair your ESP32-CAM and Bluetooth headset

### 3. Set Up Cloud Server (Huawei Cloud)
- Provision an instance with NVIDIA T4 (16GB)
- Install Docker + NVIDIA Container Toolkit
- Pull and run each container:
  - `yolox-server`
  - `blip-server`
  - `ocr-server`
  - `llama-server`
  - `tts-server`
  - `asr-server`

### 4. Run the Edge Client
```bash
cd edge_client
python3 main.py
```

## Citation
If you use LINA in academic work, please cite:
```bibtex
@inproceedings{nyemb2024lina,
  title={LINA: A Cloud-Accelerated AI Assistant for the Visually Impaired with Event-Driven Edge Perception},
  author={Nyemb Ndjem Eone, Andre Kevin and Minkoh Som, Lyne and Njimeyup, Harold and Gwade, Steve and Maka Maka, Ebenezer},
  booktitle={Deep Learning Indaba},
  year={2024}
}
```

## License
This project is licensed under the MIT License. See `LICENSE` for details.

## Acknowledgments
- SmartMove Research Team
- National Higher Polytechnic School of Douala (LGSDIA)
- Huawei Cloud (for compute resources)
- Open-source contributors to MindSpore, PaddleOCR, LLaMA, Whisper, GlowTTS, and BLIP
