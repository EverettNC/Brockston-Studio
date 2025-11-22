import os
import httpx
from openai import OpenAI

# Configuration - Your Brockston on port 8777
BROCKSTON_URL = os.getenv("BROCKSTON_BASE_URL", "http://localhost:8777")
USE_BROCKSTON = os.getenv("USE_BROCKSTON", "true").lower() == "true"

# Initialize OpenAI client as fallback
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None

def get_ai_response(user_prompt: str) -> str:
    """
    Get AI response from YOUR Brockston server for teaching students.
    Falls back to OpenAI if Brockston is unavailable.
    """
    
    # Try YOUR Brockston first
    if USE_BROCKSTON:
        try:
            response = httpx.post(
                f"{BROCKSTON_URL}/api/chat",
                json={
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are Brockston, a helpful coding assistant for teaching students. "
                                      "Be clear, educational, and encouraging. Help students learn."
                        },
                        {
                            "role": "user",
                            "content": user_prompt
                        }
                    ]
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                # Your Brockston returns {"text": "..."}
                return data.get("text", data.get("response", data.get("content", str(data))))
            else:
                # If Brockston fails, fall through to OpenAI
                print(f"Brockston returned {response.status_code}, trying OpenAI fallback...")
                
        except Exception as e:
            print(f"Brockston error: {e}, trying OpenAI fallback...")
    
    # Fallback to OpenAI if configured
    if openai_client:
        try:
            system_instruction = (
                "You are Brockston, a helpful coding assistant for teaching students. "
                "Be clear, educational, and encouraging. Help students learn."
            )
            
            completion = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
            )
            return completion.choices[0].message.content
        except Exception as e:
            return f"[AI Error]: {str(e)}"
    
    return "[No AI Available]: Please configure BROCKSTON_BASE_URL or OPENAI_API_KEY"

if __name__ == "__main__":
    # Quick test
    print(f"Using Brockston: {USE_BROCKSTON}")
    print(f"Brockston URL: {BROCKSTON_URL}")
    print(get_ai_response("Hello"))
