"""Check that a model endpoint really reads images before using it as the VLM (or comparing it with eval_vlm.py).

    python scripts/check_vlm.py --models config/models.deepseek.local.yaml
    python scripts/check_vlm.py --base-url http://<vllm>:8000/v1 --model deepseek-v4.1-flash [--api-key KEY]

Sends a small generated image with a Korean sentence, a number and a 3x3 table as an OpenAI-style `image_url`
data URL (the same request the pipeline sends) and checks the answer. A text-only model either refuses the request
or answers without the number. Prints the answer, the time and a verdict; exit code 0 only when the image was read.
"""

import argparse
import base64
import io
import random
import sys
import time
from pathlib import Path

import yaml
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

FONTS = ["C:/Windows/Fonts/malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
         "/usr/share/fonts/nanum/NanumGothic.ttf", "/System/Library/Fonts/Supplemental/AppleGothic.ttf"]


def _font(size: int):
    for f in FONTS:
        if Path(f).is_file():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def make_image(code: str) -> bytes:
    img = Image.new("RGB", (640, 300), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 20), f"점검 번호 {code}: 압력 정상", fill="black", font=_font(28))
    rows = [("항목", "값"), ("온도", "23.5"), ("습도", "41")]
    for r, (a, b) in enumerate(rows):
        y = 100 + r * 50
        d.rectangle((20, y, 320, y + 50), outline="black", width=2)
        d.line((170, y, 170, y + 50), fill="black", width=2)
        d.text((35, y + 10), a, fill="black", font=_font(24))
        d.text((185, y + 10), b, fill="black", font=_font(24))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--models", type=Path, help="models.yaml; its vlm section is used")
    ap.add_argument("--base-url")
    ap.add_argument("--model")
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--timeout", type=float, default=180)
    a = ap.parse_args()
    if a.models:
        v = yaml.safe_load(a.models.read_text(encoding="utf-8"))["vlm"]
        base, model, key = v["base_url"], v["model"], v.get("api_key") or "EMPTY"
    else:
        base, model, key = a.base_url, a.model, a.api_key
    if not base or not model:
        ap.error("give --models, or --base-url and --model")

    code = str(random.randint(1000, 9999))
    url = "data:image/png;base64," + base64.b64encode(make_image(code)).decode()
    client = OpenAI(base_url=base, api_key=key, timeout=a.timeout)
    prompt = "이 이미지에 적힌 점검 번호와 표의 온도 값을 그대로 읽어 줘. 형식: 번호=<숫자>, 온도=<값>"
    t0 = time.time()
    try:
        r = client.chat.completions.create(model=model, max_tokens=200, temperature=0, messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": url}}]}])
    except Exception as e:  # a text-only model is usually refused here
        print(f"[실패] {model} @ {base}: 이미지 요청이 거부되었습니다 ({type(e).__name__}: {str(e)[:300]})")
        print("       텍스트 전용 모델이거나, vLLM이 이 모델의 이미지 입력을 켜지 않고 떠 있습니다.")
        return 2
    secs = time.time() - t0
    answer = (r.choices[0].message.content or "").strip()
    print(f"모델: {model} @ {base}  ({secs:.1f}초, 출력 토큰 {getattr(r.usage, 'completion_tokens', '?')})")
    print(f"답: {answer[:400]}")
    ok_code, ok_temp = code in answer, "23.5" in answer
    if ok_code and ok_temp:
        print(f"[통과] 이미지를 읽었습니다: 번호 {code}, 온도 23.5")
        return 0
    print(f"[불확실] 번호 {code} {'맞음' if ok_code else '틀림'}, 온도 23.5 {'맞음' if ok_temp else '틀림'}. "
          "이미지를 보지 못했거나 읽기가 약합니다. eval_vlm.py로 자세히 비교하세요.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
