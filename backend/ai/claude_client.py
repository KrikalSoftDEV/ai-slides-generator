import anthropic
import os
import json
import re

# Initialize standard Anthropic client
api_key = os.environ.get("ANTHROPIC_API_KEY")

# Standard Anthropic client reads ANTHROPIC_API_KEY from environment
client = anthropic.Anthropic(
    api_key=api_key
)


def analyze_content_for_slides(texts: list, images: list, num_slides: int = 8) -> dict:
    # Dynamically hot-reload environment variables to allow hot-swapping keys without manual restarts
    from dotenv import load_dotenv
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(base_dir, ".env"), override=True)
    
    current_key = os.environ.get("ANTHROPIC_API_KEY")
    req_client = anthropic.Anthropic(api_key=current_key)

    # Combine text content
    combined_text = ""
    if texts:
        combined_text += "\n\n---PAGE BREAK---\n\n".join(texts)
    
    if images:
        combined_text += f"\n\n[Included {len(images)} source images/diagrams for context. Mention and summarize important visible content from these images in the slides.]"

    prompt = f"""Based on the content above, create a professional presentation with approximately {num_slides} slides.

Return a valid JSON object with this exact structure:
{{
  "presentation_title": "Your Presentation Title",
  "slides": [
    {{"type": "title", "title": "Main Title", "subtitle": "Subtitle or tagline", "notes": "Speaker notes here"}},
    {{"type": "content", "title": "Slide Title", "bullets": ["Point one", "Point two", "Point three"], "notes": "Speaker notes"}},
    {{"type": "two_column", "title": "Slide Title", "left_title": "Left Section", "left_bullets": ["Item 1", "Item 2"], "right_title": "Right Section", "right_bullets": ["Item 1", "Item 2"], "notes": "Speaker notes"}},
    {{"type": "section", "title": "Section Break Title", "subtitle": "Section description", "notes": "Speaker notes"}}
  ]
}}

Rules:
- Always start with a "title" type slide
- Use "content" for standard bullet slides
- Use "two_column" for comparisons or parallel concepts
- Use "section" as dividers between major topics
- Maximum 6 bullets per slide, keep them concise
- Extract key insights, not raw text
- Include meaningful details from every uploaded source file
- If images, charts, screenshots, diagrams, or PDF page previews are provided, describe their visible content in the generated slides
- Return ONLY the JSON object, nothing else"""

    user_content = [
        {"type": "text", "text": f"Here is the content from the uploaded documents:\n\n{combined_text}\n\n{prompt}"}
    ]
    for image in images[:8]:
        user_content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image["media_type"],
                "data": image["base64"],
            },
        })

    # We use claude-sonnet-4-6 for premium quality structured slide creation
    response = req_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        temperature=0.3,
        system="You are a professional PowerPoint slide generator. You extract structured insights from documents and format them strictly into JSON presentations. You output nothing except the raw JSON string.",
        messages=[
            {"role": "user", "content": user_content}
        ]
    )

    response_text = response.content[0].text.strip()

    # Clean response to ensure it parses as valid JSON
    if response_text.startswith("```"):
        response_text = re.sub(r'^```(?:json)?\n', '', response_text)
        response_text = re.sub(r'\n```$', '', response_text)
        response_text = response_text.strip()

    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group())

    return json.loads(response_text)
