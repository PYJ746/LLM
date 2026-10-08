import configparser
import json
from pathlib import Path

import requests


def load_config(path=None):
    if path:
        candidates = [Path(path)]
    else:
        # 从脚本所在目录逐级向上找，这样多个练习可以共用根目录的一份 config.ini
        here = Path(__file__).resolve().parent
        candidates = [d / "config.ini" for d in (here, *here.parents[:2])]

    for candidate in candidates:
        if candidate.is_file():
            conf = configparser.ConfigParser()
            conf.read(candidate, encoding="utf-8")
            llm = conf["llm"]
            return llm["base_url"], llm["api_key"], llm["model"]

    raise FileNotFoundError(f"找不到配置文件，已查找: {[str(c) for c in candidates]}")


def main():
    try:
        base_url, api_key, model = load_config()
    except Exception as e:
        print(f"Config error: {e}")
        return

    messages = []

    while True:
        prompt = input("Please input your prompt:\n")
        print("---")
        messages.append({"role": "user", "content": prompt})

        try:
            response = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "stream": True,
                },
                stream=True,
                timeout=60,
            )
            response.raise_for_status()

            reply = []
            for line in response.iter_lines():
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    break
                delta = json.loads(data)["choices"][0]["delta"]
                content = delta.get("content") or ""
                if content:
                    reply.append(content)
                print(content, end="", flush=True)
            print()

            messages.append({"role": "assistant", "content": "".join(reply)})
        except requests.HTTPError as e:
            print(f"Error: {e}")
            print(f"Server response: {e.response.text}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
