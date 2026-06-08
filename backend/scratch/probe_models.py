import os
import anthropic
from dotenv import load_dotenv

load_dotenv()
if not os.environ.get("ANTHROPIC_API_KEY"):
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY")
)

models = [
    "claude-sonnet-4-6",
    "claude-opus-4-8",
    "claude-haiku-4-5-20251001"
]

print("Probing available models...")
for model in models:
    try:
        response = client.messages.create(
            model=model,
            max_tokens=10,
            messages=[
                {"role": "user", "content": "Hi"}
            ]
        )
        print(f"✅ Success with model '{model}': Response: {response.content[0].text.strip()}")
    except Exception as e:
        print(f"❌ Failed for '{model}': {type(e).__name__} - {str(e)}")
