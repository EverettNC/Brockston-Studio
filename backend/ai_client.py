import os
from openai import OpenAI

# Initialize client with env var
# Ensure you have OPENAI_API_KEY in your .env or system environment
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_ai_response(user_prompt: str) -> str:
    """
    Direct connection to OpenAI.
    System prompt is configured for 'Teach' persona: Efficient, Code-First, No Fluff.
    """
    system_instruction = (
        "You are Brockston, a high-frequency coding assistant for a neurodivergent genius operator named Teach. "
        "Your responses must be concise, technically accurate, and 'void black' in tone. "
        "No pleasantries. No explanations unless asked. Output code immediately. "
        "Current Mission: STILLHERE (Resurrection Engine)."
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4o", # Or gpt-3.5-turbo if 4o is not available
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2, # Low temp for precision
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"[NEURAL LINK FAILURE]: {str(e)}"

if __name__ == "__main__":
    # Quick test
    print(get_ai_response("Status report."))
