import requests

text = "res_part1.wav"

resp = requests.post(
    "http://10.0.0.18:5000/synthesis",
    json={"text": text}
)

if resp.status_code == 200:
    with open(text, "wb") as f:
        f.write(resp.content)
    print(f"Audio saved to {text}")
else:
    print("Error:", resp.json())
