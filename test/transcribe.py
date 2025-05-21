import requests

url = 'http://10.0.0.18:5000/transcribe'  # Replace with your server's URL
files = {'file': open('recording_speech.wav', 'rb')}  # Replace 'audio.wav' with your file path

response = requests.post(url, files=files)

if response.status_code == 200:
    transcript = response.json()['transcript']
    print(transcript)
else:
    print(f"Error: {response.status_code}")