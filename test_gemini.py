import os
import google.generativeai as genai
from dotenv import load_dotenv

def main():
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY")
    print(f"API Key: {key}")
    genai.configure(api_key=key)
    
    # Let's list the models to see what models this key has access to!
    try:
        print("Listing available models:")
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f" - {m.name}")
    except Exception as e:
        print(f"Failed to list models: {e}")
        
    try:
        print("Testing gemini-1.5-flash:")
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content("Hello")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Failed with gemini-1.5-flash: {e}")

if __name__ == "__main__":
    main()
