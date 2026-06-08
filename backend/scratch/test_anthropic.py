import os
import anthropic
from dotenv import load_dotenv

load_dotenv()
if not os.environ.get("ANTHROPIC_API_KEY"):
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

print("API Key being used:", os.environ.get("ANTHROPIC_API_KEY"))

client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY")
)

try:
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=10,
        messages=[
            {"role": "user", "content": "Hi"}
        ]
    )
    print("Success! Response content:", response.content[0].text)
except Exception as e:
    print("Failed with Exception Type:", type(e).__name__)
    print("Error message detail:", str(e))
